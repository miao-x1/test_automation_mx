"""
性能测试模块测试

测试覆盖:
1. 模型定义: PerformanceTask / PerformanceResult / PerformanceMetric
2. Agent 类定义: PerformancePlanAgent / PerformanceScriptAgent / PerformanceAnalysisAgent
3. PerformancePlanAgent 逻辑: 并发估算 + LLM 方案生成 (含降级)
4. PerformanceScriptAgent 逻辑: Locust 模板 + JMeter 模板
5. PerformanceAnalysisAgent 逻辑: 统计计算 + 降级分析
6. 迁移文件结构验证
7. API 路由注册验证
8. Agent 注册验证 (definitions.py)
9. 前端文件存在性验证
"""
import asyncio
import json
import os
import sys
import types
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
_neo.Driver = type("Driver", (), {"session": lambda *a, **kw: MagicMock(), "close": lambda *a, **kw: None})
_neo.Session = type("Session", (), {"run": lambda *a, **kw: MagicMock(), "close": lambda *a, **kw: None})
_neo.basic_auth = lambda *a, **kw: MagicMock()
sys.modules["neo4j"] = _neo

# autogen stub
_ag = types.ModuleType("autogen_core")
def _make_class(name):
    return type(name, (), {"__init__": lambda self, *a, **kw: None})
_ag.RoutedAgent = _make_class("RoutedAgent")
_ag.message_handler = lambda *a, **kw: (lambda f: f)
_ag.MessageContext = _make_class("MessageContext")
_ag.AgentId = _make_class("AgentId")
_ag.AgentRuntime = _make_class("AgentRuntime")
_ag.CancellationToken = _make_class("CancellationToken")
_ag.DefaultTopicId = _make_class("DefaultTopicId")
_ag.SingleThreadedAgentRuntime = _make_class("SingleThreadedAgentRuntime")
_ag.ComponentBase = _make_class("ComponentBase")
_ag.default_subscription = lambda *a, **kw: (lambda f: f)
sys.modules["autogen_core"] = _ag

_aac = types.ModuleType("autogen_agentchat")
_aac_base = types.ModuleType("autogen_agentchat.base")
_aac_base.ChatAgent = _make_class("ChatAgent")
_aac_base.Response = _make_class("Response")
_aac_base.TaskResult = _make_class("TaskResult")
_aac_messages = types.ModuleType("autogen_agentchat.messages")
_aac_messages.TextMessage = _make_class("TextMessage")
_aac_messages.BaseChatMessage = _make_class("BaseChatMessage")
_aac_messages.BaseAgentEvent = _make_class("BaseAgentEvent")
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


# ================================================================== #
#  测试 1-3: 模型定义                                                 #
# ================================================================== #

def test_model_imports():
    """测试 1: 模型导入完整性"""
    errors = []
    try:
        from app.models.performance import PerformanceTask, PerformanceResult, PerformanceMetric
    except ImportError as e:
        errors.append(str(e))
    ok = len(errors) == 0
    record("模型-导入完整性", ok, "; ".join(errors))


def test_model_table_names():
    """测试 2: 模型表名正确"""
    from app.models.performance import PerformanceTask, PerformanceResult, PerformanceMetric
    ok = PerformanceTask.__tablename__ == "performance_task"
    ok = ok and PerformanceResult.__tablename__ == "performance_result"
    ok = ok and PerformanceMetric.__tablename__ == "performance_metric"
    record("模型-表名正确", ok)


def test_model_columns():
    """测试 3: 模型字段定义"""
    from app.models.performance import PerformanceTask, PerformanceResult, PerformanceMetric

    task_cols = {c.name for c in PerformanceTask.__table__.columns}
    ok = {"id", "name", "test_type", "target_url", "method", "concurrency",
          "duration_seconds", "tps_target", "status", "script_content"}.issubset(task_cols)

    result_cols = {c.name for c in PerformanceResult.__table__.columns}
    ok = ok and {"id", "task_id", "avg_tps", "peak_tps", "avg_rt", "p95_rt",
                 "error_rate", "total_requests", "analysis_json"}.issubset(result_cols)

    metric_cols = {c.name for c in PerformanceMetric.__table__.columns}
    ok = ok and {"id", "result_id", "timestamp", "elapsed", "tps", "avg_rt",
                 "cpu_percent", "memory_mb"}.issubset(metric_cols)

    record("模型-字段定义", ok)


# ================================================================== #
#  测试 4-6: Agent 类定义                                             #
# ================================================================== #

