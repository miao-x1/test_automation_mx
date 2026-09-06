"""
Locator Strategy：从元素字段生成候选定位策略，不直接认定最终 locator。

优先级 / 评分：
  data-testid 100 → aria-label 90 → placeholder 80 → label 80
  → role+name 70 → 稳定 CSS 62 → id 60 → name 属性 58
  → role 52 → text 50 → xpath 30

禁止把用例步骤里的推断文案（如「搜索」）当成真实 placeholder / accessible name。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.agent.script.locator_builder import _ROLE_BY_TYPE, _clean, _escape, _looks_usable_name

LOCATOR_SCORES = {
    "test_id": 100,
    "aria_label": 90,
    "placeholder": 80,
    "label": 80,
    "role_name": 70,
    "css": 62,
    "id": 60,
    "name_attr": 58,
    "role": 52,
    "text": 50,
    "xpath": 30,
}

# 推断步骤常用的占位文案，不能当作页面真实属性
_INFERRED_LABELS = {
    "搜索",
    "search",
    "输入框",
    "搜索框",
    "按钮",
    "搜索按钮",
    "输入",
    "点击",
    "submit",
    "button",
}

_DYNAMIC_ID = re.compile(
    r"(?i)^(?:ember|react|vue|ng|:r)[-:]|"
    r"^[0-9a-f]{8}-[0-9a-f]{4}-|"
    r"^[a-z]{1,3}\d{6,}$"
)

_FRAGILE_CSS = re.compile(
    r"(?i)\.(?:css|sc|jsx|emotion|styled)-[a-zA-Z0-9_-]{4,}"
    r"|\[class\*=['\"][a-z0-9_-]{10,}"
)

_FILL_ACTIONS = {"fill", "input", "type", "search"}
_CLICK_ACTIONS = {"click", "submit"}


def is_dynamic_id(value: str) -> bool:
    text = _clean(value)
    return bool(text) and bool(_DYNAMIC_ID.search(text))


def is_fragile_css(value: str) -> bool:
    return bool(_FRAGILE_CSS.search(_clean(value) or ""))


def is_inferred_label(value: str) -> bool:
    return _clean(value).lower() in {x.lower() for x in _INFERRED_LABELS}


def _intent_of(element: Dict[str, Any]) -> str:
    intent = _clean(element.get("intent")).lower()
    if intent in _FILL_ACTIONS or intent in _CLICK_ACTIONS:
        return "fill" if intent in _FILL_ACTIONS else "click"
    etype = _clean(element.get("type") or element.get("element_type")).lower()
    if etype in {"input", "searchbox", "textarea", "textbox"}:
        return "fill"
    if etype in {"button", "link", "submit", "menuitem"}:
        return "click"
    return intent


def _source_is_inferred(element: Dict[str, Any]) -> bool:
    return _clean(element.get("source")).lower() == "inferred"


def _candidate(ctype: str, value: str, expr: str, score: Optional[int] = None) -> Dict[str, Any]:
    return {
        "type": ctype,
        "value": value,
        "expr": expr,
        "score": LOCATOR_SCORES[ctype] if score is None else score,
    }


def candidates_from_element(element: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从真实元素字段生成候选，按评分降序。推断元素不使用其伪造 name/placeholder。"""
    if not isinstance(element, dict):
        return []

    inferred = _source_is_inferred(element)
    etype = _clean(element.get("type") or element.get("element_type")).lower()
    role = _clean(element.get("role")).lower() or _ROLE_BY_TYPE.get(etype, "")
    text = _clean(element.get("text") or element.get("accessible_name"))
    label = _clean(element.get("label") or element.get("aria_label") or element.get("aria-label"))
    aria_label = _clean(element.get("aria_label") or element.get("aria-label"))
    name = _clean(element.get("name") or element.get("element_name"))
    html_name = _clean(
        element.get("html_name")
        or element.get("name_attr")
        or element.get("attr_name")
    )
    placeholder = _clean(element.get("placeholder"))
    test_id = _clean(
        element.get("test_id")
        or element.get("data-testid")
        or element.get("data_testid")
    )
    elem_id = _clean(element.get("id") or element.get("element_id") or element.get("html_id"))
    css = _clean(element.get("css") or element.get("css_selector") or element.get("selector"))
    xpath = _clean(element.get("xpath"))
    existing = _clean(element.get("playwright_expr") or element.get("locator"))

    seen: set[str] = set()
    out: List[Dict[str, Any]] = []

    def add(item: Dict[str, Any]) -> None:
        expr = item["expr"]
        if not expr or expr in seen:
            return
        seen.add(expr)
        out.append(item)

    if test_id:
        add(_candidate("test_id", test_id, f'page.get_by_test_id("{_escape(test_id)}")'))

    if aria_label and _looks_usable_name(aria_label) and not (inferred and is_inferred_label(aria_label)):
        add(_candidate("aria_label", aria_label, f'page.get_by_label("{_escape(aria_label)}")'))

    if placeholder and _looks_usable_name(placeholder) and not (inferred and is_inferred_label(placeholder)):
        add(_candidate("placeholder", placeholder, f'page.get_by_placeholder("{_escape(placeholder)}")'))

    if label and _looks_usable_name(label) and not (inferred and is_inferred_label(label)):
        add(_candidate("label", label, f'page.get_by_label("{_escape(label)}")'))

    accessible = ""
    if not inferred:
        accessible = text or label or (name if not is_inferred_label(name) else "")
    elif text and not is_inferred_label(text):
        accessible = text

    if role and accessible and _looks_usable_name(accessible):
        add(_candidate(
            "role_name",
            f"{role}|{accessible}",
            f'page.get_by_role("{_escape(role)}", name="{_escape(accessible)}")',
        ))

    if css and css.lower() not in {"todo", "todo_replace"} and not is_fragile_css(css):
        add(_candidate("css", css, f'page.locator("{_escape(css)}")'))

    if elem_id and not is_dynamic_id(elem_id):
        add(_candidate("id", elem_id, f'page.locator("#{_escape(elem_id)}")'))

    if html_name:
        if re.match(r"^[\w-]+$", html_name):
            name_expr = f'page.locator("[name={_escape(html_name)}]")'
        else:
            name_expr = f"page.locator('[name=\"{_escape(html_name)}\"]')"
        add(_candidate("name_attr", html_name, name_expr))

    if role and not inferred:
        add(_candidate("role", role, f'page.get_by_role("{_escape(role)}")'))

    if text and _looks_usable_name(text) and not inferred and not is_inferred_label(text):
        add(_candidate("text", text, f'page.get_by_text("{_escape(text)}")'))

    if xpath and not xpath.lower().startswith("todo"):
        prefix = "" if xpath.startswith("xpath=") else "xpath="
        add(_candidate("xpath", xpath, f'page.locator("{prefix}{_escape(xpath)}")'))

    if existing.lower().startswith("page.") and existing not in seen:
        add({
            "type": "existing",
            "value": existing,
            "expr": existing,
            "score": 48,
        })

    out.sort(key=lambda c: c["score"], reverse=True)
    return out


