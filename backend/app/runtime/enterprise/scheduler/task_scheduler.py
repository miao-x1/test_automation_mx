"""
Task Scheduler - 任务调度器

核心职责:
    1. 定时任务调度 (周期性执行)
    2. 延迟任务 (指定时间后执行)
    3. 优先级排序 (调整任务执行顺序)
    4. 任务编排 (简单 DAG: A 完成后执行 B)

调度类型:
    - IMMEDIATE: 立即执行 (默认)
    - DELAYED:   延迟执行 (delay_seconds 后)
    - SCHEDULED: 定时执行 (按 cron_expression)
    - DEPENDENT: 依赖完成后执行 (after_task_ids)

使用方式:
    scheduler = get_task_scheduler()
    await scheduler.start()

    # 延迟任务
    await scheduler.schedule(TaskRequest(...), delay_seconds=60)

    # 定时任务 (每5分钟)
    await scheduler.schedule_cron(
        request=TaskRequest(...),
        cron_expression="*/5 * * * *",
    )

    # 依赖任务 (task-1 完成后执行 task-2)
    await scheduler.schedule_after(
        request=TaskRequest(...),
        after_task_ids=["task-1"],
    )
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from app.runtime.enterprise.dispatcher.task_dispatcher import (
    TaskDispatcher,
    TaskRequest,
)

logger = logging.getLogger(__name__)


# ============================================================
# 调度类型
# ============================================================

import enum


class ScheduleType(str, enum.Enum):
    """调度类型"""
    IMMEDIATE = "immediate"      # 立即执行
    DELAYED = "delayed"          # 延迟执行
    SCHEDULED = "scheduled"      # 定时执行
    DEPENDENT = "dependent"      # 依赖完成后执行


@dataclass
class ScheduledTask:
    """调度任务

    Attributes:
        schedule_id: 调度 ID
        request: 任务请求
        schedule_type: 调度类型
        delay_seconds: 延迟秒数 (DELAYED)
        cron_expression: cron 表达式 (SCHEDULED)
        after_task_ids: 依赖的 task_id 列表 (DEPENDENT)
        next_run_at: 下次执行时间 (时间戳)
        last_run_at: 上次执行时间
        run_count: 执行次数
        max_runs: 最大执行次数 (None=无限)
        enabled: 是否启用
    """
    schedule_id: str = field(default_factory=lambda: f"sched_{uuid.uuid4().hex[:10]}")
    request: TaskRequest = field(default_factory=lambda: TaskRequest(agent_name=""))
    schedule_type: ScheduleType = ScheduleType.IMMEDIATE
    delay_seconds: float = 0.0
    cron_expression: str = ""
    after_task_ids: List[str] = field(default_factory=list)
    next_run_at: Optional[float] = None
    last_run_at: Optional[float] = None
    run_count: int = 0
    max_runs: Optional[int] = None
    enabled: bool = True
    # 内部: 依赖已完成的 task_id 集合
    _completed_deps: Set[str] = field(default_factory=set, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schedule_id": self.schedule_id,
            "agent_name": self.request.agent_name,
            "action": self.request.action,
            "schedule_type": self.schedule_type.value,
            "delay_seconds": self.delay_seconds,
            "cron_expression": self.cron_expression,
            "after_task_ids": self.after_task_ids,
            "next_run_at": self.next_run_at,
            "last_run_at": self.last_run_at,
            "run_count": self.run_count,
            "max_runs": self.max_runs,
            "enabled": self.enabled,
        }


# ============================================================
# Task Scheduler
# ============================================================

class TaskScheduler:
    """任务调度器

    内部维护一个调度循环,定期检查所有 ScheduledTask:
        - DELAYED: 检查是否到时间
        - SCHEDULED: 解析 cron 表达式
        - DEPENDENT: 检查依赖是否完成
    """

    def __init__(self, dispatcher: Optional[TaskDispatcher] = None) -> None:
        self._dispatcher = dispatcher
        self._scheduled: Dict[str, ScheduledTask] = {}
        self._lock = asyncio.Lock()
        self._loop_task: Optional[asyncio.Task] = None
        self._started = False
        self._check_interval = 1.0  # 检查间隔 (秒)

    def set_dispatcher(self, dispatcher: TaskDispatcher) -> None:
        """注入 TaskDispatcher"""
        self._dispatcher = dispatcher
        logger.info("[TaskScheduler] Dispatcher 注入")

    # ----------------------------------------------------------
    # 生命周期
    # ----------------------------------------------------------

    async def start(self) -> None:
        """启动调度器"""
        if self._started:
            return
        self._started = True
        self._loop_task = asyncio.create_task(self._schedule_loop())
        logger.info("[TaskScheduler] 启动")

    async def stop(self) -> None:
        """停止调度器"""
        if not self._started:
            return
        self._started = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None
        logger.info("[TaskScheduler] 已停止")

    # ----------------------------------------------------------
    # 调度接口
    # ----------------------------------------------------------

    async def schedule(
        self,
        request: TaskRequest,
        delay_seconds: float = 0.0,
    ) -> str:
        """调度任务

        Args:
            request: 任务请求
            delay_seconds: 延迟秒数 (0=立即)

        Returns:
            schedule_id
        """
        if delay_seconds > 0:
            task = ScheduledTask(
                request=request,
                schedule_type=ScheduleType.DELAYED,
                delay_seconds=delay_seconds,
                next_run_at=time.time() + delay_seconds,
            )
        else:
            # 立即执行: 直接提交给 Dispatcher
            if self._dispatcher:
                await self._dispatcher.submit(request)
                return "immediate"
            task = ScheduledTask(
                request=request,
                schedule_type=ScheduleType.IMMEDIATE,
            )

        async with self._lock:
            self._scheduled[task.schedule_id] = task
        logger.info(
            f"[TaskScheduler] 调度任务 | id={task.schedule_id} | "
            f"type={task.schedule_type.value} | agent={request.agent_name}"
        )
        return task.schedule_id

    async def schedule_cron(
        self,
        request: TaskRequest,
        cron_expression: str,
        max_runs: Optional[int] = None,
    ) -> str:
        """定时调度 (cron 表达式)

        Args:
            request: 任务请求
            cron_expression: cron 表达式 (5字段: 分 时 日 月 周)
            max_runs: 最大执行次数 (None=无限)

        Returns:
            schedule_id
        """
        next_run = self._calc_next_cron(cron_expression)
        task = ScheduledTask(
            request=request,
            schedule_type=ScheduleType.SCHEDULED,
            cron_expression=cron_expression,
            next_run_at=next_run,
            max_runs=max_runs,
        )
        async with self._lock:
            self._scheduled[task.schedule_id] = task
        logger.info(
            f"[TaskScheduler] 定时任务 | id={task.schedule_id} | "
            f"cron={cron_expression} | next_run={datetime.fromtimestamp(next_run)}"
        )
        return task.schedule_id

    async def schedule_after(
        self,
        request: TaskRequest,
        after_task_ids: List[str],
    ) -> str:
        """依赖调度 (指定任务完成后执行)

        Args:
            request: 任务请求
            after_task_ids: 依赖的 task_id 列表 (全部完成后才执行)

        Returns:
            schedule_id
        """
        task = ScheduledTask(
            request=request,
            schedule_type=ScheduleType.DEPENDENT,
            after_task_ids=list(after_task_ids),
        )
        async with self._lock:
            self._scheduled[task.schedule_id] = task

        # 注册依赖完成回调
        for dep_task_id in after_task_ids:
            asyncio.create_task(self._wait_for_dependency(task.schedule_id, dep_task_id))

        logger.info(
            f"[TaskScheduler] 依赖任务 | id={task.schedule_id} | "
            f"after={after_task_ids}"
        )
        return task.schedule_id

    async def cancel(self, schedule_id: str) -> bool:
        """取消调度任务"""
        async with self._lock:
            task = self._scheduled.pop(schedule_id, None)
        if task is None:
            return False
        task.enabled = False
        logger.info(f"[TaskScheduler] 取消调度: {schedule_id}")
        return True

    async def list_schedules(self, enabled_only: bool = False) -> List[ScheduledTask]:
        """列出所有调度任务"""
        async with self._lock:
            tasks = list(self._scheduled.values())
        if enabled_only:
            tasks = [t for t in tasks if t.enabled]
        return tasks

    # ----------------------------------------------------------
    # 内部: 调度循环
    # ----------------------------------------------------------

    async def _schedule_loop(self) -> None:
        """调度循环"""
        logger.info("[TaskScheduler] 调度循环启动")
        while self._started:
            try:
                now = time.time()
                to_run: List[ScheduledTask] = []

                async with self._lock:
                    for task in self._scheduled.values():
                        if not task.enabled:
                            continue
                        if task.max_runs is not None and task.run_count >= task.max_runs:
                            continue
                        if task.schedule_type == ScheduleType.DELAYED:
                            if task.next_run_at and now >= task.next_run_at:
                                to_run.append(task)
                        elif task.schedule_type == ScheduleType.SCHEDULED:
                            if task.next_run_at and now >= task.next_run_at:
                                to_run.append(task)
                        elif task.schedule_type == ScheduleType.DEPENDENT:
                            if task._completed_deps == set(task.after_task_ids):
                                to_run.append(task)

                # 执行到期任务
                for task in to_run:
                    asyncio.create_task(self._run_scheduled(task))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[TaskScheduler] 调度循环异常: {e}", exc_info=True)

            await asyncio.sleep(self._check_interval)

        logger.info("[TaskScheduler] 调度循环结束")

    async def _run_scheduled(self, task: ScheduledTask) -> None:
        """执行调度任务"""
        if self._dispatcher is None:
            logger.warning("[TaskScheduler] 无 Dispatcher,跳过执行")
            return

        try:
            task_id = await self._dispatcher.submit(task.request)
            task.last_run_at = time.time()
            task.run_count += 1

            # 更新下次执行时间 (定时任务)
            if task.schedule_type == ScheduleType.SCHEDULED and task.cron_expression:
                task.next_run_at = self._calc_next_cron(task.cron_expression)
            elif task.schedule_type == ScheduleType.DEPENDENT:
                # 依赖任务执行一次后移除
                async with self._lock:
                    self._scheduled.pop(task.schedule_id, None)

            # 达到最大执行次数: 禁用
            if task.max_runs is not None and task.run_count >= task.max_runs:
                task.enabled = False
                logger.info(
                    f"[TaskScheduler] 达到最大执行次数 | id={task.schedule_id} | "
                    f"runs={task.run_count}"
                )

            logger.info(
                f"[TaskScheduler] 调度执行 | id={task.schedule_id} | "
                f"task_id={task_id} | runs={task.run_count}"
            )

        except Exception as e:
            logger.error(
                f"[TaskScheduler] 调度执行失败 | id={task.schedule_id} | error={e}",
                exc_info=True,
            )

    async def _wait_for_dependency(self, schedule_id: str, dep_task_id: str) -> None:
        """等待依赖任务完成"""
        if self._dispatcher is None:
            return
        try:
            # 等待依赖任务结果
            await self._dispatcher.wait_for_result(dep_task_id, timeout=3600)
            async with self._lock:
                task = self._scheduled.get(schedule_id)
                if task:
                    task._completed_deps.add(dep_task_id)
                    logger.info(
                        f"[TaskScheduler] 依赖完成 | id={schedule_id} | "
                        f"dep={dep_task_id}"
                    )
        except Exception as e:
            logger.warning(
                f"[TaskScheduler] 依赖等待失败 | id={schedule_id} | "
                f"dep={dep_task_id} | error={e}"
            )

    # ----------------------------------------------------------
    # 内部: cron 解析 (简化版)
    # ----------------------------------------------------------

    def _calc_next_cron(self, cron_expr: str) -> float:
        """计算下次执行时间 (简化版 cron)

        支持:
            *       : 任意值
            */N     : 每 N 个单位
            N       : 指定值
            N-M     : 范围

        5 字段: 分 时 日 月 周
        """
        try:
            parts = cron_expr.strip().split()
            if len(parts) != 5:
                # 非法 cron, 默认 60 秒后
                return time.time() + 60

            minute, hour, day, month, weekday = parts
            now = datetime.now()

            # 简化: 精确匹配下一个分钟
            # 完整实现请用 croniter 库
            if minute == "*":
                return time.time() + 60
            elif minute.startswith("*/"):
                n = int(minute[2:])
                return time.time() + n * 60
            else:
                # 指定分钟: 今天的下一个该分钟
                target_minute = int(minute)
                next_run = now.replace(
                    second=0, microsecond=0,
                    minute=target_minute if target_minute > now.minute else target_minute,
                )
                if target_minute <= now.minute:
                    next_run = next_run.replace(hour=now.hour + 1 if now.hour < 23 else 0)
                return next_run.timestamp()

        except Exception as e:
            logger.warning(f"[TaskScheduler] cron 解析失败: {cron_expr} | error={e}")
            return time.time() + 60

    # ----------------------------------------------------------
    # 统计
    # ----------------------------------------------------------

    async def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        async with self._lock:
            return {
                "started": self._started,
                "total_schedules": len(self._scheduled),
                "enabled_schedules": sum(1 for t in self._scheduled.values() if t.enabled),
                "by_type": {
                    t.schedule_type.value: sum(
                        1 for s in self._scheduled.values()
                        if s.schedule_type == t.schedule_type
                    )
                    for t in [ScheduledTask(schedule_type=st) for st in ScheduleType]
                },
                "dispatcher": (
                    type(self._dispatcher).__name__
                    if self._dispatcher else None
                ),
            }


# ============================================================
# 单例
# ============================================================

_scheduler: Optional[TaskScheduler] = None


def get_task_scheduler(dispatcher: Optional[TaskDispatcher] = None) -> TaskScheduler:
    """获取全局 TaskScheduler 单例"""
    global _scheduler
    if _scheduler is None:
        _scheduler = TaskScheduler(dispatcher=dispatcher)
        logger.info("[TaskScheduler] 单例创建")
    return _scheduler
