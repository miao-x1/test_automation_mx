"""
BaseFlow — Graph 工作流基类

遵循 AutoGen GraphFlow 思想:
    1. 定义有向图 (DAG): nodes + edges
    2. 按拓扑顺序执行节点
    3. 每个节点: 读取输入 → process → 写入输出
    4. 支持 SSE 流式事件推送
    5. 支持条件跳过节点

执行流程:
    WorkflowState(初始) → Node1 → Node2 → ... → NodeN → WorkflowState(最终)
"""
import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from app.workflow.nodes import AgentNode, FilterNode, RouterNode, WorkflowNode
from app.workflow.state import (
    NodeResult,
    NodeStatus,
    WorkflowState,
    WorkflowStatus,
)

logger = logging.getLogger(__name__)


class BaseFlow(ABC):
    """Graph 工作流基类

    使用方式:
        flow = UIFlow()
        state = WorkflowState.create(requirement="测试登录功能")
        result = await flow.run(state)             # 同步等待
        async for event in flow.run_stream(state): # SSE 流式
            yield event
    """

    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description
        self._nodes: Dict[str, WorkflowNode] = {}
        self._edges: List[Tuple[str, str]] = []
        self._entry: Optional[str] = None  # 入口节点

    # ------------------------------------------------------------------ #
    #  图构建                                                             #
    # ------------------------------------------------------------------ #

    def add_node(self, node: WorkflowNode) -> "BaseFlow":
        """添加节点"""
        if node.name in self._nodes:
            raise ValueError(f"节点已存在: {node.name}")
        self._nodes[node.name] = node
        if self._entry is None:
            self._entry = node.name
        return self

    def add_edge(self, source: str, target: str) -> "BaseFlow":
        """添加边: source → target"""
        if source not in self._nodes:
            raise ValueError(f"源节点不存在: {source}")
        if target not in self._nodes:
            raise ValueError(f"目标节点不存在: {target}")
        self._edges.append((source, target))
        return self

    def set_entry(self, node_name: str) -> "BaseFlow":
        """设置入口节点"""
        if node_name not in self._nodes:
            raise ValueError(f"节点不存在: {node_name}")
        self._entry = node_name
        return self

    @property
    def nodes(self) -> Dict[str, WorkflowNode]:
        return self._nodes

    @property
    def edges(self) -> List[Tuple[str, str]]:
        return list(self._edges)

    @property
    def entry(self) -> Optional[str]:
        return self._entry

    # ------------------------------------------------------------------ #
    #  拓扑排序                                                           #
    # ------------------------------------------------------------------ #

    def _topological_sort(self) -> List[str]:
        """Kahn 算法拓扑排序"""
        in_degree: Dict[str, int] = {n: 0 for n in self._nodes}
        adj: Dict[str, List[str]] = {n: [] for n in self._nodes}

        for src, tgt in self._edges:
            adj[src].append(tgt)
            in_degree[tgt] += 1

        # 入口节点优先
        queue: List[str] = []
        if self._entry:
            queue.append(self._entry)
        else:
            queue = [n for n, d in in_degree.items() if d == 0]

        result: List[str] = []
        while queue:
            node = queue.pop(0)
            result.append(node)
            for neighbor in adj.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(self._nodes):
            raise RuntimeError(f"图中存在环: 已排序 {len(result)}/{len(self._nodes)} 节点")

        return result

    def _get_next_nodes(self, current: str) -> List[str]:
        """获取当前节点的所有后继节点"""
        return [tgt for src, tgt in self._edges if src == current]

    # ------------------------------------------------------------------ #
    #  执行                                                               #
    # ------------------------------------------------------------------ #

    async def run(self, state: WorkflowState) -> WorkflowState:
        """同步执行工作流

        按拓扑顺序逐个执行节点, 返回最终状态。
        如果某节点失败且为必需, 终止工作流。
        """
        state.status = WorkflowStatus.RUNNING
        state.started_at = time.time()
        state.workflow_name = self.name

        order = self._topological_sort()
        logger.info(f"[Flow:{self.name}] 拓扑顺序: {' → '.join(order)}")
        state.emit_event("flow_start", {"flow": self.name, "nodes": order})

        for node_name in order:
            node = self._nodes[node_name]
            state.current_node = node_name

            node_result = NodeResult(node_name=node_name)
            node_result.started_at = time.time()

            state.emit_event("node_start", {"node": node_name})

            try:
                output = await node.process(state)
                node_result.status = NodeStatus.SUCCESS
                node_result.output = output
                node_result.completed_at = time.time()
                state.set_node_output(node.output_key, output)

                state.emit_event("node_success", {
                    "node": node_name,
                    "duration_ms": node_result.duration_ms,
                })

                # RouterNode 路由跳转
                if isinstance(node, RouterNode) and "__route__" in output:
                    route = output["__route__"]
                    if route is None:
                        break  # 结束
                    # 跳过非路由路径上的节点 (简化: 直接跳到路由目标)
                    # 注: 完整实现需要子图执行, 这里保持线性拓扑

            except Exception as e:
                node_result.status = NodeStatus.FAILED
                node_result.error = str(e)
                node_result.completed_at = time.time()
                state.add_node_result(node_result)

                logger.error(f"[Flow:{self.name}] 节点 {node_name} 失败: {e}", exc_info=True)
                state.emit_event("node_failed", {
                    "node": node_name,
                    "error": str(e),
                })

                # 必需节点失败 → 终止
                state.status = WorkflowStatus.FAILED
                state.error = f"节点 {node_name} 执行失败: {e}"
                state.completed_at = time.time()
                state.emit_event("flow_failed", {
                    "error": state.error,
                    "failed_node": node_name,
                })
                return state

            state.add_node_result(node_result)

        # 工作流完成
        state.status = WorkflowStatus.SUCCESS
        state.completed_at = time.time()
        state.final_result = self._build_final_result(state)
        state.emit_event("flow_success", {
            "final_result_keys": list(state.final_result.keys()) if state.final_result else [],
        })
        return state

    async def run_stream(self, state: WorkflowState) -> AsyncGenerator[Dict[str, Any], None]:
        """流式执行工作流 — 逐个 yield 事件 (SSE)

        事件类型:
            flow_start, node_start, node_success, node_failed,
            flow_success, flow_failed, done
        """
        state.status = WorkflowStatus.RUNNING
        state.started_at = time.time()
        state.workflow_name = self.name

        order = self._topological_sort()
        logger.info(f"[Flow:{self.name}] 流式执行, 拓扑顺序: {' → '.join(order)}")

        yield {
            "event": "flow_start",
            "data": {"flow": self.name, "nodes": order, "workflow_id": state.workflow_id},
        }

        for node_name in order:
            node = self._nodes[node_name]
            state.current_node = node_name

            yield {
                "event": "node_start",
                "data": {"node": node_name, "agent": getattr(node, "agent_name", "")},
            }

            node_result = NodeResult(node_name=node_name)
            node_result.started_at = time.time()

            try:
                output = await node.process(state)
                node_result.status = NodeStatus.SUCCESS
                node_result.output = output
                node_result.completed_at = time.time()
                state.set_node_output(node.output_key, output)

                yield {
                    "event": "node_success",
                    "data": {
                        "node": node_name,
                        "duration_ms": node_result.duration_ms,
                        "output_keys": list(output.keys()) if isinstance(output, dict) else [],
                    },
                }

            except Exception as e:
                node_result.status = NodeStatus.FAILED
                node_result.error = str(e)
                node_result.completed_at = time.time()
                state.add_node_result(node_result)

                logger.error(f"[Flow:{self.name}] 节点 {node_name} 失败: {e}", exc_info=True)

                yield {
                    "event": "node_failed",
                    "data": {"node": node_name, "error": str(e)},
                }

                state.status = WorkflowStatus.FAILED
                state.error = f"节点 {node_name} 执行失败: {e}"
                state.completed_at = time.time()

                yield {
                    "event": "flow_failed",
                    "data": {"error": state.error, "failed_node": node_name},
                }
                yield {"event": "done", "data": {"workflow_id": state.workflow_id}}
                return

            state.add_node_result(node_result)

        state.status = WorkflowStatus.SUCCESS
        state.completed_at = time.time()
        state.final_result = self._build_final_result(state)

        yield {
            "event": "flow_success",
            "data": {
                "final_result": state.final_result,
                "duration_ms": round((state.completed_at - state.started_at) * 1000, 1),
            },
        }
        yield {"event": "done", "data": {"workflow_id": state.workflow_id}}

    # ------------------------------------------------------------------ #
    #  子类实现                                                           #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def _build_final_result(self, state: WorkflowState) -> Dict[str, Any]:
        """从中间结果构建最终输出 — 子类实现"""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    #  图信息                                                             #
    # ------------------------------------------------------------------ #

    def get_graph_info(self) -> Dict[str, Any]:
        """获取图结构信息"""
        return {
            "name": self.name,
            "description": self.description,
            "entry": self._entry,
            "nodes": [
                {
                    "name": n.name,
                    "type": n.__class__.__name__,
                    "input_keys": n.input_keys,
                    "output_key": n.output_key,
                    "agent_name": getattr(n, "agent_name", None),
                    "description": n.description,
                }
                for n in self._nodes.values()
            ],
            "edges": [{"source": s, "target": t} for s, t in self._edges],
            "topological_order": self._topological_sort(),
        }
