"""
GraphFlowManager - 动态工作流图管理器

基于 AutoGen AgentChat 的 DiGraphBuilder + GraphFlow 构建。

核心特性：
1. 使用 DiGraphBuilder 动态构建有向图
2. 使用 GraphFlow 执行工作流
3. 节点可动态增删（如 SecurityReview, PerformanceReview, AccessibilityReview）
4. 支持顺序、并行、条件分支
5. 每个节点执行结果保存数据库
6. 所有事件推送给 CollectorAgent

默认业务流：
    Requirement → CaseGenerate → CaseReview → HumanFeedback
    → ScriptGenerate → Export

动态扩展示例：
    manager.add_node_after("CaseReview", "SecurityReview")
    manager.add_node_after("SecurityReview", "PerformanceReview")

使用方式：
    manager = get_graph_flow_manager()
    result = await manager.run(
        task="测试登录功能",
        task_id="task-001",
        session_key="user_1_session_a",
    )

    # SSE 流式
    async for event in manager.run_stream(task=...):
        yield event
"""
import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, AsyncGenerator

from autogen_agentchat.teams import DiGraphBuilder, GraphFlow
from autogen_agentchat.messages import TextMessage

from app.runtime.flow_node_adapter import FlowNodeAdapter
from app.agents.flows.human_feedback_agent import HumanFeedbackAgent

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  节点定义                                                            #
# ------------------------------------------------------------------ #

class NodeSpec:
    """工作流节点规格定义"""

    def __init__(
        self,
        name: str,
        agent_class: Any = None,
        step: str = "",
        description: str = "",
        is_human: bool = False,
        model_alias: str = "",
        capabilities: List[str] = None,
    ) -> None:
        self.name = name
        self.agent_class = agent_class
        self.step = step or name.lower()
        self.description = description or f"Flow node: {name}"
        self.is_human = is_human
        self.model_alias = model_alias
        self.capabilities = capabilities or []


# 默认节点定义
DEFAULT_NODES: List[NodeSpec] = [
    NodeSpec(
        name="Requirement",
        agent_class=None,  # 延迟加载
        step="requirement",
        description="需求解析节点",
        model_alias="qwen",
        capabilities=["requirement_parse"],
    ),
    NodeSpec(
        name="PageSearch",
        agent_class=None,
        step="page_search",
        description="页面搜索节点（RAG查询页面知识）",
        model_alias="qwen",
        capabilities=["rag_query", "page_search"],
    ),
    NodeSpec(
        name="RAGRetrieve",
        agent_class=None,
        step="rag",
        description="RAG上下文检索节点",
        model_alias="qwen",
        capabilities=["rag_query", "context_retrieve"],
    ),
    NodeSpec(
        name="ElementAnalysis",
        agent_class=None,
        step="element",
        description="页面元素分析节点",
        model_alias="qwen_vl",
        capabilities=["page_element_analysis"],
    ),
    NodeSpec(
        name="CaseGenerate",
        agent_class=None,
        step="case",
        description="测试用例生成节点",
        model_alias="deepseek",
        capabilities=["case_generate"],
    ),
    NodeSpec(
        name="CaseReview",
        agent_class=None,
        step="review",
        description="用例审查节点",
        model_alias="claude",
        capabilities=["review"],
    ),
    NodeSpec(
        name="HumanFeedback",
        is_human=True,
        step="feedback",
        description="人工反馈节点",
        capabilities=["human_feedback"],
    ),
    NodeSpec(
        name="ScriptGenerate",
        agent_class=None,
        step="script",
        description="脚本生成节点",
        model_alias="qwen_coder",
        capabilities=["script_generate"],
    ),
    NodeSpec(
        name="Storage",
        agent_class=None,
        step="storage",
        description="数据存储节点（MySQL+Milvus+Neo4j）",
        capabilities=["mysql_save", "vector_insert", "graph_create"],
    ),
    NodeSpec(
        name="Execution",
        agent_class=None,
        step="execution",
        description="脚本执行节点",
        capabilities=["script_execute", "playwright"],
    ),
    NodeSpec(
        name="Report",
        agent_class=None,
        step="report",
        description="测试报告生成节点",
        capabilities=["report_generate"],
    ),
    NodeSpec(
        name="Defect",
        agent_class=None,
        step="defect",
        description="缺陷分析节点",
        capabilities=["defect_analysis"],
    ),
    NodeSpec(
        name="Export",
        agent_class=None,
        step="export",
        description="结果导出节点",
        capabilities=["export"],
    ),
]

