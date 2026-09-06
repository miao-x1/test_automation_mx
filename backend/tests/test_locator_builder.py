"""P1-1: 禁止 TODO_REPLACE / 空 locator 冒充脚本生成成功。"""
from app.agent.script.locator_builder import (
    build_playwright_locator,
    enrich_elements,
    extract_url,
    is_placeholder_url,
    script_has_invalid_locators,
    usable_elements,
)
from app.agent.script.script_generation_agent import ScriptGenerationAgent


def test_placeholder_url_rejected():
    assert is_placeholder_url("") is True
    assert is_placeholder_url("https://TODO_REPLACE") is True
    assert is_placeholder_url("https://TODO_REPLACE_WITH_REAL_URL") is True
    assert is_placeholder_url("https://example.com/login") is True
    assert is_placeholder_url("https://www.baidu.com/s") is False


def test_extract_url_from_requirement_text():
    assert extract_url("打开 https://www.baidu.com 并搜索") == "https://www.baidu.com"
    assert extract_url("https://TODO_REPLACE") == ""


def test_build_locator_from_element_agent_fields():
    expr = build_playwright_locator({
        "name": "搜索按钮",
        "type": "button",
        "text": "搜索",
    })
    assert expr == 'page.get_by_role("button", name="搜索")'


def test_build_locator_placeholder_and_test_id():
    assert build_playwright_locator({
        "type": "input",
        "placeholder": "请输入用户名",
    }) == 'page.get_by_placeholder("请输入用户名")'
    assert build_playwright_locator({
        "type": "button",
        "test_id": "submit-btn",
    }) == 'page.get_by_test_id("submit-btn")'


def test_empty_element_has_no_locator():
    assert build_playwright_locator({"name": "", "type": "div"}) is None
    assert build_playwright_locator({"locator": ""}) is None
    assert build_playwright_locator({"locator": "TODO_REPLACE"}) is None


def test_enrich_elements_fills_playwright_expr():
    items = enrich_elements([{"name": "登录", "type": "button", "text": "登录"}])
    assert items[0]["playwright_expr"].startswith("page.get_by_role")
    assert usable_elements(items)


def test_invalid_script_detected():
    assert script_has_invalid_locators('page.goto("https://TODO_REPLACE")')
    assert script_has_invalid_locators('page.locator("").click()')
    assert script_has_invalid_locators("")
    assert script_has_invalid_locators(
        'page.goto("https://www.baidu.com")\npage.get_by_role("button", name="搜索").click()'
    ) is None


async def test_generate_fails_without_url():
    result = await ScriptGenerationAgent().execute(
        test_cases={"case_name": "t", "steps": []},
        elements=[{"name": "搜索", "type": "button", "text": "搜索"}],
        target_url="",
    )
    assert result["status"] == "FAILED"
    assert result["script_content"] == ""
    assert "URL" in result["error"]


def test_infer_elements_from_wrapped_cases():
    from app.agent.script.locator_builder import infer_elements_from_cases
    elems = infer_elements_from_cases([
        {"case_name": "search", "steps": [
            {"action": "fill", "description": "在搜索框输入关键词", "locator": ""},
            {"action": "click", "description": "点击搜索按钮", "locator": ""},
        ]}
    ])
    assert any(e.get("intent") == "fill" and e.get("source") == "inferred" for e in elems)
    assert all(e.get("placeholder") != "搜索" for e in elems)


def test_infer_elements_from_search_steps():
    from app.agent.script.locator_builder import infer_elements_from_cases
    elems = infer_elements_from_cases({
        "steps": [
            {"action": "fill", "description": "在搜索框输入关键词", "locator": ""},
            {"action": "click", "description": "点击搜索按钮", "locator": ""},
        ]
    })
    assert any(e.get("intent") == "fill" for e in elems)
    assert any(e.get("intent") == "click" for e in elems)
    assert all(not e.get("placeholder") for e in elems)


async def test_generate_fails_without_locator():
    result = await ScriptGenerationAgent().execute(
        test_cases={"case_name": "t", "steps": []},
        elements=[{"name": "", "type": "unknown"}],
        target_url="https://www.baidu.com",
    )
    assert result["status"] == "FAILED"
    assert result["script_content"] == ""
    assert "定位器" in result["error"]


