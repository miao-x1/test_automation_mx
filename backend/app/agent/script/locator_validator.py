"""
Locator Validator：在真实页面上依次验证候选 locator。

成功：count()>0 且 visible 且 enabled，保存 best_locator。
全部失败：返回 LOCATOR_GENERATION_FAILED，不得继续执行。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.agent.script.locator_builder import _clean
from app.agent.script.locator_strategy import (
    _CLICK_ACTIONS,
    _FILL_ACTIONS,
    candidates_from_dom_node,
    collect_candidates_for_intent,
)
from app.core.logger import log

LOCATOR_GENERATION_FAILED = "LOCATOR_GENERATION_FAILED"

_GET_BY_ROLE = re.compile(
    r'''page\.get_by_role\(\s*['"]([^'"]+)['"]\s*(?:,\s*name\s*=\s*['"]([^'"]*)['"])?\s*\)'''
)
_GET_BY_PLACEHOLDER = re.compile(r'''page\.get_by_placeholder\(\s*['"]([^'"]+)['"]''')
_GET_BY_TEST_ID = re.compile(r'''page\.get_by_test_id\(\s*['"]([^'"]+)['"]''')
_GET_BY_LABEL = re.compile(r'''page\.get_by_label\(\s*['"]([^'"]+)['"]''')
_GET_BY_TEXT = re.compile(r'''page\.get_by_text\(\s*['"]([^'"]+)['"]''')
_LOCATOR = re.compile(r'''page\.locator\(\s*(['"])(.+?)\1\s*\)''')


def resolve_locator(page, expr: str):
    """把已生成的 Playwright 表达式解析为 Locator，不 eval 任意代码。"""
    text = (expr or "").strip()
    if not text.startswith("page."):
        return page.locator(text)

    m = _GET_BY_ROLE.search(text)
    if m:
        role, name = m.group(1), m.group(2)
        if name:
            return page.get_by_role(role, name=name)
        return page.get_by_role(role)

    m = _GET_BY_PLACEHOLDER.search(text)
    if m:
        return page.get_by_placeholder(m.group(1))

    m = _GET_BY_TEST_ID.search(text)
    if m:
        return page.get_by_test_id(m.group(1))

    m = _GET_BY_LABEL.search(text)
    if m:
        return page.get_by_label(m.group(1))

    m = _GET_BY_TEXT.search(text)
    if m:
        return page.get_by_text(m.group(1))

    m = _LOCATOR.search(text)
    if m:
        return page.locator(m.group(2))

    raise ValueError(f"无法解析 locator 表达式: {expr}")


def probe_locator(page, loc) -> Dict[str, Any]:
    try:
        count = loc.count()
    except Exception as exc:
        return {"ok": False, "count": 0, "visible": False, "enabled": False, "error": str(exc)}

    if count <= 0:
        return {"ok": False, "count": 0, "visible": False, "enabled": False}

    visible = False
    enabled = False
    for i in range(min(count, 8)):
        item = loc.nth(i)
        try:
            if not item.is_visible():
                continue
            visible = True
            enabled = bool(item.is_enabled())
            if visible and enabled:
                return {"ok": True, "count": count, "visible": True, "enabled": True}
        except Exception:
            continue
    return {"ok": False, "count": count, "visible": visible, "enabled": enabled}


def probe_expr(page, expr: str) -> Dict[str, Any]:
    try:
        loc = resolve_locator(page, expr)
    except Exception as exc:
        return {"ok": False, "count": 0, "visible": False, "enabled": False, "error": str(exc)}
    result = probe_locator(page, loc)
    result["expr"] = expr
    return result


def _description_bonus(candidate: Dict[str, Any], description: str) -> int:
    """步骤描述与 locator 文案重合时加分，避免两个输入框都落到第一个 textbox。"""
    desc = _clean(description).lower()
    hay = f"{candidate.get('value') or ''} {candidate.get('expr') or ''}".lower()
    if not desc or not hay:
        return 0
    pairs = (
        (("用户名", "username"), ("username", "用户名", "user")),
        (("密码", "password"), ("password", "密码")),
        (("登录", "login"), ("login", "登录")),
        (("搜索", "search"), ("search", "搜索")),
        (("提交", "submit"), ("submit", "提交")),
    )
    bonus = 0
    for keys, needles in pairs:
        if any(key in desc for key in keys) and any(needle in hay for needle in needles):
            bonus += 25
    return bonus


def pick_best_candidate(
    page,
    candidates: List[Dict[str, Any]],
    description: str = "",
) -> Optional[Dict[str, Any]]:
    """按评分从高到低验证。只接受 count==1，避免 get_by_role('button') 点到错误按钮。"""
    ordered = sorted(
        candidates or [],
        key=lambda c: int(c.get("score") or 0) + _description_bonus(c, description),
        reverse=True,
    )
    for cand in ordered:
        expr = cand.get("expr") or ""
        if not expr:
            continue
        probe = probe_expr(page, expr)
        log.info(
            f"[LocatorValidator] try {cand.get('type')} score={cand.get('score')} "
            f"expr={expr} count={probe.get('count')} visible={probe.get('visible')} "
            f"enabled={probe.get('enabled')} ok={probe.get('ok')}"
        )
        if not probe.get("ok"):
            continue
        if int(probe.get("count") or 0) != 1:
            log.info(f"[LocatorValidator] skip ambiguous locator count={probe.get('count')} expr={expr}")
            continue
        hay = f"{cand.get('value') or ''} {expr}".lower()
        desc_l = _clean(description).lower()
        if any(tok in desc_l for tok in ("登录", "login")):
            if any(tok in hay for tok in ("submit", "提交", "clear", "清空", "modal", "弹窗", "prev-page", "next-page", "tab-")):
                log.info(f"[LocatorValidator] skip conflicting locator for 登录: {expr}")
                continue
        winner = dict(cand)
        winner["probe"] = probe
        return winner
    return None


def _discover_dom_nodes(page) -> List[Dict[str, Any]]:
    script = """
    () => {
      const sel = 'input, textarea, button, select, a, [role="button"], [role="textbox"], [role="searchbox"]';
      return Array.from(document.querySelectorAll(sel)).slice(0, 80).map((el) => {
        const style = window.getComputedStyle(el);
        const r = el.getBoundingClientRect();
        const hidden = style.display === 'none' || style.visibility === 'hidden'
          || r.width < 2 || r.height < 2;
        return {
          tag: el.tagName.toLowerCase(),
          type: (el.getAttribute('type') || '').toLowerCase(),
          id: el.id || '',
          name: el.getAttribute('name') || '',
          placeholder: el.getAttribute('placeholder') || '',
          ariaLabel: el.getAttribute('aria-label') || '',
          role: el.getAttribute('role') || '',
          testId: el.getAttribute('data-testid') || el.getAttribute('data-test-id') || '',
          text: ((el.innerText || el.value || el.getAttribute('value') || '') + '').trim().slice(0, 80),
          hidden,
        };
      }).filter((n) => !n.hidden);
    }
    """
    try:
        nodes = page.evaluate(script)
    except Exception as exc:
        log.warning(f"[LocatorValidator] DOM 发现失败: {exc}")
        return []
    return [n for n in (nodes or []) if isinstance(n, dict)]


def _filter_nodes_for_intent(nodes: List[Dict[str, Any]], intent: str) -> List[Dict[str, Any]]:
    want_fill = intent in _FILL_ACTIONS
    skip_types = {"hidden", "checkbox", "radio", "file", "image"}
    out = []
    for node in nodes:
        tag = _clean(node.get("tag")).lower()
        ntype = _clean(node.get("type")).lower()
        role = _clean(node.get("role")).lower()
        if ntype in skip_types:
            continue
        if want_fill:
            if tag in {"input", "textarea"} or role in {"textbox", "searchbox"}:
                if ntype not in {"submit", "button"}:
                    out.append(node)
        else:
            if tag in {"button", "a"} or role == "button" or ntype in {"submit", "button"}:
                out.append(node)
    return out


def discover_candidates(page, intent: str) -> List[Dict[str, Any]]:
    nodes = _filter_nodes_for_intent(_discover_dom_nodes(page), intent)
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for node in nodes:
        for cand in candidates_from_dom_node(node):
            expr = cand.get("expr") or ""
            if not expr or expr in seen:
                continue
            seen.add(expr)
            out.append(cand)
    out.sort(key=lambda c: c["score"], reverse=True)
    return out


def _normalize_steps(case_data: Any) -> List[Dict[str, Any]]:
    if not isinstance(case_data, dict):
        return []
    steps = case_data.get("steps")
    cases = case_data.get("cases")
    collected: List[Dict[str, Any]] = []
    if isinstance(steps, list):
        collected.extend([s for s in steps if isinstance(s, dict)])
    if isinstance(cases, list):
        for case in cases:
            if isinstance(case, dict) and isinstance(case.get("steps"), list):
                collected.extend([s for s in case["steps"] if isinstance(s, dict)])
    return collected


def extract_intents(case_data: Any, elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    intents: List[Dict[str, Any]] = []
    for step in _normalize_steps(case_data):
        action = _clean(step.get("action")).lower()
        desc = _clean(step.get("description") or step.get("step") or step.get("name"))
        if action in _FILL_ACTIONS:
            intents.append({"intent": "fill", "description": desc, "step": step})
        elif action in _CLICK_ACTIONS:
            intents.append({"intent": "click", "description": desc, "step": step})
        elif not action:
            lower = desc.lower()
            if any(tok in desc for tok in ("输入", "填写", "填入")) or any(
                tok in lower for tok in ("fill", "type", "input", "search")
            ):
                intents.append({"intent": "fill", "description": desc, "step": step})
            elif any(tok in desc for tok in ("点击", "单击")) or "click" in lower:
                intents.append({"intent": "click", "description": desc, "step": step})

    if intents:
        return intents

    for elem in elements or []:
        if not isinstance(elem, dict):
            continue
        etype = _clean(elem.get("type") or elem.get("element_type")).lower()
        if etype in {"input", "searchbox", "textarea", "textbox"}:
            intents.append({"intent": "fill", "description": _clean(elem.get("name")), "element": elem})
        elif etype in {"button", "link"}:
            intents.append({"intent": "click", "description": _clean(elem.get("name")), "element": elem})
    return intents


def validate_on_page(
    page,
    elements: List[Dict[str, Any]],
    case_data: Any = None,
) -> Dict[str, Any]:
    """在已打开的 page 上验证候选并绑定 best_locator。"""
    elems = [dict(e) for e in (elements or []) if isinstance(e, dict)]
    intents = extract_intents(case_data, elems)
    if not intents:
        return {
            "status": LOCATOR_GENERATION_FAILED,
            "error": f"{LOCATOR_GENERATION_FAILED}: 没有可验证的交互意图",
            "elements": elems,
            "validated": [],
        }

    validated: List[Dict[str, Any]] = []
    failures: List[str] = []
    used_exprs: set[str] = set()
    case_blob = ""
    if isinstance(case_data, dict):
        case_blob = " ".join(
            str(case_data.get(k) or "")
            for k in ("requirement", "description", "case_name")
        )
    if "登录" in case_blob and not any(
        item.get("intent") == "click" and "登录" in (item.get("description") or "")
        for item in intents
    ):
        for item in intents:
            if item.get("intent") == "click":
                item["description"] = f"{item.get('description') or ''} 登录".strip()
                break

    for item in intents:
        intent = item["intent"]
        desc = item.get("description") or ""
        candidates = [
            c for c in collect_candidates_for_intent(intent, desc, elems)
            if (c.get("expr") or "") not in used_exprs
        ]
        winner = pick_best_candidate(page, candidates, desc)
        if winner is None:
            discovered = [
                c for c in discover_candidates(page, intent)
                if (c.get("expr") or "") not in used_exprs
            ]
            winner = pick_best_candidate(page, discovered, desc)
        if winner is None:
            failures.append(f"{intent}:{desc or '?'} 全部候选失败")
            continue
        used_exprs.add(winner.get("expr") or "")

        bound = {
            "name": desc or intent,
            "type": "input" if intent == "fill" else "button",
            "intent": intent,
            "source": "validated",
            "locator_validated": True,
            "playwright_expr": winner["expr"],
            "locator": winner["expr"],
            "best_locator": winner["expr"],
            "locator_score": winner.get("score"),
            "locator_type": winner.get("type"),
            "locator_candidates": candidates[:8],
            "probe": winner.get("probe"),
        }
        validated.append(bound)
        step = item.get("step")
        if isinstance(step, dict):
            step["locator"] = winner["expr"]
            step["playwright_expr"] = winner["expr"]

    if failures:
        return {
            "status": LOCATOR_GENERATION_FAILED,
            "error": f"{LOCATOR_GENERATION_FAILED}: {'; '.join(failures)}",
            "elements": elems,
            "validated": validated,
        }

    return {
        "status": "SUCCESS",
        "error": "",
        "elements": validated,
        "validated": validated,
    }


def validate_on_html(
    html: str,
    elements: List[Dict[str, Any]],
    case_data: Any = None,
) -> Dict[str, Any]:
    """单元测试入口：对本地 HTML 做真实 Playwright 验证。"""
    from playwright.sync_api import sync_playwright

    from app.utils.browser_launcher import get_launch_kwargs

    with sync_playwright() as pw:
        browser = pw.chromium.launch(**get_launch_kwargs())
        page = browser.new_page()
        try:
            page.set_content(html, wait_until="domcontentloaded")
            return validate_on_page(page, elements, case_data)
        finally:
            browser.close()


def _validate_locators_sync(
    target_url: str,
    elements: List[Dict[str, Any]],
    case_data: Any = None,
) -> Dict[str, Any]:
    from playwright.sync_api import sync_playwright

    from app.utils.browser_launcher import get_launch_kwargs

    log.info(f"[LocatorValidator] 打开页面验证 locator: {target_url}")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(**get_launch_kwargs())
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                locale="zh-CN",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                ),
            )
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            page = context.new_page()
            try:
                page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                try:
                    page.wait_for_load_state("load", timeout=15000)
                except Exception:
                    pass
                return validate_on_page(page, elements, case_data)
            finally:
                context.close()
                browser.close()
    except Exception as exc:
        log.error(f"[LocatorValidator] 打开页面失败: {exc}")
        return {
            "status": LOCATOR_GENERATION_FAILED,
            "error": f"{LOCATOR_GENERATION_FAILED}: 无法打开页面验证 locator: {exc}",
            "elements": elements or [],
            "validated": [],
        }


def validate_locators_on_page(
    target_url: str,
    elements: List[Dict[str, Any]],
    case_data: Any = None,
) -> Dict[str, Any]:
    """打开真实 URL，验证候选 locator。打不开页面也视为生成失败。"""
    url = _clean(target_url)
    if not url:
        return {
            "status": LOCATOR_GENERATION_FAILED,
            "error": f"{LOCATOR_GENERATION_FAILED}: 缺少目标 URL",
            "elements": elements or [],
            "validated": [],
        }

    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    try:
        asyncio.get_running_loop()
        in_async_loop = True
    except RuntimeError:
        in_async_loop = False

    if in_async_loop:
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_validate_locators_sync, url, elements, case_data).result(timeout=90)
    return _validate_locators_sync(url, elements, case_data)


def script_uses_validated(script: str, elements: List[Dict[str, Any]]) -> bool:
    text = script or ""
    exprs = [
        e.get("playwright_expr")
        for e in (elements or [])
        if isinstance(e, dict) and e.get("locator_validated") and e.get("playwright_expr")
    ]
    if not exprs:
        return False
    return all(expr in text for expr in exprs)
