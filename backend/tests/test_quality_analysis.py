"""
AI 测试质量分析系统全链路测试

验证:
1. QualityReport 数据模型(CRUD + JSON 字段解析)
2. QualityAnalysisService 服务层(create/get/list/delete/dashboard/stats)
3. QualityAnalysisAgent 数据收集(测试资产/执行记录/缺陷提取)
4. QualityAnalysisAgent 四维度分析(覆盖/风险/重复/趋势)
5. 质量分数计算(四维度加权)
6. 改进建议生成
7. Agent 注册验证(DEFAULT_AGENT_SPECS)
8. API 路由完整性(9 个路由)
9. 重新生成分析
10. 仪表盘聚合统计

运行:
    cd backend
    python -m tests.test_quality_analysis
"""
import asyncio
import json
import logging
import os
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# 确保能 import app.*
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

# 测试用:强制使用 SQLite
os.environ.setdefault("USE_SQLITE", "True")
os.environ.setdefault("SQLITE_PATH", "data/test_quality.db")

# stub out optional 3rd-party modules
_STUB_MODULES = ["redis"]
for mod_name in _STUB_MODULES:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

# neo4j stub
if "neo4j" not in sys.modules:
    _neo4j_stub = types.ModuleType("neo4j")
    _neo4j_stub.GraphDatabase = type("GraphDatabase", (), {
        "driver": staticmethod(lambda *a, **kw: None),
        "verify_connectivity": staticmethod(lambda *a, **kw: None),
    })
    _neo4j_stub.Driver = type("Driver", (), {})
    _neo4j_stub.Session = type("Session", (), {})
    _neo4j_stub.Graph = type("Graph", (), {})
    _neo4j_stub.Node = type("Node", (), {})
    _neo4j_stub.Relationship = type("Relationship", (), {})
    _neo4j_stub.Path = type("Path", (), {})
    _neo4j_stub.Transaction = type("Transaction", (), {})
    _neo4j_stub.Result = type("Result", (), {})
    _neo4j_stub.Record = type("Record", (), {})
    _neo4j_stub.exceptions = types.SimpleNamespace(
        ServiceUnavailable=Exception, AuthError=Exception, CypherError=Exception,
        ClientError=Exception, DatabaseError=Exception, TransientError=Exception,
    )
    sys.modules["neo4j"] = _neo4j_stub

# pymilvus stub
if "pymilvus" not in sys.modules:
    _pymilvus_stub = types.ModuleType("pymilvus")
    _pymilvus_stub.MilvusClient = type("MilvusClient", (), {
        "__init__": lambda self, *a, **kw: None,
        "create_collection": lambda self, *a, **kw: None,
        "drop_collection": lambda self, *a, **kw: None,
        "list_collections": lambda self, *a, **kw: [],
        "describe_collection": lambda self, *a, **kw: {},
        "insert": lambda self, *a, **kw: {"insert_count": 0},
        "search": lambda self, *a, **kw: [],
        "query": lambda self, *a, **kw: [],
        "delete": lambda self, *a, **kw: {"delete_count": 0},
        "upsert": lambda self, *a, **kw: {"upsert_count": 0},
        "close": lambda self, *a, **kw: None,
    })
    _pymilvus_stub.DataType = type("DataType", (), {
        "INT64": "INT64", "FLOAT_VECTOR": "FLOAT_VECTOR", "BOOL": "BOOL",
        "DOUBLE": "DOUBLE", "VARCHAR": "VARCHAR", "JSON": "JSON",
    })
    _pymilvus_stub.CollectionSchema = type("CollectionSchema", (), {"__init__": lambda self, *a, **kw: None})
    _pymilvus_stub.FieldSchema = type("FieldSchema", (), {"__init__": lambda self, *a, **kw: None})
    _pymilvus_stub.Collection = type("Collection", (), {
        "__init__": lambda self, *a, **kw: None,
        "create": lambda self, *a, **kw: None, "drop": lambda self, *a, **kw: None,
        "load": lambda self, *a, **kw: None, "release": lambda self, *a, **kw: None,
        "insert": lambda self, *a, **kw: None, "search": lambda self, *a, **kw: [],
        "query": lambda self, *a, **kw: [],
    })
    _pymilvus_stub.utility = types.SimpleNamespace(
        list_collections=lambda *a, **kw: [], has_collection=lambda *a, **kw: False,
        drop_collection=lambda *a, **kw: None, create_collection=lambda *a, **kw: None,
        get_connection=lambda *a, **kw: None, connect=lambda *a, **kw: None,
        disconnect=lambda *a, **kw: None,
    )
    _pymilvus_stub.exceptions = types.SimpleNamespace(MilvusException=Exception)
    _pymilvus_stub.list_collections = lambda *a, **kw: []
    sys.modules["pymilvus"] = _pymilvus_stub
    sys.modules["pymilvus.utility"] = _pymilvus_stub.utility
    sys.modules["pymilvus.exceptions"] = _pymilvus_stub.exceptions

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("test_quality_analysis")

