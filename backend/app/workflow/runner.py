"""
WorkflowRunner — Runtime 集成层

将 Workflow 接入 Runtime v2:
    1. Runtime 收到 task_type=FLOW 的任务时, 委托 WorkflowRunner 执行
    2. WorkflowRunner 根据 test_type 选择对应 Flow (UI/API/Performance)
    3. 创建 WorkflowState, 执行 Flow, 推送 SSE 事件
    4. Agent 之间不直接调用, 通过 Workflow 的 DAG 编排

架构:
    Runtime v2 Dispatcher
        ↓ submit(task_type=FLOW, payload={requirement, test_type})
    WorkflowRunner
        ↓ 选择 Flow (UIFlow / APIFlow / PerformanceFlow)
    BaseFlow.run_stream(state)
        ↓ 按拓扑顺序执行节点
    AgentNode → AgentFactory.create() → Agent.execute()
        ↓ 事件推送
    ResponseCollector → SSE/WebSocket
"""
import asyncio
import logging
import time
from typing import Any, AsyncGenerator, Dict, Optional

from app.workflow.base import BaseFlow
from app.workflow.state import WorkflowState, WorkflowStatus

logger = logging.getLogger(__name__)

# Flow 注册表
_FLOW_REGISTRY: Dict[str, type] = {}


def register_flow(name: str, flow_cls: type) -> None:
    """注册工作流"""
    _FLOW_REGISTRY[name] = flow_cls
    logger.info(f"工作流已注册: {name} → {flow_cls.__name__}")


def get_flow(name: str) -> Optional[BaseFlow]:
    """获取工作流实例"""
    flow_cls = _FLOW_REGISTRY.get(name)
    if flow_cls is None:
        return None
    return flow_cls()


def list_flows() -> Dict[str, str]:
    """列出所有已注册的工作流"""
    return {name: cls.__name__ for name, cls in _FLOW_REGISTRY.items()}


def _auto_register() -> None:
    """自动注册所有内置工作流"""
    try:
        from app.workflow.ui_flow import UIFlow
        register_flow("ui_test", UIFlow)
    except Exception as e:
        logger.warning(f"注册 UIFlow 失败: {e}")

    try:
        from app.workflow.api_flow import APIFlow
        register_flow("api_test", APIFlow)
    except Exception as e:
        logger.warning(f"注册 APIFlow 失败: {e}")

    try:
        from app.workflow.performance_flow import PerformanceFlow
        register_flow("performance_test", PerformanceFlow)
    except Exception as e:
        logger.warning(f"注册 PerformanceFlow 失败: {e}")


# 自动注册
_auto_register()


class WorkflowRunner:
    """工作流执行器 — 连接 Runtime 与 Workflow

    使用:
        runner = WorkflowRunner()

        # 同步执行
        result = await runner.run("ui_test", requirement="测试登录功能")

        # SSE 流式执行
        async for event in runner.run_stream("ui_test", requirement="测试登录功能"):
            yield event
    """

    async def run(
        self,
        flow_name: str,
        requirement: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> WorkflowState:
        """同步执行工作流

        Args:
            flow_name: 工作流名称 (ui_test / api_test / performance_test)
            requirement: 用户需求文本
            metadata: 额外元数据
        Returns:
            最终的 WorkflowState
        """
        flow = get_flow(flow_name)
        if flow is None:
            raise ValueError(f"工作流不存在: {flow_name}, 可用: {list(_FLOW_REGISTRY.keys())}")

        state = WorkflowState.create(
            requirement=requirement,
            workflow_name=flow.name,
            metadata=metadata or {},
        )

        logger.info(f"[WorkflowRunner] 启动工作流: {flow_name} | id={state.workflow_id}")
        result = await flow.run(state)
        logger.info(
            f"[WorkflowRunner] 工作流完成: {flow_name} | "
            f"status={result.status.value} | "
            f"耗时={round((result.completed_at - result.started_at) * 1000, 1)}ms"
        )
        return result

    async def run_stream(
        self,
        flow_name: str,
        requirement: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """SSE 流式执行工作流

        Args:
            flow_name: 工作流名称
            requirement: 用户需求文本
            metadata: 额外元数据
        Yields:
            SSE 事件 dict: {event, data, ...}
        """
        flow = get_flow(flow_name)
        if flow is None:
            yield {
                "event": "error",
                "data": {"error": f"工作流不存在: {flow_name}"},
            }
            return

        state = WorkflowState.create(
            requirement=requirement,
            workflow_name=flow.name,
            metadata=metadata or {},
        )

        logger.info(f"[WorkflowRunner] 流式启动: {flow_name} | id={state.workflow_id}")

        async for event in flow.run_stream(state):
            yield event

        logger.info(f"[WorkflowRunner] 流式完成: {flow_name} | status={state.status.value}")


# 单例
_runner: Optional[WorkflowRunner] = None


def get_workflow_runner() -> WorkflowRunner:
    """获取 WorkflowRunner 单例"""
    global _runner
    if _runner is None:
        _runner = WorkflowRunner()
    return _runner
