"""
Runtime v2 — Task Dispatcher

职责:
    1. 接收任务 (submit)
    2. 创建任务状态 (TaskState)
    3. 分配 Agent (通过 AgentFactory, 不直接 new)
    4. 调度执行 (单机 asyncio.Queue / 未来 Redis)

核心设计:
    - DispatcherMode.STANDALONE: asyncio.PriorityQueue (单机)
    - DispatcherMode.DISTRIBUTED: Redis LPUSH/BRPOP (分布式, 预留接口)
    - 失败自动重试: FAILED + can_retry → reset_for_retry → 重新入队
    - 崩溃恢复: recover() 从内存未完成任务重置为 PENDING
    - 不直接调用 Agent, 通过 WorkerPool 分配给 AgentWorker

使用方式:
    from app.runtime.v2.dispatcher import get_dispatcher
    task_id = await get_dispatcher().submit(TaskRequest(agent_name="requirement_agent", ...))
"""
from __future__ import annotations

import asyncio
import enum
import itertools
import logging
import time
from typing import Any, Dict, List, Optional

from app.runtime.v2.state import (
    TaskState,
    TaskStatus,
    TaskPriority,
    TaskRequest,
    TaskResult,
    TaskEvent,
)

logger = logging.getLogger(__name__)


# ============================================================
# 运行模式
# ============================================================

class DispatcherMode(enum.Enum):
    """Dispatcher 运行模式"""
    STANDALONE = "standalone"    # 单机: asyncio.PriorityQueue
    DISTRIBUTED = "distributed"  # 分布式: Redis LPUSH/BRPOP


# ============================================================
# 优先级队列包装
# ============================================================

class _PriorityQueue:
    """asyncio 优先级队列 — 优先级值越小越先出队"""

    def __init__(self, maxsize: int = 1000) -> None:
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue(maxsize=maxsize)
        # 单调递增计数器作为次序键, 避免 TaskState 之间比较
        self._counter = itertools.count()

    async def put(self, state: TaskState) -> None:
        """入队 — 优先级值 + 序号保证 FIFO"""
        await self._queue.put(
            (int(state.priority), next(self._counter), state)
        )

    async def get(self, timeout: float = 1.0) -> Optional[TaskState]:
        """出队 — 带超时"""
        try:
            _, _, state = await asyncio.wait_for(
                self._queue.get(), timeout=timeout
            )
            return state
        except asyncio.TimeoutError:
            return None

    def qsize(self) -> int:
        return self._queue.qsize()


# ============================================================
# Task Dispatcher
# ============================================================