def test_agent_imports():
    """测试 4: Agent 导入完整性"""
    errors = []
    try:
        from app.domains.performance import PerformancePlanAgent, PerformanceScriptAgent, PerformanceAnalysisAgent
    except ImportError as e:
        errors.append(str(e))
    ok = len(errors) == 0
    record("Agent-导入完整性", ok, "; ".join(errors))


def test_agent_inheritance():
    """测试 5: Agent 继承 BaseRoutedAgent"""
    from app.domains.performance import PerformancePlanAgent, PerformanceScriptAgent, PerformanceAnalysisAgent
    from app.runtime.base_agent import BaseRoutedAgent

    ok = issubclass(PerformancePlanAgent, BaseRoutedAgent)
    ok = ok and issubclass(PerformanceScriptAgent, BaseRoutedAgent)
    ok = ok and issubclass(PerformanceAnalysisAgent, BaseRoutedAgent)
    record("Agent-继承BaseRoutedAgent", ok)


def test_agent_capabilities():
    """测试 6: Agent 能力标签"""
    from app.domains.performance import PerformancePlanAgent, PerformanceScriptAgent, PerformanceAnalysisAgent

    plan = PerformancePlanAgent()
    script = PerformanceScriptAgent()
    analysis = PerformanceAnalysisAgent()

    ok = "performance_planning" in plan._capabilities
    ok = ok and "script_generation" in script._capabilities
    ok = ok and "performance_analysis" in analysis._capabilities
    record("Agent-能力标签", ok)


# ================================================================== #
#  测试 7-8: PerformancePlanAgent 逻辑                                #
# ================================================================== #

async def test_plan_agent_with_llm():
    """测试 7: PlanAgent LLM 方案生成"""
    from app.domains.performance.agents import PerformancePlanAgent

    agent = PerformancePlanAgent()
    # Mock call_llm_json 返回方案
    agent.call_llm_json = AsyncMock(return_value={
        "concurrency": 50,
        "duration_seconds": 180,
        "tps_target": 100.0,
        "ramp_up": 15,
        "scenarios": [{"name": "基准测试", "description": "常规负载", "weight": 100}],
        "reasoning": "基于日业务量10万次估算",
    })

    result = await agent.handle_plan({
        "target_url": "https://api.example.com/v1/users",
        "method": "GET",
        "business_volume": 100000,
        "test_type": "api",
    })

    ok = result["status"] == "success"
    plan = result["plan"]
    ok = ok and plan["concurrency"] == 50
    ok = ok and plan["tps_target"] == 100.0
    ok = ok and plan["duration_seconds"] == 180
    ok = ok and len(plan["scenarios"]) == 1
    record("PlanAgent-LLM方案生成", ok)


async def test_plan_agent_fallback():
    """测试 8: PlanAgent LLM 失败时降级到基准估算"""
    from app.domains.performance.agents import PerformancePlanAgent

    agent = PerformancePlanAgent()
    agent.call_llm_json = AsyncMock(side_effect=Exception("LLM不可用"))

    result = await agent.handle_plan({
        "target_url": "https://api.example.com/v1/users",
        "method": "GET",
        "business_volume": 86400,  # 1次/秒
    })

    ok = result["status"] == "success"
    plan = result["plan"]
    # 并发数应 > 0 (基准估算)
    ok = ok and plan["concurrency"] > 0
    ok = ok and plan["tps_target"] > 0
    ok = ok and "基准估算" in plan["reasoning"]
    record("PlanAgent-降级估算", ok)


# ================================================================== #
#  测试 9-10: PerformanceScriptAgent 逻辑                            #
# ================================================================== #

async def test_script_agent_locust():
    """测试 9: ScriptAgent 生成 Locust 脚本"""
    from app.domains.performance.agents import PerformanceScriptAgent

    agent = PerformanceScriptAgent()
    agent.call_llm = AsyncMock(side_effect=Exception("LLM不可用"))  # 触发模板降级

    result = await agent.handle_generate({
        "plan": {"concurrency": 20, "duration_seconds": 60, "ramp_up": 10, "tps_target": 50.0},
        "target_url": "https://api.example.com/v1/users",
        "method": "GET",
        "headers": {"Authorization": "Bearer xxx"},
        "body": {},
        "script_type": "locust",
    })

    ok = result["status"] == "success"
    ok = ok and "locust" in result["script_format"].lower()
    script = result["script_content"]
    ok = ok and "HttpUser" in script
    ok = ok and "api.example.com" in script
    ok = ok and "/v1/users" in script
    ok = ok and "PerformanceTestUser" in script
    record("ScriptAgent-Locust脚本", ok)


