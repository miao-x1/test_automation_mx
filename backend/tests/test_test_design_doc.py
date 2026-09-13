import json

from app.services.requirement_analysis_doc import normalize_document as normalize_requirement
from app.services.test_design_doc import (
    attach_workbench,
    compact_requirement,
    empty_document,
    fallback_from_requirement,
    normalize_document,
    requirement_brief,
    source_index,
    to_case_input,
    to_task_input,
)
from app.services.testing_brain import classify_intent


def _requirement():
    return normalize_requirement(
        {
            "requirements": [
                {"id": "REQ-001", "text": "用户登录后进入首页"},
                {"id": "REQ-002", "text": "密码错误时提示错误"},
            ],
            "overview": {
                "name": {"text": "登录", "evidence_kind": "explicit"},
                "in_scope": {"text": "登录", "evidence_kind": "explicit"},
                "out_of_scope": {"text": "注册", "evidence_kind": "explicit"},
            },
            "functions": [{
                "id": "FN-001",
                "module": "用户",
                "name": "登录",
                "description": "账号密码登录",
                "inputs": ["账号", "密码"],
                "preconditions": ["已注册"],
                "operations": ["输入账号密码", "提交"],
                "outputs": ["进入首页"],
                "sources": ["REQ-001"],
            }],
            "exceptions": [
                {"scenario": "错误密码", "defined": True, "requirement": "提示错误", "sources": ["REQ-002"]},
                {"scenario": "并发登录", "defined": False, "requirement": "需求未定义"},
            ],
            "rules": [{"id": "BR-001", "statement": "密码错误不可登录", "sources": ["REQ-002"]}],
            "status": "confirmed",
        },
        "用户登录后进入首页。密码错误时提示错误。",
        [],
    )


def test_design_intent_in_design_workspace():
    assert classify_intent("根据已有需求分析做测试设计", "design") == "design_test"
    assert classify_intent("生成测试场景", "design") == "design_test"
    assert classify_intent("帮我设计当前项目的测试", "design") == "design_test"
    assert classify_intent("给我登录功能测试用例", "design") == "generate_cases"
    assert classify_intent("分析这个需求") == "analyze_requirement"


def test_empty_design_does_not_pretend_ready():
    doc = empty_document()
    assert doc["status"] == "empty"
    assert doc["objects"] == []
    assert "需求分析" in doc["interaction"]["summary"]


def test_fallback_traces_to_requirement_and_does_not_invent_concurrency():
    req = _requirement()
    doc = fallback_from_requirement(req, "llm unavailable")
    assert doc["llm_used"] is False
    assert doc["objects"]
    first = doc["objects"][0]
    assert first["id"].startswith("TD-")
    assert "REQ-001" in first["req_ids"]
    assert any(item["dimension"] == "normal" for item in doc["scenarios"])
    assert any(item["req_ids"] and "REQ-001" in item["req_ids"] for item in doc["scenarios"])
    assert any(item.get("item") == "注册" for item in doc["scope"]["out_of_scope"])
    assert not any("编造" in (item.get("expected") or "") for item in doc["scenarios"])
    invented = [item for item in doc["scenarios"] if "并发" in (item.get("name") or "") and item.get("dimension") == "concurrency"]
    assert invented == []