results = []


def record(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    results.append({"name": name, "status": status, "detail": detail})
    logger.info(f"[{status}] {name}" + (f" - {detail}" if detail else ""))


# ============================================================
# 数据库准备
# ============================================================

def setup_database():
    """创建测试所需的数据库表"""
    from app.db.database import Base, sync_engine
    from app.models.quality_report import QualityReport
    from app.models.test_asset import TestAsset
    from app.models.execution_record import ExecutionRecord
    from app.models.flow_result import FlowResult

    # Monkey-patch MEDIUMTEXT → Text for SQLite compatibility
    from sqlalchemy.dialects.mysql import MEDIUMTEXT
    from sqlalchemy import Text
    # Replace MEDIUMTEXT instances in column types with Text
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, MEDIUMTEXT):
                col.type = Text()

    tables_to_create = [
        QualityReport.__table__,
        TestAsset.__table__,
        ExecutionRecord.__table__,
        FlowResult.__table__,
    ]
    Base.metadata.create_all(bind=sync_engine, tables=tables_to_create)
    logger.info("测试数据库表已创建")


def cleanup_database():
    """清理测试数据"""
    from app.db.database import SessionLocal
    from app.models.quality_report import QualityReport
    from app.models.test_asset import TestAsset
    from app.models.execution_record import ExecutionRecord
    from app.models.flow_result import FlowResult

    db = SessionLocal()
    try:
        db.query(FlowResult).delete()
        db.query(ExecutionRecord).delete()
        db.query(TestAsset).delete()
        db.query(QualityReport).delete()
        db.commit()
        logger.info("测试数据已清理")
    finally:
        db.close()


