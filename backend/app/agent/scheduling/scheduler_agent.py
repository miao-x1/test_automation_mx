"""
SchedulerAgent - 定时任务调度Agent

负责：
1. 启动时加载活跃任务到调度器
2. 创建/更新/暂停/启用调度任务
3. 触发执行 → TaskExecutor
4. 执行结果通知
"""
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from app.core.logger import log
from app.models.schedule_task import ScheduleType, ScheduleStatus
from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability


# 全局调度器实例
_scheduler: Optional[AsyncIOScheduler] = None


def get_scheduler() -> AsyncIOScheduler:
    """获取全局调度器"""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    return _scheduler


class SchedulerAgent(NewBaseAgent):
    """定时任务调度Agent"""

    agent_name = "scheduler"
    display_name = "Scheduler Agent"
    description = "定时任务调度Agent - 负责定时任务的加载、调度与触发执行"
    capabilities = [AgentCapability.SCHEDULE]

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)
        self.scheduler = get_scheduler()

    def start(self):
        """启动调度器并加载活跃任务"""
        if not self.scheduler.running:
            self.scheduler.start()
            log.info("APScheduler调度器已启动")

        # 加载所有活跃任务
        self._load_active_tasks()
        log.info("定时任务加载完成")

    def stop(self):
        """停止调度器"""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            log.info("APScheduler调度器已停止")

    def _load_active_tasks(self):
        """加载所有活跃的定时任务"""
        from app.services.context_router import get_context_router, ContextType

        router = get_context_router()
        result = router.query(
            "",
            ContextType.SCHEDULE_TASK,
            top_k=200,
            filters={"status": ScheduleStatus.ACTIVE},
        )
        tasks = result.get("results", [])
        loaded = 0
        for task in tasks:
            try:
                self._add_job(task)
                loaded += 1
            except Exception as e:
                log.error(f"加载定时任务失败 | task_id={task.get('id')}, name={task.get('name')}, error={e}")
        log.info(f"已加载 {loaded}/{len(tasks)} 个定时任务")

    def add_task(self, task):
        """添加定时任务到调度器

        Note: task 可以是 ORM 对象或 dict，内部统一按 dict 处理。
        """
        if not isinstance(task, dict):
            task = task.to_dict() if hasattr(task, "to_dict") else dict(task)
        self._add_job(task)

    def remove_task(self, task_id: int):
        """从调度器移除任务"""
        job_id = f"schedule_task_{task_id}"
        try:
            self.scheduler.remove_job(job_id)
            log.info(f"已移除调度任务 | job_id={job_id}")
        except Exception:
            pass

    def pause_task(self, task_id: int):
        """暂停任务"""
        job_id = f"schedule_task_{task_id}"
        try:
            self.scheduler.pause_job(job_id)
        except Exception:
            pass

    def resume_task(self, task_id: int):
        """恢复任务"""
        job_id = f"schedule_task_{task_id}"
        try:
            self.scheduler.resume_job(job_id)
        except Exception:
            pass

    def _add_job(self, task: dict):
        """添加调度Job"""
        from app.services.context_router.storage_router import get_storage_router

        task_id = int(task.get("id"))
        job_id = f"schedule_task_{task_id}"

        # 构建触发器
        trigger = self._build_trigger(task)
        if not trigger:
            log.warning(f"无法构建触发器 | task_id={task_id}, type={task.get('schedule_type')}")
            return

        # 添加Job
        self.scheduler.add_job(
            _execute_schedule_task,
            trigger=trigger,
            id=job_id,
            args=[task_id],
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=60,
        )

        # 更新下次执行时间
        job = self.scheduler.get_job(job_id)
        if job and job.next_run_time:
            storage = get_storage_router()
            storage.mysql_update("ScheduleTask", record_id=task_id, data={"next_run_at": job.next_run_time.replace(tzinfo=None)})

        log.info(f"调度任务已添加 | id={task_id}, name={task.get('name')}, type={task.get('schedule_type')}")

    def _build_trigger(self, task: dict):
        """构建触发器"""
        try:
            task_id = task.get("id")
            start_time = task.get("start_time")
            end_time = task.get("end_time")
            start_date = start_time.isoformat() if start_time and hasattr(start_time, "isoformat") else (start_time if start_time else None)
            end_date = end_time.isoformat() if end_time and hasattr(end_time, "isoformat") else (end_time if end_time else None)

            schedule_type = task.get("schedule_type")
            if schedule_type == ScheduleType.ONCE:
                # 一次性执行
                execute_date = task.get("execute_date")
                execute_time = task.get("execute_time")
                if execute_date and execute_time:
                    run_time = datetime.strptime(f"{execute_date} {execute_time}", "%Y-%m-%d %H:%M")
                elif execute_date:
                    run_time = datetime.strptime(execute_date, "%Y-%m-%d")
                else:
                    return None
                return DateTrigger(run_date=run_time)

            elif schedule_type == ScheduleType.DAILY:
                # 每日执行
                hour, minute = 8, 0
                execute_time = task.get("execute_time")
                if execute_time:
                    parts = execute_time.split(":")
                    hour = int(parts[0])
                    minute = int(parts[1]) if len(parts) > 1 else 0
                return CronTrigger(
                    hour=hour, minute=minute,
                    start_date=start_date, end_date=end_date,
                )

            elif schedule_type == ScheduleType.CRON:
                # Cron表达式
                cron_expression = task.get("cron_expression")
                if cron_expression:
                    parts = cron_expression.strip().split()
                    if len(parts) == 5:
                        return CronTrigger(
                            minute=parts[0], hour=parts[1],
                            day=parts[2], month=parts[3],
                            day_of_week=parts[4],
                            start_date=start_date, end_date=end_date,
                        )
                return None

        except Exception as e:
            log.error(f"构建触发器失败 | task_id={task.get('id')}, error={e}")
            return None


