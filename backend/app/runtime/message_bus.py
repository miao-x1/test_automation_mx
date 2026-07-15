"""
统一消息总线

所有运行时组件间的通信通过 MessageBus：
  - publish(event): 发布事件（广播给订阅者，SSE → 前端）
  - subscribe(callback): 订阅事件（用于 SSE 推送、日志、审计等）

设计原则：
  1. 编排器是唯一的发布者
  2. SSE 端点、日志、审计等是订阅者
  3. 消息总线是进程内的（不跨进程，不需要 Redis）
  4. 支持异步回调

与旧版 MessageBus（app/agent/core/message_bus.py）的关系：
  - 旧版 MessageBus 用于 Agent 间通信，新版用于编排器 → 订阅者
  - 新版更简单，只负责事件广播，不负责 Agent 间路由
  - Agent 间通信由编排器统一管理（编排器调用 AgentFactory → Agent）
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional

from app.runtime.event import TaskEvent

logger = logging.getLogger(__name__)

# 回调类型：接收 TaskEvent
EventCallback = Callable[[TaskEvent], Any]


class MessageBus:
    """
    统一消息总线

    使用方式：
        bus = get_message_bus()

        # 订阅事件
        bus.subscribe(lambda event: print(event.event))

        # 发布事件（编排器内部使用）
        bus.publish(TaskEvent(event="flow_start", ...))
    """

    def __init__(self):
        self._subscribers: List[EventCallback] = []
        self._type_subscribers: Dict[str, List[EventCallback]] = defaultdict(list)
        self._lock = asyncio.Lock()

    def subscribe(
        self,
        callback: EventCallback,
        event_type: Optional[str] = None,
    ) -> None:
        """订阅事件

        Args:
            callback: 回调函数（同步或异步）
            event_type: 只订阅特定事件类型（None = 订阅所有）
        """
        if event_type:
            self._type_subscribers[event_type].append(callback)
        else:
            self._subscribers.append(callback)
        logger.debug(
            f"MessageBus | 新增订阅 | "
            f"type={'all' if event_type is None else event_type} | "
            f"total={len(self._subscribers) + sum(len(v) for v in self._type_subscribers.values())}"
        )

    def unsubscribe(self, callback: EventCallback) -> None:
        """取消订阅"""
        if callback in self._subscribers:
            self._subscribers.remove(callback)
        for subs in self._type_subscribers.values():
            if callback in subs:
                subs.remove(callback)

    async def publish(self, event: TaskEvent) -> None:
        """发布事件（异步广播给所有订阅者）

        Args:
            event: TaskEvent 实例
        """
        # 全局订阅者
        callbacks = list(self._subscribers)
        # 类型特定订阅者
        callbacks.extend(self._type_subscribers.get(event.event, []))
        # 也通知 "all" 类型的订阅者
        callbacks.extend(self._type_subscribers.get("*", []))

        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event)
                else:
                    callback(event)
            except Exception as e:
                logger.warning(
                    f"MessageBus | 订阅者回调异常 | "
                    f"event={event.event} | error={e}",
                    exc_info=True,
                )

    def clear(self) -> None:
        """清空所有订阅（用于测试）"""
        self._subscribers.clear()
        self._type_subscribers.clear()


# ── 单例 ──

_bus: Optional[MessageBus] = None


def get_message_bus() -> MessageBus:
    """获取全局 MessageBus 单例"""
    global _bus
    if _bus is None:
        _bus = MessageBus()
    return _bus


def reset_message_bus() -> None:
    """重置 MessageBus（用于测试）"""
    global _bus
    _bus = None