def test_normalize_keeps_trace_and_missing_data():
    doc = normalize_document(
        {
            "objects": [{"id": "TD-001", "name": "登录", "req_ids": ["REQ-001"]}],
            "scenarios": [{"id": "TS-001", "td_id": "TD-001", "name": "正确密码", "req_ids": ["REQ-001"], "dimension": "normal"}],
            "data": [{"object": "用户", "field": "密码"}],
            "coverage": [{"req_id": "REQ-001", "td_ids": ["TD-001"], "ts_ids": ["TS-001"], "covered": True}],
            "status": "draft",
        },
        _requirement(),
    )
    assert doc["data"][0]["min"] == "需求缺失"
    assert doc["data"][0]["max"] == "需求缺失"
    assert doc["scenarios"][0]["req_ids"] == ["REQ-001"]
    assert "REQ-001" in to_task_input(doc)
    assert "不是完整测试用例" in to_task_input(doc)
    assert "TC-" not in to_task_input(doc)
    assert any(item["req_id"] == "REQ-002" and item["covered"] is False for item in doc["coverage"])
    packed = to_case_input(doc)
    assert packed["kind"] == "test_design_case_input"
    assert packed["objects"][0]["id"] == "TD-001"
    assert "TC-" not in json.dumps(packed, ensure_ascii=False)


def test_workbench_inherits_requirement_without_redescribing():
    req = _requirement()
    brief = requirement_brief(req)
    assert brief["available"] is True
    assert brief["name"] == "登录"
    assert brief["requirements"][0]["id"] == "REQ-001"
    assert any(item["statement"] == "密码错误不可登录" for item in brief["rules"])
    index = source_index(req)
    assert index["REQ-001"]["text"]
    assert index["FN-001"]["title"] == "登录"
    empty = attach_workbench(empty_document(), req)
    assert empty["requirement_brief"]["available"] is True
    assert empty["plan"]["ready"] is False
    assert "登录" in empty["plan"]["headline"]
    designed = fallback_from_requirement(req, "llm unavailable")
    assert designed["plan"]["ready"] is True
    assert designed["plan"]["objects"] >= 1
    assert "测试对象" in designed["plan"]["headline"]


def test_compact_requirement_is_what_design_reads():
    packed = compact_requirement(_requirement())
    assert packed["requirements"][0]["id"] == "REQ-001"
    assert packed["functions"][0]["name"] == "登录"
    assert "source_text" not in packed


def test_design_service_refuses_without_requirement():
    from app.services.test_design_doc import TestDesignDocService

    class FakeReq:
        def get(self, *args, **kwargs):
            return empty_document() if False else {
                "status": "empty",
                "requirements": [],
                "functions": [],
            }

    class FakeMemory:
        def get_by_title(self, *args, **kwargs):
            return None
        def remember(self, *args, **kwargs):
            return {}

    service = TestDesignDocService(memory=FakeMemory(), requirements=FakeReq())
    try:
        service.design(1, 1)
        raise AssertionError("should refuse")
    except ValueError as exc:
        assert "需求分析" in str(exc)


def test_design_workspace_agent_does_not_emit_cases(monkeypatch):
    from app.services.project_agent import ProjectAgentService
    from app.services import project_agent as module

    class FakeDocs:
        def __init__(self, memory=None):
            pass

        def design_from_question(self, *args, **kwargs):
            return {
                "status": "draft",
                "completeness": 70,
                "counts": {"objects": 2, "scenarios": 5, "open_questions": 1},
                "interaction": {
                    "summary": "已完成测试设计，共 2 个测试对象、5 个测试场景。另有 1 个关键问题，补充后可以提高准确度，也可以跳过。",
                    "questions": [{"question": "禁用账号是否允许登录？"}],
                },
            }

    class FakeMemory:
        def search(self, *args, **kwargs):
            return []
        def remember(self, *args, **kwargs):
            return {}

    class FakeIndexer:
        def query_index(self, *args, **kwargs):
            return []

    monkeypatch.setattr(module, "TestDesignDocService", FakeDocs)
    agent = ProjectAgentService()
    agent.memory = FakeMemory()
    agent.indexer = FakeIndexer()
    result = agent.ask(1, 1, "根据已有需求分析做测试设计", workspace="design")
    assert result["intent"] == "design_test"
    assert result["actions"][0]["type"] == "design_test"
    assert not result["actions"][0].get("cases")
    assert "2 个测试对象" in result["answer"]
    assert "不生成完整测试用例" in result["answer"]
