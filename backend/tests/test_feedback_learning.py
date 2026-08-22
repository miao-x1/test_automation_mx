"""
AI 测试反馈学习系统全链路测试

验证:
1. FeedbackLearningRecord / FeedbackOptimization 数据模型(CRUD + JSON 字段解析)
2. FeedbackLearningService 服务层(create_learning/list_records/list_optimizations/dashboard/stats)
3. FeedbackLearningAgent 案例收集(成功/失败/修改)
4. FeedbackLearningAgent 三维度分析(成功/失败/修改)
5. RAG/Prompt/策略 三类优化建议生成
6. 优化建议应用(prompt → PromptManager / rag / strategy)
7. 优化建议拒绝
8. Agent 注册验证(DEFAULT_AGENT_SPECS)
9. API 路由完整性(13 个路由)
10. 仪表盘聚合统计

运行:
    cd backend
    python -m tests.test_feedback_learning
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
os.environ.setdefault("SQLITE_PATH", "data/test_feedback_learning.db")

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
logger = logging.getLogger("test_feedback_learning")

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
    from app.models.feedback_learning import FeedbackLearningRecord, FeedbackOptimization
    from app.models.execution_record import ExecutionRecord
    from app.models.asset_registry import AssetVersion, AssetRegistry
    from app.models.test_case_review import TestCaseReview
    from app.models.user import User, Workspace
    from app.models.prompt_version import PromptVersion

    # Monkey-patch MEDIUMTEXT → Text for SQLite compatibility
    from sqlalchemy.dialects.mysql import MEDIUMTEXT
    from sqlalchemy import Text
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, MEDIUMTEXT):
                col.type = Text()

    tables_to_create = [
        User.__table__,
        Workspace.__table__,
        AssetRegistry.__table__,
        AssetVersion.__table__,
        ExecutionRecord.__table__,
        TestCaseReview.__table__,
        PromptVersion.__table__,
        FeedbackLearningRecord.__table__,
        FeedbackOptimization.__table__,
    ]
    Base.metadata.create_all(bind=sync_engine, tables=tables_to_create)
    logger.info("测试数据库表已创建")


def cleanup_database():
    """清理测试数据"""
    from app.db.database import SessionLocal
    from app.models.feedback_learning import FeedbackLearningRecord, FeedbackOptimization
    from app.models.execution_record import ExecutionRecord
    from app.models.asset_registry import AssetVersion, AssetRegistry
    from app.models.test_case_review import TestCaseReview
    from app.models.prompt_version import PromptVersion
    from app.models.user import User, Workspace

    db = SessionLocal()
    try:
        db.query(FeedbackOptimization).delete()
        db.query(FeedbackLearningRecord).delete()
        db.query(TestCaseReview).delete()
        db.query(AssetVersion).delete()
        db.query(AssetRegistry).delete()
        db.query(ExecutionRecord).delete()
        db.query(PromptVersion).delete()
        db.query(Workspace).delete()
        db.query(User).delete()
        db.commit()
        logger.info("测试数据已清理")
    finally:
        db.close()


def seed_test_data():
    """创建测试数据(执行记录 + 资产版本 + 审核记录)"""
    from app.db.database import SessionLocal
    from app.models.execution_record import ExecutionRecord
    from app.models.asset_registry import AssetVersion, AssetRegistry
    from app.models.test_case_review import TestCaseReview
    from app.models.user import User, Workspace

    db = SessionLocal()
    try:
        # 创建测试用户(如果不存在)
        user = db.query(User).filter(User.id == 1).first()
        if user is None:
            user = User(username="test_user", email="test@test.com", hashed_password="hashed")
            db.add(user)
            db.flush()

        # 创建 workspace(避免 lazy load 失败)
        ws = db.query(Workspace).filter(Workspace.user_id == user.id).first()
        if ws is None:
            ws = Workspace(user_id=user.id, name="测试空间")
            db.add(ws)
            db.flush()

        # 1. 执行记录(成功 + 失败)
        now = datetime.now()
        executions = [
            # 成功案例
            ExecutionRecord(
                status="success", execution_type="api",
                success_count=5, failed_count=0, duration=12.5,
                user_id=1, created_by=1, created_at=now - timedelta(days=1),
            ),
            ExecutionRecord(
                status="success", execution_type="web",
                success_count=3, failed_count=0, duration=25.3,
                user_id=1, created_by=1, created_at=now - timedelta(days=2),
            ),
            ExecutionRecord(
                status="success", execution_type="api",
                success_count=8, failed_count=0, duration=8.1,
                user_id=1, created_by=1, created_at=now - timedelta(days=3),
            ),
            # 失败案例
            ExecutionRecord(
                status="failed", execution_type="web",
                success_count=2, failed_count=3, duration=30.0,
                error_message="Element not found: button#submit",
                log_content="##TEST_FAIL## Click failed on button#submit\nTimeoutError: 30000ms",
                analysis_result=json.dumps({
                    "root_cause": "元素定位器不稳定",
                    "suggestion": "使用更稳定的CSS选择器",
                }),
                user_id=1, created_by=1, created_at=now - timedelta(days=1),
            ),
            ExecutionRecord(
                status="failed", execution_type="api",
                success_count=0, failed_count=5, duration=5.0,
                error_message="Connection refused: localhost:8080",
                log_content="ConnectionError: Connection refused",
                analysis_result=json.dumps({
                    "root_cause": "服务未启动",
                    "suggestion": "检查服务状态",
                }),
                user_id=1, created_by=1, created_at=now - timedelta(days=2),
            ),
            ExecutionRecord(
                status="failed", execution_type="api",
                success_count=4, failed_count=1, duration=15.0,
                error_message="AssertionError: expected 200 but got 404",
                log_content="##TEST_FAIL## Status code assertion failed",
                analysis_result=json.dumps({
                    "root_cause": "接口返回404",
                    "suggestion": "检查路由配置",
                }),
                user_id=1, created_by=1, created_at=now - timedelta(days=3),
            ),
        ]
        for e in executions:
            db.add(e)
        db.flush()

        # 2. 资产版本(人工修改记录)
        # 先创建 AssetRegistry
        registry = AssetRegistry(
            asset_code="ASSET-TEST-0001",
            name="登录测试资产",
            asset_type="case",
            ref_type="test_case",
            ref_id=1,
            status="active",
            source="manual",
            user_id=1, created_by=1,
        )
        db.add(registry)
        db.flush()

        versions = [
            AssetVersion(
                asset_id=registry.id,
                version=1,
                snapshot_json=json.dumps({"title": "登录测试", "assertions": ["code == 200"]}),
                change_type="update",
                change_log="修改了断言条件",
                diff_summary=json.dumps({
                    "fields": ["assertions"],
                    "old": "code == 200",
                    "new": "code == 200 and message == 'success'",
                }),
                is_current=False,
                user_id=1, created_by=1,
                created_at=now - timedelta(days=5),
            ),
            AssetVersion(
                asset_id=registry.id,
                version=2,
                snapshot_json=json.dumps({"title": "登录测试", "assertions": ["code == 200"]}),
                change_type="rollback",
                change_log="回滚到v1版本",
                diff_summary=json.dumps({
                    "fields": ["assertions"],
                    "old": "code == 200 and message == 'success'",
                    "new": "code == 200",
                }),
                is_current=True,
                user_id=1, created_by=1,
                created_at=now - timedelta(days=2),
            ),
        ]
        for v in versions:
            db.add(v)
        db.flush()

        # 3. 审核记录
        reviews = [
            TestCaseReview(
                case_id=1,
                score=65.0,
                review_result="need_revision",
                suggestion=json.dumps(["增加边界条件测试", "补充异常流程"]),
                issues=json.dumps(["断言不完整", "缺少负面测试"]),
                review_comment="用例需要修订",
                created_at=now - timedelta(days=1),
            ),
            TestCaseReview(
                case_id=2,
                score=45.0,
                review_result="reject",
                suggestion=json.dumps(["重新设计测试步骤"]),
                issues=json.dumps(["步骤混乱", "预期结果不明确"]),
                review_comment="用例不通过",
                created_at=now - timedelta(days=2),
            ),
            TestCaseReview(
                case_id=3,
                score=72.0,
                review_result="need_revision",
                suggestion=json.dumps(["增加数据验证"]),
                issues=json.dumps(["数据验证不足"]),
                review_comment="需要小修",
                created_at=now - timedelta(days=3),
            ),
        ]
        for r in reviews:
            db.add(r)

        db.commit()
        logger.info("测试数据已创建: 6条执行记录 + 2条资产版本 + 3条审核记录")
    finally:
        db.close()


# ============================================================
# 测试用例
# ============================================================

def test_model_feedback_learning_record():
    """测试 1: FeedbackLearningRecord 数据模型"""
    from app.db.database import SessionLocal
    from app.models.feedback_learning import FeedbackLearningRecord

    db = SessionLocal()
    try:
        rec = FeedbackLearningRecord(
            record_type="success",
            source="execution",
            source_id=1,
            agent_name="script_generation_agent",
            content_json=json.dumps({"execution_id": 1, "success_count": 5}),
            analysis_json=json.dumps({"patterns": ["stable"]}),
            tags="login,auth",
            module="login",
            status="analyzed",
            user_id=1, created_by=1,
        )
        db.add(rec)
        db.commit()
        db.refresh(rec)

        ok = rec.id is not None
        ok = ok and rec.record_type == "success"
        ok = ok and rec.source == "execution"
        ok = ok and rec.agent_name == "script_generation_agent"
        ok = ok and rec.status == "analyzed"

        d = rec.to_dict()
        ok = ok and d["record_type"] == "success"
        ok = ok and isinstance(d["content_json"], dict)
        ok = ok and d["content_json"]["success_count"] == 5
        ok = ok and isinstance(d["analysis_json"], dict)

        # 测试不含内容的序列化
        d2 = rec.to_dict(include_content=False)
        ok = ok and "content_json" not in d2

        record("模型-FeedbackLearningRecord CRUD + JSON解析", ok)
    finally:
        db.close()


def test_model_feedback_optimization():
    """测试 2: FeedbackOptimization 数据模型"""
    from app.db.database import SessionLocal
    from app.models.feedback_learning import FeedbackOptimization

    db = SessionLocal()
    try:
        opt = FeedbackOptimization(
            title="RAG检索参数优化",
            description="将top_k从3调整为5",
            optimization_type="rag",
            agent_name="rag_agent",
            optimization_json=json.dumps({
                "retrieval_params": {"top_k": 5, "score_threshold": 0.7},
                "index_suggestions": ["增加错误处理索引"],
            }),
            source_record_ids=json.dumps([1, 2, 3]),
            summary="基于失败分析,提升检索质量",
            confidence=0.85,
            status="pending",
            user_id=1, created_by=1,
        )
        db.add(opt)
        db.commit()
        db.refresh(opt)

        ok = opt.id is not None
        ok = ok and opt.optimization_type == "rag"
        ok = ok and opt.confidence == 0.85
        ok = ok and opt.status == "pending"

        d = opt.to_dict()
        ok = ok and d["optimization_type"] == "rag"
        ok = ok and isinstance(d["optimization_json"], dict)
        ok = ok and d["optimization_json"]["retrieval_params"]["top_k"] == 5
        ok = ok and isinstance(d["source_record_ids"], list)
        ok = ok and len(d["source_record_ids"]) == 3

        # 测试不含优化内容的序列化
        d2 = opt.to_dict(include_optimization=False)
        ok = ok and "optimization_json" not in d2

        record("模型-FeedbackOptimization CRUD + JSON解析", ok)
    finally:
        db.close()


def test_service_create_learning():
    """测试 3: 服务层 - 创建学习任务"""
    from app.services.feedback_learning_service import (
        get_feedback_learning_service,
        reset_feedback_learning_service,
    )
    reset_feedback_learning_service()
    svc = get_feedback_learning_service()

    result = svc.create_learning(
        {
            "title": "反馈学习测试任务",
            "description": "测试反馈学习全流程",
            "collect_scope": {"limit": 50},
        },
        user_id=1,
        background=True,  # 后台执行(会失败但不影响记录创建)
    )

    ok = result.get("id") is not None
    ok = ok and result.get("status") == "pending"
    ok = ok and result.get("title") == "反馈学习测试任务"
    ok = ok and result.get("optimization_type") == "strategy"

    record("服务-创建学习任务", ok, f"optimization_id={result.get('id')}")
    return result.get("id")


def test_service_list_records():
    """测试 4: 服务层 - 学习记录列表"""
    from app.services.feedback_learning_service import get_feedback_learning_service
    svc = get_feedback_learning_service()

    result = svc.list_records(user_id=1, page=1, page_size=10)

    ok = "items" in result
    ok = ok and "total" in result
    ok = ok and result["page"] == 1

    # 按类型筛选
    success_result = svc.list_records(record_type="success", user_id=1)
    ok = ok and success_result["total"] >= 0

    record("服务-学习记录列表", ok, f"total={result.get('total')}")


def test_service_list_optimizations():
    """测试 5: 服务层 - 优化建议列表"""
    from app.services.feedback_learning_service import get_feedback_learning_service
    svc = get_feedback_learning_service()

    result = svc.list_optimizations(user_id=1, page=1, page_size=10)

    ok = "items" in result
    ok = ok and "total" in result

    # 按类型筛选
    rag_result = svc.list_optimizations(optimization_type="rag", user_id=1)
    ok = ok and rag_result["total"] >= 0

    record("服务-优化建议列表", ok, f"total={result.get('total')}")


def test_service_dashboard():
    """测试 6: 服务层 - 仪表盘"""
    from app.services.feedback_learning_service import get_feedback_learning_service
    svc = get_feedback_learning_service()

    result = svc.get_dashboard(user_id=1)

    ok = "records" in result
    ok = ok and "optimizations" in result
    ok = ok and "recent_optimizations" in result
    ok = ok and "by_type" in result["records"]
    ok = ok and "by_status" in result["optimizations"]
    ok = ok and "avg_confidence" in result["optimizations"]

    record("服务-仪表盘", ok, f"records={result['records'].get('total')}")


def test_service_stats():
    """测试 7: 服务层 - 统计信息"""
    from app.services.feedback_learning_service import get_feedback_learning_service
    svc = get_feedback_learning_service()

    result = svc.get_stats(user_id=1)

    ok = "records_total" in result
    ok = ok and "optimizations_total" in result
    ok = ok and "records_by_type" in result
    ok = ok and "optimizations_applied" in result
    ok = ok and "avg_confidence" in result

    record("服务-统计信息", ok)


def test_agent_case_collection():
    """测试 8: Agent 案例收集"""
    from app.agents.flows.feedback_learning_agent import FeedbackLearningAgent

    agent = FeedbackLearningAgent()
    cases = asyncio.get_event_loop().run_until_complete(
        agent._collect_cases({}, user_id=1)
    )

    ok = cases["success_count"] >= 3  # 至少3条成功
    ok = ok and cases["failure_count"] >= 3  # 至少3条失败
    ok = ok and cases["modification_count"] >= 2  # 至少2条修改

    # 验证成功案例结构
    if cases["success"]:
        s = cases["success"][0]
        ok = ok and "execution_id" in s
        ok = ok and "agent_name" in s

    # 验证失败案例结构
    if cases["failure"]:
        f = cases["failure"][0]
        ok = ok and "error_type" in f
        ok = ok and "error_message" in f

    # 验证修改案例结构
    if cases["modification"]:
        m = cases["modification"][0]
        ok = ok and "source" in m

    record("Agent-案例收集(成功/失败/修改)", ok,
           f"success={cases['success_count']}, failure={cases['failure_count']}, mod={cases['modification_count']}")


def test_agent_error_classification():
    """测试 9: Agent 错误分类"""
    from app.agents.flows.feedback_learning_agent import FeedbackLearningAgent

    agent = FeedbackLearningAgent()

    ok = agent._classify_error("TimeoutError: 30s", "") == "timeout"
    ok = ok and agent._classify_error("AssertionError", "") == "assertion"
    ok = ok and agent._classify_error("Element not found", "") == "element_not_found"
    ok = ok and agent._classify_error("Connection refused", "") == "connection"
    ok = ok and agent._classify_error("SyntaxError", "") == "syntax"
    ok = ok and agent._classify_error("", "ImportError: no module") == "import_error"
    ok = ok and agent._classify_error("random error", "") == "unknown"

    record("Agent-错误类型分类", ok)


def test_agent_infer_agent_name():
    """测试 10: Agent 名称推断"""
    from app.agents.flows.feedback_learning_agent import FeedbackLearningAgent

    agent = FeedbackLearningAgent()

    ok = agent._infer_agent_name("api") == "api_case_agent"
    ok = ok and agent._infer_agent_name("web") == "script_generation_agent"
    ok = ok and agent._infer_agent_name("android") == "script_generation_agent"
    ok = ok and agent._infer_agent_name("suite") == "execution_agent"
    ok = ok and agent._infer_agent_name("unknown") == "unknown"
    ok = ok and agent._infer_agent_name(None) == "unknown"

    record("Agent-Agent名称推断", ok)


def test_agent_save_records():
    """测试 11: Agent 保存学习记录"""
    from app.agents.flows.feedback_learning_agent import FeedbackLearningAgent
    from app.db.database import SessionLocal
    from app.models.feedback_learning import FeedbackLearningRecord

    agent = FeedbackLearningAgent()
    cases = {
        "success": [{"execution_id": 999, "agent_name": "test_agent", "execution_type": "api"}],
        "success_count": 1,
        "failure": [{"execution_id": 998, "error_type": "timeout", "error_message": "test"}],
        "failure_count": 1,
        "modification": [{"source": "asset_version", "source_id": 1}],
        "modification_count": 1,
    }

    record_ids = asyncio.get_event_loop().run_until_complete(
        agent._save_learning_records(cases, user_id=1)
    )

    ok = len(record_ids) == 3

    # 验证记录已保存
    db = SessionLocal()
    try:
        records = db.query(FeedbackLearningRecord).filter(
            FeedbackLearningRecord.id.in_(record_ids)
        ).all()
        types = [r.record_type for r in records]
        ok = ok and "success" in types
        ok = ok and "failure" in types
        ok = ok and "modification" in types

        # 清理测试数据
        for r in records:
            db.delete(r)
        db.commit()
    finally:
        db.close()

    record("Agent-保存学习记录", ok, f"saved={len(record_ids)}")


def test_agent_analyze_success():
    """测试 12: Agent 成功分析(带 LLM Mock)"""
    from app.agents.flows.feedback_learning_agent import FeedbackLearningAgent

    agent = FeedbackLearningAgent()

    success_cases = [
        {"execution_type": "api", "agent_name": "api_case_agent", "duration": 10.0},
        {"execution_type": "web", "agent_name": "script_generation_agent", "duration": 20.0},
    ]

    # Mock LLM 返回
    mock_response = json.dumps({
        "success_patterns": ["API类型执行稳定"],
        "best_practices": ["使用合理的执行策略"],
        "key_factors": ["执行类型匹配"],
        "reusable_strategies": ["复用API执行策略"],
    })

    with patch.object(agent, "call_llm", new=AsyncMock(return_value=mock_response)):
        result = asyncio.get_event_loop().run_until_complete(
            agent._analyze_success(success_cases)
        )

    ok = "success_patterns" in result
    ok = ok and len(result["success_patterns"]) > 0
    ok = ok and result["total_count"] == 2
    ok = ok and "type_distribution" in result

    record("Agent-成功分析(LLM)", ok)


def test_agent_analyze_failure():
    """测试 13: Agent 失败分析(带 LLM Mock)"""
    from app.agents.flows.feedback_learning_agent import FeedbackLearningAgent

    agent = FeedbackLearningAgent()

    failure_cases = [
        {"error_type": "timeout", "agent_name": "script_generation_agent",
         "error_message": "TimeoutError", "execution_type": "web"},
        {"error_type": "assertion", "agent_name": "api_case_agent",
         "error_message": "AssertionError", "execution_type": "api"},
        {"error_type": "timeout", "agent_name": "script_generation_agent",
         "error_message": "TimeoutError", "execution_type": "web"},
    ]

    mock_response = json.dumps({
        "common_failures": [
            {"pattern": "timeout", "frequency": "high", "root_cause": "页面加载慢", "affected_agents": ["script_generation_agent"]}
        ],
        "failure_trends": "timeout错误最频繁",
        "high_risk_areas": ["web执行"],
        "prevention_suggestions": ["增加等待时间"],
    })

    with patch.object(agent, "call_llm", new=AsyncMock(return_value=mock_response)):
        result = asyncio.get_event_loop().run_until_complete(
            agent._analyze_failure(failure_cases)
        )

    ok = "common_failures" in result
    ok = ok and len(result["common_failures"]) > 0
    ok = ok and result["total_count"] == 3
    ok = ok and "error_type_distribution" in result

    record("Agent-失败分析(LLM)", ok)


def test_agent_analyze_modification():
    """测试 14: Agent 修改分析(带 LLM Mock)"""
    from app.agents.flows.feedback_learning_agent import FeedbackLearningAgent

    agent = FeedbackLearningAgent()

    modification_cases = [
        {"source": "asset_version", "change_type": "update", "change_log": "修改断言"},
        {"source": "test_case_review", "review_score": 65.0, "review_result": "need_revision",
         "suggestion": "增加边界测试"},
    ]

    mock_response = json.dumps({
        "common_issues": [
            {"issue": "断言不完整", "frequency": "high", "fix_pattern": "增加完整断言"}
        ],
        "quality_gaps": ["用例完整性不足"],
        "improvement_areas": ["加强断言"],
        "human_preferences": ["更完整的测试步骤"],
    })

    with patch.object(agent, "call_llm", new=AsyncMock(return_value=mock_response)):
        result = asyncio.get_event_loop().run_until_complete(
            agent._analyze_modification(modification_cases)
        )

    ok = "common_issues" in result
    ok = ok and len(result["common_issues"]) > 0
    ok = ok and result["total_count"] == 2
    ok = ok and "source_distribution" in result

    record("Agent-修改分析(LLM)", ok)


def test_agent_rag_optimization():
    """测试 15: Agent RAG 优化建议生成"""
    from app.agents.flows.feedback_learning_agent import FeedbackLearningAgent

    agent = FeedbackLearningAgent()

    success_analysis = {"success_patterns": ["API稳定"]}
    failure_analysis = {
        "error_type_distribution": {"timeout": 3, "assertion": 2},
        "total_count": 5,
    }
    modification_analysis = {"total_count": 2, "common_issues": [{"issue": "断言不完整"}]}

    # Mock LLM
    mock_response = json.dumps({
        "optimizations": [
            {
                "title": "增加timeout相关知识检索",
                "description": "timeout错误频发,需补充相关知识",
                "retrieval_params": {"top_k": 5, "score_threshold": 0.7, "rerank": True},
                "index_suggestions": ["增加timeout错误索引"],
                "knowledge_gaps": ["timeout处理知识不足"],
                "confidence": 0.8,
                "reasoning": "timeout错误占比最高",
            }
        ]
    })

    with patch.object(agent, "call_llm", new=AsyncMock(return_value=mock_response)):
        result = asyncio.get_event_loop().run_until_complete(
            agent._generate_rag_optimizations(
                success_analysis, failure_analysis, modification_analysis,
                [1, 2, 3], user_id=1
            )
        )

    ok = len(result["ids"]) > 0
    ok = ok and len(result["data"]) > 0
    ok = ok and result["data"][0]["retrieval_params"]["top_k"] == 5

    record("Agent-RAG优化建议生成", ok, f"generated={len(result['ids'])}")


def test_agent_prompt_optimization():
    """测试 16: Agent Prompt 优化建议生成"""
    from app.agents.flows.feedback_learning_agent import FeedbackLearningAgent

    agent = FeedbackLearningAgent()

    mock_response = json.dumps({
        "optimizations": [
            {
                "title": "增强错误处理Prompt",
                "description": "在生成Prompt中增加错误处理指引",
                "agent_name": "script_generation_agent",
                "prompt_key": "system_prompt",
                "suggested_content": "生成脚本时增加异常处理和重试机制",
                "change_summary": "增加错误处理指引",
                "confidence": 0.85,
                "reasoning": "失败案例中错误处理不足",
            }
        ]
    })

    with patch.object(agent, "call_llm", new=AsyncMock(return_value=mock_response)):
        result = asyncio.get_event_loop().run_until_complete(
            agent._generate_prompt_optimizations(
                {}, {}, {}, [1, 2, 3], user_id=1
            )
        )

    ok = len(result["ids"]) > 0
    ok = ok and result["data"][0]["agent_name"] == "script_generation_agent"
    ok = ok and len(result["data"][0]["suggested_content"]) > 0

    record("Agent-Prompt优化建议生成", ok)


def test_agent_strategy_optimization():
    """测试 17: Agent 策略优化建议生成"""
    from app.agents.flows.feedback_learning_agent import FeedbackLearningAgent

    agent = FeedbackLearningAgent()

    mock_response = json.dumps({
        "optimizations": [
            {
                "title": "降低temperature提升稳定性",
                "description": "失败较多,降低temperature",
                "agent_name": "script_generation_agent",
                "current_config": {"temperature": 0.2, "max_tokens": 8192},
                "suggested_config": {"temperature": 0.1, "max_tokens": 8192},
                "reasoning": "降低随机性提升稳定性",
                "confidence": 0.8,
            }
        ]
    })

    with patch.object(agent, "call_llm", new=AsyncMock(return_value=mock_response)):
        result = asyncio.get_event_loop().run_until_complete(
            agent._generate_strategy_optimizations(
                {}, {"total_count": 10}, {}, [1, 2, 3], user_id=1
            )
        )

    ok = len(result["ids"]) > 0
    ok = ok and result["data"][0]["suggested_config"]["temperature"] == 0.1

    record("Agent-策略优化建议生成", ok)


def test_agent_fallback_rag():
    """测试 18: Agent RAG 回退优化(无 LLM)"""
    from app.agents.flows.feedback_learning_agent import FeedbackLearningAgent

    agent = FeedbackLearningAgent()

    failure_analysis = {
        "error_type_distribution": {"timeout": 5, "assertion": 3},
    }
    modification_analysis = {"total_count": 3}

    opts = agent._generate_rag_fallback(failure_analysis, modification_analysis)

    ok = len(opts) > 0
    ok = ok and "title" in opts[0]
    ok = ok and "retrieval_params" in opts[0]
    ok = ok and "confidence" in opts[0]

    record("Agent-RAG回退优化", ok, f"generated={len(opts)}")


def test_agent_fallback_strategy():
    """测试 19: Agent 策略回退优化(无 LLM)"""
    from app.agents.flows.feedback_learning_agent import FeedbackLearningAgent

    agent = FeedbackLearningAgent()

    # 高失败率场景
    opts = agent._generate_strategy_fallback({"total_count": 15})
    ok = len(opts) > 0
    ok = ok and opts[0]["suggested_config"]["temperature"] <= 0.1

    # 低失败率场景
    opts2 = agent._generate_strategy_fallback({"total_count": 2})
    ok = ok and len(opts2) > 0
    ok = ok and opts2[0]["suggested_config"]["temperature"] <= 0.2

    # 无失败场景
    opts3 = agent._generate_strategy_fallback({"total_count": 0})
    ok = ok and len(opts3) > 0

    record("Agent-策略回退优化", ok)


def test_agent_registration():
    """测试 20: Agent 注册验证"""
    from app.agents.factory.definitions import DEFAULT_AGENT_SPECS

    found = None
    for spec in DEFAULT_AGENT_SPECS:
        if spec.name == "feedback_learning_agent":
            found = spec
            break

    ok = found is not None
    if found:
        ok = ok and found.display_name == "反馈学习Agent"
        ok = ok and found.module_path == "app.agents.flows.feedback_learning_agent"
        ok = ok and found.class_name == "FeedbackLearningAgent"
        ok = ok and "feedback_learning" in found.capabilities
        ok = ok and "rag_optimization" in found.capabilities
        ok = ok and "prompt_optimization" in found.capabilities
        ok = ok and "strategy_optimization" in found.capabilities
        ok = ok and found.model is not None
        ok = ok and found.enabled is True

    record("Agent-注册验证(DEFAULT_AGENT_SPECS)", ok)


def test_agent_full_execution():
    """测试 21: Agent 完整执行流程(Mock LLM)"""
    from app.agents.flows.feedback_learning_agent import FeedbackLearningAgent
    from app.db.database import SessionLocal
    from app.models.feedback_learning import FeedbackOptimization

    agent = FeedbackLearningAgent()

    # 先创建一个汇总记录
    db = SessionLocal()
    try:
        opt = FeedbackOptimization(
            title="完整执行测试",
            optimization_type="strategy",
            optimization_json=json.dumps({"collect_scope": {}, "is_summary": True}),
            status="pending",
            user_id=1, created_by=1,
        )
        db.add(opt)
        db.commit()
        db.refresh(opt)
        optimization_id = opt.id
    finally:
        db.close()

    # Mock 所有 LLM 调用
    def mock_llm_side_effect(system_prompt, user_prompt, **kwargs):
        if "成功" in system_prompt:
            return json.dumps({"success_patterns": ["API稳定"], "best_practices": ["保持策略"]})
        elif "失败" in system_prompt:
            return json.dumps({
                "common_failures": [{"pattern": "timeout", "frequency": "high", "root_cause": "加载慢"}],
                "failure_trends": "timeout频发",
            })
        elif "修改" in system_prompt:
            return json.dumps({"common_issues": [{"issue": "断言不完整", "frequency": "medium"}]})
        elif "RAG" in system_prompt:
            return json.dumps({
                "optimizations": [{
                    "title": "RAG优化", "description": "提升检索",
                    "retrieval_params": {"top_k": 5}, "confidence": 0.8,
                    "reasoning": "失败分析驱动",
                }]
            })
        elif "Prompt" in system_prompt:
            return json.dumps({
                "optimizations": [{
                    "title": "Prompt优化", "description": "增强Prompt",
                    "agent_name": "case_agent", "prompt_key": "system_prompt",
                    "suggested_content": "更好的Prompt", "confidence": 0.8,
                    "reasoning": "修改分析驱动",
                }]
            })
        elif "策略" in system_prompt:
            return json.dumps({
                "optimizations": [{
                    "title": "策略优化", "description": "调整配置",
                    "agent_name": "script_generation_agent",
                    "current_config": {"temperature": 0.2},
                    "suggested_config": {"temperature": 0.1},
                    "confidence": 0.8, "reasoning": "失败率高",
                }]
            })
        elif "总结" in system_prompt:
            return json.dumps({
                "summary": "学习完成",
                "key_insights": ["洞察1"],
                "top_recommendations": ["建议1"],
            })
        return "{}"

    with patch.object(agent, "call_llm", new=AsyncMock(side_effect=mock_llm_side_effect)):
        result = asyncio.get_event_loop().run_until_complete(
            agent._do_learning(
                {"optimization_id": optimization_id, "collect_scope": {}, "user_id": 1},
            )
        )

    ok = result.get("status") == "success"
    ok = ok and result.get("optimization_id") == optimization_id
    ok = ok and "statistics" in result
    ok = ok and result["statistics"]["rag_optimizations"] >= 1
    ok = ok and result["statistics"]["prompt_optimizations"] >= 1
    ok = ok and result["statistics"]["strategy_optimizations"] >= 1
    ok = ok and len(result.get("optimization_ids", [])) >= 3

    record("Agent-完整执行流程(Mock LLM)", ok,
           f"rag={result.get('statistics', {}).get('rag_optimizations', 0)}, "
           f"prompt={result.get('statistics', {}).get('prompt_optimizations', 0)}, "
           f"strategy={result.get('statistics', {}).get('strategy_optimizations', 0)}")


def test_service_apply_optimization():
    """测试 22: 服务层 - 应用优化建议(RAG类型)"""
    from app.db.database import SessionLocal
    from app.models.feedback_learning import FeedbackOptimization
    from app.services.feedback_learning_service import get_feedback_learning_service
    svc = get_feedback_learning_service()

    # 创建一个RAG优化建议
    db = SessionLocal()
    try:
        opt = FeedbackOptimization(
            title="RAG优化-测试",
            optimization_type="rag",
            optimization_json=json.dumps({
                "retrieval_params": {"top_k": 8},
                "index_suggestions": ["增加索引"],
                "knowledge_gaps": ["知识不足"],
            }),
            status="pending",
            user_id=1, created_by=1,
        )
        db.add(opt)
        db.commit()
        db.refresh(opt)
        opt_id = opt.id
    finally:
        db.close()

    result = svc.apply_optimization(opt_id, user_id=1)

    ok = result.get("status") == "applied"
    ok = ok and result.get("optimization_type") == "rag"
    ok = ok and result["applied_result"]["applied"] is True

    record("服务-应用RAG优化建议", ok)


def test_service_reject_optimization():
    """测试 23: 服务层 - 拒绝优化建议"""
    from app.db.database import SessionLocal
    from app.models.feedback_learning import FeedbackOptimization
    from app.services.feedback_learning_service import get_feedback_learning_service
    svc = get_feedback_learning_service()

    # 创建一个优化建议
    db = SessionLocal()
    try:
        opt = FeedbackOptimization(
            title="待拒绝-测试",
            optimization_type="strategy",
            status="pending",
            user_id=1, created_by=1,
        )
        db.add(opt)
        db.commit()
        db.refresh(opt)
        opt_id = opt.id
    finally:
        db.close()

    result = svc.reject_optimization(opt_id, reason="测试拒绝", user_id=1)

    ok = result.get("status") == "rejected"
    ok = ok and result.get("reason") == "测试拒绝"

    record("服务-拒绝优化建议", ok)


def test_service_apply_already_applied():
    """测试 24: 服务层 - 重复应用优化建议"""
    from app.db.database import SessionLocal
    from app.models.feedback_learning import FeedbackOptimization
    from app.services.feedback_learning_service import get_feedback_learning_service
    svc = get_feedback_learning_service()

    db = SessionLocal()
    try:
        opt = FeedbackOptimization(
            title="已应用-测试",
            optimization_type="strategy",
            status="applied",
            user_id=1, created_by=1,
        )
        db.add(opt)
        db.commit()
        db.refresh(opt)
        opt_id = opt.id
    finally:
        db.close()

    result = svc.apply_optimization(opt_id, user_id=1)

    ok = result.get("status") == "already_applied"

    record("服务-重复应用检测", ok)


def test_api_routes():
    """测试 25: API 路由完整性"""
    from app.api.feedback_learning import router

    # 收集所有 (path, method) 组合
    route_set = set()
    for r in router.routes:
        for method in r.methods:
            route_set.add((r.path, method))

    expected = [
        ("", "POST"),
        ("/dashboard", "GET"),
        ("/stats", "GET"),
        ("/{optimization_id}/run", "POST"),
        ("/records/list", "GET"),
        ("/records/{record_id}", "GET"),
        ("/records/{record_id}", "DELETE"),
        ("/optimizations/list", "GET"),
        ("/optimizations/{optimization_id}", "GET"),
        ("/optimizations/{optimization_id}", "DELETE"),
        ("/optimizations/{optimization_id}/apply", "POST"),
        ("/optimizations/{optimization_id}/reject", "POST"),
    ]

    ok = True
    for path, method in expected:
        if (path, method) not in route_set:
            ok = False
            break

    record("API-路由完整性(12个路由)", ok, f"found={len(route_set)} route-method combos")


def test_api_registration():
    """测试 26: API 路由注册验证"""
    # 验证 feedback_learning router 模块可正常导入
    from app.api.feedback_learning import router as fl_router

    ok = fl_router is not None
    ok = ok and len(fl_router.routes) >= 10  # 至少10个路由

    record("API-路由注册验证", ok, f"routes={len(fl_router.routes)}")


def test_parse_llm_json():
    """测试 27: LLM JSON 解析"""
    from app.agents.flows.feedback_learning_agent import FeedbackLearningAgent

    # 正常 JSON
    result = FeedbackLearningAgent._parse_llm_json('{"key": "value"}')
    ok = result is not None and result["key"] == "value"

    # 带文本的 JSON
    result2 = FeedbackLearningAgent._parse_llm_json('Here is the result:\n{"key": "value2"}\nDone.')
    ok = ok and result2 is not None and result2["key"] == "value2"

    # 空/无效
    ok = ok and FeedbackLearningAgent._parse_llm_json("") is None
    ok = ok and FeedbackLearningAgent._parse_llm_json("not json") is None

    record("Agent-LLM JSON解析", ok)


def test_service_delete_operations():
    """测试 28: 服务层 - 删除操作"""
    from app.db.database import SessionLocal
    from app.models.feedback_learning import FeedbackLearningRecord, FeedbackOptimization
    from app.services.feedback_learning_service import get_feedback_learning_service
    svc = get_feedback_learning_service()

    # 创建测试数据
    db = SessionLocal()
    try:
        rec = FeedbackLearningRecord(
            record_type="success", source="execution",
            status="analyzed", user_id=1, created_by=1,
        )
        opt = FeedbackOptimization(
            title="删除测试", optimization_type="strategy",
            status="pending", user_id=1, created_by=1,
        )
        db.add_all([rec, opt])
        db.commit()
        db.refresh(rec)
        db.refresh(opt)
        record_id = rec.id
        opt_id = opt.id
    finally:
        db.close()

    # 软删除
    ok = svc.delete_record(record_id, user_id=1)
    ok = ok and svc.delete_optimization(opt_id, user_id=1)

    # 验证已删除(get返回None)
    ok = ok and svc.get_record(record_id, user_id=1) is None
    ok = ok and svc.get_optimization(opt_id, user_id=1) is None

    record("服务-删除操作(软删除)", ok)


# ============================================================
# 主函数
# ============================================================

def main():
    logger.info("=" * 60)
    logger.info("AI 测试反馈学习系统全链路测试")
    logger.info("=" * 60)

    # 准备
    setup_database()
    cleanup_database()
    seed_test_data()

    # 执行测试
    tests = [
        test_model_feedback_learning_record,
        test_model_feedback_optimization,
        test_service_create_learning,
        test_service_list_records,
        test_service_list_optimizations,
        test_service_dashboard,
        test_service_stats,
        test_agent_case_collection,
        test_agent_error_classification,
        test_agent_infer_agent_name,
        test_agent_save_records,
        test_agent_analyze_success,
        test_agent_analyze_failure,
        test_agent_analyze_modification,
        test_agent_rag_optimization,
        test_agent_prompt_optimization,
        test_agent_strategy_optimization,
        test_agent_fallback_rag,
        test_agent_fallback_strategy,
        test_agent_registration,
        test_agent_full_execution,
        test_service_apply_optimization,
        test_service_reject_optimization,
        test_service_apply_already_applied,
        test_api_routes,
        test_api_registration,
        test_parse_llm_json,
        test_service_delete_operations,
    ]

    for test_func in tests:
        try:
            test_func()
        except Exception as e:
            record(test_func.__name__, False, f"异常: {e}")
            logger.error(f"测试异常: {test_func.__name__}", exc_info=True)

    # 汇总
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    total = len(results)

    logger.info("=" * 60)
    logger.info(f"测试结果: {passed}/{total} 通过, {failed} 失败")
    logger.info("=" * 60)

    if failed > 0:
        logger.info("失败测试:")
        for r in results:
            if r["status"] == "FAIL":
                logger.info(f"  - {r['name']}: {r['detail']}")

    # 清理
    cleanup_database()

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
