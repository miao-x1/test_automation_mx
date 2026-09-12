from app.services.testing_brain import (
    build_professional_cases,
    cases_to_playwright,
    check_case_coverage,
    classify_intent,
    infer_module,
)
from app.services.project_agent import ProjectAgentService


def test_intent_picks_shortest_path():
    assert classify_intent("什么是冒烟测试？") == "answer"
    assert classify_intent("帮我找支付功能在哪个文件") == "locate"
    assert classify_intent("给我登录功能测试用例") == "generate_cases"
    assert classify_intent("分析这个需求") == "analyze_requirement"
    assert classify_intent("帮我全面测试") == "full_test"
    assert classify_intent("帮我测试登录") == "create_task"
    assert classify_intent("补充边界测试") == "supplement_boundary"
    assert classify_intent("检查测试覆盖率") == "check_coverage"
    assert classify_intent("把测试用例转成Playwright") == "to_automation"
    assert classify_intent("分析失败原因") == "analyze_failure"


def test_professional_cases_have_table_fields():
    cases = build_professional_cases("登录", "登录功能")
    assert len(cases) >= 3
    first = cases[0]
    assert first["case_code"].startswith("TC-")
    assert first["module"] == "登录"
    assert first["scenario"]
    assert first["precondition"]
    assert first["steps"]
    assert first["test_data"]
    assert first["expected_result"]
    assert first["priority"] in {"P0", "P1", "P2", "P3"}
    assert first["type"]
    assert first["tags"]
    assert first["status"] == "draft"


def test_coverage_and_playwright_use_same_cases():
    cases = build_professional_cases("支付", "支付功能")
    coverage = check_case_coverage(cases, "支付功能")
    assert coverage["case_count"] == len(cases)
    assert "score" in coverage
    script = cases_to_playwright(cases, "支付")
    assert "import { test, expect }" in script
    assert "playwright" in script.lower() or "test(" in script


def test_infer_module_from_user_goal():
    assert infer_module("给我登录功能测试用例") == "登录"
    assert infer_module("帮我测试支付") == "支付"


def test_agent_answer_does_not_open_full_flow():
    agent = ProjectAgentService()

    class FakeIndexer:
        def query_index(self, *args, **kwargs):
            return []

    class FakeMemory:
        def search(self, *args, **kwargs):
            return []
        def remember(self, *args, **kwargs):
            return {}

    agent.indexer = FakeIndexer()
    agent.memory = FakeMemory()
    result = agent.ask(1, 1, "什么是冒烟测试？", workspace="understand")
    assert result["intent"] == "answer"
    assert "没有进入完整测试流程" in result["answer"]
    assert result["path"] == "直接回答"


def test_agent_locate_still_reuses_index():
    agent = ProjectAgentService()

    class FakeIndexer:
        def query_index(self, user_id, project_id, keyword=None, kind=None, path=None, limit=40):
            if keyword and ("pay" in str(keyword).lower() or "支付" in str(keyword) or "checkout" in str(keyword).lower()):
                return [{"kind": "function", "name": "checkout", "path": "app/pay.py", "line_start": 12, "module": "pay"}]
            return []

    class FakeMemory:
        def search(self, *args, **kwargs):
            return [{"kind": "conclusion", "title": "支付定位", "content": "checkout @ app/pay.py"}]
        def remember(self, *args, **kwargs):
            return {}

    agent.indexer = FakeIndexer()
    agent.memory = FakeMemory()
    result = agent.ask(1, 1, "帮我找支付功能在哪个文件", workspace="understand")
    assert result["intent"] == "locate"
    assert "没有重新扫描整个仓库" in result["answer"]
    assert result["locations"] or "pay.py" in result["answer"]
