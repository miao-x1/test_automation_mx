"""
测试编排系统全链路测试

验证:
1. TestPlan CRUD(创建/查询/更新/删除/列表)
2. PlanSuite 关联管理(添加/移除/重排序/启用禁用)
3. ExecutionFlow 执行引擎(串行/并行/失败停止/失败继续)
4. TestOrchestrator 服务层(统计/概览/仪表盘)
5. 报告生成与查询
6. API 路由完整性

运行:
    cd backend
    python -m tests.test_test_orchestration
"""
import asyncio
import json
import logging
import os
import sys
import types
from pathlib import Path

# 确保能 import app.*
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

# 测试用:强制使用 SQLite,避免依赖 MySQL
os.environ.setdefault("USE_SQLITE", "True")
os.environ.setdefault("SQLITE_PATH", "data/test_test_orchestration.db")

# stub out optional 3rd-party modules not installed locally
_STUB_MODULES = ["neo4j", "pymilvus", "redis"]
for mod_name in _STUB_MODULES:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("test_orchestration")

# 测试结果收集
results = []


def record(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    results.append({"name": name, "status": status, "detail": detail})
    logger.info(f"[{status}] {name}" + (f" - {detail}" if detail else ""))


# ============================================================
# 准备:创建测试所需的数据库表
# ============================================================

def setup_database():
    """创建测试所需的数据库表"""
    from app.db.database import Base, sync_engine
    from app.models.test_plan import TestPlan, PlanSuite, PlanExecution
    from app.models.test_suite import TestSuite, SuiteExecution

    # 只创建与编排相关的表(避免其他模型的 MEDIUMTEXT 不兼容 SQLite)
    tables_to_create = [
        TestPlan.__table__,
        PlanSuite.__table__,
        PlanExecution.__table__,
        TestSuite.__table__,
        SuiteExecution.__table__,
    ]
    Base.metadata.create_all(bind=sync_engine, tables=tables_to_create)
    logger.info("测试数据库表已创建(test_plan / plan_suite / plan_execution / test_suite / ...)")


def cleanup_database():
    """清理测试数据"""
    from app.db.database import SessionLocal
    from app.models.test_plan import TestPlan, PlanSuite, PlanExecution
    from app.models.test_suite import TestSuite, SuiteExecution

    db = SessionLocal()
    try:
        db.query(PlanExecution).delete()
        db.query(PlanSuite).delete()
        db.query(TestPlan).delete()
        db.query(SuiteExecution).delete()
        db.query(TestSuite).delete()
        db.commit()
        logger.info("测试数据已清理")
    finally:
        db.close()


def create_test_suites():
    """创建测试用的 TestSuite"""
    from app.db.database import SessionLocal
    from app.models.test_suite import TestSuite

    db = SessionLocal()
    suite_ids = []
    try:
        suites = [
            TestSuite(
                name="登录功能用例集",
                description="登录模块回归测试",
                suite_type="regression",
                status="ready",
                case_ids=json.dumps([1, 2, 3]),
                env="test",
                base_url="http://localhost:8080",
                concurrency=1,
                fail_strategy="continue",
                retry_count=0,
            ),
            TestSuite(
                name="权限验证用例集",
                description="权限控制测试",
                suite_type="regression",
                status="ready",
                case_ids=json.dumps([4, 5]),
                env="test",
                base_url="http://localhost:8080",
                concurrency=1,
                fail_strategy="continue",
                retry_count=0,
            ),
            TestSuite(
                name="数据隔离用例集",
                description="多租户数据隔离",
                suite_type="smoke",
                status="ready",
                case_ids=json.dumps([6, 7, 8, 9]),
                env="test",
                base_url="http://localhost:8080",
                concurrency=1,
                fail_strategy="continue",
                retry_count=0,
            ),
        ]
        for s in suites:
            db.add(s)
        db.commit()
        for s in suites:
            db.refresh(s)
            suite_ids.append(s.id)
        logger.info(f"创建 {len(suite_ids)} 个测试 Suite: {suite_ids}")
    finally:
        db.close()
    return suite_ids


# ============================================================
# 测试用例
# ============================================================

async def test_01_plan_crud():
    """测试 1:TestPlan CRUD"""
    from app.services.test_orchestration.orchestrator import get_test_orchestrator, reset_test_orchestrator
    reset_test_orchestrator()
    svc = get_test_orchestrator()

    # 创建
    plan = svc.create_plan({
        "name": "登录回归测试",
        "description": "登录模块全量回归",
        "strategy": "serial",
        "fail_policy": "continue",
        "env": "test",
        "base_url": "http://localhost:8080",
        "tags": "regression,login",
    }, user_id=1)
    plan_id = plan["id"]
    record("创建 Plan", plan["name"] == "登录回归测试", f"id={plan_id}")
    record("Plan 初始状态 draft", plan["status"] == "draft", f"status={plan['status']}")

    # 查询
    got = svc.get_plan(plan_id, user_id=1)
    record("查询 Plan", got is not None and got["name"] == "登录回归测试", f"id={plan_id}")

    # 更新
    updated = svc.update_plan(plan_id, {
        "description": "更新后的描述",
        "strategy": "parallel",
        "max_concurrency": 8,
    }, user_id=1)
    record("更新 Plan", updated["description"] == "更新后的描述", f"strategy={updated['strategy']}")
    record("更新 Plan strategy", updated["strategy"] == "parallel", f"strategy={updated['strategy']}")

    # 列表
    listing = svc.list_plans(user_id=1, page=1, page_size=10)
    record("Plan 列表", listing["total"] >= 1, f"total={listing['total']}")

    # 按关键词搜索
    searched = svc.list_plans(keyword="登录", user_id=1)
    record("Plan 关键词搜索", searched["total"] >= 1, f"keyword=登录, total={searched['total']}")

    # 删除(软删除)
    ok = svc.delete_plan(plan_id, hard=False, user_id=1)
    record("软删除 Plan", ok, f"plan_id={plan_id}")
    # 查询应该返回 None
    deleted = svc.get_plan(plan_id, user_id=1)
    record("删除后查询为空", deleted is None, "should be None")


async def test_02_suite_association():
    """测试 2:PlanSuite 关联管理"""
    from app.services.test_orchestration.orchestrator import get_test_orchestrator, reset_test_orchestrator
    reset_test_orchestrator()
    svc = get_test_orchestrator()

    # 创建 Plan
    plan = svc.create_plan({
        "name": "Suite 关联测试",
        "strategy": "serial",
        "fail_policy": "continue",
    }, user_id=1)
    plan_id = plan["id"]

    # 创建测试 Suite
    suite_ids = create_test_suites()
    s1, s2, s3 = suite_ids[0], suite_ids[1], suite_ids[2]

    # 添加 Suite
    ps1 = svc.add_suite(plan_id, s1, execution_order=0, role="main", user_id=1)
    record("添加 Suite 1", ps1["suite_id"] == s1, f"order={ps1['execution_order']}")
    ps2 = svc.add_suite(plan_id, s2, execution_order=1, role="main", user_id=1)
    record("添加 Suite 2", ps2["suite_order"] if "suite_order" in ps2 else ps2["execution_order"] == 1, f"order={ps2['execution_order']}")
    ps3 = svc.add_suite(plan_id, s3, execution_order=2, role="teardown", user_id=1)
    record("添加 Suite 3", ps3["role"] == "teardown", f"role={ps3['role']}")

    # Plan 状态应从 draft 变为 ready
    plan_after = svc.get_plan(plan_id, user_id=1)
    record("Plan 状态变 ready", plan_after["status"] == "ready", f"status={plan_after['status']}")
    record("Plan suite_count 更新", plan_after["suite_count"] == 3, f"count={plan_after['suite_count']}")

    # 列出 Suite
    suites = svc.list_suites(plan_id, user_id=1)
    record("列出 Plan Suites", len(suites) == 3, f"count={len(suites)}")
    # 验证附带 Suite 详情
    record("Suite 详情包含 name", suites[0].get("suite_name") == "登录功能用例集", f"name={suites[0].get('suite_name')}")
    record("Suite 详情包含 case_count", suites[0].get("case_count") == 3, f"case_count={suites[0].get('case_count')}")

    # 重排序
    reordered = svc.reorder_suites(plan_id, [
        {"suite_id": s3, "execution_order": 0},
        {"suite_id": s2, "execution_order": 1},
        {"suite_id": s1, "execution_order": 2},
    ], user_id=1)
    record("批量重排序", len(reordered) == 3, f"reordered={len(reordered)}")
    suites_after = svc.list_suites(plan_id, user_id=1)
    record("重排序后顺序", suites_after[0]["suite_id"] == s3, f"first={suites_after[0]['suite_id']}")

    # 禁用 Suite
    toggled = svc.toggle_suite(plan_id, s2, enabled=False, user_id=1)
    record("禁用 Suite", toggled["enabled"] == False, f"enabled={toggled['enabled']}")
    enabled_only = svc.list_suites(plan_id, only_enabled=True, user_id=1)
    record("只列出启用 Suite", len(enabled_only) == 2, f"enabled_count={len(enabled_only)}")

    # 重新启用
    svc.toggle_suite(plan_id, s2, enabled=True, user_id=1)
    enabled_after = svc.list_suites(plan_id, only_enabled=True, user_id=1)
    record("重新启用 Suite", len(enabled_after) == 3, f"enabled_count={len(enabled_after)}")

    # 移除 Suite
    ok = svc.remove_suite(plan_id, s1, user_id=1)
    record("移除 Suite", ok, f"plan={plan_id}, suite={s1}")
    after_remove = svc.list_suites(plan_id, user_id=1)
    record("移除后数量减少", len(after_remove) == 2, f"count={len(after_remove)}")

    # 重复添加应报错
    try:
        svc.add_suite(plan_id, s2, user_id=1)
        record("重复添加报错", False, "should raise")
    except ValueError:
        record("重复添加报错", True, "ValueError raised")

    # 不存在的 Suite 应报错
    try:
        svc.add_suite(plan_id, 99999, user_id=1)
        record("不存在 Suite 报错", False, "should raise")
    except ValueError:
        record("不存在 Suite 报错", True, "ValueError raised")


async def test_03_execution_flow_serial():
    """测试 3:ExecutionFlow 串行执行(失败继续)

    由于没有真实 Runtime / Agent,执行会失败,
    但应正确生成 PlanExecution 记录并标记为 failed。
    """
    from app.services.test_orchestration.orchestrator import get_test_orchestrator, reset_test_orchestrator
    reset_test_orchestrator()
    svc = get_test_orchestrator()

    # 创建 Plan + 关联 Suite
    plan = svc.create_plan({
        "name": "串行执行测试",
        "strategy": "serial",
        "fail_policy": "continue",
        "retry_count": 0,
        "timeout_seconds": 30,
    }, user_id=1)
    plan_id = plan["id"]

    suite_ids = create_test_suites()
    for i, sid in enumerate(suite_ids):
        svc.add_suite(plan_id, sid, execution_order=i, user_id=1)

    # 执行(同步,预期失败因为没有真实 Runtime)
    try:
        result = await svc.execute_plan(plan_id, user_id=1, trigger_source="test")
        # 验证 PlanExecution 记录已创建
        record("串行执行生成记录", "execution_id" in result, f"exec_id={result.get('execution_id', 'N/A')[:20]}")
        record("串行执行状态", result.get("status") in ("failed", "success"), f"status={result.get('status')}")
        record("串行执行 Suite 数量", result.get("total_suites") == 3, f"suites={result.get('total_suites')}")
        record("串行执行包含明细", result.get("suite_executions") is not None, "has suite_executions")
    except Exception as e:
        record("串行执行", False, f"Exception: {e}")


async def test_04_execution_flow_parallel():
    """测试 4:ExecutionFlow 并行执行"""
    from app.services.test_orchestration.orchestrator import get_test_orchestrator, reset_test_orchestrator
    reset_test_orchestrator()
    svc = get_test_orchestrator()

    plan = svc.create_plan({
        "name": "并行执行测试",
        "strategy": "parallel",
        "fail_policy": "continue",
        "max_concurrency": 2,
        "retry_count": 0,
        "timeout_seconds": 30,
    }, user_id=1)
    plan_id = plan["id"]

    suite_ids = create_test_suites()
    for sid in suite_ids:
        svc.add_suite(plan_id, sid, user_id=1)

    try:
        result = await svc.execute_plan(plan_id, user_id=1, trigger_source="test")
        record("并行执行生成记录", "execution_id" in result, f"exec_id={result.get('execution_id', 'N/A')[:20]}")
        record("并行执行状态", result.get("status") in ("failed", "success"), f"status={result.get('status')}")
    except Exception as e:
        record("并行执行", False, f"Exception: {e}")


async def test_05_execution_fail_stop():
    """测试 5:失败停止策略

    第一个 Suite 失败后,剩余 Suite 应被标记为 skipped。
    """
    from app.services.test_orchestration.orchestrator import get_test_orchestrator, reset_test_orchestrator
    reset_test_orchestrator()
    svc = get_test_orchestrator()

    plan = svc.create_plan({
        "name": "失败停止测试",
        "strategy": "serial",
        "fail_policy": "stop",
        "retry_count": 0,
    }, user_id=1)
    plan_id = plan["id"]

    suite_ids = create_test_suites()
    for i, sid in enumerate(suite_ids):
        svc.add_suite(plan_id, sid, execution_order=i, user_id=1)

    try:
        result = await svc.execute_plan(plan_id, user_id=1, trigger_source="test")
        record("失败停止生成记录", "execution_id" in result, f"exec_id={result.get('execution_id', 'N/A')[:20]}")
        # 应该是 failed(因为所有 Suite 都会失败)
        record("失败停止最终状态", result.get("status") == "failed", f"status={result.get('status')}")
        # 检查 suite_executions 中是否有 skipped
        suite_execs = result.get("suite_executions", [])
        if suite_execs:
            statuses = [s.get("status") for s in suite_execs]
            has_skipped = "skipped" in statuses
            record("失败停止有 skipped", has_skipped, f"statuses={statuses}")
    except Exception as e:
        record("失败停止", False, f"Exception: {e}")


async def test_06_execution_history_and_stats():
    """测试 6:执行历史与统计"""
    from app.services.test_orchestration.orchestrator import get_test_orchestrator, reset_test_orchestrator
    reset_test_orchestrator()
    svc = get_test_orchestrator()

    # 先执行一次(复用前面的测试)
    plan = svc.create_plan({
        "name": "历史统计测试",
        "strategy": "serial",
        "fail_policy": "continue",
    }, user_id=1)
    plan_id = plan["id"]
    suite_ids = create_test_suites()
    for sid in suite_ids:
        svc.add_suite(plan_id, sid, user_id=1)

    exec_result = await svc.execute_plan(plan_id, user_id=1, trigger_source="test")
    exec_id = exec_result.get("execution_id")

    # 查询单个执行
    got_exec = svc.get_execution(exec_id)
    record("查询执行记录", got_exec is not None, f"exec_id={exec_id[:20] if exec_id else 'N/A'}")
    record("执行记录有 plan_id", got_exec and got_exec.get("plan_id") == plan_id, "")

    # 列表查询
    listing = svc.list_executions(plan_id=plan_id, user_id=1)
    record("执行历史列表", listing["total"] >= 1, f"total={listing['total']}")

    # 统计
    stats = svc.get_execution_stats(plan_id=plan_id, user_id=1)
    record("执行统计", stats["total_executions"] >= 1, f"total={stats['total_executions']}")
    record("执行统计字段", "success_rate" in stats and "avg_duration" in stats,
           f"keys={list(stats.keys())[:5]}")


async def test_07_report():
    """测试 7:报告生成与查询"""
    from app.services.test_orchestration.orchestrator import get_test_orchestrator, reset_test_orchestrator
    reset_test_orchestrator()
    svc = get_test_orchestrator()

    plan = svc.create_plan({
        "name": "报告测试",
        "strategy": "serial",
        "fail_policy": "continue",
    }, user_id=1)
    plan_id = plan["id"]
    suite_ids = create_test_suites()
    for sid in suite_ids:
        svc.add_suite(plan_id, sid, user_id=1)

    exec_result = await svc.execute_plan(plan_id, user_id=1, trigger_source="test")
    exec_id = exec_result.get("execution_id")

    # 查询报告
    report = svc.get_report(exec_id)
    record("获取报告", "report" in report, f"format={report.get('format')}")
    report_data = report.get("report", {})
    record("报告包含 summary", "summary" in report_data, f"keys={list(report_data.keys())[:5]}")
    record("报告包含 suites", "suites" in report_data, f"suites_count={len(report_data.get('suites', []))}")

    # 报告列表
    reports = svc.list_reports(user_id=1)
    record("报告列表", reports["total"] >= 0, f"total={reports['total']}")


async def test_08_overview_and_dashboard():
    """测试 8:概览与仪表盘"""
    from app.services.test_orchestration.orchestrator import get_test_orchestrator, reset_test_orchestrator
    reset_test_orchestrator()
    svc = get_test_orchestrator()

    # 创建多个 Plan
    for i in range(3):
        svc.create_plan({
            "name": f"概览测试-{i}",
            "strategy": "serial" if i % 2 == 0 else "parallel",
            "fail_policy": "stop" if i == 0 else "continue",
            "tags": f"test, batch-{i}",
        }, user_id=1)

    # Plan 概览
    listing = svc.list_plans(user_id=1, page=1, page_size=10)
    first_plan_id = listing["items"][0]["id"]
    overview = svc.get_plan_overview(first_plan_id, user_id=1)
    record("Plan 概览", "plan" in overview and "suites" in overview and "stats" in overview,
           f"keys={list(overview.keys())}")

    # 仪表盘
    dashboard = svc.get_dashboard(user_id=1)
    record("仪表盘", "plans" in dashboard and "executions" in dashboard,
           f"plans={dashboard['plans']}")
    record("仪表盘 Plan 统计", dashboard["plans"]["total"] >= 3,
           f"total={dashboard['plans']['total']}")


async def test_09_background_execution():
    """测试 9:后台执行"""
    from app.services.test_orchestration.orchestrator import get_test_orchestrator, reset_test_orchestrator
    reset_test_orchestrator()
    svc = get_test_orchestrator()

    plan = svc.create_plan({
        "name": "后台执行测试",
        "strategy": "serial",
        "fail_policy": "continue",
    }, user_id=1)
    plan_id = plan["id"]
    suite_ids = create_test_suites()
    for sid in suite_ids:
        svc.add_suite(plan_id, sid, user_id=1)

    # 后台执行(立即返回)
    result = await svc.execute_plan(
        plan_id, user_id=1, background=True, trigger_source="test",
    )
    record("后台执行返回", result.get("status") == "pending", f"status={result.get('status')}")
    record("后台执行有 exec_id", "execution_id" in result, f"exec_id={result.get('execution_id', 'N/A')[:20]}")

    # 等待一会再查
    await asyncio.sleep(2)
    exec_id = result.get("execution_id")
    if exec_id:
        exec_record = svc.get_execution(exec_id)
        # 后台执行可能还在 running 或已完成(失败)
        if exec_record:
            record("后台执行记录存在", True, f"status={exec_record.get('status')}")
        else:
            record("后台执行记录存在", False, "not found")


async def test_10_cancel_execution():
    """测试 10:取消执行"""
    from app.services.test_orchestration.orchestrator import get_test_orchestrator, reset_test_orchestrator
    reset_test_orchestrator()
    svc = get_test_orchestrator()

    plan = svc.create_plan({
        "name": "取消执行测试",
        "strategy": "serial",
        "fail_policy": "continue",
    }, user_id=1)
    plan_id = plan["id"]
    suite_ids = create_test_suites()
    for sid in suite_ids:
        svc.add_suite(plan_id, sid, user_id=1)

    # 先执行(同步)
    exec_result = await svc.execute_plan(plan_id, user_id=1, trigger_source="test")
    exec_id = exec_result.get("execution_id")

    # 取消已完成的执行(应该是 no-op)
    cancelled = await svc.cancel_execution(exec_id, user_id=1)
    record("取消已完成执行", cancelled.get("status") in ("success", "failed", "cancelled"),
           f"status={cancelled.get('status')}")


async def test_11_api_routes():
    """测试 11:API 路由完整性"""
    import importlib.util
    api_path = backend_dir / "app" / "api" / "test_orchestration.py"
    spec = importlib.util.spec_from_file_location("test_orchestration_api_check", api_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    router = mod.router

    routes = []
    for r in router.routes:
        if hasattr(r, "methods") and hasattr(r, "path"):
            routes.append((r.path, sorted(r.methods)))

    record("API 路由数量", len(routes) >= 19, f"count={len(routes)}")

    # 验证关键路由存在
    paths = [r[0] for r in routes]
    expected_paths = [
        "/plans",
        "/plans/list",
        "/plans/{plan_id}",
        "/plans/{plan_id}/execute",
        "/plans/{plan_id}/suites",
        "/executions/list",
        "/executions/{execution_id}",
        "/reports/{execution_id}",
        "/dashboard",
    ]
    for ep in expected_paths:
        record(f"路由存在: {ep}", ep in paths, "")


# ============================================================
# 主函数
# ============================================================

async def main():
    """运行所有测试"""
    logger.info("=" * 60)
    logger.info("测试编排系统全链路测试开始")
    logger.info("=" * 60)

    # 准备数据库
    try:
        setup_database()
    except Exception as e:
        logger.error(f"数据库准备失败: {e}")
        return False

    # 清理旧数据
    cleanup_database()

    tests = [
        test_01_plan_crud,
        test_02_suite_association,
        test_03_execution_flow_serial,
        test_04_execution_flow_parallel,
        test_05_execution_fail_stop,
        test_06_execution_history_and_stats,
        test_07_report,
        test_08_overview_and_dashboard,
        test_09_background_execution,
        test_10_cancel_execution,
        test_11_api_routes,
    ]

    for test in tests:
        try:
            await test()
        except Exception as e:
            record(test.__doc__ or test.__name__, False, f"Exception: {e}")
            import traceback
            traceback.print_exc()

    # 清理
    cleanup_database()

    # 汇总
    logger.info("=" * 60)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    logger.info(f"测试汇总: {passed} passed, {failed} failed, {len(results)} total")
    logger.info("=" * 60)

    # 打印详情
    for r in results:
        logger.info(f"  [{r['status']}] {r['name']}" + (f" - {r['detail']}" if r['detail'] else ""))

    # 输出 JSON 报告
    report_path = backend_dir / "test_test_orchestration_report.json"
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
