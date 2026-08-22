"""
Agent 数据过滤层测试

测试覆盖:
1. BaseFilter 接口 (白名单/黑名单/深度删除/截断)
2. FilterMetrics 统计 (压缩比/删除字段)
3. API 过滤器 (ApiParserFilter/ApiRagFilter/ApiCaseFilter/ApiScriptFilter)
4. UI 过滤器 (RequirementFilter/UiRagFilter/UiCaseFilter/UiScriptFilter)
5. Context 过滤器 (ContextPayloadFilter/GraphStateFilter)
6. 过滤效果对比 (模拟真实 Agent 输出, 对比过滤前后大小)
7. GraphFlow 集成验证
"""
import asyncio
import json
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# ===== Stub 3rd-party modules =====
_STUB_MODULES = ["redis", "pymilvus", "neo4j"]
for mod_name in _STUB_MODULES:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

_pm = sys.modules.get("pymilvus") or types.ModuleType("pymilvus")
if not hasattr(_pm, "DataType"):
    _pm.DataType = type("DataType", (), {"INT64": "int64", "VARCHAR": "varchar", "FLOAT_VECTOR": "float_vector", "BOOL": "bool"})
    _pm.MilvusClient = type("MilvusClient", (), {"__init__": lambda *a, **kw: None})
    _pm.CollectionSchema = type("CollectionSchema", (), {})
    _pm.FieldSchema = type("FieldSchema", (), {})
sys.modules["pymilvus"] = _pm

_pymysql = types.ModuleType("pymysql")
_pymysql.paramstyle = "format"
_pymysql.install_as_MySQLdb = lambda: None
_pymysql.connect = lambda *a, **kw: None
sys.modules["pymysql"] = _pymysql

_neo = sys.modules.get("neo4j") or types.ModuleType("neo4j")
_neo.GraphDatabase = type("GraphDatabase", (), {"driver": lambda *a, **kw: MagicMock()})
_neo.Driver = type("Driver", (), {})
_neo.Session = type("Session", (), {})
sys.modules["neo4j"] = _neo

_ag = types.ModuleType("autogen_core")
def _make_class(name):
    return type(name, (), {"__init__": lambda self, *a, **kw: None})
for n in ["RoutedAgent", "MessageContext", "AgentId", "AgentRuntime", "CancellationToken", "DefaultTopicId", "SingleThreadedAgentRuntime", "ComponentBase"]:
    setattr(_ag, n, _make_class(n))
_ag.message_handler = lambda *a, **kw: (lambda f: f)
_ag.default_subscription = lambda *a, **kw: (lambda f: f)
sys.modules["autogen_core"] = _ag

_aac = types.ModuleType("autogen_agentchat")
_aac_base = types.ModuleType("autogen_agentchat.base")
_aac_base.ChatAgent = _make_class("ChatAgent")
_aac_base.Response = _make_class("Response")
_aac_base.TaskResult = _make_class("TaskResult")
_aac_messages = types.ModuleType("autogen_agentchat.messages")
_aac_messages.TextMessage = _make_class("TextMessage")
_aac_teams = types.ModuleType("autogen_agentchat.teams")
_aac_teams.DiGraphBuilder = _make_class("DiGraphBuilder")
_aac_teams.GraphFlow = _make_class("GraphFlow")
_aac.base = _aac_base
_aac.messages = _aac_messages
_aac.teams = _aac_teams
sys.modules["autogen_agentchat"] = _aac
sys.modules["autogen_agentchat.base"] = _aac_base
sys.modules["autogen_agentchat.messages"] = _aac_messages
sys.modules["autogen_agentchat.teams"] = _aac_teams

_sse = types.ModuleType("sse_starlette")
_sse_sse = types.ModuleType("sse_starlette.sse")
_sse_sse.EventSourceResponse = type("EventSourceResponse", (), {"__init__": lambda *a, **kw: None})
sys.modules["sse_starlette"] = _sse
sys.modules["sse_starlette.sse"] = _sse_sse


# ===== 测试工具 =====
RESULTS = []

def record(name: str, ok: bool, detail: str = ""):
    status = "[PASS]" if ok else "[FAIL]"
    msg = f"{status} {name}"
    if detail and not ok:
        msg += f" | {detail}"
    print(msg)
    RESULTS.append((name, ok))


