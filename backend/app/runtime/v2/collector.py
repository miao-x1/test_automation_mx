"""
Runtime v2 — Response Collector

职责:
    1. 收集多个 Agent 执行事件
    2. 统一结果结构 (TaskResult)
    3. SSE/WebSocket 实时推送

核心设计:
    - ResponseCollector: 事件聚合 + 历史存储
    - StreamPublisher: SSE/WebSocket 客户端管理 + 推送
    - record() 是唯一入口: Worker/Dispatcher 调用此方法推送事件
    - publish() 自动触发 SSE/WebSocket 推送
    - sse_stream() 是 async generator, 供 API 端点 yield

使用方式:
    from app.runtime.v2.collector import get_collector, get_publisher

    # API 端点 SSE
    @router.get("/stream/{task_id}")
    async def stream(task_id: str):
        async def gen():
            async for event in get_publisher().sse_stream(task_id):
                yield f"data: {json.dumps(event)}\\n\\n"
        return EventSourceResponse(gen())

    # Worker 推送事件
    await get_collector().record(task_id, {"event": "progress", ...})
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from typing import Any, AsyncGenerator, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ============================================================
# Response Collector — 事件收集器
# ============================================================

class ResponseCollector:
    """事件收集器

    职责:
        1. record(task_id, event): 记录事件 (唯一入口)
        2. collect(task_id): 获取所有事件 (任务结束时调用)
        3. 自动推送给 StreamPublisher
        4. LRU 历史存储 (防止内存无限增长)

    特性:
        - record() 是 async, 支持 Worker 异步调用
        - 内部带 _lock 保证线程安全
        - 历史限制 1000 个 task, 每个 task 最多 500 事件
    """

    # 历史存储限制
    _MAX_TASKS = 1000
    _MAX_EVENTS_PER_TASK = 500

    def __init__(self) -> None:
        self._events: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._completed: Set[str] = set()
        self._lock = asyncio.Lock()
        self._publisher: Optional[StreamPublisher] = None
        self._stats = {
            "events_recorded": 0,
            "tasks_collected": 0,
        }

    # ---- 依赖注入 ----

    def set_stream_publisher(self, publisher: "StreamPublisher") -> None:
        """注入 StreamPublisher"""
        self._publisher = publisher
        logger.info("ResponseCollector 已绑定 StreamPublisher")

    # ---- 记录事件 ----

    async def record(self, task_id: str, event: Dict[str, Any]) -> None:
        """记录事件 (唯一入口)

        流程:
            1. 存入内存历史
            2. 推送给 StreamPublisher (SSE/WebSocket)
        """
        async with self._lock:
            events = self._events[task_id]

            # 限制单个 task 事件数
            if len(events) >= self._MAX_EVENTS_PER_TASK:
                events.pop(0)  # 移除最早的

            events.append(event)
            self._stats["events_recorded"] += 1

            # LRU: 超过最大 task 数时移除最早的
            if len(self._events) > self._MAX_TASKS:
                oldest = next(iter(self._events))
                if oldest != task_id:
                    self._events.pop(oldest, None)
                    self._completed.discard(oldest)

        # 推送给 StreamPublisher
        if self._publisher:
            try:
                await self._publisher.publish(task_id, event)
            except Exception as e:
                logger.warning(f"推送事件失败: {task_id} | {e}")

    # ---- 收集结果 ----

    def collect(self, task_id: str) -> List[Dict[str, Any]]:
        """收集所有事件 (任务结束时调用, 非阻塞)"""
        events = list(self._events.get(task_id, []))
        self._completed.add(task_id)
        self._stats["tasks_collected"] += 1
        return events

    async def collect_async(self, task_id: str) -> List[Dict[str, Any]]:
        """异步收集所有事件"""
        async with self._lock:
            events = list(self._events.get(task_id, []))
            self._completed.add(task_id)
            self._stats["tasks_collected"] += 1
            return events

    # ---- 查询 ----

    def get_events(self, task_id: str) -> List[Dict[str, Any]]:
        """获取任务事件"""
        return list(self._events.get(task_id, []))

    def is_completed(self, task_id: str) -> bool:
        """任务是否已完成收集"""
        return task_id in self._completed

    def clear(self, task_id: str) -> None:
        """清除任务事件"""
        self._events.pop(task_id, None)
        self._completed.discard(task_id)

    def get_stats(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "active_tasks": len(self._events),
            "completed_tasks": len(self._completed),
        }


# ============================================================
# Stream Publisher — SSE/WebSocket 推送
# ============================================================

class StreamPublisher:
    """流式推送器

    职责:
        1. publish(task_id, event): 推送事件给所有订阅者
        2. sse_stream(task_id): SSE async generator
        3. WebSocket 客户端管理

    客户端管理:
        - SSE: 每个 task_id 维护一组 asyncio.Queue
        - WebSocket: 每个 task_id 维护一组 WebSocket 连接
        - 客户端断开时自动清理

    心跳:
        - SSE: 15 秒无事件时发送 ping
        - WebSocket: 30 秒无事件时发送 ping
    """

    _SSE_TIMEOUT = 15.0    # SSE 心跳间隔
    _WS_TIMEOUT = 30.0    # WebSocket 心跳间隔
    _MAX_QUEUE_SIZE = 1000  # 每个客户端队列上限

    def __init__(self) -> None:
        # SSE 客户端: task_id → set of asyncio.Queue
        self._sse_clients: Dict[str, Set[asyncio.Queue]] = defaultdict(set)

        # WebSocket 客户端: task_id → set of WebSocket
        self._ws_clients: Dict[str, Set[Any]] = defaultdict(set)

        self._lock = asyncio.Lock()
        self._stats = {
            "events_published": 0,
            "sse_clients_total": 0,
            "ws_clients_total": 0,
        }

    # ---- SSE ----

    async def add_sse_client(self, task_id: str) -> asyncio.Queue:
        """添加 SSE 客户端"""
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._MAX_QUEUE_SIZE)
        async with self._lock:
            self._sse_clients[task_id].add(queue)
            self._stats["sse_clients_total"] += 1
        logger.info(f"SSE 客户端连接 | task={task_id} | 当前={len(self._sse_clients[task_id])}")
        return queue

    async def remove_sse_client(
        self, task_id: str, queue: asyncio.Queue
    ) -> None:
        """移除 SSE 客户端"""
        async with self._lock:
            self._sse_clients[task_id].discard(queue)
            if not self._sse_clients[task_id]:
                self._sse_clients.pop(task_id, None)
        logger.info(f"SSE 客户端断开 | task={task_id}")

    async def sse_stream(self, task_id: str) -> AsyncGenerator[Dict[str, Any], None]:
        """SSE 流生成器

        使用方式 (API 端点):
            async def gen():
                async for event in publisher.sse_stream(task_id):
                    yield event
            return EventSourceResponse(gen())

        行为:
            - 阻塞等待事件
            - 15 秒无事件发 ping 心跳
            - 收到 event=done 时结束流
        """
        queue = await self.add_sse_client(task_id)

        try:
            while True:
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=self._SSE_TIMEOUT
                    )
                    yield event

                    # done 信号: 结束流
                    if event.get("event") == "done":
                        break

                except asyncio.TimeoutError:
                    # 心跳
                    yield {
                        "event": "ping",
                        "data": {"timestamp": time.time()},
                    }

        finally:
            await self.remove_sse_client(task_id, queue)

    # ---- WebSocket ----

    async def add_ws_client(self, task_id: str, websocket: Any) -> None:
        """添加 WebSocket 客户端"""
        async with self._lock:
            self._ws_clients[task_id].add(websocket)
            self._stats["ws_clients_total"] += 1
        logger.info(f"WebSocket 客户端连接 | task={task_id}")

    async def remove_ws_client(self, task_id: str, websocket: Any) -> None:
        """移除 WebSocket 客户端"""
        async with self._lock:
            self._ws_clients[task_id].discard(websocket)
            if not self._ws_clients[task_id]:
                self._ws_clients.pop(task_id, None)
        logger.info(f"WebSocket 客户端断开 | task={task_id}")

    async def serve_ws(
        self, task_id: str, websocket: Any
    ) -> None:
        """WebSocket 服务端循环

        使用方式 (API 端点):
            @router.websocket("/ws/{task_id}")
            async def ws_endpoint(websocket: WebSocket, task_id: str):
                await websocket.accept()
                await publisher.serve_ws(task_id, websocket)
        """
        await self.add_ws_client(task_id, websocket)

        try:
            while True:
                try:
                    # 接收客户端消息 (支持 cancel 指令)
                    data = await asyncio.wait_for(
                        websocket.receive_text(),
                        timeout=self._WS_TIMEOUT,
                    )
                    msg = json.loads(data) if data else {}

                    if msg.get("type") == "cancel":
                        break
                    if msg.get("type") == "ping":
                        await websocket.send_text(
                            json.dumps({"event": "pong", "data": {}})
                        )

                except asyncio.TimeoutError:
                    # 心跳
                    await websocket.send_text(
                        json.dumps({"event": "ping", "data": {"timestamp": time.time()}})
                    )

        except Exception as e:
            logger.info(f"WebSocket 断开: {task_id} | {e}")
        finally:
            await self.remove_ws_client(task_id, websocket)

    # ---- 推送 ----

    async def publish(self, task_id: str, event: Dict[str, Any]) -> None:
        """推送事件给所有订阅者 (SSE + WebSocket)"""
        self._stats["events_published"] += 1

        # 推送给 SSE 客户端
        await self._push_to_sse(task_id, event)

        # 推送给 WebSocket 客户端
        await self._push_to_websocket(task_id, event)

    async def _push_to_sse(self, task_id: str, event: Dict[str, Any]) -> None:
        """推送给 SSE 客户端"""
        clients = self._sse_clients.get(task_id, set()).copy()
        if not clients:
            return

        for queue in clients:
            try:
                if not queue.full():
                    queue.put_nowait(event)
                else:
                    # 队列满, 丢弃最旧的事件
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    queue.put_nowait(event)
            except Exception as e:
                logger.warning(f"SSE 推送失败: {task_id} | {e}")

    async def _push_to_websocket(self, task_id: str, event: Dict[str, Any]) -> None:
        """推送给 WebSocket 客户端"""
        clients = self._ws_clients.get(task_id, set()).copy()
        if not clients:
            return

        msg = json.dumps(event, ensure_ascii=False, default=str)
        for ws in clients:
            try:
                await ws.send_text(msg)
            except Exception as e:
                logger.warning(f"WebSocket 推送失败: {task_id} | {e}")
                # 移除断开的连接
                async with self._lock:
                    self._ws_clients[task_id].discard(ws)

    # ---- 统计 ----

    def get_stats(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "active_sse_tasks": len(self._sse_clients),
            "active_ws_tasks": len(self._ws_clients),
            "sse_clients": sum(len(v) for v in self._sse_clients.values()),
            "ws_clients": sum(len(v) for v in self._ws_clients.values()),
        }


# ============================================================
# 单例
# ============================================================

_collector: Optional[ResponseCollector] = None
_publisher: Optional[StreamPublisher] = None


def get_collector() -> ResponseCollector:
    """获取 Collector 单例"""
    global _collector
    if _collector is None:
        _collector = ResponseCollector()
        # 自动绑定 publisher
        _collector.set_stream_publisher(get_publisher())
    return _collector


def get_publisher() -> StreamPublisher:
    """获取 Publisher 单例"""
    global _publisher
    if _publisher is None:
        _publisher = StreamPublisher()
    return _publisher


def reset_collector() -> None:
    """重置单例 (测试用)"""
    global _collector, _publisher
    _collector = None
    _publisher = None
