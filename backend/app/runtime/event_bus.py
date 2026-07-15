"""
EventBus - 事件总线

负责：
1. 收集 CollectorAgent 推送的事件
2. 通过 SSE 推送到前端
3. 通过 WebSocket 推送到前端
4. 支持按 task_id / session_key 订阅

设计要点：
- 每个 task_id 有独立的 asyncio.Queue
- SSE 端点从队列消费事件
- WebSocket 端点也从队列消费
- 支持多个订阅者同时监听同一 task_id
"""
import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class Subscriber:
    """事件订阅者"""
    subscriber_id: str
    task_id: str
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=1000))
    created_at: float = field(default_factory=lambda: datetime.now().timestamp())


class EventBus:
    """
    事件总线 - 统一 SSE / WebSocket 事件推送

    使用方式：
        bus = get_event_bus()

        # SSE 端点订阅
        async for event in bus.subscribe(task_id):
            yield event

        # CollectorAgent 推送事件
        bus.publish(task_id, {"event": "progress", "data": {...}})

        # WebSocket 推送
        bus.publish(task_id, {"event": "ws_message", "data": {...}})
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, Set[Subscriber]] = {}
        self._lock = asyncio.Lock()
        self._counter = 0

    async def subscribe(self, task_id: str, subscriber_id: str = "") -> Subscriber:
        """订阅指定 task_id 的事件流"""
        if not subscriber_id:
            self._counter += 1
            subscriber_id = f"sub_{self._counter}"

        sub = Subscriber(subscriber_id=subscriber_id, task_id=task_id)

        async with self._lock:
            if task_id not in self._subscribers:
                self._subscribers[task_id] = set()
            self._subscribers[task_id].add(sub)

        logger.info(f"[EventBus] Subscriber {subscriber_id} subscribed to task={task_id}")
        return sub

    async def unsubscribe(self, subscriber: Subscriber) -> None:
        """取消订阅"""
        async with self._lock:
            task_id = subscriber.task_id
            if task_id in self._subscribers:
                self._subscribers[task_id].discard(subscriber)
                if not self._subscribers[task_id]:
                    del self._subscribers[task_id]
        logger.info(f"[EventBus] Subscriber {subscriber.subscriber_id} unsubscribed from task={subscriber.task_id}")

    async def publish(self, task_id: str, event: Dict[str, Any]) -> None:
        """向指定 task_id 的所有订阅者推送事件"""
        async with self._lock:
            subs = self._subscribers.get(task_id, set()).copy()

        if not subs:
            return

        event_str = json.dumps(event, ensure_ascii=False, default=str)

        for sub in subs:
            try:
                if not sub.queue.full():
                    sub.queue.put_nowait(event_str)
                else:
                    logger.warning(f"[EventBus] Queue full for {sub.subscriber_id}, dropping event")
            except Exception as e:
                logger.error(f"[EventBus] Failed to publish to {sub.subscriber_id}: {e}")

    async def publish_to_session(self, session_key: str, event: Dict[str, Any]) -> None:
        """向指定 session_key 的所有订阅者推送事件（WebSocket 场景）"""
        async with self._lock:
            # 找到该 session 下所有 task 的订阅者
            all_subs: Set[Subscriber] = set()
            for tid, subs in self._subscribers.items():
                all_subs.update(subs)

        event_str = json.dumps(event, ensure_ascii=False, default=str)

        for sub in all_subs:
            try:
                if not sub.queue.full():
                    sub.queue.put_nowait(event_str)
            except Exception as e:
                logger.error(f"[EventBus] Failed to publish to {sub.subscriber_id}: {e}")

    def get_subscriber_count(self, task_id: str) -> int:
        """获取指定 task_id 的订阅者数量"""
        return len(self._subscribers.get(task_id, set()))

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_tasks": len(self._subscribers),
            "total_subscribers": sum(len(s) for s in self._subscribers.values()),
            "tasks": {tid: len(subs) for tid, subs in self._subscribers.items()},
        }

    async def cleanup_task(self, task_id: str) -> None:
        """清理指定 task_id 的所有订阅者"""
        async with self._lock:
            subs = self._subscribers.pop(task_id, set())
        for sub in subs:
            try:
                sub.queue.put_nowait("__DONE__")
            except Exception:
                pass
        logger.info(f"[EventBus] Cleaned up task={task_id}, removed {len(subs)} subscribers")


# ------------------------------------------------------------------ #
#  单例                                                                #
# ------------------------------------------------------------------ #

_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """获取 EventBus 单例"""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus
