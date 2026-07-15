"""端到端 Flow 测试

测试完整业务流：
RequirementMessage → RequirementAgent → PageMessage → ImageAgent
→ CaseMessage → CaseAgent → ReviewMessage → ReviewAgent
→ ScriptMessage → ScriptAgent → ExportMessage → ExportAgent
→ ResultMessage → CollectorAgent

使用 Mock LLM 模式，不调用真实 API。
"""
import os
import sys
import json
import asyncio
import traceback
import logging

# 使用 mock LLM，不调用真实 API
os.environ["LLM_PROVIDER"] = "mock"

# 设置日志级别
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")

# 设置 PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 必须在 init_db 之前导入所有模型，确保表注册到 Base.metadata
import app.models  # noqa: F401
from app.models.flow_result import FlowResult  # noqa: F401


async def main():
    print("=" * 60)
    print("端到端 Flow 测试（Mock LLM 模式）")
    print("=" * 60)

    # 1. 初始化数据库（确保 flow_result 表已创建）
    print("\n--- 1. 初始化数据库 ---")
    try:
        from app.db.database import init_db, SessionLocal, sync_engine
        from sqlalchemy import inspect as sql_inspect
        # 先创建表
        init_db()
        # 检查 flow_result 表是否存在
        inspector = sql_inspect(sync_engine)
        tables = inspector.get_table_names()
        if "flow_result" not in tables:
            print("[WARN] flow_result 表不存在，手动创建...")
            FlowResult.__table__.create(sync_engine, checkfirst=True)
            tables = inspector.get_table_names()
        print(f"[OK] 数据库初始化完成，表数量: {len(tables)}")
        assert "flow_result" in tables, "flow_result 表仍然不存在"
        print("[OK] flow_result 表已确认存在")
    except Exception as e:
        print(f"[FAIL] 数据库初始化失败: {e}")
        traceback.print_exc()
        return 1

    # 2. 初始化 Runtime 并注册所有 Flow Agent
    print("\n--- 2. 初始化 Runtime ---")
    try:
        from app.runtime.runtime import get_core_runtime
        from app.agents.flows import FLOW_AGENT_SPECS

        runtime = get_core_runtime()
        await runtime.initialize()
        print("[OK] Runtime 已初始化")

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
        print("[OK] Runtime 已启动")
        print(f"  已注册类型: {runtime.list_agent_types()}")
    except Exception as e:
        print(f"[FAIL] Runtime 初始化失败: {e}")
        traceback.print_exc()
        return 1

    # 3. 发送 RequirementMessage 启动业务流
    print("\n--- 3. 发送 RequirementMessage ---")
    import time as _time
    task_id = f"e2e-test-{int(_time.time())}"
    session_key = "default"

    try:
        from app.agents.messages import RequirementMessage
        from autogen_core import DefaultTopicId

        req_msg = RequirementMessage(
            task_id=task_id,
            session_key=session_key,
            requirement="测试用户登录功能：输入用户名和密码，点击登录按钮，验证登录成功",
            input_mode="text",
            image_paths=[],
            document_paths=[],
            urls=["https://example.com/login"],
            context={"project": "e2e-test"},
        )

        # 发布到 DefaultTopicId，所有订阅的 Agent 都会收到
        await runtime.runtime.publish_message(req_msg, DefaultTopicId())
        print(f"[OK] RequirementMessage 已发布: task={task_id}")
        print(f"  requirement: {req_msg.requirement[:80]}...")
    except Exception as e:
        print(f"[FAIL] 发布 RequirementMessage 失败: {e}")
        traceback.print_exc()
        return 1

    # 4. 等待 CollectorAgent 收到最终结果
    print("\n--- 4. 等待 CollectorAgent 收到结果 ---")
    records = []
    try:
        collector = await runtime.get_collector(session_key)
        if collector is None:
            print("[FAIL] 无法获取 CollectorAgent")
        else:
            print(f"[INFO] 等待任务完成（超时 30s）...")
            result = await collector.wait_for_result(task_id, timeout=30)

            if result is None:
                print("[FAIL] 任务超时，未收到最终结果")
            else:
                print(f"[OK] 收到最终结果!")
                print(f"  任务状态: {result.status}")
                print(f"  结果数量: {len(result.results)}")
                print(f"  错误数量: {len(result.errors)}")
                if result.final_data:
                    print(f"  最终数据: {json.dumps(result.final_data, ensure_ascii=False, indent=2)}")
    except Exception as e:
        print(f"[FAIL] 等待结果失败: {e}")
        traceback.print_exc()

    # 5. 检查 FlowResult 数据库记录
    print("\n--- 5. 检查 FlowResult 数据库记录 ---")
    try:
        db = SessionLocal()
        records = db.query(FlowResult).filter(
            FlowResult.task_id == task_id
        ).order_by(FlowResult.created_at).all()

        print(f"[OK] FlowResult 记录数: {len(records)}")
        for r in records:
            print(f"  - step={r.step}, agent={r.agent_name}, status={r.status}, "
                  f"duration={r.duration:.3f}s, type={r.message_type}")
            if r.status == "error":
                print(f"    error: {r.error_message}")
            if r.output_json:
                try:
                    out = json.loads(r.output_json)
                    print(f"    output keys: {list(out.keys())}")
                except Exception:
                    print(f"    output: {r.output_json[:100]}...")
        db.close()
    except Exception as e:
        print(f"[FAIL] 查询 FlowResult 失败: {e}")
        traceback.print_exc()

    # 6. 检查未处理消息
    print("\n--- 6. 检查 Runtime 状态 ---")
    try:
        unprocessed = runtime.runtime.unprocessed_messages_count
        print(f"  未处理消息数: {unprocessed}")
        print(f"  CollectorAgent 任务列表: {collector.list_tasks() if collector else 'N/A'}")
        for tid in (collector.list_tasks() if collector else []):
            tr = collector.get_result(tid)
            if tr:
                print(f"    task={tid}: status={tr.status}, results={len(tr.results)}, errors={len(tr.errors)}")
    except Exception as e:
        print(f"  [WARN] {e}")

    # 7. 结果汇总
    print("\n" + "=" * 60)
    if records:
        steps = [r.step for r in records]
        print(f"业务流执行步骤: {' → '.join(steps)}")
        success_count = sum(1 for r in records if r.status == "success")
        error_count = sum(1 for r in records if r.status == "error")
        print(f"成功: {success_count}, 失败: {error_count}, 总计: {len(records)}")

        if error_count == 0 and len(records) == 6:
            print("\n=== 端到端测试通过！ ===")
        else:
            print("\n=== 端到端测试完成（有错误或步骤不完整） ===")
    else:
        print("=== 端到端测试失败：无 FlowResult 记录 ===")
    print("=" * 60)

    # 8. 停止 Runtime
    try:
        await runtime.stop_when_idle()
        print("[OK] Runtime 已停止")
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(result)
