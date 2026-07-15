"""GraphFlow 动态扩展节点测试

测试在 CaseReview 之后动态插入 SecurityReview 节点，
验证无需修改主流程即可扩展。
"""
import os
import sys
import json
import asyncio
import logging
import time

os.environ["LLM_PROVIDER"] = "mock"
logging.basicConfig(level=logging.WARNING, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


async def main():
    print("=" * 60)
    print("GraphFlow 动态扩展节点测试")
    print("=" * 60)

    from app.runtime.graph_flow_manager import get_graph_flow_manager, NodeSpec

    manager = get_graph_flow_manager()

    # 1. 显示默认图
    print("\n--- 1. 默认图结构 ---")
    graph = manager.get_graph_info()
    print(f"节点: {len(graph['nodes'])}, 边: {len(graph['edges'])}")
    for n in graph["nodes"]:
        print(f"  - {n['name']}")
    for e in graph["edges"]:
        print(f"  {e['source']} → {e['target']}")

    # 2. 动态添加 SecurityReview
    print("\n--- 2. 动态添加 SecurityReview ---")
    manager.add_node_after("CaseReview", NodeSpec(
        name="SecurityReview",
        step="security_review",
        description="安全审查节点 - 检查用例的安全覆盖",
        model_alias="claude",
        capabilities=["security", "review"],
    ))

    graph = manager.get_graph_info()
    print(f"节点: {len(graph['nodes'])}, 边: {len(graph['edges'])}")
    for n in graph["nodes"]:
        print(f"  - {n['name']}")
    for e in graph["edges"]:
        print(f"  {e['source']} → {e['target']}")

    # 验证边正确
    edges = [(e["source"], e["target"]) for e in graph["edges"]]
    assert ("CaseReview", "SecurityReview") in edges, "Missing: CaseReview → SecurityReview"
    assert ("SecurityReview", "HumanFeedback") in edges, "Missing: SecurityReview → HumanFeedback"
    assert ("CaseReview", "HumanFeedback") not in edges, "Should be removed: CaseReview → HumanFeedback"
    print("[OK] 动态插入验证通过")

    # 3. 再添加 PerformanceReview
    print("\n--- 3. 动态添加 PerformanceReview ---")
    manager.add_node_after("SecurityReview", NodeSpec(
        name="PerformanceReview",
        step="performance_review",
        description="性能审查节点",
        model_alias="deepseek",
        capabilities=["performance", "review"],
    ))

    graph = manager.get_graph_info()
    print(f"节点: {len(graph['nodes'])}, 边: {len(graph['edges'])}")
    for e in graph["edges"]:
        print(f"  {e['source']} → {e['target']}")

    # 4. 执行扩展后的工作流
    print("\n--- 4. 执行扩展后的工作流（8 节点）---")
    task_id = f"graphflow-ext-{int(time.time())}"
    result = await manager.run(
        task="测试登录功能的安全性和性能",
        task_id=task_id,
        session_key="default",
    )
    print(f"  status: {result['status']}")
    print(f"  duration: {result['duration']:.3f}s")
    print(f"  stop_reason: {result.get('stop_reason')}")
    print(f"  messages_count: {result.get('messages_count')}")
    print(f"  final_output: {result.get('final_output', '')[:200]}")
    print(f"  nodes: {[n['name'] for n in result.get('nodes', [])]}")

    # 5. 清理：删除扩展节点
    print("\n--- 5. 清理扩展节点 ---")
    manager.remove_node("SecurityReview")
    manager.remove_node("PerformanceReview")
    graph = manager.get_graph_info()
    print(f"清理后: 节点={len(graph['nodes'])}, 边={len(graph['edges'])}")

    # 6. 结果汇总
    print("\n" + "=" * 60)
    if result.get("status") == "completed":
        print("=== 动态扩展节点测试通过！ ===")
    else:
        print(f"=== 测试完成（status={result.get('status')}） ===")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    r = asyncio.run(main())
    sys.exit(r)
