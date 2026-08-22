"""
Task Dispatcher - 企业级任务分发器

核心职责:
    1. 接收来自 API 层的任务请求 (TaskRequest)
    2. 将任务转换为 TaskState 并入队
    3. 分配 AgentWorker 执行
    4. 全程管理任务状态 (6 状态机)
    5. 失败自动重试 (max_retries)
    6. 任务恢复 (崩溃后从 PENDING/RUNNING 恢复)

两种运行模式:
    - STANDALONE (单机): asyncio.Queue + 进程内 Worker
    - DISTRIBUTED (分布式): Redis 队列 + 跨进程 Worker

架构:
    API Layer → TaskDispatcher.submit() → Queue
                                              ↓
                                          WorkerPool
                                              ↓
                                          AgentWorker
                                              ↓
                                          Agent.execute()
                                              ↓
                                          ResponseCollector
                                              ↓
                                          TaskDispatcher.complete()

使用方式:
    dispatcher = get_task_dispatcher()
    task_id = await dispatcher.submit(TaskRequest(
        agent_name="requirement_agent",
        action="analyze",
        payload={"text": "..."},
    ))
    state = await dispatcher.get_status(task_id)
"""
from __future__ import annotations

import asyncio
import enum
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.runtime.enterprise.dispatcher.task_state import (
    TaskState,
    TaskStatus,
    TaskPriority,
)

logger = logging.getLogger(__name__)


# ============================================================
# 运行模式
# ============================================================

class DispatcherMode(str, enum.Enum):
    """Dispatcher 运行模式"""
    STANDALONE = "standalone"        # 单机: asyncio.Queue
    DISTRIBUTED = "distributed"      # 分布式: Redis 队列


# ============================================================
# 任务请求 / 结果
# ============================================================

@dataclass
class TaskRequest:
    """任务请求 (API → Dispatcher)

    封装用户提交的任务,Dispatcher 转换为 TaskState 后入队。

    Attributes:
        agent_name: 目标 Agent 名称 (必须已在 AgentFactory 注册)
        action: 调用的 action 名称 (默认 execute)
        payload: 任务参数
        priority: 优先级 (LOW/NORMAL/HIGH/URGENT)
        user_id: 用户 ID
        session_id: 会话 ID (多会话隔离)
        timeout_seconds: 超时时间 (秒)
        max_retries: 最大重试次数
        task_id: 可指定 task_id (默认自动生成)
        task_type: 任务类型 (agent/flow)
    """
    agent_name: str
    action: str = "execute"
    payload: Dict[str, Any] = field(default_factory=dict)
    priority: TaskPriority = TaskPriority.NORMAL
    user_id: Optional[int] = None
    session_id: Optional[str] = None
    timeout_seconds: int = 300
    max_retries: int = 3
    task_id: str = field(default_factory=lambda: f"task_{uuid.uuid4().hex[:12]}")
    task_type: str = "agent"


@dataclass
class TaskResult:
    """任务结果 (Worker → Dispatcher → API)

    Attributes:
        task_id: 任务 ID
        status: 最终状态 (success/failed/timeout/cancelled)
        result: Agent 输出
        error: 错误信息
        events: 执行过程中产生的事件
        duration_ms: 总耗时 (毫秒)
        worker_id: 执行任务的 Worker ID
        retry_count: 实际重试次数
    """
    task_id: str
    status: str
    result: Optional[Any] = None
    error: Optional[str] = None
    events: List[Dict[str, Any]] = field(default_factory=list)
    duration_ms: int = 0
    worker_id: Optional[str] = None
    retry_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "events_count": len(self.events),
            "duration_ms": self.duration_ms,
            "worker_id": self.worker_id,
            "retry_count": self.retry_count,
        }


# ============================================================
# 任务队列抽象 (单机 / 分布式)
# ============================================================

class _StandaloneQueue:
    """单机模式: asyncio.PriorityQueue

    按优先级排序: URGENT > HIGH > NORMAL > LOW
    """

    _PRIORITY_WEIGHT = {
        TaskPriority.URGENT: 0,
        TaskPriority.HIGH: 1,
        TaskPriority.NORMAL: 2,
        TaskPriority.LOW: 3,
    }

    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()

    async def put(self, state: TaskState) -> None:
        weight = self._PRIORITY_WEIGHT.get(state.priority, 2)
        # (priority_weight, created_timestamp, task_id, state)
        await self._queue.put((weight, time.time(), state.task_id, state))

    async def get(self, timeout: Optional[float] = None) -> Optional[TaskState]:
        try:
            if timeout is None:
                _, _, _, state = await self._queue.get()
            else:
                _, _, _, state = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            return state
        except asyncio.TimeoutError:
            return None

    def qsize(self) -> int:
        return self._queue.qsize()

    def empty(self) -> bool:
        return self._queue.empty()


