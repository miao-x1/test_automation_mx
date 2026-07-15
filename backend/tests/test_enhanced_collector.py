"""验证增强版 CollectorAgent 端到端"""
import os
import sys
import json
import asyncio
import logging
import time

os.environ["LLM_PROVIDER"] = "mock"
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app.models  # noqa
from app.models.agent_event import AgentEvent  # noqa
from app.models.flow_result import FlowResult  # noqa


async def main():
    print("=" * 60)
    print("增强版 CollectorAgent 端到端测试")
    print("=" * 60)

    # 1. 初始化数据库
    print("\n--- 1. 初始化数据库 ---")
    try:
        from app.db.database import init_db, SessionLocal, sync_engine
        from sqlalchemy import inspect as sql_inspect
        init_db()
        inspector = sql_inspect(sync_engine)
        tables = inspector.get_table_names()
        if "agent_event" not in tables:
            print("[WARN] agent_event 表不存在，手动创建...")
            AgentEvent.__table__.create(sync_engine, checkfirst=True)
            tables = inspector.get_table_names()
        print(f"[OK] 数据库初始化完成，表数量: {len(tables)}")
        assert "agent_event" in tables
        assert "flow_result" in tables
        print("[OK] agent_event + flow_result 表已确认存在")
    except Exception as e:
        print(f"[FAIL] 数据库初始化失败: {e}")
        import traceback; traceback.print_exc()
        return 1

    # 2. 初始化 Runtime
    print("\n--- 2. 初始化 Runtime ---")
    try:
        from app.runtime.runtime import get_core_runtime
        from app.agents.flows import FLOW_AGENT_SPECS

        runtime = get_core_runtime()
        await runtime.initialize()

        for spec in FLOW_AGENT_SPECS:
            module = __import__(spec["module_path"], fromlist=[spec["class_name"]])
            cls = getattr(module, spec["class_name"])
            await runtime.register_agent_type(
                agent_type=spec["name"],
                agent_class=cls,
                factory=lambda c=cls: c(),
            )
            print(f"  [OK] {spec['name']} 已注册")

        await runtime.start()
        print(f"[OK] Runtime 已启动，类型: {runtime.list_agent_types()}")
    except Exception as e:
        print(f"[FAIL] Runtime 初始化失败: {e}")
        import traceback; traceback.print_exc()
        return 1

    # 3. 发送 RequirementMessage
    print("\n--- 3. 发送 RequirementMessage ---")
    task_id = f"enhanced-test-{int(time.time())}"
    session_key = "default"

    try:
        from app.agents.messages import RequirementMessage
        from autogen_core import DefaultTopicId

        req_msg = RequirementMessage(
            task_id=task_id,
            session_key=session_key,
            requirement="测试用户登录功能：输入用户名和密码，点击登录按钮，验证登录成功",
            input_mode="text",
            urls=["https://example.com/login"],
            context={"project": "enhanced-test"},
        )

        await runtime.runtime.publish_message(req_msg, DefaultTopicId())
        print(f"[OK] RequirementMessage 已发布: task={task_id}")
    except Exception as e:
        print(f"[FAIL] 发布消息失败: {e}")
        import traceback; traceback.print_exc()
        return 1

    # 4. 等待 CollectorAgent 结果
    print("\n--- 4. 等待结果 ---")
    try:
        collector = await runtime.get_collector(session_key)
        print(f"[INFO] 等待任务完成（超时 30s）...")
        result = await collector.wait_for_result(task_id, timeout=30)

        if result:
            print(f"[OK] 收到结果!")
            print(f"  任务状态: {result.status}")
            print(f"  结果数量: {len(result.results)}")
            print(f"  错误数量: {len(result.errors)}")
            print(f"  事件数量: {len(result.events)}")
            print(f"  总 Token: {result.total_tokens}")
            print(f"  总耗时: {result.total_duration:.3f}s")
    except Exception as e:
        print(f"[FAIL] 等待结果失败: {e}")
        import traceback; traceback.print_exc()

    # 5. 检查 FlowResult 记录
    print("\n--- 5. 检查 FlowResult 记录 ---")
    flow_records = []
    try:
        db = SessionLocal()
        flow_records = db.query(FlowResult).filter(
            FlowResult.task_id == task_id
        ).order_by(FlowResult.created_at).all()
        print(f"[OK] FlowResult 记录数: {len(flow_records)}")
        for r in flow_records:
            print(f"  - step={r.step}, agent={r.agent_name}, status={r.status}, duration={r.duration:.3f}s")
        db.close()
    except Exception as e:
        print(f"[FAIL] 查询 FlowResult 失败: {e}")

    # 6. 检查 AgentEvent 记录
    print("\n--- 6. 检查 AgentEvent 记录 ---")
    event_records = []
    try:
        db = SessionLocal()
        event_records = db.query(AgentEvent).filter(
            AgentEvent.task_id == task_id
        ).order_by(AgentEvent.created_at).all()
        print(f"[OK] AgentEvent 记录数: {len(event_records)}")
        for r in event_records:
            info = f"  - type={r.event_type}, agent={r.agent_name}, step={r.step}, status={r.status}"
            if r.model_name:
                info += f", model={r.model_name}"
            if r.total_tokens:
                info += f", tokens={r.total_tokens}"
            if r.duration:
                info += f", duration={r.duration:.3f}s"
            if r.is_retry:
                info += f", retry={r.retry_count}"
            if r.is_final:
                info += " [FINAL]"
            print(info)
        db.close()
    except Exception as e:
        print(f"[FAIL] 查询 AgentEvent 失败: {e}")

    # 7. 检查事件类型覆盖
    print("\n--- 7. 事件类型覆盖检查 ---")
    event_types_found = set()
    for r in event_records:
        event_types_found.add(r.event_type)

    expected_types = {"start", "end", "prompt"}
    print(f"  事件类型: {sorted(event_types_found)}")
    for t in sorted(expected_types):
        status = "OK" if t in event_types_found else "MISSING"
        print(f"  [{status}] {t}")

    # 8. 检查 CollectorAgent 摘要
    print("\n--- 8. CollectorAgent 任务摘要 ---")
    try:
        summary = collector.get_task_summary(task_id)
        if summary:
            print(f"  task_id: {summary['task_id']}")
            print(f"  status: {summary['status']}")
            print(f"  progress: {summary['progress']:.0%}")
            print(f"  current_step: {summary['current_step']}")
            print(f"  total_tokens: {summary['total_tokens']}")
            print(f"  total_duration: {summary['total_duration']:.3f}s")
            print(f"  results_count: {summary['results_count']}")
            print(f"  errors_count: {summary['errors_count']}")
            print(f"  events_count: {summary['events_count']}")
        else:
            print("  [FAIL] 无法获取摘要")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # 9. 检查 EventBus 状态
    print("\n--- 9. EventBus 状态 ---")
    try:
        from app.runtime.event_bus import get_event_bus
        bus = get_event_bus()
        stats = bus.get_stats()
        print(f"  EventBus 统计: {stats}")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # 10. 结果汇总
    print("\n" + "=" * 60)
    flow_success = sum(1 for r in flow_records if r.status == "success")
    flow_error = sum(1 for r in flow_records if r.status == "error")
    event_count = len(event_records)

    print(f"FlowResult: {len(flow_records)} 条（成功 {flow_success}, 失败 {flow_error}）")
    print(f"AgentEvent: {event_count} 条事件")
    print(f"事件类型: {sorted(event_types_found)}")

    if flow_error == 0 and len(flow_records) == 6 and event_count >= 12:
        print("\n=== 增强版 CollectorAgent 测试通过！ ===")
    else:
        print(f"\n=== 测试完成（FlowResult={len(flow_records)}, AgentEvent={event_count}） ===")
    print("=" * 60)

    try:
        await runtime.stop_when_idle()
        print("[OK] Runtime 已停止")
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(result)
