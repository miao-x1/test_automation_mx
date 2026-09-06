"""
FlowNodeAdapter - 将 BaseRoutedAgent 包装为 AgentChat ChatAgent

使 GraphFlow（DiGraphBuilder）可以编排现有的 Flow Agent。

GraphFlow 要求 participants 为 ChatAgent 实例，
而现有 Flow Agent 继承 autogen_core.RoutedAgent。
此适配器桥接两者：
  - ChatAgent.on_messages() → 调用 Agent 的业务逻辑
  - Agent 业务逻辑完成后 → 返回 TextMessage

设计要点：
1. 每个 FlowNodeAdapter 包装一个 Flow Agent
2. on_messages 接收前一个节点的输出，传递给 Agent 处理
3. Agent 处理完成后，适配器返回 TextMessage
4. 支持人工反馈节点（暂停等待用户输入）
"""
import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Mapping, Optional, Sequence

from autogen_agentchat.base import ChatAgent, Response, TaskResult
from autogen_core import CancellationToken

try:
    from autogen_agentchat.messages import TextMessage, BaseChatMessage, BaseAgentEvent
except ImportError:  # autogen-agentchat < 0.7.4 部分发行版无 BaseChatMessage
    from autogen_agentchat.messages import TextMessage
    try:
        from autogen_agentchat.messages import BaseAgentEvent
    except ImportError:
        from autogen_agentchat.messages import AgentEvent as BaseAgentEvent
    try:
        from autogen_agentchat.messages import ChatMessage as BaseChatMessage
    except ImportError:
        BaseChatMessage = TextMessage  # type: ignore[misc,assignment]

logger = logging.getLogger(__name__)


class FlowNodeAdapter(ChatAgent):
    """
    将 BaseRoutedAgent 包装为 ChatAgent，用于 GraphFlow 编排。

    使用方式：
        agent = RequirementAgent()
        node = FlowNodeAdapter("Requirement", agent, step="requirement")
        builder.add_node(node)

    GraphFlow 执行时：
        on_messages() → 调用 agent.execute() → 返回 TextMessage
    """

    def __init__(
        self,
        name: str,
        wrapped_agent: Any,
        step: str = "",
        description: str = "",
    ) -> None:
        self._wrapped_agent = wrapped_agent
        self._step = step
        self._name = name
        self._description = description or f"Flow node: {name}"
        self._last_output: Optional[str] = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def produced_message_types(self) -> List[type]:
        return [TextMessage]

    async def on_messages(
        self,
        messages: Sequence[BaseChatMessage],
        cancellation_token: CancellationToken,
    ) -> Response:
        """
        处理来自前一个节点的消息。

        将上游消息内容提取为 task payload，调用 wrapped agent 处理，
        返回 TextMessage 作为输出。
        """
        # 提取上游消息内容
        input_text = ""
        if messages:
            last_msg = messages[-1]
            if isinstance(last_msg, TextMessage):
                input_text = last_msg.content
            else:
                input_text = str(last_msg)

        logger.info(f"[FlowNode:{self._name}] 收到输入, length={len(input_text)}")

        # 尝试解析 JSON payload
        try:
            payload = json.loads(input_text) if input_text else {}
        except json.JSONDecodeError:
            payload = {"text": input_text}

        # 调用 wrapped agent
        try:
            import uuid as _uuid
            from autogen_core import MessageContext, DefaultTopicId

            ctx = MessageContext(
                topic_id=DefaultTopicId(),
                sender=None,
                is_rpc=False,
                message_id=_uuid.uuid4(),
                cancellation_token=cancellation_token,
            )

            import inspect

            if hasattr(self._wrapped_agent, "execute_async"):
                # 标准代理：优先使用异步执行入口 execute_async(payload, ctx)
                result = await self._wrapped_agent.execute_async(payload, ctx)
            elif hasattr(self._wrapped_agent, "execute"):
                if inspect.iscoroutinefunction(self._wrapped_agent.execute):
                    # 旧版 Flow Agent：async execute(payload, ctx)
                    result = await self._wrapped_agent.execute(payload, ctx)
                else:
                    # 标准代理同步入口：execute(**kwargs)，将 payload 展开为关键字参数
                    result = self._wrapped_agent.execute(**payload)
            else:
                result = payload

            # 序列化结果
            if isinstance(result, dict):
                output_text = json.dumps(result, ensure_ascii=False, default=str)
            else:
                output_text = str(result)

            self._last_output = output_text

            response_msg = TextMessage(content=output_text, source=self._name)
            return Response(chat_message=response_msg)

        except Exception as e:
            logger.error(f"[FlowNode:{self._name}] 处理失败: {e}", exc_info=True)
            error_output = json.dumps({"error": str(e), "step": self._step})
            self._last_output = error_output
            response_msg = TextMessage(content=error_output, source=self._name)
            return Response(chat_message=response_msg)

    async def on_messages_stream(
        self,
        messages: Sequence[BaseChatMessage],
        cancellation_token: CancellationToken,
    ):
        """流式消息处理 - 必须 yield Response 对象"""
        response = await self.on_messages(messages, cancellation_token)
        yield response

    async def on_reset(self, cancellation_token: CancellationToken) -> None:
        """重置 Agent 状态"""
        self._last_output = None

    async def on_pause(self, cancellation_token: CancellationToken) -> None:
        """暂停"""
        pass

    async def on_resume(self, cancellation_token: CancellationToken) -> None:
        """恢复"""
        pass

    def save_state(self) -> Mapping[str, Any]:
        """保存状态"""
        return {
            "name": self._name,
            "step": self._step,
            "last_output": self._last_output,
        }

    def load_state(self, state: Mapping[str, Any]) -> None:
        """加载状态"""
        self._last_output = state.get("last_output")

    async def close(self) -> None:
        """关闭"""
        pass

    @property
    def last_output(self) -> Optional[str]:
        return self._last_output

    @property
    def wrapped_agent(self) -> Any:
        return self._wrapped_agent

    @property
    def step(self) -> str:
        return self._step