# 默认边定义（顺序）
DEFAULT_EDGES: List[tuple] = [
    ("Requirement", "PageSearch"),
    ("PageSearch", "RAGRetrieve"),
    ("RAGRetrieve", "ElementAnalysis"),
    ("ElementAnalysis", "CaseGenerate"),
    ("CaseGenerate", "CaseReview"),
    ("CaseReview", "HumanFeedback"),
    ("HumanFeedback", "ScriptGenerate"),
    ("ScriptGenerate", "Storage"),
    ("Storage", "Execution"),
    ("Execution", "Report"),
    ("Report", "Defect"),
    ("Defect", "Export"),
]


# ------------------------------------------------------------------ #
#  GraphFlowManager                                                    #
# ------------------------------------------------------------------ #

class GraphFlowManager:
    """
    动态工作流图管理器

    职责：
    1. 维护节点列表和边列表
    2. 使用 DiGraphBuilder 构建 GraphFlow
    3. 执行工作流（同步 / 流式）
    4. 动态增删节点
    5. 每个节点执行结果保存数据库

    扩展示例：
        manager.add_node(NodeSpec(name="SecurityReview", ...))
        manager.add_edge("CaseReview", "SecurityReview")
        manager.add_edge("SecurityReview", "HumanFeedback")
        manager.remove_edge("CaseReview", "HumanFeedback")
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, NodeSpec] = {}
        self._edges: List[tuple] = []
        self._node_instances: Dict[str, FlowNodeAdapter] = {}
        self._human_feedback_agent: Optional[HumanFeedbackAgent] = None
        self._lock = asyncio.Lock()

        # 加载默认节点和边
        for node in DEFAULT_NODES:
            self._nodes[node.name] = node
        self._edges = list(DEFAULT_EDGES)

    # ------------------------------------------------------------------ #
    #  节点管理                                                            #
    # ------------------------------------------------------------------ #

    def add_node(self, spec: NodeSpec) -> None:
        """添加节点"""
        self._nodes[spec.name] = spec
        logger.info(f"[GraphFlow] Node added: {spec.name}")

    def remove_node(self, name: str) -> None:
        """删除节点（同时删除相关边）"""
        self._nodes.pop(name, None)
        self._edges = [(s, t) for s, t in self._edges if s != name and t != name]
        logger.info(f"[GraphFlow] Node removed: {name}")

    def add_edge(self, source: str, target: str) -> None:
        """添加边"""
        if (source, target) not in self._edges:
            self._edges.append((source, target))
            logger.info(f"[GraphFlow] Edge added: {source} → {target}")

    def remove_edge(self, source: str, target: str) -> None:
        """删除边"""
        self._edges = [(s, t) for s, t in self._edges if not (s == source and t == target)]
        logger.info(f"[GraphFlow] Edge removed: {source} → {target}")

    def add_node_after(self, after: str, spec: NodeSpec) -> None:
        """
        在指定节点之后插入新节点

        示例：
            manager.add_node_after("CaseReview", NodeSpec(name="SecurityReview", ...))
            # 自动连接 CaseReview → SecurityReview → 原下一节点
        """
        # 找到 after 节点的所有下游边
        downstream = [(s, t) for s, t in self._edges if s == after]
        self.add_node(spec)
        for s, t in downstream:
            self.remove_edge(s, t)
            self.add_edge(s, spec.name)
            self.add_edge(spec.name, t)
        if not downstream:
            # 没有下游边，直接添加
            self.add_edge(after, spec.name)
        logger.info(f"[GraphFlow] Node {spec.name} inserted after {after}")

    def list_nodes(self) -> List[Dict[str, Any]]:
        """列出所有节点"""
        return [
            {
                "name": n.name,
                "step": n.step,
                "description": n.description,
                "is_human": n.is_human,
                "model_alias": n.model_alias,
                "capabilities": n.capabilities,
            }
            for n in self._nodes.values()
        ]

    def list_edges(self) -> List[Dict[str, str]]:
        """列出所有边"""
        return [{"source": s, "target": t} for s, t in self._edges]

    # ------------------------------------------------------------------ #
    #  构建 GraphFlow                                                      #
    # ------------------------------------------------------------------ #

    def _create_node_instance(self, spec: NodeSpec, task_id: str, session_key: str) -> FlowNodeAdapter:
        """创建节点实例"""
        if spec.is_human:
            # 人工反馈节点
            human_agent = HumanFeedbackAgent(
                name=spec.name,
                description=spec.description,
                mode="auto",  # 默认 auto，可由 API 修改
            )
            self._human_feedback_agent = human_agent
            return FlowNodeAdapter(
                name=spec.name,
                wrapped_agent=human_agent,
                step=spec.step,
                description=spec.description,
            )

        # 延迟加载 Agent 类
        agent_class = spec.agent_class
        if agent_class is None:
            agent_class = self._resolve_agent_class(spec)
            if agent_class is None:
                raise ValueError(f"Cannot resolve agent class for node: {spec.name}")

        # 创建 Agent 实例
        agent = agent_class()

        # 包装为 FlowNodeAdapter
        return FlowNodeAdapter(
            name=spec.name,
            wrapped_agent=agent,
            step=spec.step,
            description=spec.description,
        )

    def _resolve_agent_class(self, spec: NodeSpec) -> Optional[type]:
        """根据节点规格解析 Agent 类"""
        # 节点名 → Agent 类映射
        mapping = {
            # 核心流程节点
            "Requirement": ("app.agent.requirement.requirement_agent", "RequirementAgent"),
            "PageSearch": ("app.agents.flows.rag_query_agent", "RAGQueryAgent"),
            "RAGRetrieve": ("app.agents.flows.rag_query_agent", "RAGQueryAgent"),
            "ElementAnalysis": ("app.agent.vision.element_agent", "ElementAgent"),
            "CaseGenerate": ("app.agent.case.case_agent", "CaseAgent"),
            "CaseReview": ("app.agent.case.review_agent", "ReviewAgent"),
            "ScriptGenerate": ("app.agent.script.script_generation_agent", "ScriptGenerationAgent"),
            "Storage": ("app.agents.flows.mysql_storage_agent", "MysqlStorageAgent"),
            "Execution": ("app.agents.flows.execution_flow_agent", "ExecutionFlowAgent"),
            "Report": ("app.agents.flows.report_agent", "ReportAgent"),
            "Defect": ("app.agents.flows.defect_agent", "DefectAgent"),
            "Export": ("app.agents.flows.export_agent", "ExportAgent"),
            # 可扩展节点（均复用 ReviewAgent）
            "SecurityReview": ("app.agents.flows.review_agent", "ReviewAgent"),
            "PerformanceReview": ("app.agents.flows.review_agent", "ReviewAgent"),
            "AccessibilityReview": ("app.agents.flows.review_agent", "ReviewAgent"),
        }
        entry = mapping.get(spec.name)
        if entry is None:
            return None
        module_path, class_name = entry
        import importlib
        module = importlib.import_module(module_path)
        return getattr(module, class_name)

    def build_flow(
        self,
        task_id: str = "",
        session_key: str = "default",
    ) -> GraphFlow:
        """
        使用 DiGraphBuilder 构建 GraphFlow

        每次调用都创建新的实例和图，
        因此动态增删节点不会影响已构建的 flow。
        """
        # 创建所有节点实例
        node_instances: Dict[str, FlowNodeAdapter] = {}
        for name, spec in self._nodes.items():
            instance = self._create_node_instance(spec, task_id, session_key)
            node_instances[name] = instance
        self._node_instances = node_instances

        # 使用 DiGraphBuilder 构建图
        builder = DiGraphBuilder()

        # 添加所有节点
        for name, instance in node_instances.items():
            builder.add_node(instance)

        # 添加所有边
        for source, target in self._edges:
            if source in node_instances and target in node_instances:
                builder.add_edge(node_instances[source], node_instances[target])

        # 构建图
        graph = builder.build()

        # 创建 GraphFlow
        flow = GraphFlow(
            participants=list(node_instances.values()),
            graph=graph,
        )

        logger.info(
            f"[GraphFlow] Built: {len(node_instances)} nodes, {len(self._edges)} edges"
        )
        return flow

    # ------------------------------------------------------------------ #
    #  执行                                                                #
    # ------------------------------------------------------------------ #

    async def run(
        self,
        task: str,
        task_id: str = "",
        session_key: str = "default",
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        执行 GraphFlow 工作流

        Args:
            task: 任务描述
            task_id: 任务ID
            session_key: 会话标识
            context: 上下文数据

        Returns:
            工作流结果
        """
        if not task_id:
            task_id = str(uuid.uuid4())

        start_time = time.time()
        logger.info(f"[GraphFlow] Starting: task={task_id}, session={session_key}")

        # 构建初始 payload
        initial_payload = {
            "task_id": task_id,
            "session_key": session_key,
            "requirement": task,
            "context": context or {},
        }

        # 构建 flow
        flow = self.build_flow(task_id=task_id, session_key=session_key)

        # 执行
        try:
            result = await flow.run(
                task=json.dumps(initial_payload, ensure_ascii=False)
            )

            duration = time.time() - start_time
            logger.info(f"[GraphFlow] Completed: task={task_id}, duration={duration:.3f}s")

            # 提取最终结果
            final_output = ""
            if result.messages:
                last_msg = result.messages[-1]
                if isinstance(last_msg, TextMessage):
                    final_output = last_msg.content

            return {
                "task_id": task_id,
                "session_key": session_key,
                "status": "completed",
                "duration": duration,
                "stop_reason": result.stop_reason,
                "messages_count": len(result.messages),
                "final_output": final_output,
                "nodes": list(self._nodes.keys()),
                "edges": [{"source": s, "target": t} for s, t in self._edges],
            }

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"[GraphFlow] Failed: task={task_id}, error={e}", exc_info=True)
            return {
                "task_id": task_id,
                "session_key": session_key,
                "status": "failed",
                "duration": duration,
                "error": str(e),
                "nodes": list(self._nodes.keys()),
                "edges": [{"source": s, "target": t} for s, t in self._edges],
            }

    async def run_stream(
        self,
        task: str,
        task_id: str = "",
        session_key: str = "default",
        context: Optional[Dict] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式执行 GraphFlow 工作流

        Yields:
            各节点的输出消息
        """
        if not task_id:
            task_id = str(uuid.uuid4())

        start_time = time.time()
        logger.info(f"[GraphFlow] Starting stream: task={task_id}")

        initial_payload = {
            "task_id": task_id,
            "session_key": session_key,
            "requirement": task,
            "context": context or {},
        }

        flow = self.build_flow(task_id=task_id, session_key=session_key)

        try:
            async for event in flow.run_stream(
                task=json.dumps(initial_payload, ensure_ascii=False)
            ):
                if isinstance(event, TextMessage):
                    yield {
                        "event": "node_message",
                        "data": {
                            "source": event.source,
                            "content": event.content[:500],  # 截断
                            "task_id": task_id,
                        },
                    }
                elif hasattr(event, "stop_reason"):
                    # TaskResult
                    duration = time.time() - start_time
                    yield {
                        "event": "task_result",
                        "data": {
                            "task_id": task_id,
                            "stop_reason": event.stop_reason,
                            "messages_count": len(event.messages),
                            "duration": duration,
                            "status": "completed",
                        },
                    }
                else:
                    yield {
                        "event": "flow_event",
                        "data": {
                            "task_id": task_id,
                            "type": type(event).__name__,
                            "content": str(event)[:500],
                        },
                    }

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"[GraphFlow] Stream failed: task={task_id}, error={e}")
            yield {
                "event": "error",
                "data": {
                    "task_id": task_id,
                    "error": str(e),
                    "duration": duration,
                },
            }

        yield {"event": "done", "data": {"task_id": task_id}}

    # ------------------------------------------------------------------ #
    #  人工反馈                                                            #
    # ------------------------------------------------------------------ #

    def submit_human_feedback(self, feedback_id: str, feedback: Dict) -> bool:
        """提交人工反馈"""
        if self._human_feedback_agent:
            return self._human_feedback_agent.submit_feedback(feedback_id, feedback)
        return False

    # ------------------------------------------------------------------ #
    #  状态查询                                                            #
    # ------------------------------------------------------------------ #

    def get_graph_info(self) -> Dict[str, Any]:
        """获取图结构信息"""
        return {
            "nodes": self.list_nodes(),
            "edges": self.list_edges(),
            "node_count": len(self._nodes),
            "edge_count": len(self._edges),
        }


# ------------------------------------------------------------------ #
#  单例                                                                #
# ------------------------------------------------------------------ #

_graph_flow_manager: Optional[GraphFlowManager] = None


def get_graph_flow_manager() -> GraphFlowManager:
    """获取 GraphFlowManager 单例"""
    global _graph_flow_manager
    if _graph_flow_manager is None:
        _graph_flow_manager = GraphFlowManager()
    return _graph_flow_manager
