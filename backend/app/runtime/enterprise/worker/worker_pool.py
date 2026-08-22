"""
Worker Pool - Worker 池管理

职责:
    1. 维护一组 AgentWorker
    2. 接收 Dispatcher 分配的任务
    3. 选择空闲 Worker 执行
    4. 支持动态扩缩容
    5. 监控 Worker 健康

并发模型:
    - 每个 Worker 一次执行一个任务
    - WorkerPool 内部用 asyncio.Semaphore 控制并发
    - 任务队列: 当所有 Worker 都忙时,任务等待
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Dict, List, Optional

from app.runtime.enterprise.worker.agent_worker import AgentWorker
from app.runtime.enterprise.dispatcher.task_state import TaskState, TaskStatus

logger = logging.getLogger(__name__)


class WorkerPool:
    """Worker 池

    使用方式:
        pool = WorkerPool(size=4)
        await pool.start()
        dispatcher.set_worker_pool(pool)
        # ...
        await pool.stop()
    """

    def __init__(
        self,
        size: int = 4,
        dispatcher: Any = None,
    ) -> None:
        self.size = size
        self.dispatcher = dispatcher
        self._workers: List[AgentWorker] = []
        self._semaphore = asyncio.Semaphore(size)
        self._running_tasks: Dict[str, asyncio.Task] = {}  # task_id → asyncio.Task
        self._started = False
        self._lock = asyncio.Lock()

        # 创建 Worker
        for i in range(size):
            worker = AgentWorker(
                worker_id=f"worker-{i+1:03d}",
                worker_pool=self,
            )
            self._workers.append(worker)

    # ----------------------------------------------------------
    # 生命周期
    # ----------------------------------------------------------

    async def start(self) -> None:
        """启动 WorkerPool"""
        if self._started:
            return
        self._started = True
        logger.info(
            f"[WorkerPool] 启动 | size={self.size} | "
            f"workers={[w.worker_id for w in self._workers]}"
        )

    async def stop(self) -> None:
        """停止 WorkerPool

        等待所有正在执行的任务完成 (或超时)。
        """
        if not self._started:
            return
        self._started = False

        # 取消所有运行中的任务
        async with self._lock:
            pending = list(self._running_tasks.values())

        if pending:
            logger.info(f"[WorkerPool] 等待 {len(pending)} 个任务完成...")
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

        self._running_tasks.clear()
        logger.info("[WorkerPool] 已停止")

    def set_dispatcher(self, dispatcher: Any) -> None:
        """注入 Dispatcher"""
        self.dispatcher = dispatcher

    # ----------------------------------------------------------
    # 任务分配
    # ----------------------------------------------------------

    async def assign(self, state: TaskState) -> None:
        """接收 Dispatcher 分配的任务

        选择空闲 Worker 执行。如果所有 Worker 都忙,任务会等待。

        Args:
            state: 任务状态
        """
        if not self._started:
            logger.warning(f"[WorkerPool] 未启动,拒绝任务: {state.task_id}")
            if self.dispatcher:
                await self.dispatcher.complete(
                    task_id=state.task_id,
                    status=TaskStatus.FAILED,
                    error="WorkerPool 未启动",
                )
            return

        # 获取信号量 (等待空闲 Worker)
        await self._semaphore.acquire()

        # 选择空闲 Worker
        worker = self._select_worker()
        if worker is None:
            self._semaphore.release()
            logger.error(f"[WorkerPool] 无可用 Worker (task={state.task_id})")
            if self.dispatcher:
                await self.dispatcher.complete(
                    task_id=state.task_id,
                    status=TaskStatus.FAILED,
                    error="无可用 Worker",
                )
            return

        # 立即标记 Worker 为忙碌 (避免并发分配到同一 Worker)
        worker._busy = True
        worker._current_task = state.task_id

        # 创建执行任务
        async def _run():
            try:
                await worker.execute(state, self.dispatcher)
            except asyncio.CancelledError:
                logger.info(f"[WorkerPool] 任务取消: {state.task_id}")
                if self.dispatcher:
                    await self.dispatcher.complete(
                        task_id=state.task_id,
                        status=TaskStatus.CANCELLED,
                        error="任务被取消",
                    )
            except Exception as e:
                logger.error(
                    f"[WorkerPool] Worker 异常: {e}",
                    exc_info=True,
                )
                if self.dispatcher:
                    await self.dispatcher.complete(
                        task_id=state.task_id,
                        status=TaskStatus.FAILED,
                        error=str(e),
                    )
            finally:
                # 确保 Worker 重置 (execute 内部也会 reset,这里是兜底)
                worker._busy = False
                worker._current_task = None
                self._semaphore.release()
                async with self._lock:
                    self._running_tasks.pop(state.task_id, None)

        async with self._lock:
            task = asyncio.create_task(_run())
            self._running_tasks[state.task_id] = task

        logger.info(
            f"[WorkerPool] 任务分配 | task={state.task_id} | "
            f"worker={worker.worker_id}"
        )

    def _select_worker(self) -> Optional[AgentWorker]:
        """选择空闲 Worker (轮询)"""
        for worker in self._workers:
            if not worker.is_busy:
                return worker
        return None

    # ----------------------------------------------------------
    # 扩缩容
    # ----------------------------------------------------------

    async def resize(self, new_size: int) -> None:
        """动态调整 Worker 数量

        Args:
            new_size: 新的 Worker 数量
        """
        if new_size < 1:
            raise ValueError("Worker 数量必须 >= 1")

        async with self._lock:
            if new_size > self.size:
                # 扩容
                for i in range(self.size, new_size):
                    worker = AgentWorker(
                        worker_id=f"worker-{i+1:03d}",
                        worker_pool=self,
                    )
                    self._workers.append(worker)
                logger.info(f"[WorkerPool] 扩容: {self.size} → {new_size}")
            elif new_size < self.size:
                # 缩容 (等待空闲 Worker 退出)
                to_remove = self.size - new_size
                removed = []
                for worker in list(self._workers):
                    if not worker.is_busy and len(removed) < to_remove:
                        self._workers.remove(worker)
                        removed.append(worker.worker_id)
                logger.info(
                    f"[WorkerPool] 缩容: {self.size} → {len(self._workers)} "
                    f"(移除: {removed})"
                )

            self.size = new_size
            # 重建信号量
            self._semaphore = asyncio.Semaphore(new_size)

    # ----------------------------------------------------------
    # 状态查询
    # ----------------------------------------------------------

    async def get_busy_count(self) -> int:
        """获取忙碌 Worker 数量"""
        return sum(1 for w in self._workers if w.is_busy)

    async def get_idle_count(self) -> int:
        """获取空闲 Worker 数量"""
        return sum(1 for w in self._workers if not w.is_busy)

    def get_worker_stats(self) -> List[Dict[str, Any]]:
        """获取所有 Worker 的统计信息"""
        return [w.stats() for w in self._workers]

    async def get_stats(self) -> Dict[str, Any]:
        """获取 WorkerPool 统计信息"""
        busy = await self.get_busy_count()
        idle = await self.get_idle_count()
        return {
            "size": self.size,
            "started": self._started,
            "busy_workers": busy,
            "idle_workers": idle,
            "running_tasks": len(self._running_tasks),
            "workers": self.get_worker_stats(),
        }


# ============================================================
# 单例
# ============================================================

_worker_pool: Optional[WorkerPool] = None


def get_worker_pool(size: int = 4) -> WorkerPool:
    """获取全局 WorkerPool 单例

    Args:
        size: Worker 数量 (仅首次调用生效)
    """
    global _worker_pool
    if _worker_pool is None:
        _worker_pool = WorkerPool(size=size)
        logger.info(f"[WorkerPool] 单例创建 | size={size}")
    return _worker_pool