class _DistributedQueue:
    """分布式模式: Redis List

    使用 LPUSH/BRPOP 实现生产者-消费者模型。
    优先级通过不同 key 实现 (urgent/high/normal/low)。
    """

    _KEY_PREFIX = "runtime:task_queue"
    _PRIORITY_KEYS = {
        TaskPriority.URGENT: f"{_KEY_PREFIX}:urgent",
        TaskPriority.HIGH: f"{_KEY_PREFIX}:high",
        TaskPriority.NORMAL: f"{_KEY_PREFIX}:normal",
        TaskPriority.LOW: f"{_KEY_PREFIX}:low",
    }
    _ALL_KEYS = list(_PRIORITY_KEYS.values())

    def __init__(self) -> None:
        self._redis = None

    def _get_redis(self):
        if self._redis is None:
            try:
                import redis
                from app.core.config import settings
                self._redis = redis.from_url(
                    settings.redis_url,
                    decode_responses=True,
                    socket_timeout=5,
                    socket_connect_timeout=5,
                )
                self._redis.ping()
                logger.info("[DistributedQueue] Redis 连接成功")
            except Exception as e:
                logger.error(f"[DistributedQueue] Redis 连接失败: {e}")
                self._redis = None
                raise
        return self._redis

    async def put(self, state: TaskState) -> None:
        r = self._get_redis()
        key = self._PRIORITY_KEYS.get(state.priority, self._PRIORITY_KEYS[TaskPriority.NORMAL])
        payload = json.dumps(state.to_dict(), ensure_ascii=False, default=str)
        # 用 to_thread 避免 brpop 阻塞事件循环
        await asyncio.to_thread(r.lpush, key, payload)

    async def get(self, timeout: Optional[float] = None) -> Optional[TaskState]:
        r = self._get_redis()
        # 按优先级顺序 BRPOP
        brpop_timeout = int(timeout) if timeout else 1
        try:
            # 传入多个 key,Redis 会按顺序检查
            result = await asyncio.to_thread(r.brpop, self._ALL_KEYS, brpop_timeout)
            if result is None:
                return None
            _, payload = result
            data = json.loads(payload)
            # 重建 TaskState
            return self._rebuild_state(data)
        except Exception as e:
            logger.error(f"[DistributedQueue] get 失败: {e}")
            return None

    def _rebuild_state(self, data: Dict[str, Any]) -> TaskState:
        """从字典重建 TaskState (跨进程恢复时使用)"""
        state = TaskState(
            task_id=data["task_id"],
            task_type=data.get("task_type", "agent"),
            agent_name=data.get("agent_name", ""),
            action=data.get("action", "execute"),
            payload=data.get("payload", {}),
            status=TaskStatus(data.get("status", "pending")),
            priority=TaskPriority(data.get("priority", "normal")),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
            created_at=data.get("created_at", datetime.now().isoformat()),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            user_id=data.get("user_id"),
            session_id=data.get("session_id"),
            timeout_seconds=data.get("timeout_seconds", 300),
            worker_id=data.get("worker_id"),
        )
        return state

    def qsize(self) -> int:
        r = self._get_redis()
        total = 0
        for key in self._ALL_KEYS:
            total += r.llen(key)
        return total

    def empty(self) -> bool:
        return self.qsize() == 0


# ============================================================
# Task Dispatcher
# ============================================================