class TaskDispatcher:
    """任务调度器

    生命周期:
        start() → submit() × N → _dispatch_loop → complete() → stop()

    线程安全:
        - _tasks / _futures 通过 _lock 保护
        - _dispatch_loop 单协程消费, 避免竞态

    重试机制:
        Worker 执行失败 → complete(FAILED) → can_retry → reset_for_retry → 重新入队
    """

    def __init__(
        self,
        mode: DispatcherMode = DispatcherMode.STANDALONE,
        worker_pool: Any = None,
    ) -> None:
        self.mode = mode
        self._worker_pool = worker_pool

        # 任务状态存储
        self._tasks: Dict[str, TaskState] = {}
        self._futures: Dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

        # 队列
        self._queue: Optional[_PriorityQueue] = None

        # 运行状态
        self._started = False
        self._dispatch_task: Optional[asyncio.Task] = None

        # 统计
        self._stats = {
            "submitted": 0,
            "completed": 0,
            "failed": 0,
            "retried": 0,
            "cancelled": 0,
        }

    # ---- 依赖注入 ----

    def set_worker_pool(self, pool: Any) -> None:
        """注入 WorkerPool"""
        self._worker_pool = pool
        logger.info("Dispatcher 已绑定 WorkerPool")

    def set_response_collector(self, collector: Any) -> None:
        """注入 ResponseCollector"""
        self._collector = collector
        logger.info("Dispatcher 已绑定 ResponseCollector")

    # ---- 生命周期 ----

    async def start(self) -> None:
        """启动 Dispatcher"""
        if self._started:
            logger.warning("Dispatcher 已在运行")
            return

        self._queue = _PriorityQueue()
        self._started = True

        # STANDALONE 模式启动分发循环
        # DISTRIBUTED 模式不启动 (Worker 在外部进程消费 Redis)
        if self.mode == DispatcherMode.STANDALONE:
            self._dispatch_task = asyncio.create_task(self._dispatch_loop())
            logger.info(
                f"Dispatcher 启动 | 模式={self.mode.value} | "
                f"WorkerPool={'已绑定' if self._worker_pool else '未绑定'}"
            )
        else:
            logger.info(
                f"Dispatcher 启动 | 模式={self.mode.value} | "
                f"分布式模式: Worker 在外部进程运行"
            )

    async def stop(self) -> None:
        """停止 Dispatcher"""
        self._started = False

        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
            self._dispatch_task = None

        # 等待所有 Future 完成
        async with self._lock:
            for task_id, future in list(self._futures.items()):
                if not future.done():
                    state = self._tasks.get(task_id)
                    if state and not state.is_terminal:
                        future.set_result(TaskResult.from_state(state))

        logger.info(
            f"Dispatcher 已停止 | 统计: {self._stats}"
        )

    # ---- 提交任务 ----

    async def submit(self, request: TaskRequest) -> str:
        """提交任务

        Args:
            request: 任务请求

        Returns:
            task_id: 任务 ID

        Raises:
            RuntimeError: Dispatcher 未启动
            ValueError: Agent 不存在或未启用
        """
        if not self._started:
            raise RuntimeError("Dispatcher 未启动, 请先调用 start()")

        # 校验 Agent 存在
        from app.agents.factory import AgentRegistry
        if not AgentRegistry.exists(request.agent_name):
            raise ValueError(
                f"Agent 不存在: {request.agent_name} "
                f"(已注册: {len(AgentRegistry.list_agents())} 个)"
            )

        if not AgentRegistry.is_enabled(request.agent_name):
            raise ValueError(f"Agent 已禁用: {request.agent_name}")

        # 创建 TaskState
        state = TaskState.from_request(request)

        # 存储
        async with self._lock:
            self._tasks[state.task_id] = state
            self._futures[state.task_id] = asyncio.get_running_loop().create_future()
            self._stats["submitted"] += 1

        # 发布 start 事件
        self._emit_event(state, "start", message=f"任务已提交: {request.agent_name}")

        # 入队
        await self._queue.put(state)

        logger.info(
            f"任务提交 | task={state.task_id} | agent={request.agent_name} | "
            f"priority={request.priority.name}"
        )

        return state.task_id

    # ---- 分发循环 ----

    async def _dispatch_loop(self) -> None:
        """分发循环 — 从队列取任务分配给 WorkerPool"""
        logger.info("Dispatcher 分发循环启动")

        while self._started:
            try:
                state = await self._queue.get(timeout=1.0)
                if state is None:
                    continue  # 超时

                # 检查是否已取消
                if state.status == TaskStatus.CANCELLED:
                    logger.info(f"任务已取消, 跳过: {state.task_id}")
                    continue

                # 分配给 WorkerPool
                if self._worker_pool:
                    asyncio.create_task(
                        self._worker_pool.assign(state, self)
                    )
                else:
                    # 无 WorkerPool, 直接标记失败
                    await self.complete(
                        task_id=state.task_id,
                        status=TaskStatus.FAILED,
                        error="无可用 WorkerPool",
                    )

            except asyncio.CancelledError:
                logger.info("Dispatcher 分发循环收到取消信号")
                break
            except Exception as e:
                logger.error(f"Dispatcher 分发循环异常: {e}", exc_info=True)
                await asyncio.sleep(1)

        logger.info("Dispatcher 分发循环结束")

    # ---- 完成回调 ----

    async def complete(
        self,
        task_id: str,
        status: TaskStatus,
        result: Any = None,
        error: Optional[str] = None,
        events: Optional[List[Dict]] = None,
        worker_id: Optional[str] = None,
    ) -> None:
        """任务完成回调 — 由 Worker 调用

        逻辑:
            1. 更新 TaskState
            2. 如果 FAILED + can_retry → 重置并重新入队
            3. 否则设置 Future 结果
            4. 发布 end/error 事件
        """
        async with self._lock:
            state = self._tasks.get(task_id)
            if state is None:
                logger.warning(f"任务不存在: {task_id}")
                return

            # 状态转换
            try:
                state.transition(status)
            except ValueError as e:
                logger.warning(f"状态转换失败: {task_id} | {e}")
                return

            # 更新结果
            state.result = result
            state.error = error
            if worker_id:
                state.worker_id = worker_id
            if events:
                state.events.extend(events)

            # 检查重试
            if status == TaskStatus.FAILED and state.can_retry:
                self._stats["retried"] += 1
                logger.info(
                    f"任务重试 | task={task_id} | "
                    f"retry={state.retry_count + 1}/{state.max_retries}"
                )
                self._emit_event(
                    state, "retry",
                    message=f"第 {state.retry_count + 1} 次重试",
                    data={"reason": error},
                )
                state.reset_for_retry()
                await self._queue.put(state)
                return

            # 终态: 设置 Future
            future = self._futures.get(task_id)
            if future and not future.done():
                task_result = TaskResult.from_state(state)
                future.set_result(task_result)

            # 更新统计
            if status == TaskStatus.SUCCESS:
                self._stats["completed"] += 1
            elif status == TaskStatus.FAILED:
                self._stats["failed"] += 1
            elif status == TaskStatus.CANCELLED:
                self._stats["cancelled"] += 1

        # 发布完成事件
        if status == TaskStatus.SUCCESS:
            self._emit_event(
                state, "end",
                message="任务完成",
                data={"result": result} if result else {},
            )
        elif status in (TaskStatus.FAILED, TaskStatus.TIMEOUT):
            self._emit_event(
                state, "error",
                message=error or "任务失败",
                status="error",
            )

        # 发布 done 信号 (SSE 流终止)
        self._emit_event(state, "done")

        logger.info(
            f"任务完成 | task={task_id} | status={status.value} | "
            f"耗时={state.duration_ms}ms"
        )

    # ---- 取消 ----

    async def cancel(self, task_id: str) -> bool:
        """取消任务"""
        async with self._lock:
            state = self._tasks.get(task_id)
            if state is None:
                return False

            if state.is_terminal:
                return False

            try:
                state.transition(TaskStatus.CANCELLED)
            except ValueError:
                return False

            future = self._futures.get(task_id)
            if future and not future.done():
                future.set_result(TaskResult.from_state(state))

            self._stats["cancelled"] += 1

        self._emit_event(state, "done", message="任务已取消")
        logger.info(f"任务取消: {task_id}")
        return True

    # ---- 查询 ----

    async def get_task(self, task_id: str) -> Optional[TaskState]:
        """获取任务状态"""
        async with self._lock:
            return self._tasks.get(task_id)

    async def get_result(self, task_id: str) -> Optional[TaskResult]:
        """等待并获取任务结果 (阻塞)"""
        async with self._lock:
            future = self._futures.get(task_id)
            state = self._tasks.get(task_id)

        if future is None or state is None:
            return None

        if not future.done():
            await future

        return future.result()

    async def wait_for_result(
        self, task_id: str, timeout: Optional[float] = None
    ) -> Optional[TaskResult]:
        """等待任务结果 (带超时)"""
        async with self._lock:
            future = self._futures.get(task_id)

        if future is None:
            return None

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def get_status(self, task_id: str) -> Optional[TaskStatus]:
        """查询任务状态 (非阻塞)"""
        state = self._tasks.get(task_id)
        return state.status if state else None

    def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """列出任务"""
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        tasks = tasks[:limit]
        return [t.to_dict() for t in tasks]

    def get_stats(self) -> Dict[str, Any]:
        """获取统计"""
        return {
            **self._stats,
            "queue_size": self._queue.qsize() if self._queue else 0,
            "total_tasks": len(self._tasks),
            "running": sum(
                1 for t in self._tasks.values()
                if t.status == TaskStatus.RUNNING
            ),
            "pending": sum(
                1 for t in self._tasks.values()
                if t.status == TaskStatus.PENDING
            ),
        }

    # ---- 崩溃恢复 ----

    async def recover(self) -> int:
        """崩溃恢复 — 将 RUNNING 状态的任务重置为 PENDING

        Returns:
            恢复的任务数
        """
        recovered = 0
        async with self._lock:
            for state in self._tasks.values():
                if state.status == TaskStatus.RUNNING:
                    state.status = TaskStatus.PENDING
                    state.started_at = None
                    state.worker_id = None
                    await self._queue.put(state)
                    recovered += 1
                    logger.info(f"任务恢复: {state.task_id}")

        logger.info(f"崩溃恢复完成, 恢复 {recovered} 个任务")
        return recovered

    # ---- 事件发布 ----

    def _emit_event(
        self,
        state: TaskState,
        event_type: str,
        message: str = "",
        data: Optional[Dict] = None,
        status: str = "running",
    ) -> None:
        """发布事件到 ResponseCollector"""
        collector = getattr(self, "_collector", None)
        if collector is None:
            return

        event = TaskEvent(
            task_id=state.task_id,
            event_type=event_type,
            agent_name=state.agent_name,
            status=status,
            message=message,
            data=data or {},
        )

        # 同步调用 record (非异步, 避免阻塞)
        try:
            asyncio.create_task(collector.record(state.task_id, event.to_dict()))
        except RuntimeError:
            # 无事件循环时跳过
            pass


# ============================================================
# 单例
# ============================================================

_dispatcher: Optional[TaskDispatcher] = None


def get_dispatcher(
    mode: Optional[DispatcherMode] = None,
) -> TaskDispatcher:
    """获取 Dispatcher 单例"""
    global _dispatcher
    if _dispatcher is None:
        # 自动选择模式: Redis 启用时用 DISTRIBUTED
        if mode is None:
            try:
                from app.core.config import settings
                mode = (
                    DispatcherMode.DISTRIBUTED
                    if getattr(settings, "REDIS_ENABLED", False)
                    else DispatcherMode.STANDALONE
                )
            except Exception:
                mode = DispatcherMode.STANDALONE

        _dispatcher = TaskDispatcher(mode=mode)
    return _dispatcher


def reset_dispatcher() -> None:
    """重置 Dispatcher 单例 (测试用)"""
    global _dispatcher
    _dispatcher = None
