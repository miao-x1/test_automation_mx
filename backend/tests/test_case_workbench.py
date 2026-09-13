from app.services.case_workbench import CaseWorkbenchService, _normalize_steps
from app.services.test_design_doc import fallback_from_requirement
from app.services.requirement_analysis_doc import normalize_document as normalize_requirement


def _requirement():
    return normalize_requirement(
        {
            "requirements": [
                {"id": "REQ-001", "text": "用户登录后进入首页"},
                {"id": "REQ-002", "text": "密码错误时提示错误"},
            ],
            "overview": {"name": {"text": "登录", "evidence_kind": "explicit"}},
            "functions": [{
                "id": "FN-001",
                "module": "用户",
                "name": "登录",
                "operations": ["输入账号", "输入密码", "提交"],
                "outputs": ["进入首页"],
                "inputs": ["账号", "密码"],
                "preconditions": ["已注册"],
                "sources": ["REQ-001"],
            }],
            "exceptions": [
                {"scenario": "错误密码", "defined": True, "requirement": "提示错误", "sources": ["REQ-002"]},
            ],
            "status": "confirmed",
        },
        "用户登录后进入首页。密码错误时提示错误。",
        [],
    )


def test_from_text_does_not_need_design():
    service = CaseWorkbenchService()
    drafts = service._from_text("测试一个电商登录功能，需要覆盖正常登录、密码错误、账号不存在、账号锁定、验证码错误。", {})
    names = " ".join(item["case_name"] for item in drafts)
    assert "正常登录" in names
    assert "错误密码" in names
    assert "账号不存在" in names
    assert "账号锁定" in names
    assert "验证码错误" in names
    for item in drafts:
        assert item["steps"]
        assert item["expected_result"]


def test_from_design_inherits_td_ts_req():
    design = fallback_from_requirement(_requirement(), "llm unavailable")
    service = CaseWorkbenchService()
    drafts = service._from_design(design, {})
    assert drafts
    assert any(item.get("test_design_ids") for item in drafts)
    assert any(item.get("test_scenario_ids") or item.get("requirement_ids") for item in drafts)
    assert all(item.get("case_name") for item in drafts)
    types = {item.get("type") for item in drafts}
    assert "functional" in types or "error" in types
    assert any(item.get("steps") for item in drafts)


def test_from_requirement_without_design():
    service = CaseWorkbenchService()
    drafts = service._from_requirement(_requirement(), {})
    assert any("登录" in (item.get("case_name") or "") for item in drafts)
    assert any("REQ-001" in (item.get("requirement_ids") or []) for item in drafts)


def test_quality_flags_vague_and_missing():
    service = CaseWorkbenchService()
    quality = service.check_quality([
        {"case_code": "TC-1", "case_name": "登录", "case_name": "登录", "steps": [{"action": "检查结果"}], "expected_result": ""},
        {"case_code": "TC-2", "case_name": "登录", "precondition": "有账号", "test_data": "test001", "steps": [{"action": "打开登录页", "data": "test001", "expected": "页面打开"}], "expected_result": "进入首页"},
    ])
    assert quality["duplicates"]
    assert any("模糊" in item["problem"] or "预期" in item["problem"] or "数据" in item["problem"] for item in quality["issues"])


def test_normalize_steps_are_structured():
    steps = _normalize_steps(["打开登录页", "输入账号"], data="test001", expected="进入首页")
    assert steps[0]["stepNo"] == 1
    assert steps[0]["action"] == "打开登录页"
    assert steps[-1]["expected"] == "进入首页"


def test_generate_refuses_empty_without_blocking_on_design():
    class FakeReq:
        def get(self, *args, **kwargs):
            return {"status": "empty", "requirements": [], "functions": []}

    class FakeDesign:
        def get(self, *args, **kwargs):
            return {"status": "empty", "objects": [], "scenarios": []}

    service = CaseWorkbenchService()
    service.requirements = FakeReq()
    service.designs = FakeDesign()
    try:
        service.generate(1, 1, {})
        assert False
    except ValueError as exc:
        assert "不依赖上一阶段" in str(exc)
        assert "请先完成测试设计" not in str(exc)
