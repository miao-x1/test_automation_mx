"""P1-1: 真实页面验证候选 locator，全部失败必须返回失败状态。"""
from app.agent.script.locator_strategy import LOCATOR_SCORES, candidates_from_element
from app.agent.script.locator_validator import (
    LOCATOR_GENERATION_FAILED,
    validate_on_html,
)


def test_placeholder_locator_success():
    result = validate_on_html(
        '<input placeholder="请输入用户名">',
        [{"type": "input", "placeholder": "请输入用户名"}],
        {"steps": [{"action": "fill", "description": "输入用户名"}]},
    )
    assert result["status"] == "SUCCESS"
    expr = result["elements"][0]["playwright_expr"]
    assert "get_by_placeholder" in expr
    assert "请输入用户名" in expr
    assert result["elements"][0]["locator_score"] == LOCATOR_SCORES["placeholder"]


def test_role_locator_success():
    result = validate_on_html(
        '<button>保存</button>',
        [{"type": "button", "role": "button", "text": "保存"}],
        {"steps": [{"action": "click", "description": "点击保存"}]},
    )
    assert result["status"] == "SUCCESS"
    expr = result["elements"][0]["playwright_expr"]
    assert "get_by_role" in expr
    assert "button" in expr


def test_css_fallback_success():
    result = validate_on_html(
        '<input name="user-email">',
        [{"type": "input", "placeholder": "不存在的占位符", "css": "input[name=user-email]"}],
        {"steps": [{"action": "fill", "description": "输入邮箱"}]},
    )
    assert result["status"] == "SUCCESS"
    expr = result["elements"][0]["playwright_expr"]
    assert "locator" in expr
    assert "user-email" in expr
    assert "get_by_placeholder" not in expr


def test_all_candidates_fail_returns_failed_status():
    result = validate_on_html(
        "<div>hello</div>",
        [{"type": "input", "placeholder": "请输入"}],
        {"steps": [{"action": "fill", "description": "输入关键词"}]},
    )
    assert result["status"] == LOCATOR_GENERATION_FAILED
    assert LOCATOR_GENERATION_FAILED in result["error"]
    assert result["validated"] == []


async def test_validate_locators_on_page_inside_asyncio_loop(monkeypatch):
    from app.agent.script.locator_validator import validate_locators_on_page

    def fake_sync(url, elements, case_data=None):
        return {
            "status": "SUCCESS",
            "error": "",
            "elements": [{"playwright_expr": 'page.get_by_role("textbox")', "locator_validated": True}],
            "validated": [],
        }

    monkeypatch.setattr(
        "app.agent.script.locator_validator._validate_locators_sync",
        fake_sync,
    )
    result = validate_locators_on_page(
        "https://www.baidu.com",
        [{"type": "input"}],
        {"steps": [{"action": "fill", "description": "输入"}]},
    )
    assert result["status"] == "SUCCESS"


def test_strategy_scores_prefer_testid_over_xpath():
    cands = candidates_from_element({
        "type": "button",
        "test_id": "submit-btn",
        "xpath": "//div[3]/button",
        "text": "提交",
    })
    types = [c["type"] for c in cands]
    assert types.index("test_id") < types.index("xpath")
    assert cands[0]["score"] == 100