# ===== 测试数据生成器 =====

def make_requirement_output():
    """模拟 RequirementAgent 完整输出"""
    return {
        "status": "success",
        "step": "requirement",
        "task_id": "task-001",
        "intent": "login_test",
        "summary": "测试用户登录功能",
        "target_url": "https://example.com/login",
        "steps": ["打开登录页", "输入用户名", "输入密码", "点击登录", "验证跳转"],
        "business_flow": {
            "name": "登录流程",
            "description": "用户通过输入用户名和密码进行登录验证, " * 10,  # 大文本
            "stages": [{"name": "输入阶段", "actions": ["输入用户名", "输入密码"]}],
        },
        "test_points": [
            {"point": "正常登录", "type": "functional", "priority": "high", "description": "测试用户使用正确的用户名和密码进行登录, " * 5},
            {"point": "密码错误", "type": "negative", "priority": "high", "description": "测试密码错误时的提示, " * 5},
            {"point": "空用户名", "type": "boundary", "priority": "medium", "description": "测试用户名为空时的验证, " * 5},
        ],
        "risk_points": [
            {"risk": "登录失败锁定", "level": "medium", "impact": "用户无法登录", "mitigation": "增加重试机制和提示, " * 10},
        ],
        "requirement_items": [
            {"intent": "login_test", "description": "登录测试", "steps": ["打开登录页", "输入用户名"]},
        ],
    }


def make_rag_output():
    """模拟 RAGAgent 完整输出 (含大量历史数据)"""
    elements = [
        {"id": f"e{i}", "score": 0.9 - i * 0.05, "task_id": "task-001", "page_name": "登录页",
         "element_name": f"元素_{i}", "element_type": "input", "locator": f"#input_{i}",
         "description": f"这是元素 {i} 的详细描述, " * 10, "source": "milvus"}
        for i in range(15)
    ]
    cases = [
        {"id": f"c{i}", "score": 0.85, "task_id": "task-001", "case_name": f"历史用例_{i}",
         "description": f"历史用例 {i} 的详细描述, " * 10,
         "steps": [{"step": 1, "action": "click", "locator": f"#btn_{i}"} for _ in range(5)],
         "source": "mysql"}
        for i in range(10)
    ]
    scripts = [
        {"id": f"s{i}", "score": 0.8, "task_id": "task-001", "script_name": f"历史脚本_{i}",
         "script_content": f"import pytest\n" + "def test_{i}():\n    assert True\n" * 50,
         "description": f"历史脚本 {i} 的描述, " * 10, "source": "mysql"}
        for i in range(5)
    ]
    return {
        "status": "success",
        "elements": elements,
        "cases": cases,
        "scripts": scripts,
        "element_count": 15,
        "case_count": 10,
        "script_count": 5,
        "query_steps": ["打开登录页", "输入用户名"],
    }


def make_case_output():
    """模拟 CaseAgent 完整输出"""
    return {
        "status": "success",
        "cases": [
            {
                "case_name": "正常登录测试",
                "description": "测试用户使用正确的用户名和密码登录系统, " * 5,
                "preconditions": ["用户已注册", "数据库已连接", "网络正常"],
                "steps": [
                    {"action": "goto", "locator": "", "value": "https://example.com/login", "description": "打开登录页"},
                    {"action": "fill", "locator": "#username", "value": "testuser", "description": "输入用户名"},
                    {"action": "fill", "locator": "#password", "value": "testpass", "description": "输入密码"},
                    {"action": "click", "locator": "#login-btn", "value": "", "description": "点击登录"},
                ],
                "assertions": [{"type": "verify_url", "locator": "", "expected": "/dashboard"}],
                "priority": "high",
                "expected_result": "登录成功, 跳转到仪表盘",
            }
        ],
        "case_count": 1,
        "source": "gen1",
        "coverage_notes": "",
        "degradation_info": None,
    }