def intent_seed_candidates(intent: str, description: str = "") -> List[Dict[str, Any]]:
    """通用意图种子，不写死具体站点 selector，也不发明 placeholder=搜索。"""
    intent = _clean(intent).lower()
    desc = _clean(description).lower()
    is_search = "搜索" in description or "search" in desc
    out: List[Dict[str, Any]] = []

    if intent in _FILL_ACTIONS or is_search and intent != "click":
        out.extend([
            _candidate("role", "searchbox", 'page.get_by_role("searchbox")'),
            _candidate("role", "textbox", 'page.get_by_role("textbox")'),
            _candidate("css", "input[type=search]", 'page.locator("input[type=search]")'),
            _candidate("css", "textarea", 'page.locator("textarea")', score=40),
        ])
    if intent in _CLICK_ACTIONS:
        out.extend([
            _candidate("role", "button", 'page.get_by_role("button")', score=45),
            _candidate("css", "input[type=submit]", 'page.locator("input[type=submit]")', score=55),
        ])
    return out


def candidates_from_dom_node(node: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把真实 DOM 节点转成候选（发现层，不是硬编码站点）。"""
    if not isinstance(node, dict):
        return []
    fake = {
        "source": "dom",
        "type": node.get("type") or node.get("tag") or "",
        "role": node.get("role") or "",
        "text": node.get("text") or "",
        "label": node.get("ariaLabel") or node.get("label") or "",
        "aria_label": node.get("ariaLabel") or "",
        "placeholder": node.get("placeholder") or "",
        "test_id": node.get("testId") or "",
        "id": node.get("id") or "",
        "html_name": node.get("name") or "",
        "css": "",
    }
    tag = _clean(node.get("tag")).lower()
    input_type = _clean(node.get("type")).lower()
    if tag == "input" and input_type == "search":
        fake["role"] = fake["role"] or "searchbox"
        fake["type"] = "searchbox"
    elif tag in {"input", "textarea"}:
        fake["role"] = fake["role"] or "textbox"
        fake["type"] = "input" if tag == "input" else "textarea"
    elif tag == "button" or input_type in {"submit", "button"}:
        fake["role"] = fake["role"] or "button"
        fake["type"] = "button"
    return candidates_from_element(fake)


def element_matches_intent(element: Dict[str, Any], intent: str) -> bool:
    want = "fill" if intent in _FILL_ACTIONS else "click" if intent in _CLICK_ACTIONS else intent
    return _intent_of(element) == want or not _intent_of(element)


def collect_candidates_for_intent(
    intent: str,
    description: str,
    elements: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    matched = [e for e in (elements or []) if isinstance(e, dict) and element_matches_intent(e, intent)]
    if not matched:
        matched = [e for e in (elements or []) if isinstance(e, dict)]
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for elem in matched:
        for cand in candidates_from_element(elem):
            if cand["expr"] in seen:
                continue
            seen.add(cand["expr"])
            out.append(cand)
    for cand in intent_seed_candidates(intent, description):
        if cand["expr"] in seen:
            continue
        seen.add(cand["expr"])
        out.append(cand)
    out.sort(key=lambda c: c["score"], reverse=True)
    return out