def _fake_validate(_url, elements, case_data=None):
    from app.agent.script.locator_builder import enrich_elements
    enriched = enrich_elements(list(elements or []))
    if not enriched:
        enriched = [
            {
                "name": "input",
                "type": "input",
                "intent": "fill",
                "playwright_expr": 'page.get_by_role("textbox")',
                "locator": 'page.get_by_role("textbox")',
            },
            {
                "name": "button",
                "type": "button",
                "intent": "click",
                "playwright_expr": 'page.get_by_role("button")',
                "locator": 'page.get_by_role("button")',
            },
        ]
    for item in enriched:
        item["locator_validated"] = True
        if not item.get("playwright_expr"):
            item["playwright_expr"] = 'page.get_by_role("textbox")'
            item["locator"] = item["playwright_expr"]
    return {"status": "SUCCESS", "elements": enriched, "error": ""}


async def test_execute_reads_cases_list_from_pipeline(monkeypatch):
    """orchestrator merge_input 把 CaseResult 摊平为 cases=list。"""
    agent = ScriptGenerationAgent()

    def boom(*_a, **_k):
        raise RuntimeError("skip llm")

    monkeypatch.setattr(agent, "_generate_level1", boom)
    monkeypatch.setattr(agent, "_generate_level3", boom)
    monkeypatch.setattr(
        "app.agent.script.script_generation_agent.validate_locators_on_page",
        _fake_validate,
    )
    result = await agent.execute(
        cases=[{
            "case_name": "search",
            "steps": [
                {"action": "fill", "description": "在搜索框输入关键词", "locator": ""},
                {"action": "click", "description": "点击搜索按钮", "locator": ""},
            ],
        }],
        elements=[],
        requirement="打开 https://www.baidu.com 搜索",
        target_url="",
    )
    assert result["status"] == "SUCCESS"
    assert "get_by_" in result["script_content"]
    assert "TODO_REPLACE" not in result["script_content"]


def test_infer_fill_value_from_requirement_text():
    from app.agent.script.locator_builder import infer_fill_value
    assert infer_fill_value(
        {"action": "fill", "description": "在搜索框输入关键词"},
        {"requirement": "打开 https://www.baidu.com ，在搜索框输入自动化测试，点击搜索按钮"},
    ) == "自动化测试"
    assert infer_fill_value({"action": "fill", "value": "hello"}, {}) == "hello"
    req = "打开页面，在用户名输入 alice，在密码输入 pass123，点击登录"
    assert infer_fill_value(
        {"action": "fill", "description": "输入用户名"},
        {"requirement": req},
    ) == "alice"
    assert infer_fill_value(
        {"action": "fill", "description": "输入密码"},
        {"requirement": req},
    ) == "pass123"


def test_infer_elements_from_string_steps():
    from app.agent.script.locator_builder import infer_elements_from_cases
    elems = infer_elements_from_cases({
        "title": "百度搜索",
        "steps": "1. 在搜索框输入自动化测试\n2. 点击搜索按钮",
    })
    assert any(e.get("intent") in {"fill", "click"} for e in elems)


async def test_generate_level4_uses_role_locator(monkeypatch):
    agent = ScriptGenerationAgent()

    def boom(*_a, **_k):
        raise RuntimeError("skip llm")

    monkeypatch.setattr(agent, "_generate_level1", boom)
    monkeypatch.setattr(agent, "_generate_level3", boom)
    monkeypatch.setattr(
        "app.agent.script.script_generation_agent.validate_locators_on_page",
        _fake_validate,
    )

    result = await agent.execute(
        test_cases={"case_name": "search", "steps": [{"action": "click", "description": "搜索"}]},
        elements=[{"name": "搜索", "type": "button", "text": "搜索"}],
        target_url="https://www.baidu.com",
    )
    assert result["status"] == "SUCCESS"
    assert "TODO_REPLACE" not in result["script_content"]
    assert "page.locator(\"\")" not in result["script_content"]
    assert "get_by_role" in result["script_content"]
    assert "https://www.baidu.com" in result["script_content"]