def make_script_output():
    """模拟 ScriptGenerationAgent 完整输出"""
    return {
        "status": "success",
        "script_content": "import pytest\nfrom playwright.sync_api import Page\n\n" + "def test_login():\n    pass\n" * 30,
        "script_format": "playwright",
        "script_quality": 0.85,
        "degradation_info": {
            "level": 1,
            "source": "strategy",
            "quality": "high",
            "action_required": False,
            "message": "使用策略Agent生成脚本, " * 10,
        },
        "reuse_info": {
            "reused": False,
            "script_content": "import pytest\n" + "def test_reused():\n    pass\n" * 20,
        },
        "strategy_used": {
            "primary": "strategy_agent",
            "secondary": ["flow_script", "playwright_prompt"],
            "confidence": 0.9,
            "reason": "选择策略Agent因为需求明确, " * 10,
            "degradation_chain": ["strategy", "flow_script", "playwright_prompt", "playwright_agent"],
            "locator_priority": ["css", "xpath", "text"],
        },
        "retry_strategy": {
            "max_retries": 3,
            "retry_intervals": [1, 5, 15],
            "degradation_chain": ["strategy", "flow_script", "playwright_prompt", "playwright_agent"],
            "retry_on": ["timeout", "assertion_error"],
        },
        "degradation_chain": ["strategy", "flow_script", "playwright_prompt", "playwright_agent"],
        "generation_time_ms": 3500,
    }


def make_api_parser_output():
    """模拟 SwaggerParserAgent 完整输出"""
    return {
        "status": "success",
        "intent": "api_login_test",
        "summary": "测试用户登录API",
        "target_url": "https://api.example.com",
        "raw_requirement": '{"openapi": "3.0", "paths": {"' + "/api/v1/login" + '": {"post": {...}}}"' * 50,
        "apis": [
            {"name": "登录接口", "method": "POST", "path": "/api/v1/login",
             "headers": {"Content-Type": "application/json"},
             "request_schema": {"type": "object", "properties": {"username": {"type": "string"}, "password": {"type": "string"}}, "required": ["username", "password"]},
             "response_schema": {"type": "object", "properties": {"token": {"type": "string"}, "expires": {"type": "integer"}}},
             "depends": [], "priority": "high"}
        ],
        "total": 1,
        "metadata": {
            "api_title": "Example API",
            "api_version": "1.0.0",
            "api_count": 1,
            "apis": [{"name": "登录接口", "method": "POST", "path": "/api/v1/login"}],
        },
        "source_files": ["swagger.json"],
        "parsed_at": "2026-07-22T10:00:00",
        "parse_version": 1,
        "user_id": 1,
        "pages": [{"name": "登录页", "description": "用户登录页面, " * 10, "elements": [{"name": "用户名", "type": "input"}]}],
        "test_points": [{"point": "正常登录", "description": "测试正确凭据登录, " * 5, "test_data": {"username": "test"}}],
        "constraints": [{"rule": "token有效", "description": "token有效期24小时, " * 5}],
        "source_types": ["swagger"],
        "session_key": "session-001",
        "fallback": False,
        "session_id": 1,
    }


# ================================================================== #
#  测试 1-4: BaseFilter 接口                                          #
# ================================================================== #

def test_base_whitelist():
    """测试 1: 白名单模式"""
    from app.agent.filter.base_filter import BaseFilter, FilterResult

    class TestFilter(BaseFilter):
        name = "TestWhitelist"
        keep_fields = {"a", "b"}

    data = {"a": 1, "b": 2, "c": 3, "d": 4}
    result = TestFilter().apply(data)

    ok = "a" in result.data and "b" in result.data
    ok = ok and "c" not in result.data and "d" not in result.data
    ok = ok and set(result.metrics.dropped_fields) == {"c", "d"}
    record("BaseFilter-白名单", ok)


def test_base_blacklist():
    """测试 2: 黑名单模式"""
    from app.agent.filter.base_filter import BaseFilter

    class TestFilter(BaseFilter):
        name = "TestBlacklist"
        keep_fields = set()
        drop_fields = {"c", "d"}

    data = {"a": 1, "b": 2, "c": 3, "d": 4}
    result = TestFilter().apply(data)

    ok = "a" in result.data and "b" in result.data
    ok = ok and "c" not in result.data and "d" not in result.data
    record("BaseFilter-黑名单", ok)