def seed_test_data():
    """创建测试数据(测试资产 + 执行记录 + 缺陷数据)"""
    from app.db.database import SessionLocal
    from app.models.test_asset import TestAsset
    from app.models.execution_record import ExecutionRecord
    from app.models.flow_result import FlowResult

    db = SessionLocal()
    try:
        # 1. 测试资产(覆盖多个模块和类型)
        assets = [
            TestAsset(
                title="登录功能-正常登录",
                asset_type="api",
                status="published",
                executable=True,
                priority="P0",
                tags="login,auth",
                content_json=json.dumps({
                    "module": "login",
                    "steps": [{"action": "POST /api/login"}],
                    "assertions": [{"path": "$.code", "operator": "eq", "expected": 200}],
                }),
                user_id=1, created_by=1,
            ),
            TestAsset(
                title="登录功能-密码错误",
                asset_type="api",
                status="published",
                executable=True,
                priority="P0",
                tags="login,auth",
                content_json=json.dumps({"module": "login"}),
                user_id=1, created_by=1,
            ),
            TestAsset(
                title="支付功能-正常支付",
                asset_type="api",
                status="published",
                executable=True,
                priority="P0",
                tags="payment",
                content_json=json.dumps({"module": "payment"}),
                user_id=1, created_by=1,
            ),
            TestAsset(
                title="支付功能-余额不足",
                asset_type="api",
                status="published",
                executable=True,
                priority="P1",
                tags="payment",
                content_json=json.dumps({"module": "payment"}),
                user_id=1, created_by=1,
            ),
            TestAsset(
                title="用户管理-查询用户列表",
                asset_type="web",
                status="draft",
                executable=False,
                priority="P2",
                tags="user",
                content_json=json.dumps({"module": "user"}),
                user_id=1, created_by=1,
            ),
            TestAsset(
                title="登录功能-正常登录(重复)",
                asset_type="api",
                status="published",
                executable=True,
                priority="P1",
                tags="login,auth",
                content_json=json.dumps({"module": "login"}),
                user_id=1, created_by=1,
            ),
        ]
        for a in assets:
            db.add(a)
        db.flush()

        # 2. 执行记录(含失败记录)
        now = datetime.now()
        executions = [
            ExecutionRecord(
                execution_type="api",
                status="success",
                success_count=2, failed_count=0,
                user_id=1, created_by=1,
                created_at=now - timedelta(days=30),
            ),
            ExecutionRecord(
                execution_type="api",
                status="failed",
                success_count=1, failed_count=1,
                error_message="AssertionError: expected 200 but got 500",
                log_content="##TEST_FAIL## 登录功能-密码错误\nAssertionError: expected 200 but got 500",
                user_id=1, created_by=1,
                created_at=now - timedelta(days=20),
            ),
            ExecutionRecord(
                execution_type="web",
                status="failed",
                success_count=0, failed_count=1,
                error_message="TimeoutError: element not found after 30s",
                log_content="##TEST_FAIL## 用户管理\nTimeoutError: element not found",
                user_id=1, created_by=1,
                created_at=now - timedelta(days=10),
            ),
            ExecutionRecord(
                execution_type="api",
                status="success",
                success_count=3, failed_count=0,
                user_id=1, created_by=1,
                created_at=now - timedelta(days=5),
            ),
        ]
        for e in executions:
            db.add(e)
        db.flush()

        # 3. 缺陷数据(flow_result 表)
        defects = [
            FlowResult(
                task_id=1,
                session_key="test_1",
                step="defect",
                agent_name="defect_agent",
                status="success",
                message_type="DefectMessage",
                output_json=json.dumps({
                    "module": "login",
                    "error_type": "assertion",
                    "severity": "high",
                    "error_message": "密码错误时返回500",
                }),
                created_at=now - timedelta(days=20),
            ),
            FlowResult(
                task_id=2,
                session_key="test_2",
                step="defect",
                agent_name="defect_agent",
                status="success",
                message_type="DefectMessage",
                output_json=json.dumps({
                    "module": "user",
                    "error_type": "timeout",
                    "severity": "medium",
                    "error_message": "元素未找到",
                }),
                created_at=now - timedelta(days=10),
            ),
        ]
        for d in defects:
            db.add(d)

        db.commit()
        logger.info("测试数据已创建: 6 个资产, 4 个执行记录, 2 个缺陷")
    finally:
        db.close()


# ============================================================
# 测试用例
# ============================================================

