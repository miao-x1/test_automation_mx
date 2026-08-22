"""
Workflow Nodes — Graph 节点实现

每个节点遵循统一接口:
    输入: 从 WorkflowState 读取数据 (input_keys)
    处理: 执行业务逻辑 (process)
    输出: 写入 WorkflowState (output_key)

节点类型:
    AgentNode  — 包装 Agent, 通过 AgentFactory 创建, 不直接 new
    FilterNode — 数据过滤/转换/条件判断节点
    RouterNode — 路由节点, 根据条件选择下一步
"""
import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

from app.workflow.state import NodeResult, NodeStatus, WorkflowState

logger = logging.getLogger(__name__)


class WorkflowNode(ABC):
    """Graph 节点基类

    每个节点:
        - 声明 input_keys: 需要从 state 中读取的数据键
        - 声明 output_key:  输出结果存入 state 的键
        - 实现 process():   核心处理逻辑
    """

    def __init__(
        self,
        name: str,
        input_keys: Optional[List[str]] = None,
        output_key: Optional[str] = None,
        description: str = "",
    ) -> None:
        self.name = name
        self.input_keys = input_keys or []
        self.output_key = output_key or name
        self.description = description

    @abstractmethod
    async def process(self, state: WorkflowState) -> Dict[str, Any]:
        """处理逻辑 — 从 state 读取输入, 返回输出 dict

        Args:
            state: 工作流共享状态
        Returns:
            输出 dict, 会被存入 state.intermediate[self.output_key]
        """
        raise NotImplementedError

    def build_payload(self, state: WorkflowState) -> Dict[str, Any]:
        """从 state 中按 input_keys 收集输入数据"""
        payload: Dict[str, Any] = {}
        # 始终带上原始需求
        payload["requirement"] = state.requirement
        # 带上元数据
        for k, v in state.metadata.items():
            payload.setdefault(k, v)
        # 按 input_keys 从中间结果收集
        for key in self.input_keys:
            val = state.get(key)
            if val is not None:
                payload[key] = val
        return payload

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name}>"


# ================================================================== #
#  AgentNode — 包装 Agent 的节点                                       #
# ================================================================== #

class AgentNode(WorkflowNode):
    """Agent 节点 — 通过 AgentFactory 创建 Agent 并执行

    设计:
        1. 不直接 new Agent, 通过 AgentFactory.create()
        2. 支持同步 execute() 和异步 execute_async() 两种调用方式
        3. 执行结果自动存入 state
    """

    def __init__(
        self,
        name: str,
        agent_name: str,
        action: str = "execute",
        input_keys: Optional[List[str]] = None,
        output_key: Optional[str] = None,
        timeout: float = 120.0,
        description: str = "",
    ) -> None:
        super().__init__(name, input_keys, output_key, description)
        self.agent_name = agent_name
        self.action = action
        self.timeout = timeout

    async def process(self, state: WorkflowState) -> Dict[str, Any]:
        payload = self.build_payload(state)
        payload["task_id"] = state.workflow_id

        logger.info(f"[Node:{self.name}] 创建 Agent: {self.agent_name}")

        # 通过 AgentFactory 创建 (不直接 new)
        from app.agents.factory import AgentFactory
        agent = await AgentFactory.create(
            name=self.agent_name,
            runtime=None,
            session_key=state.workflow_id,
        )

        # 优先调用 execute_async (GraphFlow 兼容入口)
        result: Any = None
        exec_async = getattr(agent, "execute_async", None)
        if exec_async is not None and (asyncio.iscoroutinefunction(exec_async) or asyncio.iscoroutine(getattr(agent, "execute_async", None))):
            result = await asyncio.wait_for(
                exec_async(payload, ctx=None),
                timeout=self.timeout,
            )
        elif hasattr(agent, "execute"):
            raw = agent.execute(**payload)
            if asyncio.iscoroutine(raw):
                raw = await asyncio.wait_for(raw, timeout=self.timeout)
            result = raw
        else:
            raise RuntimeError(
                f"Agent {self.agent_name} 没有实现 execute() 或 execute_async()"
            )

        if not isinstance(result, dict):
            result = {"result": result}

        status = result.get("status", "success")
        if status == "error":
            raise RuntimeError(
                f"Agent {self.agent_name} 返回错误: {result.get('message', '未知错误')}"
            )

        logger.info(f"[Node:{self.name}] Agent 执行完成, 输出键: {list(result.keys())}")
        return result


# ================================================================== #
#  FilterNode — 数据过滤/转换节点                                       #
# ================================================================== #

class FilterNode(WorkflowNode):
    """过滤器节点 — 数据格式转换/条件检查

    用于 Agent 之间的数据适配:
        - 提取上游输出中的特定字段
        - 转换数据格式适配下游 Agent
        - 条件检查 (如 RAG 结果为空时跳过用例生成)
    """

    def __init__(
        self,
        name: str,
        filter_func: Callable[[WorkflowState], Dict[str, Any]],
        input_keys: Optional[List[str]] = None,
        output_key: Optional[str] = None,
        description: str = "",
    ) -> None:
        super().__init__(name, input_keys, output_key, description)
        self.filter_func = filter_func

    async def process(self, state: WorkflowState) -> Dict[str, Any]:
        result = self.filter_func(state)
        if not isinstance(result, dict):
            result = {"result": result}
        logger.info(f"[Filter:{self.name}] 数据过滤完成, 输出键: {list(result.keys())}")
        return result


# ================================================================== #
#  RouterNode — 条件路由节点                                            #
# ================================================================== #

class RouterNode(WorkflowNode):
    """路由节点 — 根据条件选择下一步执行路径

    返回值包含 __route__ 字段, 指定下一个要执行的节点名
    """

    def __init__(
        self,
        name: str,
        routes: Dict[str, Callable[[WorkflowState], bool]],
        default_route: Optional[str] = None,
        description: str = "",
    ) -> None:
        super().__init__(name, description=description)
        self.routes = routes
        self.default_route = default_route

    async def process(self, state: WorkflowState) -> Dict[str, Any]:
        for target, condition in self.routes.items():
            if condition(state):
                logger.info(f"[Router:{self.name}] 路由到: {target}")
                return {"__route__": target}
        if self.default_route:
            logger.info(f"[Router:{self.name}] 默认路由到: {self.default_route}")
            return {"__route__": self.default_route}
        logger.info(f"[Router:{self.name}] 无匹配路由, 结束")
        return {"__route__": None}