def test_base_deep_drop():
    """测试 3: 深度字段删除"""
    from app.agent.filter.base_filter import BaseFilter

    class TestFilter(BaseFilter):
        name = "TestDeepDrop"
        keep_fields = {"items", "config"}
        deep_drop_fields = {"items[].description", "config.secret"}

    data = {
        "items": [{"name": "a", "description": "desc a"}, {"name": "b", "description": "desc b"}],
        "config": {"secret": "password123", "timeout": 30},
        "extra": "should_drop",
    }
    result = TestFilter().apply(data)

    ok = "items" in result.data and "config" in result.data
    ok = ok and "extra" not in result.data
    ok = ok and all("description" not in item for item in result.data["items"])
    ok = ok and "secret" not in result.data["config"]
    ok = ok and result.data["config"]["timeout"] == 30
    record("BaseFilter-深度删除", ok)


def test_base_metrics():
    """测试 4: FilterMetrics 统计"""
    from app.agent.filter.base_filter import BaseFilter

    class TestFilter(BaseFilter):
        name = "TestMetrics"
        keep_fields = {"a"}

    data = {"a": "hello", "b": "x" * 1000, "c": "y" * 500}
    result = TestFilter().apply(data)

    m = result.metrics
    ok = m.original_size_bytes > m.filtered_size_bytes
    ok = ok and m.reduction_ratio > 0.5
    ok = ok and len(m.dropped_fields) == 2
    ok = ok and m.duration_ms >= 0
    record("BaseFilter-Metrics统计", ok)


# ================================================================== #
#  测试 5-8: UI 过滤器                                               #
# ================================================================== #

def test_requirement_filter():
    """测试 5: RequirementFilter 过滤效果"""
    from app.agent.filter import RequirementFilter

    data = make_requirement_output()
    result = RequirementFilter().apply(data)

    ok = "risk_points" not in result.data
    ok = ok and "requirement_items" not in result.data
    ok = ok and "intent" in result.data
    ok = ok and "steps" in result.data
    ok = ok and "business_flow" in result.data

    m = result.metrics
    print(f"    需求解析: {m.original_size_bytes}B → {m.filtered_size_bytes}B (减少 {m.reduction_ratio*100:.1f}%)")

    record("RequirementFilter-过滤效果", ok)


def test_ui_rag_filter():
    """测试 6: UiRagFilter 过滤效果"""
    from app.agent.filter import UiRagFilter

    data = make_rag_output()
    result = UiRagFilter().apply(data)

    ok = "scripts" not in result.data
    ok = ok and "elements" in result.data
    ok = ok and all("description" not in e for e in result.data.get("elements", []))
    ok = ok and all("source" not in e for e in result.data.get("elements", []))

    m = result.metrics
    print(f"    RAG输出: {m.original_size_bytes}B → {m.filtered_size_bytes}B (减少 {m.reduction_ratio*100:.1f}%)")

    record("UiRagFilter-过滤效果", ok)


def test_ui_case_filter():
    """测试 7: UiCaseFilter 过滤效果"""
    from app.agent.filter import UiCaseFilter

    data = make_case_output()
    result = UiCaseFilter().apply(data)

    cases = result.data.get("cases", [])
    ok = len(cases) == 1
    if cases:
        ok = ok and "preconditions" not in cases[0]
        ok = ok and "description" not in cases[0]
        ok = ok and "steps" in cases[0]
        ok = ok and "assertions" in cases[0]

    m = result.metrics
    print(f"    用例输出: {m.original_size_bytes}B → {m.filtered_size_bytes}B (减少 {m.reduction_ratio*100:.1f}%)")

    record("UiCaseFilter-过滤效果", ok)


def test_ui_script_filter():
    """测试 8: UiScriptFilter 过滤效果"""
    from app.agent.filter import UiScriptFilter

    data = make_script_output()
    result = UiScriptFilter().apply(data)

    ok = "reuse_info" not in result.data
    ok = ok and "strategy_used" not in result.data
    ok = ok and "retry_strategy" not in result.data
    ok = ok and "script_content" in result.data
    ok = ok and "script_quality" in result.data
    ok = ok and "degradation_info" in result.data
    ok = ok and "message" not in result.data["degradation_info"]

    m = result.metrics
    print(f"    脚本输出: {m.original_size_bytes}B → {m.filtered_size_bytes}B (减少 {m.reduction_ratio*100:.1f}%)")

    record("UiScriptFilter-过滤效果", ok)