async def test_script_agent_jmeter():
    """测试 10: ScriptAgent 生成 JMeter 配置"""
    from app.domains.performance.agents import PerformanceScriptAgent

    agent = PerformanceScriptAgent()

    result = await agent.handle_generate({
        "plan": {"concurrency": 30, "duration_seconds": 120, "ramp_up": 15},
        "target_url": "https://api.example.com/v1/data",
        "method": "POST",
        "headers": {"Content-Type": "application/json"},
        "body": {"name": "test"},
        "script_type": "jmeter",
    })

    ok = result["status"] == "success"
    ok = ok and result["script_format"] == "jmeter_xml"
    xml = result["jmeter_config"]
    ok = ok and "jmeterTestPlan" in xml
    ok = ok and "ThreadGroup" in xml
    ok = ok and "30" in xml  # concurrency
    ok = ok and "api.example.com" in xml
    record("ScriptAgent-JMeter配置", ok)


# ================================================================== #
#  测试 11-12: PerformanceAnalysisAgent 逻辑                          #
# ================================================================== #

async def test_analysis_agent_statistics():
    """测试 11: AnalysisAgent 统计计算"""
    from app.domains.performance.agents import PerformanceAnalysisAgent

    agent = PerformanceAnalysisAgent()

    result_summary = {
        "avg_tps": 80.0,
        "peak_tps": 120.0,
        "avg_rt": 200.0,
        "p95_rt": 500.0,
        "p99_rt": 800.0,
        "error_rate": 1.5,
        "total_requests": 10000,
        "total_errors": 150,
        "concurrency": 50,
        "duration_seconds": 120,
    }
    metrics = [
        {"elapsed": 10, "tps": 70, "avg_rt": 180, "concurrent_users": 50, "error_count": 10, "cpu_percent": 45, "memory_mb": 512},
        {"elapsed": 30, "tps": 85, "avg_rt": 210, "concurrent_users": 50, "error_count": 50, "cpu_percent": 65, "memory_mb": 640},
        {"elapsed": 60, "tps": 90, "avg_rt": 220, "concurrent_users": 50, "error_count": 100, "cpu_percent": 75, "memory_mb": 720},
    ]
    plan = {"tps_target": 100.0, "concurrency": 50, "duration_seconds": 120}

    stats = agent._compute_statistics(result_summary, metrics, plan)

    ok = stats["avg_tps"] == 80.0
    ok = ok and stats["tps_target"] == 100.0
    ok = ok and stats["tps_achievement_pct"] == 80.0
    ok = ok and stats["tps_cv_pct"] > 0  # 有波动
    ok = ok and stats["cpu_peak_pct"] == 75.0
    ok = ok and stats["mem_peak_mb"] == 720.0
    ok = ok and stats["metric_count"] == 3
    record("AnalysisAgent-统计计算", ok)


async def test_analysis_agent_fallback():
    """测试 12: AnalysisAgent LLM 失败时降级分析"""
    from app.domains.performance.agents import PerformanceAnalysisAgent

    agent = PerformanceAnalysisAgent()
    agent.call_llm_json = AsyncMock(side_effect=Exception("LLM不可用"))

    result = await agent.handle_analyze({
        "result_summary": {
            "avg_tps": 60, "peak_tps": 80, "avg_rt": 300,
            "p95_rt": 2500, "p99_rt": 3500,
            "error_rate": 8.0, "total_requests": 5000, "total_errors": 400,
            "concurrency": 50, "duration_seconds": 100,
        },
        "metrics": [
            {"elapsed": 10, "tps": 50, "avg_rt": 200, "concurrent_users": 50, "error_count": 50, "cpu_percent": 85, "memory_mb": 800},
        ],
        "target_plan": {"tps_target": 100.0, "concurrency": 50},
    })

    ok = result["status"] == "success"
    analysis = result["analysis"]
    # TPS达标率60% → 扣分, P95>2000 → 扣分, 错误率>5% → 扣分, CPU>80 → 扣分
    ok = ok and analysis["score"] < 60  # 应该是不及格
    ok = ok and analysis["verdict"] == "FAIL"
    ok = ok and len(analysis["bottlenecks"]) >= 3  # 至少3个瓶颈
    ok = ok and len(analysis["recommendations"]) >= 3
    record("AnalysisAgent-降级分析", ok)


# ================================================================== #
#  测试 13: 迁移文件验证                                               #
# ================================================================== #

