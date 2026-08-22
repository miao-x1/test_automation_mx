"""
AutoGen Core Runtime - CollectorAgent（增强版）

核心职责：
1. 接收所有 Agent 的输出（ResultMessage / ProgressMessage / ErrorMessage / AgentEventMessage）
2. 保存到数据库（agent_event 表 + flow_result 表）
3. 记录日志（结构化日志）
4. 更新任务状态（内存中维护 TaskResult）
5. 更新 Session
6. 推送 SSE（通过 EventBus）
7. 推送 WebSocket（通过 EventBus）

设计要点：
- 任何 Agent 不得直接返回 FastAPI
- 所有 Agent 输出统一发送给 CollectorAgent
- 前端查看 AI 过程全部来自 CollectorAgent
- 所有关键节点全部记录：开始/结束/Prompt/模型/Token/耗时/错误/重试/最终结果
"""
import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from autogen_core import (
    RoutedAgent,
    message_handler,
    MessageContext,
    AgentId,
    DefaultTopicId,
    default_subscription,
)

from app.runtime.messages import (
    ResultMessage,
    ProgressMessage,
    ErrorMessage,
    AgentEventMessage,
    TaskStatusMessage,
)
from app.runtime.event_bus import get_event_bus

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  任务结果聚合                                                        #
# ------------------------------------------------------------------ #

@dataclass
class TaskResult:
    """单个任务的聚合结果"""
    task_id: str
    session_key: str = "default"
    status: str = "running"                    # running / completed / failed / timeout
    results: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    final_data: Optional[Dict[str, Any]] = None
    progress: float = 0.0
    current_step: str = ""
    current_agent: str = ""
    total_tokens: int = 0
    total_duration: float = 0.0
    _completion_event: Optional[asyncio.Event] = field(default=None, repr=False)

    def __post_init__(self):
        if self._completion_event is None:
            self._completion_event = asyncio.Event()

    def add_result(self, msg: ResultMessage) -> None:
        entry = {
            "agent_type": msg.agent_type,
            "agent_key": msg.agent_key,
            "status": msg.status,
            "data": msg.data,
            "error": msg.error,
            "duration": msg.duration,
            "timestamp": msg.timestamp,
            "is_final": msg.is_final,
        }
        if msg.status == "error":
            self.errors.append(entry)
        else:
            self.results.append(entry)

        if msg.duration:
            self.total_duration += msg.duration

        if msg.is_final:
            self.final_data = msg.data
            self.status = "failed" if msg.status == "error" else "completed"
            self.completed_at = time.time()
            self.progress = 1.0
            if self._completion_event and not self._completion_event.is_set():
                self._completion_event.set()

    def add_event(self, msg: AgentEventMessage) -> None:
        entry = {
            "event_type": msg.event_type,
            "agent_type": msg.agent_type,
            "agent_name": msg.agent_name,
            "step": msg.step,
            "status": msg.status,
            "model_name": msg.model_name,
            "prompt_tokens": msg.prompt_tokens,
            "completion_tokens": msg.completion_tokens,
            "total_tokens": msg.total_tokens,
            "duration": msg.duration,
            "message": msg.message,
            "error_message": msg.error_message,
            "is_retry": msg.is_retry,
            "is_final": msg.is_final,
            "timestamp": msg.timestamp,
        }
        self.events.append(entry)

        # 累加 Token
        if msg.total_tokens:
            self.total_tokens += msg.total_tokens

        # 更新进度
        if msg.event_type == "start":
            self.current_step = msg.step
            self.current_agent = msg.agent_name
        elif msg.event_type == "progress":
            if msg.data.get("progress"):
                self.progress = max(self.progress, msg.data["progress"])

    @property
    def is_complete(self) -> bool:
        return self.status in ("completed", "failed")

    @property
    def duration(self) -> float:
        end = self.completed_at or time.time()
        return end - self.started_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "session_key": self.session_key,
            "status": self.status,
            "results": self.results,
            "errors": self.errors,
            "events": self.events,
            "duration": self.duration,
            "total_tokens": self.total_tokens,
            "total_duration": self.total_duration,
            "progress": self.progress,
            "current_step": self.current_step,
            "current_agent": self.current_agent,
            "final_data": self.final_data,
        }

    async def wait_for_completion(self, timeout: float = 300) -> bool:
        if self._completion_event is None:
            return False
        try:
            await asyncio.wait_for(self._completion_event.wait(), timeout=timeout)
            return self.status == "completed"
        except asyncio.TimeoutError:
            self.status = "timeout"
            return False


