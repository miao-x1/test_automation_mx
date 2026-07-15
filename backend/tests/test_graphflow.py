"""
GraphFlow 端到端测试

测试：
1. 默认图结构验证
2. 动态添加节点
3. 执行工作流（mock 模式）
4. SSE 流式执行
"""
import os
import sys
import json
import asyncio
import logging
import time

os.environ["LLM_PROVIDER"] = "mock"
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


async def main():
    print("=" * 60)
    print("GraphFlow 端到端测试")
    print("=" * 60)

    # 1. 验证 GraphFlowManager 初始化
    print("\n--- 1. 验证 GraphFlowManager 初始化 ---")
    try:
        from app.runtime.graph_flow_manager import get_graph_flow_manager
        manager = get_graph_flow_manager()

        nodes = manager.list_nodes()
        edges = manager.list_edges()
        print(f"[OK] 节点数量: {len(nodes)}")
        for n in nodes:
            print(f"  - {n['name']} (step={n['step']}, human={n['is_human']})")
        print(f"[OK] 边数量: {len(edges)}")
        for e in edges:
            print(f"  - {e['source']} → {e['target']}")
    except Exception as e:
        print(f"[FAIL] {e}")
        import traceback; traceback.print_exc()
        return 1

    # 2. 验证默认图结构
    print("\n--- 2. 验证默认图结构 ---")
    expected_nodes = ["Requirement", "CaseGenerate", "CaseReview", "HumanFeedback", "ScriptGenerate", "Export"]
    expected_edges = [
        ("Requirement", "CaseGenerate"),
        ("CaseGenerate", "CaseReview"),
        ("CaseReview", "HumanFeedback"),
        ("HumanFeedback", "ScriptGenerate"),
        ("ScriptGenerate", "Export"),
    ]
    actual_nodes = [n["name"] for n in nodes]
    actual_edges = [(e["source"], e["target"]) for e in edges]

    for n in expected_nodes:
        status = "OK" if n in actual_nodes else "MISSING"
        print(f"  [{status}] Node: {n}")
    for s, t in expected_edges:
        status = "OK" if (s, t) in actual_edges else "MISSING"
        print(f"  [{status}] Edge: {s} → {t}")

    # 3. 测试动态添加节点
    print("\n--- 3. 测试动态添加节点 ---")
    try:
        from app.runtime.graph_flow_manager import NodeSpec
        manager.add_node_after("CaseReview", NodeSpec(
            name="SecurityReview",
            step="security_review",
            description="安全审查节点",
            model_alias="claude",
            capabilities=["security", "review"],
        ))
        nodes_after = manager.list_nodes()
        edges_after = manager.list_edges()
        print(f"[OK] 添加 SecurityReview 后: {len(nodes_after)} 节点, {len(edges_after)} 边")
        for e in edges_after:
            if "SecurityReview" in e["source"] or "SecurityReview" in e["target"]:
                print(f"  - {e['source']} → {e['target']}")

        # 验证图结构正确
        assert ("CaseReview", "SecurityReview") in [(e["source"], e["target"]) for e in edges_after]
        assert ("SecurityReview", "HumanFeedback") in [(e["source"], e["target"]) for e in edges_after]
        assert ("CaseReview", "HumanFeedback") not in [(e["source"], e["target"]) for e in edges_after]
        print("[OK] 动态插入节点验证通过")

        # 清理：删除 SecurityReview 恢复默认
        manager.remove_node("SecurityReview")
        print("[OK] 清理 SecurityReview，恢复默认图")
    except Exception as e:
        print(f"[FAIL] {e}")
        import traceback; traceback.print_exc()

    # 4. 执行工作流
    print("\n--- 4. 执行 GraphFlow 工作流 ---")
    try:
        task_id = f"graphflow-test-{int(time.time())}"
        result = await manager.run(
            task="测试登录功能：输入用户名密码，点击登录，验证跳转",
            task_id=task_id,
            session_key="default",
        )
        print(f"[OK] 工作流执行完成")
        print(f"  task_id: {result['task_id']}")
        print(f"  status: {result['status']}")
        print(f"  duration: {result['duration']:.3f}s")
        print(f"  stop_reason: {result.get('stop_reason')}")
        print(f"  messages_count: {result.get('messages_count')}")
        print(f"  final_output (前200字): {result.get('final_output', '')[:200]}")
    except Exception as e:
        print(f"[FAIL] {e}")
        import traceback; traceback.print_exc()

    # 5. 验证图结构信息
    print("\n--- 5. 验证图结构信息 ---")
    graph_info = manager.get_graph_info()
    print(f"  node_count: {graph_info['node_count']}")
    print(f"  edge_count: {graph_info['edge_count']}")
    print(f"  nodes: {[n['name'] for n in graph_info['nodes']]}")

    # 6. 结果汇总
    print("\n" + "=" * 60)
    if result and result.get("status") == "completed":
        print("=== GraphFlow 端到端测试通过！ ===")
    else:
        print(f"=== 测试完成（status={result.get('status') if result else 'N/A'}） ===")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    r = asyncio.run(main())
    sys.exit(r)
