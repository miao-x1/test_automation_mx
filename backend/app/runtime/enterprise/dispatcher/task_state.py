"""
任务状态机 — 统一任务状态管理

6 状态机:
    PENDING → RUNNING → SUCCESS
                    ↘ → FAILED
                    ↘ → TIMEOUT
                    ↘ → CANCELLED

    任何状态 → CANCELLED (用户取消)

状态转移规则:
    PENDING → RUNNING (Worker 开始执行)
    RUNNING → SUCCESS (执行成功)
    RUNNING → FAILED (执行失败)
    RUNNING → TIMEOUT (超时)
    PENDING/RUNNING → CANCELLED (用户取消)
    FAILED → PENDING (重试,重置状态)
"""
import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


class TaskStatus(str, enum.Enum):
    """任务状态"""
    PENDING = "pending"        # 已提交,待执行
    RUNNING = "running"        # 执行中
    SUCCESS = "success"        # 成功
    FAILED = "failed"          # 失败
    TIMEOUT = "timeout"        # 超时
    CANCELLED = "cancelled"    # 已取消


class TaskPriority(str, enum.Enum):
    """任务优先级"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


# 合法的状态转移
VALID_TRANSITIONS = {
    TaskStatus.PENDING: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.TIMEOUT, TaskStatus.CANCELLED},
    TaskStatus.FAILED: {TaskStatus.PENDING},  # 重试
    TaskStatus.SUCCESS: set(),    # 终态
    TaskStatus.TIMEOUT: set(),    # 终态
    TaskStatus.CANCELLED: set(),  # 终态
}


@dataclass
class TaskState:
    """任务状态对象

    存储任务的所有状态信息,包括:
    - 基本信息(id, type, agent_name, action, payload)
    - 执行状态(status, priority, retry_count)
    - 时间跟踪(created_at, started_at, completed_at)
    - 结果(result, error, events)
    """
    task_id: str
    task_type: str = "agent"
    agent_name: str = ""
    action: str = "execute"
    payload: Dict[str, Any] = field(default_factory=dict)

    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    retry_count: int = 0
    max_retries: int = 3

    # 时间跟踪
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    # 结果
    result: Optional[Any] = None
    error: Optional[str] = None
    events: list = field(default_factory=list)

    # 元数据
    user_id: Optional[int] = None
    session_id: Optional[str] = None
    timeout_seconds: int = 300
    worker_id: Optional[str] = None

    def transition(self, new_status: TaskStatus) -> bool:
        """状态转移

        返回:
            True: 转移成功
            False: 非法转移
        """
        allowed = VALID_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            return False

        old_status = self.status
        self.status = new_status

        if new_status == TaskStatus.RUNNING and self.started_at is None:
            self.started_at = datetime.now().isoformat()
        elif new_status in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.TIMEOUT, TaskStatus.CANCELLED):
            self.completed_at = datetime.now().isoformat()

        return True

    def can_retry(self) -> bool:
        """是否可以重试"""
        return (
            self.status == TaskStatus.FAILED
            and self.retry_count < self.max_retries
        )

    def reset_for_retry(self) -> None:
        """重置状态以重试"""
        self.retry_count += 1
        self.status = TaskStatus.PENDING
        self.started_at = None
        self.completed_at = None
        self.error = None

    def is_terminal(self) -> bool:
        """是否终态"""
        return self.status in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.TIMEOUT, TaskStatus.CANCELLED)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "agent_name": self.agent_name,
            "action": self.action,
            "status": self.status.value,
            "priority": self.priority.value,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "result": self.result,
            "error": self.error,
            "events_count": len(self.events),
            "user_id": self.user_id,
            "session_id": self.session_id,
            "worker_id": self.worker_id,
        }
