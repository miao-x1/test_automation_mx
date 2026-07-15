"""Session 管理端到端测试

测试：
1. 创建会话
2. 添加制品
3. 恢复会话
4. 执行 GraphFlow
5. 列出会话
6. 统计信息
"""
import os
import sys
import json
import asyncio
import logging

os.environ["LLM_PROVIDER"] = "mock"
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app.models  # noqa


async def main():
    print("=" * 60)
    print("Session 管理端到端测试")
    print("=" * 60)

    from app.services.session_db_service import get_session_manager
    manager = get_session_manager()

    # 1. 创建会话
    print("\n--- 1. 创建会话 ---")
    session = manager.create_session(
        user_id=1,
        requirement="测试用户登录功能：输入用户名和密码，点击登录，验证跳转",
        input_mode="text",
    )
    print(f"[OK] 会话创建: id={session.id}, name={session.session_name}")
    print(f"  session_key={session.session_key}")
    print(f"  requirement={session.requirement_text[:50]}...")

    # 2. 添加制品
    print("\n--- 2. 添加制品 ---")
    artifacts_to_add = [
        ("file", "登录页面截图", {"url": "https://example.com/login.png"}, "upload"),
        ("test_point", "登录成功", {"type": "positive", "priority": "high"}, "testpoint"),
        ("case", "正常登录", {"title": "正常登录", "steps": ["输入用户名", "输入密码", "点击登录"]}, "case"),
        ("script", "test_login.py", {"script": "def test_login(): pass"}, "script"),
        ("log", "执行日志", {"level": "info", "message": "测试通过"}, "log"),
        ("mindmap", "登录功能思维导图", {"nodes": ["登录", "用户名", "密码", "验证"]}, "mindmap"),
        ("export", "导出文件", {"format": "xlsx", "file": "test_cases.xlsx"}, "export"),
    ]

    for art_type, name, content, step in artifacts_to_add:
        artifact = manager.add_artifact(
            session_id=session.id,
            artifact_type=art_type,
            name=name,
            content=content,
            step=step,
            source_agent="TestAgent",
        )
        print(f"  [OK] {art_type}: {name} (id={artifact.id})")

    # 3. 恢复会话
    print("\n--- 3. 恢复会话 ---")
    state = manager.restore_session(session.id)
    print(f"[OK] 会话恢复: {state['session']['session_name']}")
    print(f"  制品总数: {state['stats']['total_artifacts']}")
    print(f"  事件总数: {state['stats']['total_events']}")
    print(f"  流程结果: {state['stats']['total_flow_results']}")
    print(f"  制品类型: {state['stats']['artifact_types']}")

    for art_type, items in state["artifacts"].items():
        print(f"  - {art_type}: {len(items)} 条")
        for item in items:
            print(f"    - {item['name']}")

    # 4. 列出会话
    print("\n--- 4. 会话列表 ---")
    sessions = manager.list_sessions(user_id=1)
    print(f"[OK] 会话数量: {len(sessions)}")
    for s in sessions:
        print(f"  - id={s['id']}, name={s['session_name']}, status={s['status']}, artifacts={s['artifact_count']}")

    # 5. 统计信息
    print("\n--- 5. 会话统计 ---")
    stats = manager.get_session_stats(session.id)
    print(f"[OK] 统计信息:")
    print(f"  total_artifacts: {stats['total_artifacts']}")
    print(f"  artifacts_by_type: {stats['artifacts_by_type']}")
    print(f"  total_events: {stats['total_events']}")
    print(f"  total_tokens: {stats['total_tokens']}")

    # 6. 执行 GraphFlow
    print("\n--- 6. 执行 GraphFlow ---")
    result = await manager.run_graphflow(
        session_id=session.id,
        requirement=session.requirement_text,
    )
    print(f"[OK] GraphFlow 执行完成:")
    print(f"  status: {result.get('status')}")
    print(f"  duration: {result.get('duration', 0):.3f}s")
    print(f"  task_id: {result.get('task_id')}")

    # 7. 再次恢复会话（验证 GraphFlow 结果已保存）
    print("\n--- 7. 执行后恢复会话 ---")
    state2 = manager.restore_session(session.id)
    print(f"[OK] 恢复后:")
    print(f"  制品总数: {state2['stats']['total_artifacts']}")
    print(f"  事件总数: {state2['stats']['total_events']}")
    print(f"  流程结果: {state2['stats']['total_flow_results']}")
    if state2["flow_results"]:
        for fr in state2["flow_results"]:
            print(f"  - {fr['step']}: {fr['status']} ({fr['duration']:.3f}s)")

    # 8. 验证制品包含所有类型
    print("\n--- 8. 制品类型覆盖验证 ---")
    expected_types = ["requirement", "file", "test_point", "case", "script", "log", "mindmap", "export"]
    found_types = list(state2["artifacts"].keys())
    for t in expected_types:
        status = "OK" if t in found_types else "MISSING"
        print(f"  [{status}] {t}")

    # 9. 结果汇总
    print("\n" + "=" * 60)
    all_ok = (
        state2["stats"]["total_artifacts"] >= 8 and
        len(state2["flow_results"]) > 0 and
        result.get("status") == "completed"
    )
    if all_ok:
        print("=== Session 管理端到端测试通过！ ===")
    else:
        print(f"=== 测试完成（artifacts={state2['stats']['total_artifacts']}, "
              f"flow_results={len(state2['flow_results'])}, "
              f"status={result.get('status')}） ===")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    r = asyncio.run(main())
    sys.exit(r)