def test_migration_file():
    """测试 13: 迁移文件 032 结构验证"""
    import importlib.util

    migration_path = os.path.join(
        os.path.dirname(__file__), "..", "alembic", "versions", "032_add_performance_tables.py"
    )
    migration_path = os.path.abspath(migration_path)

    ok = os.path.exists(migration_path)
    if not ok:
        record("迁移文件-存在性", False, f"文件不存在: {migration_path}")
        return

    spec = importlib.util.spec_from_file_location("migration_032", migration_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    ok = mod.revision == "032"
    ok = ok and mod.down_revision == "031"
    ok = ok and callable(mod.upgrade)
    ok = ok and callable(mod.downgrade)
    record("迁移文件-结构验证", ok)


# ================================================================== #
#  测试 14: Agent 注册验证                                              #
# ================================================================== #

def test_agent_registration():
    """测试 14: Agent 在 definitions.py 中注册"""
    from app.agents.factory.definitions import DEFAULT_AGENT_SPECS

    names = {spec.name for spec in DEFAULT_AGENT_SPECS}
    ok = "performance_plan_agent" in names
    ok = ok and "performance_script_agent" in names
    ok = ok and "performance_analysis_agent" in names

    # 验证 spec 属性
    plan_spec = next(s for s in DEFAULT_AGENT_SPECS if s.name == "performance_plan_agent")
    ok = ok and plan_spec.module_path == "app.domains.performance.agents"
    ok = ok and plan_spec.class_name == "PerformancePlanAgent"

    record("Agent-注册验证", ok)


# ================================================================== #
#  测试 15: API 路由验证                                               #
# ================================================================== #

def test_api_routes():
    """测试 15: API 路由注册验证"""
    # 检查 __init__.py 中导入了 performance_router
    api_init_path = os.path.join(
        os.path.dirname(__file__), "..", "app", "api", "__init__.py"
    )
    api_init_path = os.path.abspath(api_init_path)

    with open(api_init_path, "r", encoding="utf-8") as f:
        content = f.read()

    ok = "performance_router" in content
    ok = ok and 'prefix="/performance"' in content
    record("API-路由注册", ok)


# ================================================================== #
#  测试 16-17: 前端文件验证                                            #
# ================================================================== #

def test_frontend_service():
    """测试 16: 前端 service 文件存在"""
    frontend_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "frontend", "src", "services", "performance.ts"
    )
    frontend_path = os.path.abspath(frontend_path)

    ok = os.path.exists(frontend_path)
    if ok:
        with open(frontend_path, "r", encoding="utf-8") as f:
            content = f.read()
        ok = "createTask" in content and "runPlan" in content and "getMetrics" in content
    record("前端-Service文件", ok)


def test_frontend_pages():
    """测试 17: 前端页面文件存在"""
    base = os.path.join(
        os.path.dirname(__file__), "..", "..", "frontend", "src", "pages", "performance"
    )
    base = os.path.abspath(base)

    list_ok = os.path.exists(os.path.join(base, "PerformanceListPage.tsx"))
    detail_ok = os.path.exists(os.path.join(base, "PerformanceDetailPage.tsx"))

    ok = list_ok and detail_ok
    if ok:
        with open(os.path.join(base, "PerformanceDetailPage.tsx"), "r", encoding="utf-8") as f:
            detail_content = f.read()
        ok = "recharts" in detail_content.lower() or "LineChart" in detail_content
        ok = ok and "Tabs" in detail_content
    record("前端-页面文件", ok)


# ================================================================== #
#  测试 18: models __init__ 导出                                       #
# ================================================================== #

def test_models_export():
    """测试 18: models __init__ 导出性能模型"""
    from app.models import PerformanceTask, PerformanceResult, PerformanceMetric
    ok = PerformanceTask is not None and PerformanceResult is not None and PerformanceMetric is not None
    record("模块-__init__导出", ok)


# ================================================================== #
#  主函数                                                              #
# ================================================================== #

async def main():
    print("=" * 60)
    print("性能测试模块测试")
    print("=" * 60)

    test_model_imports()
    test_model_table_names()
    test_model_columns()

    test_agent_imports()
    test_agent_inheritance()
    test_agent_capabilities()

    await test_plan_agent_with_llm()
    await test_plan_agent_fallback()

    await test_script_agent_locust()
    await test_script_agent_jmeter()

    await test_analysis_agent_statistics()
    await test_analysis_agent_fallback()

    test_migration_file()
    test_agent_registration()
    test_api_routes()

    test_frontend_service()
    test_frontend_pages()

    test_models_export()

    print("\n" + "=" * 60)
    passed = sum(1 for _, ok in RESULTS if ok)
    failed = sum(1 for _, ok in RESULTS if not ok)
    total = len(RESULTS)
    print(f"测试结果: {passed}/{total} 通过, {failed} 失败")
    print("=" * 60)
    if failed == 0:
        print("全部测试通过!")
    else:
        for name, ok in RESULTS:
            if not ok:
                print(f"  失败: {name}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