async def _execute_schedule_task(task_id: int):
    """调度器回调：执行定时任务"""
    from app.agent.scheduling.task_executor import TaskExecutor
    from app.services.context_router import get_context_router, ContextType
    from app.services.context_router.storage_router import get_storage_router

    router = get_context_router()
    storage = get_storage_router()
    run_log_id = None
    started_at = None

    try:
        task = router.query_by_id(ContextType.SCHEDULE_TASK, record_id=task_id)
        if not task:
            log.warning(f"定时任务不存在 | id={task_id}")
            return

        # 检查有效时间
        now = datetime.now()
        end_time = task.get("end_time")
        if end_time and now > end_time:
            storage.mysql_update("ScheduleTask", record_id=task_id, data={"status": ScheduleStatus.EXPIRED})
            log.info(f"定时任务已过期 | id={task_id}")
            return

        # 累计执行次数
        current_run_count = task.get("run_count", 0) or 0
        new_run_count = current_run_count + 1

        # 创建执行日志
        started_at = now
        run_log_id = storage.mysql_save("ScheduleRunLog", {
            "schedule_task_id": task_id,
            "run_number": new_run_count,
            "status": "running",
            "trigger_type": "schedule",
            "started_at": now,
            "user_id": task.get("user_id"),
            "created_by": task.get("user_id"),
        })

        log.info(f"定时任务开始执行 | id={task_id}, name={task.get('name')}, run=#{new_run_count}")

        # 执行任务
        executor = TaskExecutor()
        result = await executor.execute(task, {"id": run_log_id, "started_at": started_at}, None)

        # 更新执行日志
        finished_at = datetime.now()
        duration = (finished_at - started_at).seconds if started_at else 0
        run_status = result.get("status", "failed")
        run_log_update = {
            "status": run_status,
            "finished_at": finished_at,
            "duration": duration,
            "result_summary": result.get("summary", ""),
            "error_message": result.get("error", ""),
            "task_id": result.get("task_id"),
            "retry_count": result.get("retry_count", 0),
        }
        if run_log_id:
            storage.mysql_update("ScheduleRunLog", record_id=run_log_id, data=run_log_update)

        # 更新任务状态
        task_update = {
            "last_run_at": now,
            "last_run_status": run_status,
            "run_count": new_run_count,
        }
        if run_status == "failed":
            current_fail_count = task.get("fail_count", 0) or 0
            task_update["fail_count"] = current_fail_count + 1

        # 更新下次执行时间
        job_id = f"schedule_task_{task_id}"
        scheduler = get_scheduler()
        job = scheduler.get_job(job_id)
        if job and job.next_run_time:
            task_update["next_run_at"] = job.next_run_time.replace(tzinfo=None)

        storage.mysql_update("ScheduleTask", record_id=task_id, data=task_update)

        # 通知
        if run_status == "success" and task.get("notify_on_success"):
            _send_notification(task, "success", run_log_update["result_summary"])
        elif run_status == "failed" and task.get("notify_on_failure"):
            _send_notification(task, "failed", run_log_update["error_message"])

        log.info(f"定时任务执行完成 | id={task_id}, status={run_status}, duration={duration}s")

    except Exception as e:
        log.error(f"定时任务执行异常 | id={task_id}, error={e}", exc_info=True)
        try:
            if run_log_id:
                storage.mysql_update("ScheduleRunLog", record_id=run_log_id, data={
                    "status": "failed",
                    "error_message": str(e),
                    "finished_at": datetime.now(),
                })
        except Exception:
            pass


def _send_notification(task: dict, status: str, message: str):
    """发送通知（预留接口）"""
    channels = (task.get("notify_channels") or "").split(",")
    log.info(f"通知 | task={task.get('name')}, status={status}, channels={channels}, msg={message[:50]}")
    # TODO: 实现邮件/webhook通知
