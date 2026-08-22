"""
Response Collector - 响应收集器

核心职责:
    1. 收集所有 Agent 执行过程中产生的事件
    2. 按 task_id 聚合事件
    3. 通过 StreamPublisher 推送 SSE / WebSocket
    4. 持久化事件到数据库 (agent_event 表)
    5. 提供事件订阅与查询接口

事件类型:
    - start:    Agent 开始执行
    - progress: 进度更新
    - prompt:   LLM 调用 (含 token/耗时)
    - end:      Agent 执行完成
    - error:    错误
    - retry:    重试
    - final:    最终结果

数据流:
    AgentWorker → Collector.collect(task_id) → 事件列表
                  Collector.subscribe(task_id) → StreamPublisher → SSE/WebSocket
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ResponseCollector:
    """响应收集器

    每个任务的事件按 task_id 聚合,任务完成后事件保留可查询。
    """

    def __init__(self, stream_publisher: Any = None) -> None:
        self._stream_publisher = stream_publisher
        # task_id → 事件列表
        self._events: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        # task_id → asyncio.Queue (用于实时订阅)
        self._subscribers: Dict[str, List[asyncio.Queue]] = defaultdict(list)
        # task_id → 完成事件
        self._completion_events: Dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()
        # 保留最近 N 个已完成任务的事件 (LRU)
        self._max_history = 1000
        self._completed_tasks: List[str] = []  # 按 FIFO 顺序

    def set_stream_publisher(self, publisher: Any) -> None:
        """注入 StreamPublisher"""
        self._stream_publisher = publisher
        logger.info(f"[ResponseCollector] StreamPublisher 注入: {type(publisher).__name__}")

    # ----------------------------------------------------------
    # 事件收集
    # ----------------------------------------------------------

    async def record(self, task_id: str, event: Dict[str, Any]) -> None:
        """记录单个事件

        Args:
            task_id: 任务 ID
            event: 事件字典 (type, step, message, data, timestamp...)
        """
        event.setdefault("timestamp", time.time())
        event.setdefault("task_id", task_id)

        async with self._lock:
            self._events[task_id].append(event)

        # 推送给实时订阅者
        await self._notify_subscribers(task_id, event)

        # 推送到 StreamPublisher (SSE/WebSocket)
        if self._stream_publisher:
            try:
                await self._stream_publisher.publish(task_id, event)
            except Exception as e:
                logger.warning(f"[ResponseCollector] StreamPublisher 推送失败: {e}")

        # 持久化到数据库
        await self._persist_event(task_id, event)

    async def record_batch(self, task_id: str, events: List[Dict[str, Any]]) -> None:
        """批量记录事件"""
        for event in events:
            await self.record(task_id, event)

    async def collect(self, task_id: str) -> List[Dict[str, Any]]:
        """收集任务的所有事件 (任务完成后调用)

        Args:
            task_id: 任务 ID

        Returns:
            事件列表 (按时间排序)
        """
        async with self._lock:
            events = list(self._events.get(task_id, []))

        # 标记任务完成
        await self._mark_completed(task_id)

        logger.info(
            f"[ResponseCollector] 收集完成 | task_id={task_id} | "
            f"events={len(events)}"
        )
        return events

    # ----------------------------------------------------------
    # 订阅 / 查询
    # ----------------------------------------------------------

    async def subscribe(
        self,
        task_id: str,
        timeout: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """订阅任务事件 (实时)

        阻塞直到任务完成或超时,返回所有事件。

        Args:
            task_id: 任务 ID
            timeout: 超时 (秒)

        Returns:
            事件列表
        """
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._subscribers[task_id].append(queue)
            # 获取已有事件 (不重复)
            existing = list(self._events.get(task_id, []))
            completion_event = self._completion_events.get(task_id)
            if completion_event is None:
                completion_event = asyncio.Event()
                self._completion_events[task_id] = completion_event

        # 先推送已有事件
        for event in existing:
            await queue.put(event)

        events: List[Dict[str, Any]] = []
        try:
            while True:
                if completion_event.is_set() and queue.empty():
                    break
                try:
                    event = await asyncio.wait_for(
                        queue.get(),
                        timeout=timeout or 1.0,
                    )
                    events.append(event)
                except asyncio.TimeoutError:
                    if completion_event.is_set():
                        break
        finally:
            async with self._lock:
                if queue in self._subscribers[task_id]:
                    self._subscribers[task_id].remove(queue)

        return events

    async def get_events(
        self,
        task_id: str,
        event_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """查询任务事件"""
        async with self._lock:
            events = list(self._events.get(task_id, []))
        if event_type:
            events = [e for e in events if e.get("type") == event_type]
        return events[:limit]

    async def list_tasks(self, limit: int = 50) -> List[str]:
        """列出有事件的 task_id"""
        async with self._lock:
            return list(self._events.keys())[:limit]

    # ----------------------------------------------------------
    # 内部: 通知订阅者
    # ----------------------------------------------------------

    async def _notify_subscribers(self, task_id: str, event: Dict[str, Any]) -> None:
        """通知所有实时订阅者"""
        async with self._lock:
            subscribers = list(self._subscribers.get(task_id, []))
        for queue in subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(f"[ResponseCollector] 订阅队列已满: {task_id}")

    async def _mark_completed(self, task_id: str) -> None:
        """标记任务完成"""
        async with self._lock:
            event = self._completion_events.get(task_id)
            if event is None:
                event = asyncio.Event()
                self._completion_events[task_id] = event
            event.set()

            # LRU 清理
            if task_id not in self._completed_tasks:
                self._completed_tasks.append(task_id)
                if len(self._completed_tasks) > self._max_history:
                    old_task = self._completed_tasks.pop(0)
                    self._events.pop(old_task, None)
                    self._subscribers.pop(old_task, None)
                    self._completion_events.pop(old_task, None)

    # ----------------------------------------------------------
    # 内部: 持久化
    # ----------------------------------------------------------

    async def _persist_event(self, task_id: str, event: Dict[str, Any]) -> None:
        """持久化事件到数据库

        复用现有的 agent_event 表。
        """
        try:
            from app.db.database import SessionLocal
            from app.models.agent_event import AgentEvent

            db = SessionLocal()
            try:
                record = AgentEvent(
                    task_id=task_id,
                    session_key=event.get("session_key", "default"),
                    agent_type=event.get("agent_type", ""),
                    agent_name=event.get("agent_name", ""),
                    event_type=event.get("type", "info"),
                    step=event.get("step", ""),
                    status=event.get("status", "info"),
                    message=event.get("message", ""),
                    model_name=event.get("model_name"),
                    prompt_tokens=event.get("prompt_tokens"),
                    completion_tokens=event.get("completion_tokens"),
                    total_tokens=event.get("total_tokens"),
                    duration=event.get("duration"),
                    input_json=str(event.get("data", {}))[:2000] if event.get("data") else None,
                    error_message=event.get("error_message"),
                    message_type=event.get("message_type", "AgentEvent"),
                    is_final=event.get("is_final", False),
                )
                db.add(record)
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.debug(f"[ResponseCollector] 持久化失败 (忽略): {e}")

    # ----------------------------------------------------------
    # 统计
    # ----------------------------------------------------------

    async def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        async with self._lock:
            return {
                "active_tasks": len(self._events),
                "completed_tasks": len(self._completed_tasks),
                "total_subscribers": sum(
                    len(subs) for subs in self._subscribers.values()
                ),
                "max_history": self._max_history,
                "stream_publisher": (
                    type(self._stream_publisher).__name__
                    if self._stream_publisher else None
                ),
            }


# ============================================================
# 单例
# ============================================================

_collector: Optional[ResponseCollector] = None


def get_response_collector() -> ResponseCollector:
    """获取全局 ResponseCollector 单例"""
    global _collector
    if _collector is None:
        _collector = ResponseCollector()
        logger.info("[ResponseCollector] 单例创建")
    return _collector
