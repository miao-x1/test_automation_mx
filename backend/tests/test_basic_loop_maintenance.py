"""单页基础闭环维护：路径解析、URL 校验、缺图、SSE 收尾、定位失败文案。"""
import os
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))
os.environ.setdefault("USE_SQLITE", "True")
os.environ.setdefault("APP_ENV", "development")

import pytest

from app.agent.script.locator_builder import extract_url, infer_elements_from_cases
from app.agent.script.locator_validator import LOCATOR_GENERATION_FAILED, validate_on_html
from app.core.upload_paths import resolve_upload_path, resolve_upload_paths


def test_resolve_relative_upload_path(tmp_path, monkeypatch):
    from app.core import config
    monkeypatch.setattr(config.settings, "UPLOAD_DIR", str(tmp_path))
    nested = tmp_path / "requirement_images"
    nested.mkdir()
    shot = nested / "page.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n")
    resolved = resolve_upload_path("requirement_images/page.png")
    assert Path(resolved).is_file()
    assert resolve_upload_paths(["requirement_images/page.png"])[0] == resolved


def test_resolve_missing_image_does_not_crash(tmp_path, monkeypatch):
    from app.core import config
    monkeypatch.setattr(config.settings, "UPLOAD_DIR", str(tmp_path))
    resolved = resolve_upload_path("requirement_images/missing.png")
    assert resolved.endswith("missing.png")
    assert not Path(resolved).is_file()


def test_clip_execution_log_for_mysql():
    from app.services.execution.legacy_runner import _clip_db_text
    assert _clip_db_text(None) is None
    assert _clip_db_text("ok") == "ok"
    long = "x" * 70000
    clipped = _clip_db_text(long)
    assert len(clipped) < 70000
    assert clipped.endswith("[truncated]")


def test_page_url_required():
    assert extract_url("打开 https://127.0.0.1:8000/fixtures/basic-web-app/ 并登录")
    assert extract_url("随便测一下登录") == ""
    assert extract_url("ftp://internal.local/page") == ""


def test_element_agent_missing_image_returns_failed(tmp_path, monkeypatch):
    from app.core import config
    from app.agent.vision.element_agent import ElementAgent

    monkeypatch.setattr(config.settings, "UPLOAD_DIR", str(tmp_path))
    agent = ElementAgent()
    result = agent.execute(image_paths=["requirement_images/nope.png"])
    assert result["status"] == "FAILED"
    assert "图片不存在" in result["message"]


def test_element_agent_empty_image_is_invalid():
    from app.agent.vision.element_agent import ElementAgent
    result = ElementAgent().execute(image_paths=[])
    assert result["status"] == "INVALID_INPUT"


def test_infer_structured_actions_from_requirement_steps():
    cases = [{
        "title": "登录",
        "steps": [
            {"action": "fill", "description": "输入用户名"},
            {"action": "fill", "description": "输入密码"},
            {"action": "click", "description": "点击登录按钮"},
        ],
    }]
    elements = infer_elements_from_cases(cases)
    assert len(elements) >= 2
    assert all(item.get("playwright_expr") or item.get("type") for item in elements)


def test_fixture_login_steps_get_distinct_locators():
    html = (backend_dir.parent / "test-fixtures" / "basic-web-app" / "index.html").read_text(encoding="utf-8")
    result = validate_on_html(
        html,
        [],
        {
            "steps": [
                {"action": "fill", "description": "输入用户名"},
                {"action": "fill", "description": "输入密码"},
                {"action": "click", "description": "点击登录按钮"},
            ]
        },
    )
    assert result["status"] == "SUCCESS"
    exprs = [e["playwright_expr"] for e in result["elements"]]
    assert len(set(exprs)) == 3
    assert any("username" in expr or "用户名" in expr for expr in exprs)
    assert any("password" in expr or "密码" in expr for expr in exprs)
    assert any("login" in expr or "登录" in expr for expr in exprs)
    assert all("get_by_role(\"textbox\")" not in expr for expr in exprs)
    assert all("get_by_role(\"button\")" not in expr or "name=" in expr for expr in exprs)
    assert all("submit-btn" not in expr for expr in exprs)


def test_fixture_login_requirement_does_not_click_submit():
    html = (backend_dir.parent / "test-fixtures" / "basic-web-app" / "index.html").read_text(encoding="utf-8")
    result = validate_on_html(
        html,
        [],
        {
            "requirement": "打开页面，在用户名输入 alice，在密码输入 pass123，点击登录，验证出现登录成功。",
            "steps": [
                {"action": "fill", "description": "输入用户名"},
                {"action": "fill", "description": "输入密码"},
                {"action": "click", "description": "点击提交按钮"},
            ],
        },
    )
    assert result["status"] == "SUCCESS"
    click_expr = next(e["playwright_expr"] for e in result["elements"] if e.get("intent") == "click")
    assert "submit-btn" not in click_expr
    assert "login-btn" in click_expr or "登录" in click_expr


def test_login_template_does_not_assert_password_in_url():
    from app.agent.script.script_generation_agent import ScriptGenerationAgent

    script = ScriptGenerationAgent()._generate_from_template(
        {
            "case_name": "login_test",
            "requirement": "在用户名输入 alice，在密码输入 pass123，点击登录，验证出现登录成功。",
            "steps": [
                {"action": "fill", "description": "输入用户名", "locator": 'page.get_by_test_id("username")'},
                {"action": "fill", "description": "输入密码", "locator": 'page.get_by_test_id("password")'},
                {"action": "click", "description": "点击登录", "locator": 'page.get_by_test_id("login-btn")'},
            ],
        },
        [],
        "http://127.0.0.1:8000/fixtures/basic-web-app/",
    )
    assert "get_by_test_id(\"username\")" in script
    assert "get_by_test_id(\"password\")" in script
    assert "alice" in script
    assert "pass123" in script
    assert "to_have_url" not in script
    assert "登录成功" in script


def test_search_template_still_asserts_url():
    from app.agent.script.script_generation_agent import ScriptGenerationAgent

    script = ScriptGenerationAgent()._generate_from_template(
        {
            "case_name": "search_test",
            "steps": [
                {"action": "fill", "description": "输入搜索词", "locator": 'page.get_by_role("searchbox")', "value": "自动化测试"},
                {"action": "click", "description": "点击搜索", "locator": 'page.get_by_role("button", name="搜索")'},
            ],
        },
        [],
        "https://www.baidu.com",
    )
    assert "to_have_url" in script
    assert "自动化测试" in script


def test_fixture_html_locators_and_missing_element():
    html = (backend_dir.parent / "test-fixtures" / "basic-web-app" / "index.html").read_text(encoding="utf-8")
    ok = validate_on_html(
        html,
        [
            {"type": "input", "placeholder": "请输入用户名", "test_id": "username"},
            {"type": "button", "text": "登录", "test_id": "login-btn"},
        ],
        {"steps": [{"action": "fill", "description": "输入用户名"}, {"action": "click", "description": "登录"}]},
    )
    assert ok["status"] == "SUCCESS"
    missing = validate_on_html(
        "<div>只有静态文本</div>",
        [{"type": "input", "placeholder": "请输入不存在的框"}],
        {"steps": [{"action": "fill", "description": "输入不存在的框"}]},
    )
    assert missing["status"] == LOCATOR_GENERATION_FAILED
    assert LOCATOR_GENERATION_FAILED in missing["error"]


def test_rule_based_analysis_element_not_found():
    from app.agent.execution.execution_agent import ExecutionAgent
    analysis = ExecutionAgent()._rule_based_analysis(
        "TimeoutError: page.get_by_role('button', name='不存在')",
        "Locator.click: Timeout 30000ms exceeded",
    )
    assert analysis["fail_step"] == "元素未找到"


@pytest.mark.asyncio
async def test_sse_wrapper_marks_failed_without_terminal(monkeypatch):
    from app.api.requirement import sse_wrapper
    from app.models.requirement_task import RequirementStatus

    marked = []
    monkeypatch.setattr(
        "app.api.requirement._mark_requirement_status",
        lambda task_id, status, error_message=None: marked.append((task_id, status, error_message)),
    )

    async def events():
        yield {"event": "flow_start"}

    async for _ in sse_wrapper(events(), task_id=88):
        pass
    assert marked
    assert marked[0][0] == 88
    assert marked[0][1] == RequirementStatus.FAILED


@pytest.mark.asyncio
async def test_execute_sse_marks_failed_on_disconnect(monkeypatch):
    from types import SimpleNamespace
    from app.models.execution_record import ExecutionRecord, ExecutionStatus
    from app.services.execution.legacy_runner import LegacyExecutionRunner

    rec = SimpleNamespace(
        id=7,
        task_id=3,
        status=ExecutionStatus.PENDING,
        error_message=None,
    )
    script = SimpleNamespace(task_id=3, script_content="pass")

    class _Query:
        def __init__(self, obj):
            self.obj = obj

        def filter(self, *_a, **_k):
            return self

        def first(self):
            return self.obj

    class _DB:
        def query(self, model):
            return _Query(rec if model is ExecutionRecord else script)

        def commit(self):
            return None

        def refresh(self, _obj):
            return None

        def close(self):
            return None

        def rollback(self):
            return None

    monkeypatch.setattr("app.services.execution.legacy_runner.SessionLocal", lambda: _DB())

    class _SlowAgent:
        def execute_script(self, **_kwargs):
            import time
            time.sleep(30)
            return {"status": "success", "success_count": 1, "failed_count": 0}

    monkeypatch.setattr(
        "app.services.execution.legacy_runner.AgentRegistry.create",
        lambda *_a, **_k: _SlowAgent(),
    )

    agen = LegacyExecutionRunner.run_execution(7)
    first = await agen.__anext__()
    assert "开始执行" in first
    await agen.aclose()
    assert rec.status == ExecutionStatus.FAILED
    assert rec.error_message


@pytest.mark.asyncio
async def test_sse_wrapper_keeps_success(monkeypatch):
    from app.api.requirement import sse_wrapper

    marked = []
    monkeypatch.setattr("app.api.requirement._persist_requirement_result", lambda *a, **k: None)
    monkeypatch.setattr(
        "app.api.requirement._mark_requirement_status",
        lambda *a, **k: marked.append(a),
    )

    async def events():
        yield {"event": "flow_success"}
        yield {"event": "done"}

    async for _ in sse_wrapper(events(), task_id=89):
        pass
    assert marked == []
