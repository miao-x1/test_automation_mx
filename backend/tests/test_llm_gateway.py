"""
LLM Gateway 全链路测试

验证:
1. Gateway 初始化与 Provider 加载
2. Mock 调用(正常路径)
3. 失败切换(模拟 qwen/deepseek 失败 → mock 兜底)
4. 费用计算
5. 熔断器(连续失败触发熔断)
6. 路由链管理
7. Token 与费用统计
8. JSON 解析

运行:
    cd backend
    python -m tests.test_llm_gateway
"""
import asyncio
import os
import sys
import json
import logging
from pathlib import Path

# 确保能 import app.*
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

# 测试用:强制使用 SQLite,避免依赖 MySQL
os.environ.setdefault("USE_SQLITE", "True")
os.environ.setdefault("SQLITE_PATH", "data/test_llm_gateway.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("test_llm_gateway")

# 测试结果收集
results = []


def record(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    results.append({"name": name, "status": status, "detail": detail})
    logger.info(f"[{status}] {name}" + (f" - {detail}" if detail else ""))


async def test_01_init():
    """测试 1:Gateway 初始化"""
    from app.llm import get_gateway, LLMGateway
    gateway = get_gateway()
    gateway.initialize(force=True)
    providers = gateway.list_providers()
    record("Gateway 初始化", len(providers) >= 5, f"providers={len(providers)}")
    # 验证 5 个供应商
    names = {p["name"] for p in providers}
    expected = {"qwen", "deepseek", "openai", "ollama", "mock"}
    record("供应商完整性", expected.issubset(names), f"missing={expected - names}")


async def test_02_mock_chat():
    """测试 2:Mock 调用(正常路径)"""
    from app.llm import get_gateway
    gateway = get_gateway()
    # 强制只用 mock
    resp = await gateway.chat_with_response(
        agent_name="test_agent",
        system_prompt="你是测试助手",
        user_prompt="返回一个JSON",
        preferred_provider="mock",
        preferred_model="mock-model",
        task_id="test-001",
        step="mock_test",
    )
    record("Mock 调用成功", resp.success, f"model={resp.model}, tokens={resp.total_tokens}")
    record("Mock 返回内容", len(resp.content) > 0, f"content_len={len(resp.content)}")
    record("Mock Token 统计", resp.total_tokens > 0, f"prompt={resp.prompt_tokens}, completion={resp.completion_tokens}")


async def test_03_fallback():
    """测试 3:失败切换(强制走不存在的 provider → 切换到可用 provider)"""
    from app.llm import get_gateway
    from app.llm.model_router import RouteTarget, get_model_router
    gateway = get_gateway()
    router = get_model_router()

    # 注册一个故意失败的链:先用不存在的 provider,再走 mock
    # chain 名必须与 agent_name 一致才能命中
    router.register_chain("fallback_test_agent", [
        RouteTarget("nonexistent", "fake-model"),  # 会跳过(不存在)
        RouteTarget("mock", "mock-model"),          # 兜底
    ])

    resp = await gateway.chat_with_response(
        agent_name="fallback_test_agent",
        system_prompt="测试切换",
        user_prompt="hello",
        task_id="test-fallback-001",
    )
    # nonexistent 不存在会跳过,最终命中 mock
    record("失败切换兜底", resp.success, f"provider={resp.provider}, fallback={resp.fallback_used}")
    record("切换到 mock", resp.provider == "mock", f"provider={resp.provider}")


async def test_04_cost():
    """测试 4:费用计算"""
    from app.llm.cost_calculator import get_cost_calculator
    calc = get_cost_calculator()
    # qwen-plus: input 0.0008, output 0.002
    cost = calc.calculate("qwen-plus", prompt_tokens=1000, completion_tokens=500, provider="qwen")
    expected = 1000 / 1000 * 0.0008 + 500 / 1000 * 0.002
    record("费用计算(qwen-plus)", abs(cost - expected) < 0.0001, f"cost={cost:.6f}, expected={expected:.6f}")
    # ollama: 零成本
    cost_ollama = calc.calculate("qwen2.5:7b", prompt_tokens=1000, completion_tokens=500, provider="ollama")
    record("费用计算(ollama 零成本)", cost_ollama == 0.0, f"cost={cost_ollama}")
    # mock: 零成本
    cost_mock = calc.calculate("mock-model", prompt_tokens=100, completion_tokens=50, provider="mock")
    record("费用计算(mock 零成本)", cost_mock == 0.0, f"cost={cost_mock}")


async def test_05_circuit_breaker():
    """测试 5:熔断器"""
    from app.llm.model_router import get_model_router
    router = get_model_router()

    # 模拟连续失败
    router.reset_health("test_provider")
    health = router.get_health("test_provider")
    record("熔断器初始状态", health.state == "closed", f"state={health.state}")

    # 触发 3 次失败(threshold=3)
    for i in range(3):
        router.record_failure("test_provider")
    health = router.get_health("test_provider")
    record("熔断器触发(3次失败)", health.state == "open", f"state={health.state}, failures={health.consecutive_failures}")
    record("熔断时拒绝请求", not health.allow_request(), "should be False")

    # 重置
    router.reset_health("test_provider")
    health = router.get_health("test_provider")
    record("熔断器重置", health.state == "closed", f"state={health.state}")


async def test_06_route_chain():
    """测试 6:路由链管理"""
    from app.llm.model_router import RouteTarget, get_model_router
    router = get_model_router()

    # 创建自定义链
    router.register_chain("custom_agent", [
        RouteTarget("mock", "mock-model"),
    ])
    chain = router.get_chain("custom_agent")
    record("创建路由链", chain.name == "custom_agent" and len(chain.targets) == 1, f"chain={chain.name}")

    # 查询不存在的链 → 回退 default
    chain = router.get_chain("nonexistent_chain")
    record("未知链回退 default", chain.name == "default", f"fallback_chain={chain.name}")

    # 删除链
    ok = router.remove_chain("custom_agent")
    record("删除路由链", ok, "removed")
    # 再查应回退
    chain = router.get_chain("custom_agent")
    record("删除后回退", chain.name == "default", f"chain={chain.name}")


async def test_07_stats_and_logs():
    """测试 7:统计与日志查询"""
    from app.llm import get_gateway
    gateway = get_gateway()

    # 先做几次调用
    for i in range(3):
        await gateway.chat(
            agent_name="stats_test_agent",
            system_prompt="统计测试",
            user_prompt=f"调用 {i}",
            preferred_provider="mock",
            preferred_model="mock-model",
        )

    # 查询统计
    stats = gateway.get_stats(agent_name="stats_test_agent")
    record("统计查询", stats["total_calls"] >= 3, f"calls={stats['total_calls']}")

    # 查询日志
    logs = gateway.list_recent_logs(agent_name="stats_test_agent", limit=10)
    record("日志查询", len(logs) >= 3, f"logs={len(logs)}")
    if logs:
        log = logs[0]
        record("日志字段完整", all(k in log for k in ["agent_name", "provider", "model", "total_tokens", "cost", "status"]),
               f"keys={list(log.keys())[:6]}")


async def test_08_chat_json():
    """测试 8:JSON 解析"""
    from app.llm import get_gateway
    gateway = get_gateway()

    result = await gateway.chat_json(
        agent_name="json_test",
        system_prompt="你是一个JSON生成器,只返回JSON",
        user_prompt='返回 {"status": "ok", "code": 200}',
        preferred_provider="mock",
        preferred_model="mock-model",
        temperature=0,
    )
    record("JSON 解析", "status" in result or "raw" in result, f"result={str(result)[:100]}")


async def test_09_health_check():
    """测试 9:健康检查"""
    from app.llm import get_gateway
    gateway = get_gateway()
    results = await gateway.health_check_all()
    record("健康检查执行", len(results) > 0, f"checked={len(results)}")
    # mock 一定健康
    mock_result = next((r for r in results if r["provider"] == "mock"), None)
    if mock_result:
        record("Mock 健康检查", mock_result["healthy"], f"healthy={mock_result['healthy']}")


async def test_10_overview():
    """测试 10:总览接口"""
    from app.llm import get_gateway
    gateway = get_gateway()
    overview = gateway.to_dict()
    record("总览接口", "providers" in overview and "chains" in overview, f"keys={list(overview.keys())}")


async def main():
    """运行所有测试"""
    logger.info("=" * 60)
    logger.info("LLM Gateway 全链路测试开始")
    logger.info("=" * 60)

    # 确保 SQLite 测试库表存在(只创建 llm_call_log,避免其他模型的 MEDIUMTEXT 不兼容 SQLite)
    try:
        from app.db.database import Base, sync_engine
        from app.models.llm_call_log import LLMCallLog
        Base.metadata.create_all(bind=sync_engine, tables=[LLMCallLog.__table__])
        logger.info("测试数据库表已创建(llm_call_log)")
    except Exception as e:
        logger.warning(f"建表失败(非致命): {e}")

    tests = [
        test_01_init,
        test_02_mock_chat,
        test_03_fallback,
        test_04_cost,
        test_05_circuit_breaker,
        test_06_route_chain,
        test_07_stats_and_logs,
        test_08_chat_json,
        test_09_health_check,
        test_10_overview,
    ]

    for test in tests:
        try:
            await test()
        except Exception as e:
            record(test.__doc__ or test.__name__, False, f"Exception: {e}")
            import traceback
            traceback.print_exc()

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
    report_path = backend_dir / "test_llm_gateway_report.json"
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