# ------------------------------------------------------------------ #
#  CollectorAgent                                                      #
# ------------------------------------------------------------------ #

@default_subscription
class CollectorAgent(RoutedAgent):
    """
    CollectorAgent - 增强版结果收集 Agent

    接收所有 Agent 的输出，负责：
    1. 保存到数据库（agent_event 表）
    2. 记录结构化日志
    3. 更新任务状态（TaskResult）
    4. 推送 SSE（通过 EventBus）
    5. 推送 WebSocket（通过 EventBus）

    所有 Agent 不得直接返回 FastAPI，统一发送给 CollectorAgent。
    前端查看 AI 过程全部来自 CollectorAgent。
    """

    # 已完成的 TaskResult 保留时间（秒），超过后自动清理
    _RESULT_TTL_SECONDS = 300
    # 清理检查间隔（每次清理的间隔秒数）
    _CLEANUP_INTERVAL = 60

    def __init__(self) -> None:
        super().__init__("CollectorAgent - 全量事件收集器")
        self._results: Dict[str, TaskResult] = {}
        self._lock = asyncio.Lock()
        self._event_bus = get_event_bus()
        self._last_cleanup: float = time.time()

    # ------------------------------------------------------------------ #
    #  消息处理（@message_handler）                                       #
    # ------------------------------------------------------------------ #

    @message_handler
    async def handle_result(self, message: ResultMessage, ctx: MessageContext) -> None:
        """处理 ResultMessage - 最终/中间结果"""
        async with self._lock:
            if message.task_id not in self._results:
                self._results[message.task_id] = TaskResult(
                    task_id=message.task_id,
                    session_key=message.agent_key or "default",
                )
            result = self._results[message.task_id]
            result.add_result(message)

        logger.info(
            f"[Collector] Result: task={message.task_id}, "
            f"agent={message.agent_type}, status={message.status}, "
            f"final={message.is_final}, task_status={result.status}"
        )

        # 保存到数据库
        await self._save_result_to_db(message)

        # 推送 SSE / WebSocket
        await self._push_event(message.task_id, {
            "event": "result",
            "data": {
                "task_id": message.task_id,
                "agent_type": message.agent_type,
                "status": message.status,
                "data": message.data,
                "error": message.error,
                "duration": message.duration,
                "is_final": message.is_final,
            },
        })

        # 如果是最终结果，推送任务状态变更
        if message.is_final:
            await self._push_task_status(
                message.task_id,
                result.session_key,
                result.status,
                progress=1.0,
                message=f"任务{'完成' if result.status == 'completed' else '失败'}",
                data=result.to_dict(),
            )
            # 延迟清理已完成的旧结果
            await self._maybe_cleanup()

    @message_handler
    async def handle_progress(self, message: ProgressMessage, ctx: MessageContext) -> None:
        """处理 ProgressMessage - 进度推送"""
        async with self._lock:
            if message.task_id not in self._results:
                self._results[message.task_id] = TaskResult(
                    task_id=message.task_id,
                )
            result = self._results[message.task_id]
            result.progress = max(result.progress, message.progress)
            result.current_step = message.step
            result.current_agent = message.agent_type

        logger.info(
            f"[Collector] Progress: task={message.task_id}, "
            f"agent={message.agent_type}, step={message.step}, "
            f"progress={message.progress:.0%}, status={message.status}"
        )

        # 推送 SSE
        await self._push_event(message.task_id, {
            "event": "progress",
            "data": {
                "task_id": message.task_id,
                "agent_type": message.agent_type,
                "step": message.step,
                "status": message.status,
                "progress": message.progress,
                "message": message.message,
                "data": message.data,
            },
        })

    @message_handler
    async def handle_error(self, message: ErrorMessage, ctx: MessageContext) -> None:
        """处理 ErrorMessage - 错误通知"""
        logger.error(
            f"[Collector] Error: task={message.task_id}, "
            f"agent={message.agent_type}, type={message.error_type}, "
            f"msg={message.message}"
        )

        # 保存到数据库
        await self._save_error_to_db(message)

        # 推送 SSE
        await self._push_event(message.task_id, {
            "event": "error",
            "data": {
                "task_id": message.task_id,
                "agent_type": message.agent_type,
                "error_type": message.error_type,
                "message": message.message,
                "traceback": message.traceback,
            },
        })

    @message_handler
    async def handle_agent_event(self, message: AgentEventMessage, ctx: MessageContext) -> None:
        """处理 AgentEventMessage - 详细事件记录（Prompt/Model/Token/重试等）"""
        async with self._lock:
            if message.task_id not in self._results:
                self._results[message.task_id] = TaskResult(
                    task_id=message.task_id,
                    session_key=message.session_key,
                )
            result = self._results[message.task_id]
            result.add_event(message)

        # 结构化日志
        log_msg = (
            f"[Collector] Event: task={message.task_id}, "
            f"agent={message.agent_name}, type={message.event_type}, "
            f"step={message.step}, status={message.status}"
        )
        if message.model_name:
            log_msg += f", model={message.model_name}"
        if message.total_tokens:
            log_msg += f", tokens={message.total_tokens}"
        if message.duration:
            log_msg += f", duration={message.duration:.3f}s"
        if message.is_retry:
            log_msg += f", retry={message.retry_count}"

        if message.status == "error":
            logger.error(log_msg + f", error={message.error_message}")
        elif message.status == "warning":
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

        # 保存到数据库
        await self._save_event_to_db(message)

        # 推送 SSE / WebSocket
        sse_event = {
            "event": "agent_event",
            "data": {
                "task_id": message.task_id,
                "session_key": message.session_key,
                "agent_type": message.agent_type,
                "agent_name": message.agent_name,
                "event_type": message.event_type,
                "step": message.step,
                "status": message.status,
                "model_name": message.model_name,
                "prompt": message.prompt[:200] if message.prompt else "",
                "prompt_tokens": message.prompt_tokens,
                "completion_tokens": message.completion_tokens,
                "total_tokens": message.total_tokens,
                "duration": message.duration,
                "message": message.message,
                "error_message": message.error_message,
                "is_retry": message.is_retry,
                "retry_count": message.retry_count,
                "is_final": message.is_final,
                "timestamp": message.timestamp,
            },
        }
        await self._push_event(message.task_id, sse_event)

        # 如果事件标记为最终结果，推送任务状态
        if message.is_final:
            await self._push_task_status(
                message.task_id,
                message.session_key,
                "completed" if message.status != "error" else "failed",
                progress=1.0,
                message=message.message or "任务完成",
            )
            # 延迟清理已完成的旧结果
            await self._maybe_cleanup()

    # ------------------------------------------------------------------ #
    #  内存清理                                                            #
    # ------------------------------------------------------------------ #

    async def _maybe_cleanup(self) -> None:
        """定期清理已完成的旧结果，防止 _results 字典无限增长。"""
        now = time.time()
        if now - self._last_cleanup < self._CLEANUP_INTERVAL:
            return
        self._last_cleanup = now

        expired_keys = []
        async with self._lock:
            for tid, result in self._results.items():
                if result.is_complete and result.completed_at:
                    if now - result.completed_at > self._RESULT_TTL_SECONDS:
                        expired_keys.append(tid)
            for key in expired_keys:
                del self._results[key]

        if expired_keys:
            logger.info(f"[Collector] Cleaned up {len(expired_keys)} expired task results")

    # ------------------------------------------------------------------ #
    #  数据库保存                                                          #
    # ------------------------------------------------------------------ #

    async def _save_result_to_db(self, msg: ResultMessage) -> None:
        """保存 ResultMessage 到数据库"""
        try:
            from app.db.database import SessionLocal
            from app.models.agent_event import AgentEvent

            db = SessionLocal()
            try:
                event = AgentEvent(
                    task_id=msg.task_id,
                    session_key=msg.agent_key or "default",
                    agent_type=msg.agent_type,
                    agent_name=msg.agent_type,
                    event_type="result",
                    step="result",
                    status=msg.status,
                    duration=msg.duration,
                    output_json=json.dumps(msg.data, ensure_ascii=False, default=str),
                    error_message=msg.error or None,
                    message_type="ResultMessage",
                    is_final=msg.is_final,
                )
                db.add(event)
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.error(f"[Collector] Failed to save result to DB: {e}")

    async def _save_error_to_db(self, msg: ErrorMessage) -> None:
        """保存 ErrorMessage 到数据库"""
        try:
            from app.db.database import SessionLocal
            from app.models.agent_event import AgentEvent

            db = SessionLocal()
            try:
                event = AgentEvent(
                    task_id=msg.task_id,
                    session_key="default",
                    agent_type=msg.agent_type,
                    agent_name=msg.agent_type,
                    event_type="error",
                    step="error",
                    status="error",
                    message=msg.message,
                    error_message=msg.message,
                    error_traceback=msg.traceback,
                    message_type="ErrorMessage",
                )
                db.add(event)
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.error(f"[Collector] Failed to save error to DB: {e}")

    async def _save_event_to_db(self, msg: AgentEventMessage) -> None:
        """保存 AgentEventMessage 到数据库"""
        try:
            from app.db.database import SessionLocal
            from app.models.agent_event import AgentEvent

            db = SessionLocal()
            try:
                # 截断 Prompt 避免过大
                prompt_truncated = msg.prompt[:2000] if msg.prompt else None
                user_prompt_truncated = msg.user_prompt[:2000] if msg.user_prompt else None

                event = AgentEvent(
                    task_id=msg.task_id,
                    session_key=msg.session_key,
                    agent_type=msg.agent_type,
                    agent_name=msg.agent_name,
                    event_type=msg.event_type,
                    step=msg.step,
                    status=msg.status,
                    model_name=msg.model_name or None,
                    prompt=prompt_truncated,
                    user_prompt=user_prompt_truncated,
                    prompt_tokens=msg.prompt_tokens or None,
                    completion_tokens=msg.completion_tokens or None,
                    total_tokens=msg.total_tokens or None,
                    duration=msg.duration or None,
                    input_json=json.dumps(msg.data, ensure_ascii=False, default=str) if msg.data else None,
                    output_json=None,
                    message=msg.message or None,
                    error_message=msg.error_message or None,
                    error_traceback=msg.error_traceback or None,
                    retry_count=msg.retry_count,
                    is_retry=msg.is_retry,
                    message_type=msg.message_type or "AgentEventMessage",
                    is_final=msg.is_final,
                )
                db.add(event)
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.error(f"[Collector] Failed to save event to DB: {e}")

    # ------------------------------------------------------------------ #
    #  EventBus 推送（SSE / WebSocket）                                   #
    # ------------------------------------------------------------------ #

    async def _push_event(self, task_id: str, event: Dict[str, Any]) -> None:
        """通过 EventBus 推送事件到所有订阅者（SSE + WebSocket）"""
        try:
            await self._event_bus.publish(task_id, event)
        except Exception as e:
            logger.warning(f"[Collector] EventBus publish failed: {e}")

    async def _push_task_status(
        self,
        task_id: str,
        session_key: str,
        status: str,
        progress: float = 0.0,
        message: str = "",
        data: Optional[Dict] = None,
    ) -> None:
        """推送任务状态变更"""
        status_msg = TaskStatusMessage(
            task_id=task_id,
            session_key=session_key,
            status=status,
            progress=progress,
            message=message,
            data=data or {},
        )
        await self._push_event(task_id, {
            "event": "task_status",
            "data": status_msg.model_dump(),
        })

    # ------------------------------------------------------------------ #
    #  查询接口                                                           #
    # ------------------------------------------------------------------ #

    def get_result(self, task_id: str) -> Optional[TaskResult]:
        """获取任务结果。"""
        return self._results.get(task_id)

    async def wait_for_result(self, task_id: str, timeout: float = 300) -> Optional[TaskResult]:
        """
        等待任务完成并返回结果。

        如果任务尚未开始，创建占位 TaskResult 并等待完成事件。
        """
        async with self._lock:
            if task_id not in self._results:
                self._results[task_id] = TaskResult(task_id=task_id)
            result = self._results[task_id]

        if result.is_complete:
            return result
        await result.wait_for_completion(timeout=timeout)
        return result

    def list_tasks(self) -> List[str]:
        """列出所有 task_id。"""
        return list(self._results.keys())

    def clear_task(self, task_id: str) -> None:
        """清理已完成任务的结果。"""
        self._results.pop(task_id, None)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息。"""
        total = len(self._results)
        completed = sum(1 for r in self._results.values() if r.status == "completed")
        failed = sum(1 for r in self._results.values() if r.status == "failed")
        running = sum(1 for r in self._results.values() if r.status == "running")
        return {
            "total_tasks": total,
            "completed": completed,
            "failed": failed,
            "running": running,
        }

    def get_task_events(self, task_id: str) -> List[Dict[str, Any]]:
        """获取指定任务的所有事件（前端查看 AI 过程）。"""
        result = self._results.get(task_id)
        if result is None:
            return []
        return result.events

    def get_task_summary(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务摘要（前端展示）。"""
        result = self._results.get(task_id)
        if result is None:
            return None
        return {
            "task_id": result.task_id,
            "status": result.status,
            "progress": result.progress,
            "current_step": result.current_step,
            "current_agent": result.current_agent,
            "total_tokens": result.total_tokens,
            "total_duration": result.total_duration,
            "duration": result.duration,
            "results_count": len(result.results),
            "errors_count": len(result.errors),
            "events_count": len(result.events),
            "final_data": result.final_data,
        }
