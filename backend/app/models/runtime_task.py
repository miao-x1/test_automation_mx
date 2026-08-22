"""
RuntimeTask - 企业级 Agent Runtime 任务记录

持久化 TaskDispatcher 的任务状态,支持:
    1. 崩溃恢复 (从 DB 恢复 PENDING/RUNNING 任务)
    2. 历史任务查询
    3. 指标统计 (成功率/平均耗时/吞吐量)

与内存中的 TaskState 一一对应,通过 task_id 关联。
"""
import enum
from sqlalchemy import (
    Column, String, Integer, Float, Text, DateTime, Boolean,
    Enum as SQLEnum, Index, JSON,
)
from sqlalchemy.dialects import mysql

from app.models.base import BaseModel


class RuntimeTaskStatus(str, enum.Enum):
    """Runtime 任务状态 (与 TaskState.TaskStatus 一致)"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class RuntimeTaskPriority(str, enum.Enum):
    """任务优先级"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class RuntimeTask(BaseModel):
    """Runtime 任务记录表

    每次 TaskDispatcher.submit() 创建一行,
    每次 complete() 更新状态与结果。
    """
    __tablename__ = "runtime_task"

    # ---------- 任务标识 ----------
    task_id = Column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
        comment="任务 ID (与内存 TaskState.task_id 一致)",
    )
    parent_task_id = Column(
        String(64),
        nullable=True,
        index=True,
        comment="父任务 ID (用于任务编排/DAG)",
    )

    # ---------- 任务内容 ----------
    task_type = Column(
        String(32),
        nullable=False,
        default="agent",
        index=True,
        comment="任务类型: agent / flow",
    )
    agent_name = Column(
        String(128),
        nullable=False,
        index=True,
        comment="目标 Agent 名称",
    )
    action = Column(
        String(64),
        nullable=False,
        default="execute",
        comment="调用的 action",
    )
    payload_json = Column(
        mysql.MEDIUMTEXT(),
        nullable=True,
        comment="任务参数 JSON",
    )

    # ---------- 状态 ----------
    status = Column(
        SQLEnum(
            RuntimeTaskStatus,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=RuntimeTaskStatus.PENDING,
        nullable=False,
        index=True,
        comment="任务状态",
    )
    priority = Column(
        SQLEnum(
            RuntimeTaskPriority,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=RuntimeTaskPriority.NORMAL,
        nullable=False,
        index=True,
        comment="优先级",
    )

    # ---------- 重试 ----------
    retry_count = Column(
        Integer,
        default=0,
        nullable=False,
        comment="已重试次数",
    )
    max_retries = Column(
        Integer,
        default=3,
        nullable=False,
        comment="最大重试次数",
    )

    # ---------- 时间 ----------
    created_at_ts = Column(
        DateTime,
        nullable=True,
        index=True,
        comment="任务创建时间 (来自 TaskState)",
    )
    started_at_ts = Column(
        DateTime,
        nullable=True,
        comment="任务开始执行时间",
    )
    completed_at_ts = Column(
        DateTime,
        nullable=True,
        index=True,
        comment="任务完成时间",
    )
    duration_ms = Column(
        Integer,
        nullable=True,
        index=True,
        comment="执行耗时 (毫秒)",
    )
    timeout_seconds = Column(
        Integer,
        default=300,
        nullable=False,
        comment="超时时间 (秒)",
    )

    # ---------- 执行者 ----------
    worker_id = Column(
        String(64),
        nullable=True,
        index=True,
        comment="执行任务的 Worker ID",
    )
    user_id = Column(
        Integer,
        nullable=True,
        index=True,
        comment="提交任务的用户 ID",
    )
    session_id = Column(
        String(64),
        nullable=True,
        index=True,
        comment="会话 ID (多会话隔离)",
    )

    # ---------- 结果 ----------
    result_json = Column(
        mysql.MEDIUMTEXT(),
        nullable=True,
        comment="任务结果 JSON",
    )
    error = Column(
        Text(),
        nullable=True,
        comment="错误信息",
    )
    events_count = Column(
        Integer,
        default=0,
        nullable=False,
        comment="事件数量",
    )

    # ---------- 索引 ----------
    __table_args__ = (
        # 复合索引: 按状态+创建时间查询
        Index("idx_runtime_task_status_created", "status", "created_at_ts"),
        # 复合索引: 按用户+状态查询
        Index("idx_runtime_task_user_status", "user_id", "status"),
        # 复合索引: 按 Agent+状态查询
        Index("idx_runtime_task_agent_status", "agent_name", "status"),
        # 复合索引: 按完成时间+状态 (用于指标统计)
        Index("idx_runtime_task_completed_status", "completed_at_ts", "status"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "parent_task_id": self.parent_task_id,
            "task_type": self.task_type,
            "agent_name": self.agent_name,
            "action": self.action,
            "status": self.status.value if self.status else None,
            "priority": self.priority.value if self.priority else None,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "created_at": self.created_at_ts.isoformat() if self.created_at_ts else None,
            "started_at": self.started_at_ts.isoformat() if self.started_at_ts else None,
            "completed_at": self.completed_at_ts.isoformat() if self.completed_at_ts else None,
            "duration_ms": self.duration_ms,
            "timeout_seconds": self.timeout_seconds,
            "worker_id": self.worker_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "error": self.error,
            "events_count": self.events_count,
        }
