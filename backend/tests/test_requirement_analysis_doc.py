from app.services.requirement_analysis_doc import (
    compute_completeness,
    empty_document,
    fallback_document,
    normalize_document,
    parse_json_object,
    split_requirements,
    strip_agent_tags,
    to_design_input,
)
from app.services.testing_brain import classify_intent


def test_intent_recognizes_prd_analysis():
    assert classify_intent("分析当前需求") == "analyze_requirement"
    assert classify_intent("解析这份 PRD") == "analyze_requirement"
    assert classify_intent("分析当前项目") != "analyze_requirement"


def test_split_requirements_keeps_original_ids():
    items = split_requirements("REQ-001 用户登录后进入首页\nREQ-002 管理员可以禁用账号")
    assert [item["id"] for item in items] == ["REQ-001", "REQ-002"]
    assert "登录后进入首页" in items[0]["text"]


def test_split_requirements_does_not_invent_rules():
    items = split_requirements("用户可以修改订单。")
    assert items
    assert items[0]["id"] == "REQ-001"
    assert items[0]["text"] == "用户可以修改订单。"


def test_fallback_marks_missing_and_does_not_invent_rules():
    doc = fallback_document("用户可以修改订单。", "llm unavailable")
    assert doc["llm_used"] is False
    assert doc["rules"] == []
    assert doc["functions"] == []
    assert any(item["defined"] is False for item in doc["exceptions"])
    assert doc["counts"]["requirements"] == 1
    assert "修改订单" in doc["requirements"][0]["text"]
    assert doc["overview"]["goal"]["evidence_kind"] == "missing"


def test_normalize_does_not_fill_data_rules():
    doc = normalize_document(
        {
            "requirements": [{"id": "REQ-001", "text": "用户填写手机号"}],
            "data": [{"object": "用户", "field": "手机号"}],
            "status": "draft",
        },
        "用户填写手机号",
        [],
    )
    row = doc["data"][0]
    assert row["type"] == "需求缺失"
    assert row["required"] == "需求缺失"
    assert row["evidence_kind"] == "missing"


def test_completeness_drops_when_gaps_exist():
    thin = normalize_document({"requirements": [{"text": "登录"}], "status": "draft"}, "登录", [])
    rich = normalize_document(
        {
            "requirements": [{"id": "REQ-001", "text": "登录"}],
            "overview": {
                "name": {"text": "登录", "evidence_kind": "explicit"},
                "goal": {"text": "进入首页", "evidence_kind": "explicit"},
                "background": {"text": "已有账号", "evidence_kind": "explicit"},
                "users": {"text": "注册用户", "evidence_kind": "explicit"},
                "in_scope": {"text": "登录", "evidence_kind": "explicit"},
            },
            "functions": [{"module": "用户", "name": "登录", "description": "账号登录"}],
            "rules": [{"statement": "密码错误不可登录"}],
            "roles": [{"name": "用户", "can": ["登录"]}],
            "flows": [{"name": "登录", "steps": ["开始", "登录"]}],
            "data": [{"object": "用户", "field": "账号", "type": "string", "required": "是"}],
            "exceptions": [{"scenario": "空值", "defined": False}],
            "gaps": [],
            "risks": [{"level": "高", "point": "撞库"}],
            "status": "draft",
        },
        "登录",
        [],
    )
    assert compute_completeness(rich) > compute_completeness(thin)
    assert rich["counts"]["high_risks"] == 1


def test_design_input_is_traceable_not_test_cases():
    doc = normalize_document(
        {
            "requirements": [{"id": "REQ-001", "text": "用户登录后进入首页"}],
            "functions": [{"id": "FN-001", "module": "用户", "name": "登录", "sources": ["REQ-001"]}],
            "rules": [{"id": "BR-001", "category": "状态限制", "statement": "未注册不可登录", "sources": ["REQ-001"]}],
            "status": "draft",
        },
        "用户登录后进入首页",
        [],
    )
    text = to_design_input(doc)
    assert "REQ-001" in text
    assert "不是测试用例" in text
    assert "TC-" not in text


def test_strip_agent_tags_and_parse_json():
    assert strip_agent_tags("@当前项目 @需求分析\n分析当前需求") == "分析当前需求"
    parsed = parse_json_object("```json\n{\"functions\":[]}\n```")
    assert parsed["functions"] == []


def test_understand_agent_writes_requirement_doc_not_cases(monkeypatch):
    from app.services.project_agent import ProjectAgentService
    from app.services import project_agent as module

    class FakeDocs:
        def __init__(self, memory=None):
            pass

        def analyze_from_question(self, *args, **kwargs):
            return {
                "status": "draft",
                "completeness": 61,
                "counts": {"functions": 2, "rules": 3, "open_questions": 1, "high_risks": 0, "requirements": 4},
                "interaction": {
                    "summary": "已完成需求分析，共识别 2 项功能、3 条业务规则。另有 1 个关键问题，补充后可以提高准确度，也可以直接跳过。",
                    "questions": [{"id": "Q1", "question": "哪些订单状态允许修改？", "skippable": True}],
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

    monkeypatch.setattr(module, "RequirementAnalysisDocService", FakeDocs)
    agent = ProjectAgentService()
    agent.memory = FakeMemory()
    agent.indexer = FakeIndexer()
    result = agent.ask(1, 1, "分析这个需求", workspace="understand")
    assert result["intent"] == "analyze_requirement"
    assert result["actions"][0]["type"] == "requirement_analysis"
    assert result["actions"][0]["path"] == "/understand/requirements"
    assert not result["actions"][0].get("cases")
    assert "已生成" not in result["answer"]
    assert "2 项功能" in result["answer"]
    assert "哪些订单状态允许修改" in result["answer"]
    assert "不会在本阶段生成测试用例" in result["answer"]


def test_empty_document_is_honest():
    doc = empty_document()
    assert doc["status"] == "empty"
    assert doc["completeness"] == 0
    assert doc["functions"] == []
    assert "还没有" in doc["interaction"]["summary"]
