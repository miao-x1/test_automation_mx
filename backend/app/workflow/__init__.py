"""
app.workflow — Graph 工作流模块

架构:
    API → WorkflowRunner → BaseFlow → AgentNode → AgentFactory → Agent

工作流类型:
    UIFlow          — UI 自动化测试 (Requirement → RAG → Case → Script)
    APIFlow         — API 自动化测试
    PerformanceFlow — 性能测试

核心概念:
    WorkflowNode  — Graph 节点 (输入 → 处理 → 输出)
    WorkflowState — 工作流状态 (需求 / 中间结果 / 最终结果)
    BaseFlow      — 工作流基类 (DAG 拓扑执行 + SSE 流式)
    WorkflowRunner — Runtime 集成层

快速使用:
    from app.workflow import get_workflow_runner

    # SSE 流式
    runner = get_workflow_runner()
    async for event in runner.run_stream("ui_test", requirement="测试登录功能"):
        yield event
"""
from app.workflow.state import (
    WorkflowState,
    WorkflowStatus,
    NodeStatus,
    NodeResult,
)
from app.workflow.nodes import (
    WorkflowNode,
    AgentNode,
    FilterNode,
    RouterNode,
)
from app.workflow.base import BaseFlow
from app.workflow.runner import (
    WorkflowRunner,
    get_workflow_runner,
    register_flow,
    get_flow,
    list_flows,
)

__all__ = [
    # State
    "WorkflowState",
    "WorkflowStatus",
    "NodeStatus",
    "NodeResult",
    # Nodes
    "WorkflowNode",
    "AgentNode",
    "FilterNode",
    "RouterNode",
    # Flow
    "BaseFlow",
    # Runner
    "WorkflowRunner",
    "get_workflow_runner",
    "register_flow",
    "get_flow",
    "list_flows",
]