async def test_01_quality_report_model():
    """测试 1:QualityReport 数据模型"""
    from app.db.database import SessionLocal
    from app.models.quality_report import QualityReport

    db = SessionLocal()
    try:
        # 创建
        report = QualityReport(
            title="测试质量报告",
            description="2026年Q2质量分析",
            status="pending",
            analysis_scope=json.dumps({"modules": ["login", "payment"]}),
            user_id=1, created_by=1,
        )
        db.add(report)
        db.flush()

        record("创建 QualityReport", report.id is not None, f"id={report.id}")
        record("默认状态 pending", report.status == "pending", "")
        record("默认 is_deleted False", report.is_deleted is False, "")

        # to_dict (不含分析)
        d = report.to_dict(include_analysis=False)
        record("to_dict 返回 id", d["id"] == report.id, "")
        record("to_dict 返回 title", d["title"] == "测试质量报告", "")
        record("to_dict 返回 status", d["status"] == "pending", "")
        record("to_dict 返回 analysis_scope", d["analysis_scope"] == {"modules": ["login", "payment"]}, "")

        # 更新分析结果
        report.status = "completed"
        report.quality_score = 75.5
        report.coverage_score = 80.0
        report.risk_score = 70.0
        report.duplication_score = 85.0
        report.defect_score = 67.0
        report.summary = "质量评估良好"
        report.coverage_analysis = json.dumps({"coverage_rate": 0.8})
        report.risk_analysis = json.dumps({"high_risk_modules": []})
        report.duplication_analysis = json.dumps({"duplication_rate": 0.15})
        report.defect_trend = json.dumps({"trend": "stable"})
        report.recommendations = json.dumps(["建议1", "建议2"])
        report.input_stats = json.dumps({"asset_count": 6})
        db.flush()

        # to_dict (含分析)
        d2 = report.to_dict(include_analysis=True)
        record("to_dict quality_score", d2["quality_score"] == 75.5, "")
        record("to_dict coverage_analysis 解析", d2["coverage_analysis"]["coverage_rate"] == 0.8, "")
        record("to_dict recommendations 解析", d2["recommendations"] == ["建议1", "建议2"], "")
        record("to_dict input_stats 解析", d2["input_stats"]["asset_count"] == 6, "")

        # 清理
        db.delete(report)
        db.commit()
    finally:
        db.close()


async def test_02_service_crud():
    """测试 2:QualityAnalysisService CRUD"""
    from app.services.quality_analysis_service import (
        get_quality_analysis_service,
        reset_quality_analysis_service,
    )
    reset_quality_analysis_service()
    svc = get_quality_analysis_service()

    # 1. 创建
    report = svc.create_analysis({
        "title": "Q2 质量分析",
        "description": "第二季度测试质量分析",
        "analysis_scope": {"modules": ["login", "payment"]},
    }, user_id=1, background=True)  # background=True 避免同步等待
    report_id = report["id"]
    record("创建分析任务", report["title"] == "Q2 质量分析", f"id={report_id}")
    record("创建后状态 pending", report["status"] == "pending", "")

    # 2. 查询
    got = svc.get_report(report_id, user_id=1)
    record("查询报告", got is not None and got["id"] == report_id, "")

    # 3. 列表
    listing = svc.list_reports(user_id=1, page=1, page_size=10)
    record("列表查询", listing["total"] >= 1, f"total={listing['total']}")

    # 4. 按状态筛选
    pending_list = svc.list_reports(status="pending", user_id=1)
    record("按状态筛选", pending_list["total"] >= 1, "")

    # 5. 更新
    updated = svc.update_report(report_id, {"title": "更新后的标题"}, user_id=1)
    record("更新标题", updated["title"] == "更新后的标题", "")

    # 6. 软删除
    ok = svc.delete_report(report_id, hard=False, user_id=1)
    record("软删除", ok, "")
    deleted = svc.get_report(report_id, user_id=1)
    record("删除后查询返回 None", deleted is None, "")

    # 7. 硬删除(清理)
    svc.delete_report(report_id, hard=True, user_id=1)


async def test_03_agent_data_collection():
    """测试 3:Agent 数据收集"""
    from app.agents.flows.quality_analysis_agent import QualityAnalysisAgent

    agent = QualityAnalysisAgent()
    input_data = await agent._collect_input_data({}, user_id=1)

    record("收集测试资产", input_data["asset_count"] >= 6, f"count={input_data['asset_count']}")
    record("收集执行记录", input_data["execution_count"] >= 4, f"count={input_data['execution_count']}")
    record("收集缺陷数据", input_data["defect_count"] >= 2, f"count={input_data['defect_count']}")

    # 验证隐含缺陷提取
    implied = [d for d in input_data["defects"] if d.get("id") is None]
    record("隐含缺陷提取", len(implied) >= 1, f"implied={len(implied)}")

    # 验证模块提取
    modules = input_data.get("modules", [])
    record("模块提取", len(modules) >= 1, f"modules={modules}")