# ================================================================== #
#  测试 9-12: API 过滤器                                             #
# ================================================================== #

def test_api_parser_filter():
    """测试 9: ApiParserFilter 过滤效果"""
    from app.agent.filter import ApiParserFilter

    data = make_api_parser_output()
    result = ApiParserFilter().apply(data)

    ok = "raw_requirement" not in result.data
    ok = ok and "source_files" not in result.data
    ok = ok and "parsed_at" not in result.data
    ok = ok and "apis" in result.data

    m = result.metrics
    print(f"    API解析: {m.original_size_bytes}B → {m.filtered_size_bytes}B (减少 {m.reduction_ratio*100:.1f}%)")

    record("ApiParserFilter-过滤效果", ok)


def test_api_rag_filter():
    """测试 10: ApiRagFilter 过滤效果"""
    from app.agent.filter import ApiRagFilter

    data = make_rag_output()
    result = ApiRagFilter().apply(data)

    ok = "elements" not in result.data
    ok = ok and "cases" in result.data
    ok = ok and all("description" not in c for c in result.data.get("cases", []))

    m = result.metrics
    print(f"    API RAG: {m.original_size_bytes}B → {m.filtered_size_bytes}B (减少 {m.reduction_ratio*100:.1f}%)")

    record("ApiRagFilter-过滤效果", ok)


def test_api_case_filter():
    """测试 11: ApiCaseFilter 过滤效果"""
    from app.agent.filter import ApiCaseFilter

    data = {
        "status": "success",
        "cases": [{
            "case_id": 1, "title": "API登录测试", "method": "POST",
            "url": "/api/login", "headers": {"Content-Type": "application/json"},
            "pre_steps": [{"step": 1, "action": "login"}],
            "variables": {"token": ""},
            "body": {"username": "test", "password": "pass"},
            "assertions": [{"type": "status_code", "expected": 200}],
            "priority": "high", "tags": ["auth"], "feature_ref": "login",
            "type": "api",
        }],
        "total": 1,
        "case_types": ["api"],
    }
    result = ApiCaseFilter().apply(data)

    cases = result.data.get("cases", [])
    ok = len(cases) == 1
    if cases:
        ok = ok and "pre_steps" not in cases[0]
        ok = ok and "variables" not in cases[0]
        ok = ok and "method" in cases[0]
        ok = ok and "url" in cases[0]

    m = result.metrics
    print(f"    API用例: {m.original_size_bytes}B → {m.filtered_size_bytes}B (减少 {m.reduction_ratio*100:.1f}%)")

    record("ApiCaseFilter-过滤效果", ok)


def test_api_script_filter():
    """测试 12: ApiScriptFilter 过滤效果"""
    from app.agent.filter import ApiScriptFilter

    data = make_script_output()
    result = ApiScriptFilter().apply(data)

    ok = "reuse_info" not in result.data
    ok = ok and "strategy_used" not in result.data
    ok = ok and "script_content" in result.data

    m = result.metrics
    print(f"    API脚本: {m.original_size_bytes}B → {m.filtered_size_bytes}B (减少 {m.reduction_ratio*100:.1f}%)")

    record("ApiScriptFilter-过滤效果", ok)


# ================================================================== #
#  测试 13-14: Context 过滤器                                        #
# ================================================================== #

def test_context_payload_filter():
    """测试 13: ContextPayloadFilter 按 input_keys 裁剪"""
    from app.agent.filter import ContextPayloadFilter

    payload = {
        "requirement": "测试登录",
        "task_id": "task-001",
        "action": "generate",
        "steps": ["打开页面"],
        "elements": [{"name": "用户名输入框"}],
        "raw_requirement": "x" * 5000,
        "debug_info": {"trace": "y" * 3000},
    }

    f = ContextPayloadFilter(input_keys={"steps", "elements"})
    result = f.apply(payload)

    ok = "steps" in result.data
    ok = ok and "elements" in result.data
    ok = ok and "raw_requirement" not in result.data
    ok = ok and "debug_info" not in result.data

    m = result.metrics
    print(f"    Payload: {m.original_size_bytes}B → {m.filtered_size_bytes}B (减少 {m.reduction_ratio*100:.1f}%)")

    record("ContextPayloadFilter-裁剪", ok)


