"""
Runtime v2 — Agent Worker

职责:
    1. 执行 Agent 任务 (通过 AgentFactory 创建 Agent, 不直接 new)
    2. 成功/失败/异常捕获
    3. 自动重试 (由 Dispatcher 控制)

核心设计:
    - AgentWorker: 单任务执行器, 通过 AgentFactory.create() 获取 Agent
    - WorkerPool: Worker 池管理, asyncio.Semaphore 并发控制
    - 不依赖 AutoGen Runtime (直接调用 agent.execute())
    - 超时控制 (asyncio.wait_for)
    - 异常分类处理 (TimeoutError / CancelledError / Exception)

使用方式:
    from app.runtime.v2.worker import get_worker_pool
    pool = get_worker_pool(size=4)
    await pool.start()
    # Dispatcher 会自动调用 pool.assign(state, dispatcher)
"""
from __future__ import annotations

import asyncio
import logging
import time
import traceback
import uuid
from typing import Any, Dict, List, Optional

from app.runtime.v2.state import (
    TaskState,
    TaskStatus,
    TaskEvent,
)

logger = logging.getLogger(__name__)


# ============================================================
# Agent Worker — 单任务执行器
# ============================================================

class AgentWorker:
    """Agent 任务执行器

    职责:
        1. 接收 TaskState
        2. 通过 AgentFactory.create() 创建 Agent (不直接 new)
        3. 调用 agent.execute(payload, ctx)
        4. 超时控制 + 异常捕获
        5. 回调 Dispatcher.complete()

    注意:
        - Worker 不管理 Agent 生命周期 (AgentFactory 管理缓存)
        - Worker 是无状态的, 可复用执行不同任务
        - Worker ID 用于追踪任务由哪个 Worker 执行
    """

    def __init__(self, worker_id: Optional[str] = None) -> None:
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self._busy = False
        self._current_task: Optional[str] = None
        self._tasks_done = 0
        self._tasks_failed = 0
        # 跟踪 fire-and-forget task 引用，防止被 GC 回收
        self._pending_tasks: set = set()

    @property
    def is_busy(self) -> bool:
        return self._busy

    @property
    def current_task(self) -> Optional[str]:
        return self._current_task

    async def execute(
        self,
        state: TaskState,
        dispatcher: Any,
    ) -> None:
        """执行任务

        流程:
            1. 状态转移 PENDING → RUNNING
            2. 创建 Agent (AgentFactory)
            3. 调用 agent.execute() (带超时)
            4. 回调 dispatcher.complete()

        Args:
            state: 任务状态
            dispatcher: Dispatcher 实例 (用于回调)
        """
        self._busy = True
        self._current_task = state.task_id
        start_time = time.time()

        logger.info(
            f"[Worker {self.worker_id}] 开始执行 | "
            f"task={state.task_id} | agent={state.agent_name} | "
            f"action={state.action}"
        )

        # 状态转移 PENDING → RUNNING
        try:
            state.transition(TaskStatus.RUNNING)
            state.worker_id = self.worker_id
        except ValueError as e:
            logger.warning(
                f"[Worker {self.worker_id}] 状态转换失败: {e}"
            )
            await dispatcher.complete(
                task_id=state.task_id,
                status=TaskStatus.FAILED,
                error=f"状态转换失败: {e}",
                worker_id=self.worker_id,
            )
            self._reset()
            return

        # 发布 start 事件
        self._emit_progress(dispatcher, state, message="Agent 执行开始")

        result: Any = None
        error: Optional[str] = None
        final_status = TaskStatus.SUCCESS

        try:
            # 执行 Agent (带超时)
            result = await asyncio.wait_for(
                self._invoke_agent(state),
                timeout=state.timeout_seconds,
            )

            # 检查 Agent 返回错误
            if isinstance(result, dict) and result.get("status") == "error":
                error = (
                    result.get("message")
                    or result.get("error")
                    or "Agent 返回错误"
                )
                final_status = TaskStatus.FAILED
                logger.warning(
                    f"[Worker {self.worker_id}] Agent 返回错误 | "
                    f"task={state.task_id} | error={error}"
                )
            else:
                logger.info(
                    f"[Worker {self.worker_id}] Agent 执行成功 | "
                    f"task={state.task_id}"
                )

        except asyncio.TimeoutError:
            final_status = TaskStatus.TIMEOUT
            error = f"任务超时 ({state.timeout_seconds}s)"
            logger.warning(
                f"[Worker {self.worker_id}] 任务超时 | "
                f"task={state.task_id} | timeout={state.timeout_seconds}s"
            )

        except asyncio.CancelledError:
            final_status = TaskStatus.CANCELLED
            error = "任务被取消"
            logger.info(
                f"[Worker {self.worker_id}] 任务被取消 | "
                f"task={state.task_id}"
            )
            # 取消不重试, 直接回调
            await dispatcher.complete(
                task_id=state.task_id,
                status=final_status,
                error=error,
                worker_id=self.worker_id,
            )
            self._reset()
            raise

        except Exception as e:
            final_status = TaskStatus.FAILED
            error = f"{type(e).__name__}: {e}"
            tb = traceback.format_exc()
            logger.error(
                f"[Worker {self.worker_id}] 任务异常 | "
                f"task={state.task_id} | error={error}\n{tb}"
            )

        # 统计
        duration_ms = int((time.time() - start_time) * 1000)
        self._tasks_done += 1
        if final_status == TaskStatus.FAILED:
            self._tasks_failed += 1

        # 收集事件
        events = self._collect_events(dispatcher, state)

        # 发布进度事件
        if final_status == TaskStatus.SUCCESS:
            self._emit_progress(
                dispatcher, state,
                status="success",
                message=f"Agent 执行完成 ({duration_ms}ms)",
                data={"result": result} if result else {},
            )
        else:
            self._emit_progress(
                dispatcher, state,
                status="error",
                message=error or "执行失败",
            )

        # 回调 Dispatcher
        await dispatcher.complete(
            task_id=state.task_id,
            status=final_status,
            result=result if final_status == TaskStatus.SUCCESS else None,
            error=error,
            events=events,
            worker_id=self.worker_id,
        )

        self._reset()

    # ---- Agent 调用 ----

    async def _invoke_agent(self, state: TaskState) -> Any:
        """通过 AgentFactory 创建 Agent 并执行

        关键: 不直接 new Agent, 通过 AgentFactory.create()
        """
        from app.agents.factory import AgentFactory

        agent = await AgentFactory.create(
            name=state.agent_name,
            runtime=None,  # 不依赖 AutoGen Runtime
            session_key=state.session_id or state.task_id,
        )

        if agent is None:
            raise ValueError(f"Agent 创建失败: {state.agent_name}")

        # 构造 payload
        payload = dict(state.payload)
        payload.setdefault("task_id", state.task_id)
        payload.setdefault("action", state.action)
        payload.setdefault("session_id", state.session_id)
        payload.setdefault("user_id", state.user_id)

        # 调用 Agent — 统一入口 agent.execute()
        if hasattr(agent, "execute"):
            # BaseRoutedAgent 路径
            try:
                from autogen_core import MessageContext, CancellationToken
                ctx = MessageContext(
                    sender=None,
                    topic_id=None,
                    is_rpc=False,
                    cancellation_token=CancellationToken(),
                    message_id=str(uuid.uuid4()),
                )
            except ImportError:
                ctx = None  # autogen_core 不可用时降级

            from app.runtime.execute_adapter import invoke_execute
            return await invoke_execute(agent, payload, ctx)

        elif hasattr(agent, "dispatch_action"):
            # 旧式 Agent
            result = agent.dispatch_action(state.action, payload)
            if asyncio.iscoroutine(result):
                result = await result
            return result

        elif hasattr(agent, state.action):
            # 直接方法调用
            method = getattr(agent, state.action)
            result = method(payload)
            if asyncio.iscoroutine(result):
                result = await result
            return result

        else:
            raise ValueError(
                f"Agent {state.agent_name} 无 execute/dispatch_action/{state.action} 方法"
            )

    # ---- 事件辅助 ----

    def _emit_progress(
        self,
        dispatcher: Any,
        state: TaskState,
        status: str = "running",
        message: str = "",
        data: Optional[Dict] = None,
    ) -> None:
        """发布进度事件"""
        collector = getattr(dispatcher, "_collector", None)
        if collector is None:
            return

        event = TaskEvent(
            task_id=state.task_id,
            event_type="progress",
            agent_name=state.agent_name,
            status=status,
            message=message,
            data=data or {},
        )

        try:
            task = asyncio.create_task(
                collector.record(state.task_id, event.to_dict())
            )
            self._pending_tasks.add(task)
            task.add_done_callback(self._pending_tasks.discard)
        except RuntimeError:
            pass

    def _collect_events(
        self,
        dispatcher: Any,
        state: TaskState,
    ) -> List[Dict[str, Any]]:
        """收集 Collector 中的事件"""
        collector = getattr(dispatcher, "_collector", None)
        if collector is None:
            return []

        try:
            events = collector.collect(state.task_id)
            if asyncio.iscoroutine(events):
                # 不阻塞, 返回空
                return []
            return events if isinstance(events, list) else []
        except Exception:
            return []

    def _reset(self) -> None:
        """重置 Worker 状态"""
        self._busy = False
        self._current_task = None

    def get_stats(self) -> Dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "busy": self._busy,
            "current_task": self._current_task,
            "tasks_done": self._tasks_done,
            "tasks_failed": self._tasks_failed,
        }