async def test_04_agent_coverage_analysis():
    """测试 4:覆盖不足分析"""
    from app.agents.flows.quality_analysis_agent import QualityAnalysisAgent

    agent = QualityAnalysisAgent()

    # mock LLM 调用
    agent.call_llm = AsyncMock(return_value=json.dumps({
        "uncovered_modules": [{"module": "user", "reason": "无可执行用例", "severity": "medium"}],
        "coverage_assessment": "覆盖率一般,用户管理模块未覆盖",
        "risk_areas": ["user 模块"],
        "suggestions": ["补充用户管理模块测试"],
    }))

    input_data = await agent._collect_input_data({}, user_id=1)
    result = await agent._analyze_coverage(input_data)

    record("覆盖率计算", "coverage_rate" in result, f"rate={result.get('coverage_rate')}")
    record("总模块数", "total_modules" in result, f"total={result.get('total_modules')}")
    record("已覆盖模块", "covered_modules" in result, f"covered={result.get('covered_modules')}")
    record("按类型覆盖", "by_type" in result, "")
    record("未覆盖模块列表", "uncovered_modules" in result, "")
    record("改进建议", "suggestions" in result, "")


async def test_05_agent_risk_analysis():
    """测试 5:高风险模块分析"""
    from app.agents.flows.quality_analysis_agent import QualityAnalysisAgent

    agent = QualityAnalysisAgent()
    agent.call_llm = AsyncMock(return_value=json.dumps({
        "high_risk_modules": [{"module": "login", "risk_score": 0.8, "reasons": ["缺陷密度高"]}],
        "medium_risk_modules": [],
        "risk_assessment": "登录模块风险较高",
        "suggestions": ["增加登录模块测试"],
    }))

    input_data = await agent._collect_input_data({}, user_id=1)
    result = await agent._analyze_risk(input_data)

    record("高风险模块列表", "high_risk_modules" in result, "")
    record("风险分布", "risk_distribution" in result, "")
    record("风险分布含 high", "high" in result.get("risk_distribution", {}), "")


async def test_06_agent_duplication_analysis():
    """测试 6:重复测试分析"""
    from app.agents.flows.quality_analysis_agent import QualityAnalysisAgent

    agent = QualityAnalysisAgent()
    agent.call_llm = AsyncMock(return_value=json.dumps({
        "duplicate_groups": [{"group_id": "grp_1", "cases": ["登录功能-正常登录", "登录功能-正常登录(重复)"], "similarity": 0.9}],
        "duplication_assessment": "存在1组重复用例",
        "suggestions": ["合并重复用例"],
    }))

    input_data = await agent._collect_input_data({}, user_id=1)
    result = await agent._analyze_duplication(input_data)

    record("总用例数", "total_cases" in result, f"total={result.get('total_cases')}")
    record("重复用例数", "duplicate_count" in result, "")
    record("重复率", "duplication_rate" in result, "")
    record("重复组列表", "duplicate_groups" in result, "")

    # 验证相似度计算
    sim = agent._compute_similarity(
        {"title": "登录功能-正常登录", "module": "login", "asset_type": "api"},
        {"title": "登录功能-正常登录(重复)", "module": "login", "asset_type": "api"},
    )
    record("相似度计算 >= 0.5", sim >= 0.5, f"sim={sim:.4f}")


