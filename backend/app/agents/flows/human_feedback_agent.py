"""
HumanFeedbackAgent - 人工反馈节点

在 GraphFlow 中作为独立节点存在。
接收前序节点（如 CaseReview）的输出，
暂停等待人工反馈，收到后传递给后续节点（如 ScriptGenerate）。

支持模式：
1. auto: 自动通过（用于测试，不等待人工）
2. manual: 等待人工反馈（通过 EventBus 或 DB 轮询获取）
3. timeout: 超时后自动通过

人工反馈通过 CollectorAgent + EventBus 推送到前端，
前端提交反馈后通过 API 写入，本节点轮询获取。
"""
import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Mapping, Optional, Sequence

from autogen_agentchat.base import ChatAgent, Response
from autogen_agentchat.messages import TextMessage
from autogen_core import CancellationToken

from app.runtime.event_bus import get_event_bus

logger = logging.getLogger(__name__)


class HumanFeedbackAgent(ChatAgent):
    """
    人工反馈节点

    GraphFlow 执行到此节点时：
    1. 将前序输出推送给前端（通过 EventBus）
    2. 等待人工反馈（auto 模式自动通过）
    3. 将反馈附加到输出，传递给后续节点
    """

    def __init__(
        self,
        name: str = "HumanFeedback",
        description: str = "人工反馈节点，等待用户确认或修改建议",
        mode: str = "auto",               # auto / manual / timeout
        timeout: float = 300.0,            # manual 模式超时时间
        feedback_key: str = "human_feedback",
    ) -> None:
        self._name = name
        self._description = description
        self._mode = mode
        self._timeout = timeout
        self._feedback_key = feedback_key
        self._pending_feedback: Dict[str, asyncio.Future] = {}

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
        messages: Sequence,
        cancellation_token: CancellationToken,
    ) -> Response:
        """处理前序节点输出，等待人工反馈"""
        # 提取上游输入
        input_text = ""
        if messages:
            last_msg = messages[-1]
            if isinstance(last_msg, TextMessage):
                input_text = last_msg.content
            else:
                input_text = str(last_msg)

        try:
            input_data = json.loads(input_text) if input_text else {}
        except json.JSONDecodeError:
            input_data = {"text": input_text}

        logger.info(f"[HumanFeedback] 收到输入, mode={self._mode}")

        # 生成反馈请求 ID
        feedback_id = str(uuid.uuid4())
        task_id = input_data.get("task_id", feedback_id)

        # 推送等待反馈事件
        await self._push_feedback_request(task_id, input_data)

        feedback = None

        if self._mode == "auto":
            # 自动通过
            feedback = {
                "approved": True,
                "comments": "自动通过（auto 模式）",
                "modifications": {},
            }
            logger.info(f"[HumanFeedback] Auto mode, auto-approve")

        elif self._mode == "manual":
            # 等待人工反馈
            logger.info(f"[HumanFeedback] Waiting for human feedback (timeout={self._timeout}s)...")
            feedback = await self._wait_for_feedback(task_id, feedback_id, self._timeout)

            if feedback is None:
                # 超时
                feedback = {
                    "approved": True,
                    "comments": "超时自动通过",
                    "modifications": {},
                    "timeout": True,
                }
                logger.warning(f"[HumanFeedback] Timeout, auto-approve")

        elif self._mode == "timeout":
            # 短超时模式
            feedback = await self._wait_for_feedback(task_id, feedback_id, min(self._timeout, 30))
            if feedback is None:
                feedback = {
                    "approved": True,
                    "comments": "超时自动通过",
                    "modifications": {},
                    "timeout": True,
                }

        # 合并反馈到输出
        output_data = dict(input_data)
        output_data[self._feedback_key] = feedback
        output_data["feedback_id"] = feedback_id

        output_text = json.dumps(output_data, ensure_ascii=False, default=str)

        # 推送反馈完成事件
        await self._push_feedback_received(task_id, feedback)

        response_msg = TextMessage(content=output_text, source=self._name)
        return Response(chat_message=response_msg)

    async def on_messages_stream(
        self,
        messages: Sequence,
        cancellation_token: CancellationToken,
    ):
        response = await self.on_messages(messages, cancellation_token)
        yield response

    async def on_reset(self, cancellation_token: CancellationToken) -> None:
        self._pending_feedback.clear()

    async def on_pause(self, cancellation_token: CancellationToken) -> None:
        pass

    async def on_resume(self, cancellation_token: CancellationToken) -> None:
        pass

    def save_state(self) -> Mapping[str, Any]:
        return {"name": self._name, "mode": self._mode}

    def load_state(self, state: Mapping[str, Any]) -> None:
        pass

    async def close(self) -> None:
        pass

    # ------------------------------------------------------------------ #
    #  人工反馈等待                                                        #
    # ------------------------------------------------------------------ #

    async def _wait_for_feedback(
        self, task_id: str, feedback_id: str, timeout: float
    ) -> Optional[Dict]:
        """
        等待人工反馈

        通过轮询 CollectorAgent 获取反馈数据。
        前端提交反馈后，通过 API 写入 CollectorAgent 的事件中。
        """
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._pending_feedback[feedback_id] = future

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            return None
        finally:
            self._pending_feedback.pop(feedback_id, None)

    def submit_feedback(self, feedback_id: str, feedback: Dict) -> bool:
        """
        提交人工反馈（由 FastAPI 调用）

        返回 True 表示成功交付，False 表示无等待中的请求。
        """
        future = self._pending_feedback.get(feedback_id)
        if future is None or future.done():
            return False

        if not future.cancelled():
            future.set_result(feedback)
        return True

    async def _push_feedback_request(self, task_id: str, input_data: Dict) -> None:
        """推送反馈请求到前端"""
        bus = get_event_bus()
        await bus.publish(task_id, {
            "event": "human_feedback_required",
            "data": {
                "task_id": task_id,
                "input": input_data,
                "message": "等待人工反馈确认...",
            },
        })

    async def _push_feedback_received(self, task_id: str, feedback: Dict) -> None:
        """推送反馈已收到"""
        bus = get_event_bus()
        await bus.publish(task_id, {
            "event": "human_feedback_received",
            "data": {
                "task_id": task_id,
                "feedback": feedback,
                "message": "人工反馈已收到",
            },
        })