class TaskDispatcher:
    """企业级任务分发器

    生命周期:
        1. start()    — 启动 Dispatcher (创建队列, 连接 WorkerPool)
        2. submit()   — 接收任务, 创建 TaskState, 入队
        3. (Worker)   — WorkerPool 取出任务, 调用 Agent.execute()
        4. complete() — Worker 完成后回调, 更新状态
        5. cancel()    — 用户取消任务
        6. retry()     — 失败重试
        7. recover()   — 崩溃恢复 (启动时调用)
        8. stop()      — 停止 Dispatcher

    线程安全:
        - _tasks: asyncio.Lock 保护
        - _futures: 每个 task_id 一个 asyncio.Future, 用于 await 结果
    """

    def __init__(
        self,
        mode: DispatcherMode = DispatcherMode.STANDALONE,
        worker_pool: Any = None,
    ) -> None:
        self.mode = mode
        self._worker_pool = worker_pool  # 延迟注入, 避免循环依赖
        self._queue = (
            _StandaloneQueue() if mode == DispatcherMode.STANDALONE
            else _DistributedQueue()
        )
        self._tasks: Dict[str, TaskState] = {}
        self._futures: Dict[str, asyncio.Future] = {}
        self._results: Dict[str, TaskResult] = {}
        self._lock = asyncio.Lock()
        self._started = False
        self._dispatch_task: Optional[asyncio.Task] = None

    # ----------------------------------------------------------
    # 生命周期
    # ----------------------------------------------------------

    async def start(self) -> None:
        """启动 Dispatcher"""
        if self._started:
            logger.warning("[TaskDispatcher] 已启动, 重复调用")
            return

        # 恢复未完成的任务
        await self.recover()

        # 启动分发协程 (单机模式)
        if self.mode == DispatcherMode.STANDALONE:
            self._dispatch_task = asyncio.create_task(self._dispatch_loop())
            logger.info("[TaskDispatcher] 分发协程已启动 (单机模式)")
        else:
            # 分布式模式: Worker 在独立进程/机器中运行
            logger.info("[TaskDispatcher] 分布式模式, Worker 在外部进程")

        self._started = True
        logger.info(
            f"[TaskDispatcher] 启动完成 | mode={self.mode.value} | "
            f"tasks={len(self._tasks)}"
        )

    async def stop(self) -> None:
        """停止 Dispatcher"""
        if not self._started:
            return

        # 立即标记为停止,防止 complete() 触发重试
        self._started = False

        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
            self._dispatch_task = None

        # 取消所有未完成的 Future
        async with self._lock:
            for task_id, fut in self._futures.items():
                if not fut.done():
                    fut.cancel()
                    state = self._tasks.get(task_id)
                    if state and state.transition(TaskStatus.CANCELLED):
                        logger.info(f"[TaskDispatcher] 任务取消: {task_id}")
            self._futures.clear()

        logger.info("[TaskDispatcher] 已停止")

    def set_worker_pool(self, pool: Any) -> None:
        """注入 WorkerPool (避免循环依赖)"""
        self._worker_pool = pool
        logger.info(f"[TaskDispatcher] WorkerPool 注入: {type(pool).__name__}")

    # ----------------------------------------------------------
    # 任务提交
    # ----------------------------------------------------------

    async def submit(self, request: TaskRequest) -> str:
        """提交任务

        Args:
            request: 任务请求

        Returns:
            task_id: 任务 ID

        Raises:
            RuntimeError: Dispatcher 未启动
            ValueError: Agent 不存在
        """
        if not self._started:
            raise RuntimeError("TaskDispatcher 未启动, 请先调用 start()")

        # 校验 Agent 是否注册
        try:
            from app.agents.factory.factory import get_agent_factory
            factory = get_agent_factory()
            if not factory.exists(request.agent_name):
                raise ValueError(f"Agent 不存在: {request.agent_name}")
            if not factory.is_enabled(request.agent_name):
                raise ValueError(f"Agent 已禁用: {request.agent_name}")
        except ImportError:
            logger.warning("[TaskDispatcher] AgentFactory 未就绪, 跳过校验")

        # 创建 TaskState
        state = TaskState(
            task_id=request.task_id,
            task_type=request.task_type,
            agent_name=request.agent_name,
            action=request.action,
            payload=request.payload,
            priority=request.priority,
            user_id=request.user_id,
            session_id=request.session_id,
            timeout_seconds=request.timeout_seconds,
            max_retries=request.max_retries,
        )

        # 存储状态
        async with self._lock:
            self._tasks[task_id := state.task_id] = state
            self._futures[task_id] = asyncio.get_event_loop().create_future()

        # 持久化到数据库
        try:
            from app.services.runtime_persistence import get_runtime_persistence
            persistence = get_runtime_persistence()
            if persistence.enabled:
                persistence.create_task(state)
        except Exception as e:
            logger.debug(f"[TaskDispatcher] 持久化失败 (忽略): {e}")

        # 入队
        await self._queue.put(state)

        logger.info(
            f"[TaskDispatcher] 任务已提交 | task_id={state.task_id} | "
            f"agent={state.agent_name} | action={state.action} | "
            f"priority={state.priority.value}"
        )
        return state.task_id

    async def submit_and_wait(
        self,
        request: TaskRequest,
        timeout: Optional[float] = None,
    ) -> TaskResult:
        """提交任务并等待结果

        Args:
            request: 任务请求
            timeout: 等待超时 (秒), None=使用 request.timeout_seconds

        Returns:
            TaskResult
        """
        task_id = await self.submit(request)
        return await self.wait_for_result(
            task_id,
            timeout=timeout or request.timeout_seconds,
        )

    async def wait_for_result(
        self,
        task_id: str,
        timeout: Optional[float] = None,
    ) -> TaskResult:
        """等待任务结果

        Args:
            task_id: 任务 ID
            timeout: 超时 (秒)

        Returns:
            TaskResult

        Raises:
            asyncio.TimeoutError: 超时
            KeyError: 任务不存在
        """
        async with self._lock:
            fut = self._futures.get(task_id)
        if fut is None:
            # 任务已完成,从结果缓存中取
            if task_id in self._results:
                return self._results[task_id]
            raise KeyError(f"任务不存在或已完成: {task_id}")

        wait_timeout = timeout
        if wait_timeout is None:
            state = self._tasks.get(task_id)
            wait_timeout = state.timeout_seconds if state else 300

        try:
            await asyncio.wait_for(asyncio.shield(fut), timeout=wait_timeout)
        except asyncio.TimeoutError:
            await self._handle_timeout(task_id)
            raise
        except asyncio.CancelledError:
            await self.cancel(task_id)
            raise

        return self._results.get(task_id, TaskResult(
            task_id=task_id,
            status="failed",
            error="结果丢失",
        ))

    # ----------------------------------------------------------
    # 任务分发循环 (单机模式)
    # ----------------------------------------------------------

    async def _dispatch_loop(self) -> None:
        """分发循环: 从队列取任务, 分配给 Worker"""
        logger.info("[TaskDispatcher] 分发循环启动")
        while self._started:
            try:
                state = await self._queue.get(timeout=1)
                if state is None:
                    continue

                # 校验状态 (可能是取消的)
                if state.status == TaskStatus.CANCELLED:
                    logger.info(f"[TaskDispatcher] 跳过已取消任务: {state.task_id}")
                    continue

                # 分配给 WorkerPool
                if self._worker_pool:
                    asyncio.create_task(self._worker_pool.assign(state))
                else:
                    # 无 WorkerPool, 直接标记失败
                    await self.complete(
                        task_id=state.task_id,
                        status=TaskStatus.FAILED,
                        error="无可用 WorkerPool",
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[TaskDispatcher] 分发循环异常: {e}", exc_info=True)
                await asyncio.sleep(1)

        logger.info("[TaskDispatcher] 分发循环结束")

    # ----------------------------------------------------------
    # 任务完成回调 (Worker 调用)
    # ----------------------------------------------------------

    async def complete(
        self,
        task_id: str,
        status: TaskStatus,
        result: Optional[Any] = None,
        error: Optional[str] = None,
        events: Optional[List[Dict[str, Any]]] = None,
        duration_ms: int = 0,
        worker_id: Optional[str] = None,
    ) -> None:
        """任务完成回调

        由 AgentWorker 在 Agent 执行完成后调用。

        Args:
            task_id: 任务 ID
            status: 最终状态 (SUCCESS/FAILED/TIMEOUT/CANCELLED)
            result: Agent 输出
            error: 错误信息
            events: 执行事件
            duration_ms: 耗时
            worker_id: 执行任务的 Worker ID
        """
        async with self._lock:
            state = self._tasks.get(task_id)
            if state is None:
                logger.warning(f"[TaskDispatcher] 完成回调: 任务不存在 {task_id}")
                return

            # 状态转移
            if not state.transition(status):
                logger.warning(
                    f"[TaskDispatcher] 非法状态转移: {state.status} → {status} "
                    f"(task={task_id})"
                )
                return

            state.result = result
            state.error = error
            state.events = events or state.events
            state.worker_id = worker_id or state.worker_id

            # 构建结果
            task_result = TaskResult(
                task_id=task_id,
                status=status.value,
                result=result,
                error=error,
                events=state.events,
                duration_ms=duration_ms,
                worker_id=worker_id,
                retry_count=state.retry_count,
            )
            self._results[task_id] = task_result

            # 持久化更新到数据库
            try:
                from app.services.runtime_persistence import get_runtime_persistence
                persistence = get_runtime_persistence()
                if persistence.enabled:
                    persistence.update_task(
                        task_id=task_id,
                        status=status.value,
                        completed_at=datetime.now().isoformat() if status != TaskStatus.RUNNING else None,
                        duration_ms=duration_ms,
                        worker_id=worker_id,
                        result=result,
                        error=error,
                        events_count=len(state.events),
                    )
            except Exception as e:
                logger.debug(f"[TaskDispatcher] 持久化更新失败 (忽略): {e}")

            # 唤醒等待的 Future
            fut = self._futures.get(task_id)
            if fut and not fut.done():
                fut.set_result(task_result)

        logger.info(
            f"[TaskDispatcher] 任务完成 | task_id={task_id} | "
            f"status={status.value} | duration={duration_ms}ms | "
            f"worker={worker_id}"
        )

        # 失败自动重试 (仅在运行中时)
        if (
            status == TaskStatus.FAILED
            and state.can_retry()
            and self._started  # 停止时不重试
        ):
            logger.info(
                f"[TaskDispatcher] 自动重试 | task_id={task_id} | "
                f"retry={state.retry_count + 1}/{state.max_retries}"
            )
            await self.retry(task_id)

    async def _handle_timeout(self, task_id: str) -> None:
        """处理任务超时"""
        async with self._lock:
            state = self._tasks.get(task_id)
            if state and state.transition(TaskStatus.TIMEOUT):
                state.error = f"任务超时 ({state.timeout_seconds}s)"
                task_result = TaskResult(
                    task_id=task_id,
                    status=TaskStatus.TIMEOUT.value,
                    error=state.error,
                    duration_ms=state.timeout_seconds * 1000,
                )
                self._results[task_id] = task_result
                fut = self._futures.get(task_id)
                if fut and not fut.done():
                    fut.set_result(task_result)
        logger.warning(f"[TaskDispatcher] 任务超时: {task_id}")

    # ----------------------------------------------------------
    # 查询 / 管理
    # ----------------------------------------------------------

    async def get_status(self, task_id: str) -> Optional[TaskState]:
        """查询任务状态"""
        async with self._lock:
            return self._tasks.get(task_id)

    async def get_result(self, task_id: str) -> Optional[TaskResult]:
        """获取任务结果 (已完成)"""
        async with self._lock:
            return self._results.get(task_id)

    async def cancel(self, task_id: str) -> bool:
        """取消任务

        Returns:
            True: 取消成功 / False: 任务不存在或已终态
        """
        async with self._lock:
            state = self._tasks.get(task_id)
            if state is None:
                return False
            if not state.transition(TaskStatus.CANCELLED):
                return False

            task_result = TaskResult(
                task_id=task_id,
                status=TaskStatus.CANCELLED.value,
                error="用户取消",
            )
            self._results[task_id] = task_result

            fut = self._futures.get(task_id)
            if fut and not fut.done():
                fut.set_result(task_result)

        logger.info(f"[TaskDispatcher] 任务取消: {task_id}")
        return True

    async def retry(self, task_id: str) -> bool:
        """重试失败的任务

        Returns:
            True: 重试已启动 / False: 不可重试
        """
        async with self._lock:
            state = self._tasks.get(task_id)
            if state is None:
                return False
            if not state.can_retry():
                logger.warning(
                    f"[TaskDispatcher] 不可重试: {task_id} "
                    f"(status={state.status}, retries={state.retry_count}/{state.max_retries})"
                )
                return False

            state.reset_for_retry()
            # 清除旧结果
            self._results.pop(task_id, None)
            # 重建 Future
            self._futures[task_id] = asyncio.get_event_loop().create_future()

        # 重新入队
        await self._queue.put(state)
        logger.info(
            f"[TaskDispatcher] 任务重试 | task_id={task_id} | "
            f"retry={state.retry_count}/{state.max_retries}"
        )
        return True

    async def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        user_id: Optional[int] = None,
        limit: int = 100,
    ) -> List[TaskState]:
        """列出任务

        Args:
            status: 过滤状态
            user_id: 过滤用户
            limit: 返回数量上限
        """
        async with self._lock:
            tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        if user_id is not None:
            tasks = [t for t in tasks if t.user_id == user_id]
        # 按创建时间倒序
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return tasks[:limit]

    async def recover(self) -> int:
        """崩溃恢复

        将 PENDING 和 RUNNING 状态的任务重置为 PENDING 重新入队。
        同时从数据库加载未完成任务。
        通常在 start() 时自动调用。

        Returns:
            恢复的任务数量
        """
        # 1. 从数据库加载未完成任务
        db_tasks: List[Dict[str, Any]] = []
        try:
            from app.services.runtime_persistence import get_runtime_persistence
            persistence = get_runtime_persistence()
            if persistence.enabled:
                db_tasks = persistence.load_pending_tasks()
                logger.info(f"[TaskDispatcher] 从 DB 加载 {len(db_tasks)} 个未完成任务")
        except Exception as e:
            logger.warning(f"[TaskDispatcher] 从 DB 加载失败: {e}")

        # 2. 将 DB 任务重建为 TaskState
        for task_data in db_tasks:
            task_id = task_data.get("task_id")
            if task_id is None:
                continue
            # 如果内存中已有,跳过
            if task_id in self._tasks:
                continue
            # 重建 TaskState
            try:
                state = TaskState(
                    task_id=task_id,
                    task_type=task_data.get("task_type", "agent"),
                    agent_name=task_data.get("agent_name", ""),
                    action=task_data.get("action", "execute"),
                    payload=json.loads(task_data.get("payload_json") or "{}"),
                    status=TaskStatus(task_data.get("status", "pending")),
                    priority=TaskPriority(task_data.get("priority", "normal")),
                    retry_count=task_data.get("retry_count", 0),
                    max_retries=task_data.get("max_retries", 3),
                    created_at=task_data.get("created_at") or datetime.now().isoformat(),
                    user_id=task_data.get("user_id"),
                    session_id=task_data.get("session_id"),
                    timeout_seconds=task_data.get("timeout_seconds", 300),
                )
                async with self._lock:
                    self._tasks[task_id] = state
                    self._futures[task_id] = asyncio.get_event_loop().create_future()
            except Exception as e:
                logger.warning(f"[TaskDispatcher] 重建任务失败: {task_id} | {e}")

        # 3. 重置内存中的 RUNNING 任务
        recovered = 0
        async with self._lock:
            for state in self._tasks.values():
                if state.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                    if state.status == TaskStatus.RUNNING:
                        state.status = TaskStatus.PENDING
                        state.started_at = None
                        state.worker_id = None
                        # 同步到 DB
                        try:
                            from app.services.runtime_persistence import get_runtime_persistence
                            persistence = get_runtime_persistence()
                            if persistence.enabled:
                                persistence.mark_recovered(state.task_id)
                        except Exception:
                            pass
                    recovered += 1

        # 4. 重新入队
        if recovered > 0:
            async with self._lock:
                to_recover = [
                    s for s in self._tasks.values()
                    if s.status == TaskStatus.PENDING
                ]
            for state in to_recover:
                await self._queue.put(state)

        if recovered > 0:
            logger.info(f"[TaskDispatcher] 恢复 {recovered} 个未完成任务")
        return recovered

    # ----------------------------------------------------------
    # 统计
    # ----------------------------------------------------------

    async def get_stats(self) -> Dict[str, Any]:
        """获取 Dispatcher 统计信息"""
        async with self._lock:
            status_counts: Dict[str, int] = {}
            for state in self._tasks.values():
                key = state.status.value
                status_counts[key] = status_counts.get(key, 0) + 1

            return {
                "mode": self.mode.value,
                "started": self._started,
                "queue_size": self._queue.qsize(),
                "total_tasks": len(self._tasks),
                "completed_results": len(self._results),
                "pending_futures": sum(
                    1 for f in self._futures.values() if not f.done()
                ),
                "status_counts": status_counts,
                "worker_pool": type(self._worker_pool).__name__ if self._worker_pool else None,
            }


# ============================================================
# 单例
# ============================================================

_dispatcher: Optional[TaskDispatcher] = None


def get_task_dispatcher(
    mode: Optional[DispatcherMode] = None,
) -> TaskDispatcher:
    """获取全局 TaskDispatcher 单例

    首次调用时创建。后续调用返回同一实例。
    mode 参数仅在首次调用时生效。
    """
    global _dispatcher
    if _dispatcher is None:
        if mode is None:
            # 根据配置自动选择
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
        logger.info(f"[TaskDispatcher] 单例创建 | mode={mode.value}")
    return _dispatcher