async def test_07_agent_defect_trend():
    """测试 7:缺陷趋势分析"""
    from app.agents.flows.quality_analysis_agent import QualityAnalysisAgent

    agent = QualityAnalysisAgent()
    agent.call_llm = AsyncMock(return_value=json.dumps({
        "trend": "stable",
        "trend_assessment": "缺陷趋势稳定",
        "by_module": [{"module": "login", "count": 1, "top_errors": ["assertion"]}],
        "predictions": "预计下月缺陷数持平",
        "suggestions": ["持续监控"],
    }))

    input_data = await agent._collect_input_data({}, user_id=1)
    result = await agent._analyze_defect_trend(input_data)

    record("趋势判断", "trend" in result, f"trend={result.get('trend')}")
    record("按类型分布", "by_type" in result, "")


async def test_08_quality_score_computation():
    """测试 8:质量分数计算"""
    from app.agents.flows.quality_analysis_agent import QualityAnalysisAgent

    agent = QualityAnalysisAgent()

    # 测试各分项分数计算
    coverage_score = agent._compute_coverage_score(
        {"coverage_rate": 0.8}, {"asset_count": 10}
    )
    record("覆盖率分数 = 80", coverage_score == 80.0, f"score={coverage_score}")

    risk_score = agent._compute_risk_score({
        "risk_distribution": {"high": 1, "medium": 2, "low": 3}
    })
    record("风险分数计算", 0 <= risk_score <= 100, f"score={risk_score}")

    dup_score = agent._compute_duplication_score(
        {"duplication_rate": 0.15}, {"asset_count": 10}
    )
    record("重复度分数计算", 0 <= dup_score <= 100, f"score={dup_score}")

    defect_score = agent._compute_defect_score(
        {"trend": "decreasing"}, {"defect_count": 2, "execution_count": 4}
    )
    record("缺陷分数计算", 0 <= defect_score <= 100, f"score={defect_score}")


async def test_09_agent_registration():
    """测试 9:Agent 注册验证"""
    # 验证 DEFAULT_AGENT_SPECS 中有 quality_analysis_agent
    from app.agents.factory.definitions import DEFAULT_AGENT_SPECS

    found = None
    for spec in DEFAULT_AGENT_SPECS:
        if spec.name == "quality_analysis_agent":
            found = spec
            break

    record("DEFAULT_AGENT_SPECS 包含 quality_analysis_agent", found is not None, "")
    if found:
        record("display_name 正确", found.display_name == "质量分析Agent", "")
        record("module_path 正确", found.module_path == "app.agents.flows.quality_analysis_agent", "")
        record("class_name 正确", found.class_name == "QualityAnalysisAgent", "")
        record("agent_type 是 llm", found.agent_type == "llm", "")
        record("capabilities 包含 quality_analysis", "quality_analysis" in found.capabilities, "")
        record("enabled 为 True", found.enabled is True, "")


async def test_10_api_routes():
    """测试 10:API 路由完整性"""
    from app.api.quality_analysis import router

    record("API 路由数量 >= 9", len(router.routes) >= 9, f"actual={len(router.routes)}")

    all_paths = [r.path for r in router.routes]
    record("路由 /list 存在", "/list" in all_paths, "")
    record("路由 /dashboard 存在", "/dashboard" in all_paths, "")
    record("路由 /stats 存在", "/stats" in all_paths, "")
    record("路由 /{report_id} 存在", "/{report_id}" in all_paths, "")
    record("路由 /{report_id}/regenerate 存在", "/{report_id}/regenerate" in all_paths, "")
    record("路由 /{report_id}/run 存在", "/{report_id}/run" in all_paths, "")

    # 验证路由已注册到 api_router
    api_init_path = backend_dir / "app" / "api" / "__init__.py"
    api_init_content = api_init_path.read_text(encoding="utf-8")
    has_import = "from app.api.quality_analysis import router as quality_analysis_router" in api_init_content
    has_register = 'api_router.include_router(quality_analysis_router' in api_init_content
    has_prefix = 'prefix="/quality-analysis"' in api_init_content
    record("api/__init__.py 导入 quality_analysis_router", has_import, "")
    record("api/__init__.py 注册路由", has_register, "")
    record("api/__init__.py 设置 prefix=/quality-analysis", has_prefix, "")


