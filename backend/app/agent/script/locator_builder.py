"""
从 ImageAgent / ElementAgent 元素信息构建稳定 Playwright locator。

优先级：
  get_by_role → get_by_label → get_by_placeholder → get_by_test_id
  → get_by_text → CSS → XPath

无法确定稳定定位器时返回 None，禁止用空字符串或 TODO 冒充成功。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

_PLACEHOLDER_URL_MARKERS = (
    "todo_replace",
    "todo_replace_with_real_url",
    "example.com",
    "example.org",
)

_ROLE_BY_TYPE = {
    "button": "button",
    "input": "textbox",
    "searchbox": "searchbox",
    "textarea": "textbox",
    "checkbox": "checkbox",
    "radio": "radio",
    "select": "combobox",
    "dropdown": "combobox",
    "link": "link",
    "tab": "tab",
    "menu": "menuitem",
    "menuitem": "menuitem",
    "img": "img",
    "image": "img",
}

_INVALID_SCRIPT_PATTERNS = (
    re.compile(r"TODO_REPLACE", re.IGNORECASE),
    re.compile(r"page\.locator\(\s*['\"]\s*['\"]\s*\)"),
    re.compile(r"page\.locator\(\s*['\"]TODO", re.IGNORECASE),
    re.compile(r"get_by_(?:role|label|text|placeholder|test_id)\(\s*['\"]\s*['\"]"),
)

_URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def is_placeholder_url(url: Any) -> bool:
    text = _clean(url).lower()
    if not text:
        return True
    if any(marker in text for marker in _PLACEHOLDER_URL_MARKERS):
        return True
    parsed = urlparse(text)
    return parsed.scheme not in ("http", "https") or not parsed.netloc


def extract_url(*candidates: Any) -> str:
    """从多个来源提取第一个真实 URL。"""
    for candidate in candidates:
        if isinstance(candidate, dict):
            for key in ("target_url", "page_url", "url", "entry_url", "base_url"):
                found = extract_url(candidate.get(key))
                if found:
                    return found
            continue
        if isinstance(candidate, list):
            for item in candidate:
                found = extract_url(item)
                if found:
                    return found
            continue
        text = _clean(candidate)
        if text and not is_placeholder_url(text):
            return text
        if text:
            match = _URL_IN_TEXT.search(text)
            if match and not is_placeholder_url(match.group(0).rstrip(").,;")):
                return match.group(0).rstrip(").,;")
    return ""


def _looks_usable_name(name: str) -> bool:
    if not name or name.lower() in {"todo", "todo_replace", "n/a", "none", "null"}:
        return False
    return len(name) <= 80


def build_playwright_locator(element: Dict[str, Any]) -> Optional[str]:
    """根据元素字段选择最稳定的 Playwright 调用表达式。"""
    if not isinstance(element, dict):
        return None

    etype = _clean(element.get("type") or element.get("element_type")).lower()
    role = _clean(element.get("role")).lower() or _ROLE_BY_TYPE.get(etype, "")
    text = _clean(element.get("text") or element.get("accessible_name"))
    label = _clean(element.get("label") or element.get("aria_label") or element.get("aria-label"))
    name = _clean(element.get("name") or element.get("element_name"))
    placeholder = _clean(element.get("placeholder"))
    test_id = _clean(
        element.get("test_id")
        or element.get("data-testid")
        or element.get("data_testid")
    )
    css = _clean(element.get("css") or element.get("css_selector") or element.get("selector"))
    xpath = _clean(element.get("xpath"))
    existing = _clean(element.get("locator") or element.get("playwright_expr"))

    if existing.lower().startswith("page."):
        if not any(p.search(existing) for p in _INVALID_SCRIPT_PATTERNS):
            return existing
        existing = ""

    accessible = text or label or name
    if role and accessible and _looks_usable_name(accessible):
        return f'page.get_by_role("{_escape(role)}", name="{_escape(accessible)}")'

    if label and _looks_usable_name(label):
        return f'page.get_by_label("{_escape(label)}")'

    if placeholder and _looks_usable_name(placeholder):
        return f'page.get_by_placeholder("{_escape(placeholder)}")'

    if test_id:
        return f'page.get_by_test_id("{_escape(test_id)}")'

    if text and _looks_usable_name(text) and etype in {"button", "link", "tab", "menuitem", "menu"}:
        return f'page.get_by_text("{_escape(text)}")'

    if css and css.lower() not in {"todo", "todo_replace"}:
        return f'page.locator("{_escape(css)}")'

    if xpath and not xpath.lower().startswith("todo"):
        prefix = "" if xpath.startswith("xpath=") else "xpath="
        return f'page.locator("{prefix}{_escape(xpath)}")'

    if existing and existing.lower() not in {"todo", "todo_replace"}:
        if existing.startswith("/") or existing.startswith("./"):
            return f'page.locator("xpath={_escape(existing)}")'
        return f'page.locator("{_escape(existing)}")'

    return None


def enrich_elements(elements: List[Any]) -> List[Dict[str, Any]]:
    """为元素补全 playwright_expr / locator；无法定位的元素保持原样且不写空 locator。"""
    enriched: List[Dict[str, Any]] = []
    for raw in elements or []:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        expr = build_playwright_locator(item)
        if expr:
            item["playwright_expr"] = expr
            if not _clean(item.get("locator")):
                item["locator"] = expr
        enriched.append(item)
    return enriched


def usable_elements(elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [e for e in elements if isinstance(e, dict) and build_playwright_locator(e)]


def _normalize_case_steps(case: Dict[str, Any]) -> List[Dict[str, Any]]:
    """统一 steps：列表字典，或 CaseAgent RAG 的多行字符串。"""
    raw = case.get("steps")
    if isinstance(raw, list):
        steps: List[Dict[str, Any]] = []
        for item in raw:
            if isinstance(item, dict):
                steps.append(item)
            elif isinstance(item, str) and item.strip():
                steps.append(_step_from_text(item.strip()))
        return steps
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [s for s in parsed if isinstance(s, dict)]
        except (TypeError, ValueError):
            pass
        return [
            _step_from_text(line)
            for line in re.split(r"[\n;]+", raw)
            if _clean(re.sub(r"^\d+[\.、]\s*", "", line))
        ]
    return []


def _step_from_text(text: str) -> Dict[str, Any]:
    desc = _clean(re.sub(r"^\d+[\.、]\s*", "", text))
    lower = desc.lower()
    if any(token in desc for token in ("输入", "填写", "填入")) or any(
        token in lower for token in ("fill", "type", "input")
    ):
        action = "fill"
    elif any(token in desc for token in ("点击", "单击")) or "click" in lower:
        action = "click"
    else:
        action = ""
    return {"action": action, "description": desc, "locator": ""}


_GENERIC_FILL_WORDS = {
    "关键词", "关键字", "内容", "文本", "搜索词", "search", "keyword", "text", "value",
}


def infer_fill_value(step: Dict[str, Any], case_data: Any = None) -> str:
    """从步骤或用例描述提取真实输入值，不用站点硬编码。"""
    if not isinstance(step, dict):
        step = {}
    for key in ("value", "input", "data", "text"):
        raw = _clean(step.get(key))
        if raw and raw.lower() not in _GENERIC_FILL_WORDS and raw not in _GENERIC_FILL_WORDS:
            return raw

    texts = [
        _clean(step.get("description") or step.get("step") or step.get("name")),
    ]
    if isinstance(case_data, dict):
        texts.extend([
            _clean(case_data.get("description")),
            _clean(case_data.get("requirement")),
            _clean(case_data.get("case_name")),
        ])
        for case in case_data.get("cases") or []:
            if isinstance(case, dict):
                texts.extend([
                    _clean(case.get("description")),
                    _clean(case.get("requirement")),
                ])
    blob = " ".join(t for t in texts if t)

    quoted = re.search(r"[「\"'“](.+?)[」\"'”]", blob)
    if quoted and quoted.group(1) not in _GENERIC_FILL_WORDS:
        return quoted.group(1)

    step_desc = texts[0] if texts else ""
    field_patterns = []
    if any(tok in step_desc for tok in ("密码", "password")):
        field_patterns.append(r"(?:密码|password)\s*(?:输入|填写|填入|为|:|：)\s*([^\s，。,；;]{2,40})")
    elif any(tok in step_desc for tok in ("用户名", "账号", "username")):
        field_patterns.append(r"(?:用户名|账号|username)\s*(?:输入|填写|填入|为|:|：)\s*([^\s，。,；;]{2,40})")
    for pattern in field_patterns:
        field_match = re.search(pattern, blob, re.I)
        if field_match:
            word = field_match.group(1).strip("「」\"'“”")
            if word and word.lower() not in _GENERIC_FILL_WORDS:
                return word

    _skip_words = _GENERIC_FILL_WORDS | {"按钮", "搜索按钮", "提交", "确定", "用户名", "密码", "账号", "username", "password"}
    for typed in re.finditer(r"(?:输入|填写|填入)\s*([^\s，。,；;]{2,40})", blob):
        word = typed.group(1).strip("「」\"'“”")
        if word in _skip_words or word.lower() in _skip_words or "框" in word:
            continue
        return word
    return ""


def infer_elements_from_cases(case_data: Any) -> List[Dict[str, Any]]:
    """从用例步骤描述推断可定位元素（无截图时的最小补充，不用空 locator）。"""
    cases = case_data if isinstance(case_data, list) else [case_data] if isinstance(case_data, dict) else []
    inferred: List[Dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        for step in _normalize_case_steps(case):
            action = _clean(step.get("action")).lower()
            desc = _clean(step.get("description") or step.get("step") or step.get("name"))
            existing = _clean(step.get("locator") or step.get("playwright_expr"))
            if existing and existing.lower() not in {"todo", "todo_replace"}:
                inferred.append({
                    "name": desc or existing,
                    "type": "input" if action in {"fill", "input", "type"} else "button",
                    "locator": existing,
                })
                continue
            if action in {"fill", "input", "type"}:
                is_search = "搜索" in desc or "search" in desc.lower()
                inferred.append({
                    "name": desc[:24] or ("search_input" if is_search else "input"),
                    "type": "searchbox" if is_search else "input",
                    "intent": "fill",
                    "source": "inferred",
                })
            elif action in {"click", "submit"}:
                inferred.append({
                    "name": desc[:24] or "click_target",
                    "type": "button",
                    "intent": "click",
                    "source": "inferred",
                })
    return enrich_elements(inferred)


def script_has_invalid_locators(script: str) -> Optional[str]:
    """若脚本含占位 URL / 空 locator，返回错误说明。"""
    text = script or ""
    if not text.strip():
        return "脚本内容为空"
    for pattern in _INVALID_SCRIPT_PATTERNS:
        if pattern.search(text):
            return "脚本包含 TODO_REPLACE 或空定位器，无法执行"
    if "page.locator(\"\")" in text or "page.locator('')" in text:
        return "脚本包含空 locator"
    return None
