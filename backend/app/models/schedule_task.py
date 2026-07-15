"""
定时任务模型

支持 once/daily/cron 三种调度类型
"""
import enum
from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime, Boolean, ForeignKey, Index
from app.models.base import OwnedModel


class ScheduleType(str, enum.Enum):
    """调度类型"""
    ONCE = "once"       # 一次性
    DAILY = "daily"     # 每日
    CRON = "cron"       # Cron表达式


class ScheduleStatus(str, enum.Enum):
    """定时任务状态"""
    ACTIVE = "active"       # 启用
    PAUSED = "paused"       # 暂停
    EXPIRED = "expired"     # 已过期
    DISABLED = "disabled"   # 已禁用


class ScheduleTask(OwnedModel):
    """定时任务表"""
    __tablename__ = "schedule_task"

    # 基本信息
    name = Column(String(100), nullable=False, comment="任务名称")
    description = Column(Text, nullable=True, comment="任务描述")

    # 调度配置
    schedule_type = Column(
        String(20), default=ScheduleType.DAILY, nullable=False,
        comment="调度类型: once/daily/cron"
    )
    cron_expression = Column(String(100), nullable=True, comment="Cron表达式（schedule_type=cron时使用）")
    execute_time = Column(String(10), nullable=True, comment="执行时间 HH:MM（daily/once时使用）")
    execute_date = Column(String(20), nullable=True, comment="执行日期 YYYY-MM-DD（once时使用）")

    # 有效时间范围
    start_time = Column(DateTime, nullable=True, comment="生效开始时间")
    end_time = Column(DateTime, nullable=True, comment="生效结束时间")

    # 执行配置
    timeout = Column(Integer, default=3600, comment="超时时间（秒）")
    max_retries = Column(Integer, default=3, comment="最大重试次数")
    retry_interval = Column(Integer, default=60, comment="重试间隔（秒）")

    # 通知配置
    notify_on_success = Column(Boolean, default=False, comment="成功时通知")
    notify_on_failure = Column(Boolean, default=True, comment="失败时通知")
    notify_channels = Column(String(200), nullable=True, comment="通知渠道（逗号分隔: email,webhook）")

    # 关联的需求/任务
    requirement_id = Column(Integer, ForeignKey("requirement_task.id", ondelete="SET NULL"), nullable=True, comment="关联的需求ID")
    task_config = Column(Text, nullable=True, comment="任务配置JSON（需求文本/URL/脚本等）")

    # 状态
    status = Column(String(20), default=ScheduleStatus.ACTIVE, nullable=False, comment="状态")
    last_run_at = Column(DateTime, nullable=True, comment="上次执行时间")
    last_run_status = Column(String(20), nullable=True, comment="上次执行状态: success/failed/timeout")
    next_run_at = Column(DateTime, nullable=True, comment="下次执行时间")
    run_count = Column(Integer, default=0, comment="累计执行次数")
    fail_count = Column(Integer, default=0, comment="累计失败次数")

    def to_dict(self):
        d = super().to_dict()
        for k in ("start_time", "end_time", "last_run_at", "next_run_at", "created_at", "updated_at"):
            if d.get(k) and isinstance(d[k], datetime):
                d[k] = d[k].isoformat()
        return d


class ScheduleRunLog(OwnedModel):
    """定时任务执行历史记录"""
    __tablename__ = "schedule_run_log"

    schedule_task_id = Column(Integer, ForeignKey("schedule_task.id", ondelete="CASCADE"), nullable=False, index=True, comment="定时任务ID")
    execution_id = Column(Integer, ForeignKey("execution_record.id", ondelete="SET NULL"), nullable=True, comment="关联的执行记录ID")
    run_number = Column(Integer, nullable=False, comment="第几次执行")
    status = Column(String(20), nullable=False, comment="执行状态: running/success/failed/timeout/cancelled")
    trigger_type = Column(String(20), default="schedule", nullable=False, comment="触发方式: schedule/manual/retry")
    operator = Column(String(100), nullable=True, comment="操作人（手动触发时记录）")
    started_at = Column(DateTime, default=datetime.now, comment="开始时间")
    finished_at = Column(DateTime, nullable=True, comment="结束时间")
    duration = Column(Integer, nullable=True, comment="执行耗时（秒）")
    retry_count = Column(Integer, default=0, comment="本次重试次数")
    result_summary = Column(Text, nullable=True, comment="执行结果摘要")
    error_message = Column(Text, nullable=True, comment="错误信息")
    logs = Column(Text, nullable=True, comment="执行日志")
    task_id = Column(Integer, ForeignKey("task.id", ondelete="SET NULL"), nullable=True, comment="关联的任务ID")

    def to_dict(self):
        d = super().to_dict()
        for k in ("started_at", "finished_at", "created_at", "updated_at"):
            if d.get(k) and isinstance(d[k], datetime):
                d[k] = d[k].isoformat()
        return d


Index('idx_schedule_task_status', ScheduleTask.status)
Index('idx_run_log_schedule', ScheduleRunLog.schedule_task_id)
Index('idx_run_log_status', ScheduleRunLog.status)