async def test_11_dashboard():
    """测试 11:质量仪表盘"""
    from app.services.quality_analysis_service import (
        get_quality_analysis_service,
        reset_quality_analysis_service,
    )
    reset_quality_analysis_service()
    svc = get_quality_analysis_service()

    # 创建几个报告
    for i in range(3):
        svc.create_analysis({
            "title": f"报告 {i+1}",
            "description": "测试",
        }, user_id=1, background=True)

    # 手动更新一个报告为 completed
    from app.db.database import SessionLocal
    from app.models.quality_report import QualityReport
    db = SessionLocal()
    try:
        report = db.query(QualityReport).filter(QualityReport.title == "报告 1").first()
        if report:
            report.status = "completed"
            report.quality_score = 75.5
            report.coverage_score = 80.0
            report.risk_score = 70.0
            report.duplication_score = 85.0
            report.defect_score = 67.0
            db.commit()
    finally:
        db.close()

    dashboard = svc.get_dashboard(user_id=1)
    record("仪表盘总数", dashboard["total"] >= 3, f"total={dashboard['total']}")
    record("仪表盘 by_status", "completed" in dashboard["by_status"], "")
    record("仪表盘 avg_scores", "quality" in dashboard["avg_scores"], "")
    record("仪表盘 avg_scores.quality > 0", dashboard["avg_scores"]["quality"] > 0, "")
    record("仪表盘 recent_reports", len(dashboard["recent_reports"]) > 0, "")


async def test_12_stats():
    """测试 12:统计信息"""
    from app.services.quality_analysis_service import get_quality_analysis_service

    svc = get_quality_analysis_service()
    stats = svc.get_stats(user_id=1)

    record("统计总数", "total" in stats, f"total={stats['total']}")
    record("统计 completed", "completed" in stats, "")
    record("统计 analyzing", "analyzing" in stats, "")
    record("统计 failed", "failed" in stats, "")
    record("统计 avg_quality_score", "avg_quality_score" in stats, "")


async def test_13_agent_execute_mock():
    """测试 13:Agent 完整执行流程(mock LLM)"""
    from app.agents.flows.quality_analysis_agent import QualityAnalysisAgent
    from app.services.quality_analysis_service import get_quality_analysis_service
    from app.db.database import SessionLocal
    from app.models.quality_report import QualityReport

    svc = get_quality_analysis_service()
    # 创建报告
    report = svc.create_analysis({
        "title": "完整流程测试",
        "description": "测试 Agent 完整执行",
        "analysis_scope": {},
    }, user_id=1, background=True)
    report_id = report["id"]

    # 创建 Agent 并 mock LLM
    agent = QualityAnalysisAgent()

    # mock call_llm 返回不同的 JSON
    call_count = [0]

    async def mock_call_llm(system_prompt="", user_prompt="", **kwargs):
        call_count[0] += 1
        if "覆盖率分析" in system_prompt:
            return json.dumps({
                "uncovered_modules": [{"module": "user", "reason": "无测试", "severity": "medium"}],
                "coverage_assessment": "覆盖率需提升",
                "suggestions": ["补充 user 模块测试"],
            })
        elif "风险评估" in system_prompt:
            return json.dumps({
                "high_risk_modules": [{"module": "login", "risk_score": 0.8, "reasons": ["缺陷多"]}],
                "risk_assessment": "登录模块高风险",
                "suggestions": ["加强登录测试"],
            })
        elif "重复性分析" in system_prompt:
            return json.dumps({
                "duplicate_groups": [],
                "duplication_assessment": "重复率低",
                "suggestions": ["保持现状"],
            })
        elif "缺陷趋势" in system_prompt:
            return json.dumps({
                "trend": "stable",
                "trend_assessment": "趋势稳定",
                "suggestions": ["持续监控"],
            })
        elif "综合质量" in system_prompt:
            return json.dumps({
                "summary": "整体质量良好,需关注登录模块",
                "quality_assessment": "质量评估良好",
                "top_issues": ["登录模块缺陷较多"],
                "recommendations": ["加强登录测试", "补充用户管理测试"],
            })
        return "{}"

    agent.call_llm = mock_call_llm

    # 执行分析
    result = await agent._do_analysis({"report_id": report_id, "user_id": 1})

    record("Agent 执行返回 success", result.get("status") == "success", f"status={result.get('status')}")
    record("Agent 执行返回 quality_score", "quality_score" in result, f"score={result.get('quality_score')}")
    record("Agent 执行返回 coverage_score", "coverage_score" in result, "")
    record("Agent 执行返回 risk_score", "risk_score" in result, "")
    record("Agent 执行返回 recommendations", "recommendations" in result, "")
    record("LLM 调用次数 >= 5", call_count[0] >= 5, f"calls={call_count[0]}")

    # 验证报告已保存到数据库
    db = SessionLocal()
    try:
        saved = db.query(QualityReport).filter(QualityReport.id == report_id).first()
        record("报告状态为 completed", saved.status == "completed", f"status={saved.status}")
        record("报告 quality_score 已保存", saved.quality_score is not None, f"score={saved.quality_score}")
        record("报告 summary 已保存", saved.summary is not None, "")
        record("报告 coverage_analysis 已保存", saved.coverage_analysis is not None, "")
        record("报告 recommendations 已保存", saved.recommendations is not None, "")
    finally:
        db.close()

    # 清理
    svc.delete_report(report_id, hard=True, user_id=1)