def test_context_payload_deep_truncate():
    """测试 14: ContextPayloadFilter 深度截断"""
    from app.agent.filter import ContextPayloadFilter

    payload = {
        "requirement": "测试",
        "task_id": "t1",
        "action": "execute",
        "big_list": [{"data": i} for i in range(100)],
        "big_text": "x" * 10000,
    }

    f = ContextPayloadFilter(input_keys={"big_list", "big_text"}, max_payload_size=2000)
    result = f.apply(payload)

    ok = len(result.data["big_list"]) <= 20
    ok = ok and len(result.data["big_text"]) < 2100
    ok = ok and result.data["big_text"].endswith("[auto-truncated]")

    record("ContextPayloadFilter-深度截断", ok)


def test_graph_state_filter():
    """测试 15: GraphStateFilter 清理中间结果"""
    from app.agent.filter import GraphStateFilter

    intermediate = {
        "requirement": {"intent": "login", "raw_requirement": "x" * 3000, "steps": ["s1"]},
        "rag": {"elements": [], "script_content": "y" * 2000},
    }

    # 不保留任何节点, 全部清理
    f = GraphStateFilter(preserve_nodes=set())
    result = f.cleanup_intermediate(intermediate)

    ok = "[cleaned:" in result["requirement"]["raw_requirement"]
    ok = ok and result["requirement"]["steps"] == ["s1"]
    ok = ok and "[cleaned:" in result["rag"]["script_content"]

    record("GraphStateFilter-中间结果清理", ok)


# ================================================================== #
#  测试 16: 全链路过滤效果对比                                        #
# ================================================================== #

def test_full_pipeline_filter_comparison():
    """测试 16: 全链路过滤效果对比 (模拟完整 UI 测试流程)"""
    from app.agent.filter import (
        RequirementFilter, UiRagFilter, UiCaseFilter, UiScriptFilter,
    )

    print("\n    ═══════════════════════════════════════════════════")
    print("    ║           全链路过滤效果对比                       ║")
    print("    ═══════════════════════════════════════════════════")
    print("    ║ 节点                │ 原始大小  │ 过滤后   │ 压缩比 ║")
    print("    ╠─────────────────────┼───────────┼──────────┼────────╣")

    total_original = 0
    total_filtered = 0

    # 1. Requirement
    data = make_requirement_output()
    r = RequirementFilter().apply(data)
    print(f"    ║ RequirementAgent    │ {r.metrics.original_size_bytes:>7}B   │ {r.metrics.filtered_size_bytes:>7}B  │ {r.metrics.reduction_ratio*100:>5.1f}% ║")
    total_original += r.metrics.original_size_bytes
    total_filtered += r.metrics.filtered_size_bytes

    # 2. RAG
    data = make_rag_output()
    r = UiRagFilter().apply(data)
    print(f"    ║ RAGAgent            │ {r.metrics.original_size_bytes:>7}B   │ {r.metrics.filtered_size_bytes:>7}B  │ {r.metrics.reduction_ratio*100:>5.1f}% ║")
    total_original += r.metrics.original_size_bytes
    total_filtered += r.metrics.filtered_size_bytes

    # 3. Case
    data = make_case_output()
    r = UiCaseFilter().apply(data)
    print(f"    ║ CaseAgent           │ {r.metrics.original_size_bytes:>7}B   │ {r.metrics.filtered_size_bytes:>7}B  │ {r.metrics.reduction_ratio*100:>5.1f}% ║")
    total_original += r.metrics.original_size_bytes
    total_filtered += r.metrics.filtered_size_bytes

    # 4. Script
    data = make_script_output()
    r = UiScriptFilter().apply(data)
    print(f"    ║ ScriptAgent         │ {r.metrics.original_size_bytes:>7}B   │ {r.metrics.filtered_size_bytes:>7}B  │ {r.metrics.reduction_ratio*100:>5.1f}% ║")
    total_original += r.metrics.original_size_bytes
    total_filtered += r.metrics.filtered_size_bytes

    print("    ╠─────────────────────┼───────────┼──────────┼────────╣")
    overall_ratio = round(1 - total_filtered / total_original, 4) if total_original > 0 else 0
    print(f"    ║ 合计                │ {total_original:>7}B   │ {total_filtered:>7}B  │ {overall_ratio*100:>5.1f}% ║")
    print("    ═══════════════════════════════════════════════════")

    ok = total_filtered < total_original
    ok = ok and overall_ratio > 0.3

    record("全链路过滤效果对比", ok)


