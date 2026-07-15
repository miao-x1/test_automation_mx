"""
AutoGen Core Runtime - Legacy Agent 适配器

LegacyAgentAdapter 将现有的非 RoutedAgent Agent 包装为 AutoGen Core 兼容的 Agent。

现有 Agent 的特点：
1. 继承旧的 BaseAgent（app.agent.base）或 NewBaseAgent（app.agent.base_agent）
2. 有 execute(**kwargs) 方法（同步或异步）
3. 通过 MessageBus 或直接方法调用通信

适配器做的工作：
1. 接收 TaskMessage / AgentRequest
2. 调用旧 Agent 的 execute() 或指定方法
3. 将结果包装为 ResultMessage 发送给 CollectorAgent
"""
import asyncio
import logging
import time
import traceback
from typing import Any, Dict, Optional, Type

from autogen_core import (
    RoutedAgent,
    message_handler,
    MessageContext,
    AgentId,
    DefaultTopicId,
    default_subscription,
)

from app.runtime.messages import (
    TaskMessage,
    AgentRequest,
    AgentResponse,
    ProgressMessage,
    ResultMessage,
)

logger = logging.getLogger(__name__)


@default_subscription
class LegacyAgentAdapter(RoutedAgent):
    """
    适配器：将旧版 Agent 包装为 AutoGen Core 兼容 Agent

    工作原理：
    1. 接收 TaskMessage → 调用旧 Agent 的 execute(**payload) → 发送 ResultMessage
    2. 接收 AgentRequest → 调用旧 Agent 的指定方法 → 返回 AgentResponse
    3. 旧 Agent 间不再直接 new 对方，而是通过消息机制
    """

    def __init__(self, agent_class: Type, **init_kwargs) -> None:
        super().__init__(f"LegacyAdapter for {agent_class.__name__}")
        self._agent_class = agent_class
        self._init_kwargs = init_kwargs
        self._agent_instance: Optional[Any] = None
        self._start_time: Optional[float] = None

    def _get_agent(self) -> Any:
        """懒加载创建旧 Agent 实例。"""
        if self._agent_instance is None:
            try:
                self._agent_instance = self._agent_class(**self._init_kwargs)
                logger.info(f"[Adapter] Created instance: {self._agent_class.__name__}")
            except Exception as e:
                logger.error(f"[Adapter] Failed to create {self._agent_class.__name__}: {e}")
                raise
        return self._agent_instance

    @message_handler
    async def handle_task(self, message: TaskMessage, ctx: MessageContext) -> None:
        """处理 TaskMessage：调用旧 Agent 的 execute()。"""
        self._start_time = time.time()
        task_id = message.task_id
        action = message.action or "execute"
        logger.info(f"[Adapter:{self._agent_class.__name__}] Task: {task_id}, action: {action}")

        try:
            # 发布进度
            await self._publish_progress(
                task_id=task_id,
                step=f"{self._agent_class.__name__} 启动",
                status="running",
                progress=0.0,
                message=f"开始处理: {action}",
            )

            agent = self._get_agent()
            result = await self._invoke_method(agent, action, message.payload)

            duration = time.time() - self._start_time

            # 发布完成进度
            await self._publish_progress(
                task_id=task_id,
                step=f"{self._agent_class.__name__} 完成",
                status="completed",
                progress=1.0,
                message=f"处理完成: {action}",
                data={"duration": duration},
            )

            # 投递结果
            await self._send_result(
                task_id=task_id,
                data=result if isinstance(result, dict) else {"result": result},
                duration=duration,
            )

        except Exception as e:
            duration = time.time() - (self._start_time or time.time())
            error_tb = traceback.format_exc()
            logger.error(f"[Adapter:{self._agent_class.__name__}] Task failed: {e}\n{error_tb}")

            await self._publish_progress(
                task_id=task_id,
                step=f"{self._agent_class.__name__} 错误",
                status="failed",
                progress=1.0,
                message=str(e),
            )

            await self._send_result(
                task_id=task_id,
                status="error",
                error=str(e),
                data={"traceback": error_tb},
                duration=duration,
            )

    @message_handler
    async def handle_request(self, message: AgentRequest, ctx: MessageContext) -> AgentResponse:
        """处理 AgentRequest：调用旧 Agent 的指定方法并返回响应。"""
        self._start_time = time.time()
        action = message.target_action or "execute"
        logger.info(f"[Adapter:{self._agent_class.__name__}] Request: action={action}")

        try:
            agent = self._get_agent()
            result = await self._invoke_method(agent, action, message.payload)
            duration = time.time() - self._start_time

            return AgentResponse(
                request_id=message.request_id,
                sender_type=self._agent_class.__name__,
                status="success",
                data=result if isinstance(result, dict) else {"result": result},
                duration=duration,
            )

        except Exception as e:
            duration = time.time() - (self._start_time or time.time())
            logger.error(f"[Adapter:{self._agent_class.__name__}] Request failed: {e}")
            return AgentResponse(
                request_id=message.request_id,
                sender_type=self._agent_class.__name__,
                status="error",
                error=str(e),
                duration=duration,
            )

    async def _invoke_method(self, agent: Any, method_name: str, payload: Dict[str, Any]) -> Any:
        """
        调用旧 Agent 的方法

        优先级：
        1. 如果 method_name == "execute"，调用 agent.execute(**payload)
        2. 否则尝试调用 agent.{method_name}(**payload)
        3. 如果方法不存在，回退到 execute(**payload)

        支持同步和异步方法。
        """
        method = getattr(agent, method_name, None)
        if method is None and method_name != "execute":
            # 回退到 execute
            method = getattr(agent, "execute", None)

        if method is None:
            raise ValueError(
                f"Agent {self._agent_class.__name__} has no method '{method_name}' or 'execute'"
            )

        # 调用方法
        if asyncio.iscoroutinefunction(method):
            return await method(**payload)
        else:
            # 同步方法可能较慢，在线程池中运行
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: method(**payload))

    async def _publish_progress(self, **kwargs) -> None:
        """发布进度消息。"""
        msg = ProgressMessage(**kwargs)
        try:
            await self.publish_message(msg, DefaultTopicId())
        except Exception as e:
            logger.warning(f"[Adapter:{self._agent_class.__name__}] publish_progress failed: {e}")

    async def _send_result(self, task_id: str, data: Dict = None, status: str = "success",
                           error: str = None, duration: float = 0.0) -> None:
        """发送结果给 CollectorAgent。"""
        msg = ResultMessage(
            task_id=task_id,
            agent_type=self._agent_class.__name__,
            agent_key=self.id.key if self.id else "default",
            status=status,
            data=data or {},
            error=error or "",
            duration=duration,
        )
        try:
            collector_id = AgentId("collector", self.id.key if self.id else "default")
            await self.send_message(msg, collector_id)
        except Exception as e:
            logger.warning(f"[Adapter:{self._agent_class.__name__}] send_result failed: {e}")