async def test_14_service_regenerate():
    """测试 14:重新生成分析"""
    from app.services.quality_analysis_service import get_quality_analysis_service

    svc = get_quality_analysis_service()
    report = svc.create_analysis({
        "title": "重新生成测试",
        "description": "测试",
    }, user_id=1, background=True)
    report_id = report["id"]

    # 重新生成(background=True 避免同步等待)
    result = svc.regenerate(report_id, user_id=1, background=True)
    record("重新生成返回 id", result["id"] == report_id, "")
    record("重新生成后状态 pending", result["status"] == "pending", "")
    record("重新生成后 quality_score None", result.get("quality_score") is None, "")

    # 清理
    svc.delete_report(report_id, hard=True, user_id=1)


# ============================================================
# 主函数
# ============================================================

async def main():
    """运行所有测试"""
    logger.info("=" * 60)
    logger.info("AI 测试质量分析系统全链路测试开始")
    logger.info("=" * 60)

    try:
        setup_database()
    except Exception as e:
        logger.error(f"数据库准备失败: {e}")
        return False

    cleanup_database()
    seed_test_data()

    tests = [
        test_01_quality_report_model,
        test_02_service_crud,
        test_03_agent_data_collection,
        test_04_agent_coverage_analysis,
        test_05_agent_risk_analysis,
        test_06_agent_duplication_analysis,
        test_07_agent_defect_trend,
        test_08_quality_score_computation,
        test_09_agent_registration,
        test_10_api_routes,
        test_11_dashboard,
        test_12_stats,
        test_13_agent_execute_mock,
        test_14_service_regenerate,
    ]

    for test in tests:
        try:
            await test()
        except Exception as e:
            record(test.__doc__ or test.__name__, False, f"Exception: {e}")
            import traceback
            traceback.print_exc()

    cleanup_database()

    # 汇总
    logger.info("=" * 60)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    logger.info(f"测试汇总: {passed} passed, {failed} failed, {len(results)} total")
    logger.info("=" * 60)

    for r in results:
        logger.info(f"  [{r['status']}] {r['name']}" + (f" - {r['detail']}" if r['detail'] else ""))

    report_path = backend_dir / "test_quality_analysis_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "summary": {"passed": passed, "failed": failed, "total": len(results)},
            "results": results,
        }, f, ensure_ascii=False, indent=2)
    logger.info(f"报告已保存: {report_path}")

    return failed == 0


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
