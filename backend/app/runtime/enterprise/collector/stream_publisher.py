"""
Stream Publisher - 流式推送器

职责:
    1. 将 Agent 事件推送到前端
    2. 支持 SSE (Server-Sent Events)
    3. 支持 WebSocket
    4. 管理客户端连接

SSE 与 WebSocket 区别:
    - SSE: 单向推送 (Server → Client), 自动重连, 适合事件流
    - WebSocket: 双向通信, 适合交互式场景

使用方式:
    publisher = get_stream_publisher()

    # SSE 端点 (FastAPI)
    @app.get("/api/runtime/stream/{task_id}")
    async def stream(task_id: str):
        async def event_generator():
            async for event in publisher.sse_stream(task_id):
                yield event
        return EventSourceResponse(event_generator())

    # WebSocket 端点 (FastAPI)
    @app.websocket("/api/runtime/ws/{task_id}")
    async def ws_endpoint(websocket: WebSocket, task_id: str):
        await publisher.add_ws_client(task_id, websocket)
        try:
            await publisher.serve_ws(task_id, websocket)
        finally:
            await publisher.remove_ws_client(task_id, websocket)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from typing import Any, AsyncGenerator, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class StreamPublisher:
    """流式推送器

    管理两类客户端:
        - SSE 客户端: task_id → List[asyncio.Queue]
        - WebSocket 客户端: task_id → Set[WebSocket]
    """

    def __init__(self) -> None:
        # SSE: task_id → 客户端队列列表
        self._sse_clients: Dict[str, List[asyncio.Queue]] = defaultdict(list)
        # WebSocket: task_id → WebSocket 集合
        self._ws_clients: Dict[str, Set] = defaultdict(set)
        self._lock = asyncio.Lock()
        # 统计
        self._events_published = 0
        self._sse_clients_total = 0
        self._ws_clients_total = 0

    # ----------------------------------------------------------
    # 发布事件
    # ----------------------------------------------------------

    async def publish(self, task_id: str, event: Dict[str, Any]) -> None:
        """发布事件到所有订阅该 task 的客户端

        Args:
            task_id: 任务 ID
            event: 事件字典
        """
        self._events_published += 1

        # 推送给 SSE 客户端
        await self._push_to_sse(task_id, event)

        # 推送给 WebSocket 客户端
        await self._push_to_websocket(task_id, event)

    async def publish_batch(self, task_id: str, events: List[Dict[str, Any]]) -> None:
        """批量发布事件"""
        for event in events:
            await self.publish(task_id, event)

    async def publish_done(self, task_id: str) -> None:
        """发送任务完成信号 (SSE: event=done)"""
        await self._push_to_sse(task_id, {"event": "done", "task_id": task_id})
        await self._push_to_websocket(task_id, {"event": "done", "task_id": task_id})

    # ----------------------------------------------------------
    # SSE 客户端管理
    # ----------------------------------------------------------

    async def add_sse_client(self, task_id: str) -> asyncio.Queue:
        """添加 SSE 客户端

        Returns:
            asyncio.Queue: 客户端专属队列,从中读取事件
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        async with self._lock:
            self._sse_clients[task_id].append(queue)
            self._sse_clients_total += 1
        logger.info(
            f"[StreamPublisher] SSE 客户端连接 | task_id={task_id} | "
            f"total={len(self._sse_clients[task_id])}"
        )
        return queue

    async def remove_sse_client(self, task_id: str, queue: asyncio.Queue) -> None:
        """移除 SSE 客户端"""
        async with self._lock:
            if queue in self._sse_clients[task_id]:
                self._sse_clients[task_id].remove(queue)
            if not self._sse_clients[task_id]:
                self._sse_clients.pop(task_id, None)
        logger.info(f"[StreamPublisher] SSE 客户端断开 | task_id={task_id}")

    async def sse_stream(self, task_id: str) -> AsyncGenerator[Dict[str, Any], None]:
        """SSE 事件生成器

        使用方式 (FastAPI):
            async def event_generator():
                async for event in publisher.sse_stream(task_id):
                    yield event
            return EventSourceResponse(event_generator())
        """
        queue = await self.add_sse_client(task_id)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield event
                    # done 信号: 结束流
                    if event.get("event") == "done":
                        break
                except asyncio.TimeoutError:
                    # 发送心跳保活
                    yield {"event": "ping", "data": {"timestamp": time.time()}}
                except asyncio.CancelledError:
                    break
        finally:
            await self.remove_sse_client(task_id, queue)

    async def _push_to_sse(self, task_id: str, event: Dict[str, Any]) -> None:
        """推送到所有 SSE 客户端"""
        async with self._lock:
            clients = list(self._sse_clients.get(task_id, []))
        for queue in clients:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    f"[StreamPublisher] SSE 队列已满,丢弃事件 | task_id={task_id}"
                )

    # ----------------------------------------------------------
    # WebSocket 客户端管理
    # ----------------------------------------------------------

    async def add_ws_client(self, task_id: str, websocket: Any) -> None:
        """添加 WebSocket 客户端"""
        async with self._lock:
            self._ws_clients[task_id].add(websocket)
            self._ws_clients_total += 1
        logger.info(
            f"[StreamPublisher] WebSocket 客户端连接 | task_id={task_id} | "
            f"total={len(self._ws_clients[task_id])}"
        )

    async def remove_ws_client(self, task_id: str, websocket: Any) -> None:
        """移除 WebSocket 客户端"""
        async with self._lock:
            self._ws_clients[task_id].discard(websocket)
            if not self._ws_clients[task_id]:
                self._ws_clients.pop(task_id, None)
        logger.info(f"[StreamPublisher] WebSocket 客户端断开 | task_id={task_id}")

    async def serve_ws(self, task_id: str, websocket: Any) -> None:
        """服务 WebSocket 连接

        接收客户端消息 (心跳/取消),推送服务端事件。

        使用方式 (FastAPI):
            @app.websocket("/ws/{task_id}")
            async def ws_endpoint(ws: WebSocket, task_id: str):
                await ws.accept()
                await publisher.add_ws_client(task_id, ws)
                try:
                    await publisher.serve_ws(task_id, ws)
                finally:
                    await publisher.remove_ws_client(task_id, ws)
        """
        try:
            while True:
                # 接收客户端消息 (心跳/控制)
                try:
                    msg = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                    if msg == "ping":
                        await websocket.send_text(json.dumps({"event": "pong"}))
                    elif msg == "cancel":
                        logger.info(f"[StreamPublisher] 客户端取消 | task_id={task_id}")
                        break
                except asyncio.TimeoutError:
                    # 发送心跳
                    await websocket.send_text(json.dumps({
                        "event": "ping",
                        "timestamp": time.time(),
                    }))
        except Exception as e:
            logger.info(f"[StreamPublisher] WebSocket 连接关闭: {e}")

    async def _push_to_websocket(self, task_id: str, event: Dict[str, Any]) -> None:
        """推送到所有 WebSocket 客户端"""
        async with self._lock:
            clients = list(self._ws_clients.get(task_id, set()))
        for ws in clients:
            try:
                await ws.send_text(json.dumps(event, ensure_ascii=False, default=str))
            except Exception as e:
                logger.warning(
                    f"[StreamPublisher] WebSocket 推送失败 | task_id={task_id} | error={e}"
                )
                # 移除失效连接
                async with self._lock:
                    self._ws_clients[task_id].discard(ws)

    # ----------------------------------------------------------
    # 广播
    # ----------------------------------------------------------

    async def broadcast(self, event: Dict[str, Any]) -> None:
        """广播事件到所有客户端 (所有 task)"""
        async with self._lock:
            all_task_ids = set(self._sse_clients.keys()) | set(self._ws_clients.keys())
        for task_id in all_task_ids:
            await self.publish(task_id, event)

    # ----------------------------------------------------------
    # 统计
    # ----------------------------------------------------------

    async def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        async with self._lock:
            return {
                "events_published": self._events_published,
                "sse_tasks": len(self._sse_clients),
                "sse_clients_total": sum(
                    len(qs) for qs in self._sse_clients.values()
                ),
                "ws_tasks": len(self._ws_clients),
                "ws_clients_total": sum(
                    len(ws_set) for ws_set in self._ws_clients.values()
                ),
                "sse_clients_history": self._sse_clients_total,
                "ws_clients_history": self._ws_clients_total,
            }

    async def get_client_info(self, task_id: str) -> Dict[str, Any]:
        """获取指定任务的客户端信息"""
        async with self._lock:
            return {
                "task_id": task_id,
                "sse_clients": len(self._sse_clients.get(task_id, [])),
                "ws_clients": len(self._ws_clients.get(task_id, set())),
            }


# ============================================================
# 单例
# ============================================================

_publisher: Optional[StreamPublisher] = None


def get_stream_publisher() -> StreamPublisher:
    """获取全局 StreamPublisher 单例"""
    global _publisher
    if _publisher is None:
        _publisher = StreamPublisher()
        logger.info("[StreamPublisher] 单例创建")
    return _publisher
