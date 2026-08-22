"""
Runtime v2 — Task Scheduler

职责:
    1. 立即执行 (IMMEDIATE)
    2. 延迟执行 (DELAYED)
    3. 定时执行 (SCHEDULED, cron)
    4. 依赖执行 (DEPENDENT, 前置任务完成后触发)

核心设计:
    - TaskScheduler 内部维护一个调度循环
    - 到期任务自动提交给 Dispatcher
    - 支持 cron 表达式 (简化版: */N * * * *)
    - 依赖任务: 监听前置任务的 Future 完成后自动提交

使用方式:
    from app.runtime.v2.scheduler import get_scheduler

    # 立即执行
    task_id = await scheduler.submit_now(TaskRequest(agent_name="..."))

    # 延迟 60 秒执行
    task_id = await scheduler.submit_delayed(TaskRequest(...), delay_seconds=60)

    # 定时执行 (每 5 分钟)
    task_id = await scheduler.submit_scheduled(TaskRequest(...), cron="*/5 * * * *")

    # 依赖执行 (前置完成后触发)
    task_id = await scheduler.submit_dependent(TaskRequest(...), depends_on=prev_task_id)
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.runtime.v2.state import TaskRequest

logger = logging.getLogger(__name__)


# ============================================================
# 调度类型
# ============================================================

class ScheduleType:
    """调度类型"""
    IMMEDIATE = "immediate"    # 立即执行
    DELAYED = "delayed"         # 延迟执行
    SCHEDULED = "scheduled"     # 定时执行 (cron)
    DEPENDENT = "dependent"     # 依赖执行


@dataclass
class ScheduledTask:
    """调度任务定义"""
    schedule_id: str
    request: TaskRequest
    schedule_type: str = ScheduleType.IMMEDIATE
    delay_seconds: int = 0
    cron: Optional[str] = None
    depends_on: Optional[str] = None  # 前置 task_id
    next_run: Optional[float] = None  # 下次执行时间戳
    last_run: Optional[float] = None  # 上次执行时间戳
    run_count: int = 0
    is_active: bool = True


# ============================================================
# Cron 解析 (简化版)
# ============================================================

class CronParser:
    """简化版 cron 解析器

    支持格式: "*/N * * * *" 或 "M H D M W"
    五个字段: minute hour day-of-month month day-of-week
    支持: *, */N, 具体数字
    """

    @staticmethod
    def next_run(cron: str, from_time: Optional[float] = None) -> float:
        """计算下次执行时间

        Returns:
            下次执行的时间戳 (Unix timestamp)
        """
        if from_time is None:
            from_time = time.time()

        now = datetime.fromtimestamp(from_time)
        parts = cron.strip().split()

        if len(parts) != 5:
            # 格式错误, 默认 1 分钟后
            return from_time + 60

        minute, hour, day, month, weekday = parts

        # 从下一分钟开始搜索
        search = now.replace(second=0, microsecond=0) + timedelta(minutes=1)

        # 最多搜索 7 天
        for _ in range(7 * 24 * 60):
            if (
                CronParser._match(search.minute, minute)
                and CronParser._match(search.hour, hour)
                and CronParser._match(search.day, day)
                and CronParser._match(search.month, month)
                and CronParser._match(search.weekday() + 1 if search.weekday() < 6 else 0, weekday)
            ):
                return search.timestamp()
            search += timedelta(minutes=1)

        return from_time + 86400  # 默认 1 天后

    @staticmethod
    def _match(value: int, pattern: str) -> bool:
        """匹配单个字段"""
        if pattern == "*":
            return True
        if pattern.startswith("*/"):
            try:
                n = int(pattern[2:])
                return n > 0 and value % n == 0
            except ValueError:
                return False
        try:
            return value == int(pattern)
        except ValueError:
            return False


# ============================================================
# Task Scheduler
# ============================================================

class TaskScheduler:
    """任务调度器

    生命周期:
        start() → 调度循环 → 到期任务 submit 到 Dispatcher → stop()

    调度循环:
        每 1 秒检查一次, 将到期的延迟/定时任务提交给 Dispatcher
    """

    def __init__(self, dispatcher: Any = None) -> None:
        self._dispatcher = dispatcher
        self._scheduled: Dict[str, ScheduledTask] = {}
        self._started = False
        self._loop_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    # ---- 依赖注入 ----

    def set_dispatcher(self, dispatcher: Any) -> None:
        """注入 Dispatcher"""
        self._dispatcher = dispatcher
        logger.info("TaskScheduler 已绑定 Dispatcher")

    # ---- 生命周期 ----

    async def start(self) -> None:
        """启动调度器"""
        if self._started:
            return
        self._started = True
        self._loop_task = asyncio.create_task(self._schedule_loop())
        logger.info("TaskScheduler 启动")

    async def stop(self) -> None:
        """停止调度器"""
        self._started = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        logger.info("TaskScheduler 已停止")

    # ---- 提交调度 ----

    async def submit_now(self, request: TaskRequest) -> str:
        """立即执行"""
        if not self._dispatcher:
            raise RuntimeError("Dispatcher 未绑定")

        task_id = await self._dispatcher.submit(request)
        return task_id

    async def submit_delayed(
        self, request: TaskRequest, delay_seconds: int
    ) -> str:
        """延迟执行"""
        import uuid
        schedule_id = f"sched-{uuid.uuid4().hex[:8]}"

        scheduled = ScheduledTask(
            schedule_id=schedule_id,
            request=request,
            schedule_type=ScheduleType.DELAYED,
            delay_seconds=delay_seconds,
            next_run=time.time() + delay_seconds,
        )

        async with self._lock:
            self._scheduled[schedule_id] = scheduled

        logger.info(
            f"延迟任务调度 | id={schedule_id} | "
            f"agent={request.agent_name} | delay={delay_seconds}s"
        )
        return schedule_id

    async def submit_scheduled(
        self, request: TaskRequest, cron: str
    ) -> str:
        """定时执行 (cron)"""
        import uuid
        schedule_id = f"sched-{uuid.uuid4().hex[:8]}"

        next_run = CronParser.next_run(cron)

        scheduled = ScheduledTask(
            schedule_id=schedule_id,
            request=request,
            schedule_type=ScheduleType.SCHEDULED,
            cron=cron,
            next_run=next_run,
        )

        async with self._lock:
            self._scheduled[schedule_id] = scheduled

        logger.info(
            f"定时任务调度 | id={schedule_id} | "
            f"agent={request.agent_name} | cron={cron} | "
            f"next_run={datetime.fromtimestamp(next_run).isoformat()}"
        )
        return schedule_id

    async def submit_dependent(
        self, request: TaskRequest, depends_on: str
    ) -> str:
        """依赖执行 — 前置任务完成后触发"""
        import uuid
        schedule_id = f"sched-{uuid.uuid4().hex[:8]}"

        scheduled = ScheduledTask(
            schedule_id=schedule_id,
            request=request,
            schedule_type=ScheduleType.DEPENDENT,
            depends_on=depends_on,
        )

        async with self._lock:
            self._scheduled[schedule_id] = scheduled

        # 监听前置任务完成
        if self._dispatcher:
            asyncio.create_task(
                self._wait_for_dependency(schedule_id, depends_on)
            )

        logger.info(
            f"依赖任务调度 | id={schedule_id} | "
            f"agent={request.agent_name} | depends_on={depends_on}"
        )
        return schedule_id

    async def _wait_for_dependency(
        self, schedule_id: str, depends_on: str
    ) -> None:
        """等待前置任务完成"""
        try:
            result = await self._dispatcher.wait_for_result(depends_on)
            if result and result.is_success:
                # 前置成功, 提交当前任务
                async with self._lock:
                    scheduled = self._scheduled.get(schedule_id)
                    if scheduled and scheduled.is_active:
                        scheduled.next_run = time.time()
            else:
                # 前置失败, 取消依赖任务
                async with self._lock:
                    scheduled = self._scheduled.get(schedule_id)
                    if scheduled:
                        scheduled.is_active = False
                logger.info(
                    f"依赖任务取消 (前置失败) | id={schedule_id}"
                )
        except Exception as e:
            logger.error(f"依赖等待异常 | id={schedule_id} | {e}")

    # ---- 调度循环 ----

    async def _schedule_loop(self) -> None:
        """调度循环 — 每 1 秒检查到期任务"""
        logger.info("TaskScheduler 调度循环启动")

        while self._started:
            try:
                now = time.time()
                to_run: List[ScheduledTask] = []

                async with self._lock:
                    for scheduled in self._scheduled.values():
                        if not scheduled.is_active:
                            continue
                        if scheduled.next_run and scheduled.next_run <= now:
                            to_run.append(scheduled)

                # 提交到期任务
                for scheduled in to_run:
                    await self._execute_scheduled(scheduled)

                await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"调度循环异常: {e}", exc_info=True)
                await asyncio.sleep(5)

        logger.info("TaskScheduler 调度循环结束")

    async def _execute_scheduled(self, scheduled: ScheduledTask) -> None:
        """执行调度任务"""
        try:
            task_id = await self._dispatcher.submit(scheduled.request)
            scheduled.last_run = time.time()
            scheduled.run_count += 1

            logger.info(
                f"调度任务执行 | id={scheduled.schedule_id} | "
                f"task={task_id} | run_count={scheduled.run_count}"
            )

            # 计算下次执行时间
            if scheduled.schedule_type == ScheduleType.SCHEDULED:
                scheduled.next_run = CronParser.next_run(scheduled.cron)
            elif scheduled.schedule_type == ScheduleType.DELAYED:
                # 延迟任务执行一次后停用
                scheduled.is_active = False
            elif scheduled.schedule_type == ScheduleType.DEPENDENT:
                # 依赖任务执行一次后停用
                scheduled.is_active = False

        except Exception as e:
            logger.error(
                f"调度任务执行失败 | id={scheduled.schedule_id} | {e}"
            )

    # ---- 管理 ----

    def cancel_schedule(self, schedule_id: str) -> bool:
        """取消调度"""
        scheduled = self._scheduled.get(schedule_id)
        if scheduled:
            scheduled.is_active = False
            return True
        return False

    def list_schedules(self) -> List[Dict[str, Any]]:
        """列出所有调度"""
        return [
            {
                "schedule_id": s.schedule_id,
                "agent_name": s.request.agent_name,
                "schedule_type": s.schedule_type,
                "cron": s.cron,
                "delay_seconds": s.delay_seconds,
                "depends_on": s.depends_on,
                "next_run": datetime.fromtimestamp(s.next_run).isoformat() if s.next_run else None,
                "last_run": datetime.fromtimestamp(s.last_run).isoformat() if s.last_run else None,
                "run_count": s.run_count,
                "is_active": s.is_active,
            }
            for s in self._scheduled.values()
        ]

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_schedules": len(self._scheduled),
            "active": sum(1 for s in self._scheduled.values() if s.is_active),
            "started": self._started,
        }


# ============================================================
# 单例
# ============================================================

_scheduler: Optional[TaskScheduler] = None


def get_scheduler(dispatcher: Any = None) -> TaskScheduler:
    """获取 Scheduler 单例"""
    global _scheduler
    if _scheduler is None:
        _scheduler = TaskScheduler(dispatcher=dispatcher)
    return _scheduler


def reset_scheduler() -> None:
    """重置 Scheduler 单例 (测试用)"""
    global _scheduler
    _scheduler = None