# ============================================================
# Worker Pool — Worker 池管理
# ============================================================

class WorkerPool:
    """Worker 池

    职责:
        1. 管理多个 AgentWorker
        2. asyncio.Semaphore 并发控制
        3. 分配任务给空闲 Worker
        4. 动态扩缩容

    设计:
        - Worker 是无状态的, 可复用
        - Semaphore 控制最大并发数
        - assign() 异步执行, 不阻塞 Dispatcher
    """

    def __init__(self, size: int = 4) -> None:
        self.size = size
        self._semaphore = asyncio.Semaphore(size)
        self._workers: List[AgentWorker] = [
            AgentWorker(worker_id=f"worker-{i}")
            for i in range(size)
        ]
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._started = False

    async def start(self) -> None:
        """启动 WorkerPool"""
        self._started = True
        logger.info(
            f"WorkerPool 启动 | size={self.size} | "
            f"workers={[w.worker_id for w in self._workers]}"
        )

    async def stop(self) -> None:
        """停止 WorkerPool"""
        self._started = False

        # 等待所有运行中任务完成 (最多 30 秒)
        if self._running_tasks:
            logger.info(f"等待 {len(self._running_tasks)} 个任务完成...")
            done, pending = await asyncio.wait(
                list(self._running_tasks.values()),
                timeout=30,
            )
            for task in pending:
                task.cancel()

        self._running_tasks.clear()
        logger.info("WorkerPool 已停止")

    async def assign(self, state: TaskState, dispatcher: Any) -> None:
        """分配任务给 Worker

        流程:
            1. 获取 Semaphore 许可 (阻塞直到有空闲)
            2. 选择空闲 Worker
            3. 异步执行 Worker.execute()
            4. 释放许可
        """
        # 等待空闲许可
        await self._semaphore.acquire()

        # 选择空闲 Worker
        worker = self._select_worker()
        if worker is None:
            self._semaphore.release()
            await dispatcher.complete(
                task_id=state.task_id,
                status=TaskStatus.FAILED,
                error="无可用 Worker",
            )
            return

        # 异步执行
        task = asyncio.create_task(
            self._run(worker, state, dispatcher)
        )
        self._running_tasks[state.task_id] = task

    async def _run(
        self,
        worker: AgentWorker,
        state: TaskState,
        dispatcher: Any,
    ) -> None:
        """执行 Worker 任务 (包装层)"""
        try:
            await worker.execute(state, dispatcher)
        except asyncio.CancelledError:
            logger.info(f"Worker 任务被取消: {state.task_id}")
        except Exception as e:
            logger.error(
                f"Worker 执行异常: {state.task_id} | {e}",
                exc_info=True,
            )
        finally:
            self._semaphore.release()
            self._running_tasks.pop(state.task_id, None)

    def _select_worker(self) -> Optional[AgentWorker]:
        """选择空闲 Worker"""
        for worker in self._workers:
            if not worker.is_busy:
                return worker
        # 所有 Worker 都忙时, 返回第一个 (Semaphore 已控制并发)
        return self._workers[0] if self._workers else None

    def resize(self, new_size: int) -> None:
        """动态调整 Worker 数量"""
        if new_size < 1:
            new_size = 1

        old_size = self.size
        if new_size > old_size:
            # 扩容
            for i in range(old_size, new_size):
                self._workers.append(
                    AgentWorker(worker_id=f"worker-{i}")
                )
        elif new_size < old_size:
            # 缩容 (只缩空闲的)
            idle_workers = [w for w in self._workers if not w.is_busy]
            while len(self._workers) > new_size and idle_workers:
                w = idle_workers.pop()
                self._workers.remove(w)

        self.size = len(self._workers)
        # 重建 Semaphore (需要新实例)
        self._semaphore = asyncio.Semaphore(self.size)
        logger.info(f"WorkerPool 扩缩容: {old_size} → {self.size}")

    def get_stats(self) -> Dict[str, Any]:
        return {
            "size": self.size,
            "started": self._started,
            "running_tasks": len(self._running_tasks),
            "idle_workers": sum(1 for w in self._workers if not w.is_busy),
            "busy_workers": sum(1 for w in self._workers if w.is_busy),
            "workers": [w.get_stats() for w in self._workers],
        }


# ============================================================
# 单例
# ============================================================

_worker_pool: Optional[WorkerPool] = None


def get_worker_pool(size: int = 4) -> WorkerPool:
    """获取 WorkerPool 单例"""
    global _worker_pool
    if _worker_pool is None:
        _worker_pool = WorkerPool(size=size)
    return _worker_pool


def reset_worker_pool() -> None:
    """重置 WorkerPool 单例 (测试用)"""
    global _worker_pool
    _worker_pool = None