# ================================================================== #
#  测试 17: GraphFlow 集成验证                                        #
# ================================================================== #

async def test_graphflow_integration():
    """测试 17: GraphFlow 集成 Filter (Mock)"""
    from app.workflow.ui_flow import UIFlow
    from app.workflow.state import WorkflowState, WorkflowStatus

    flow = UIFlow()
    state = WorkflowState.create(requirement="测试登录功能", workflow_name="ui_test_flow")

    mock_req = MagicMock()
    mock_req.execute_async = AsyncMock(return_value=make_requirement_output())
    mock_req.execute_async = AsyncMock(return_value={
        "status": "success", "intent": "login", "summary": "登录测试",
        "target_url": "https://example.com", "steps": ["打开页面"],
        "business_flow": {"stages": []}, "test_points": [],
        "risk_points": [], "requirement_items": [],
    })

    mock_rag = MagicMock()
    mock_rag.execute = MagicMock(return_value=make_rag_output())
    mock_rag.execute_async = None

    mock_case = MagicMock()
    mock_case.execute = MagicMock(return_value=make_case_output())
    mock_case.execute_async = None

    mock_script = MagicMock()
    mock_script.execute = AsyncMock(return_value=make_script_output())
    mock_script.execute_async = None

    with patch("app.agents.factory.AgentFactory") as mock_factory:
        async def mc(name, **kw):
            return {"requirement_agent": mock_req, "rag_agent": mock_rag,
                    "case_agent": mock_case, "script_generation_agent": mock_script}.get(name, MagicMock())
        mock_factory.create = AsyncMock(side_effect=mc)
        result = await flow.run(state)

    ok = result.status == WorkflowStatus.SUCCESS

    # 验证过滤后的数据不包含大文本字段
    rag_output = result.get_node_output("rag_input")
    ok = ok and "scripts" not in rag_output  # UiRagFilter 删除了 scripts

    case_output = result.get_node_output("script_input")
    ok = ok and "test_cases" in case_output

    record("GraphFlow-Filter集成", ok)


# ================================================================== #
#  测试 18: 模块导入                                                  #
# ================================================================== #

def test_module_imports():
    """测试 18: 模块导入验证"""
    try:
        from app.agent.filter import (
            BaseFilter, FilterMetrics, FilterResult,
            ApiParserFilter, ApiRagFilter, ApiCaseFilter, ApiScriptFilter,
            RequirementFilter, UiRagFilter, UiCaseFilter, UiScriptFilter,
            ContextPayloadFilter, GraphStateFilter,
        )
        ok = True
    except Exception as e:
        ok = False
        print(f"  导入失败: {e}")

    record("模块导入", ok)


# ================================================================== #
#  主函数                                                              #
# ================================================================== #

async def main():
    print("=" * 60)
    print("Agent 数据过滤层测试")
    print("=" * 60)

    # BaseFilter
    test_base_whitelist()
    test_base_blacklist()
    test_base_deep_drop()
    test_base_metrics()

    # UI Filters
    test_requirement_filter()
    test_ui_rag_filter()
    test_ui_case_filter()
    test_ui_script_filter()

    # API Filters
    test_api_parser_filter()
    test_api_rag_filter()
    test_api_case_filter()
    test_api_script_filter()

    # Context Filters
    test_context_payload_filter()
    test_context_payload_deep_truncate()
    test_graph_state_filter()

    # 全链路对比
    test_full_pipeline_filter_comparison()

    # GraphFlow 集成
    await test_graphflow_integration()

    # 模块导入
    test_module_imports()

    # 汇总
    print("=" * 60)
    passed = sum(1 for _, ok in RESULTS if ok)
    total = len(RESULTS)
    failed = total - passed
    print(f"测试结果: {passed}/{total} 通过, {failed} 失败")
    print("=" * 60)
    if failed == 0:
        print("全部测试通过!")
    else:
        for name, ok in RESULTS:
            if not ok:
                print(f"  FAIL: {name}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
