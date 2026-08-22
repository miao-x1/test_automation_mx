"""
Runtime v2 — 任务状态定义

职责:
    定义任务的状态机、优先级、状态对象和统一结果结构。
    这是整个 Runtime 的数据基础, Dispatcher/Worker/Collector 都依赖这些类型。

设计原则:
    1. 状态机不可非法跳转 (VALID_TRANSITIONS 强校验)
    2. TaskState 可序列化为 JSON (支持跨进程恢复, 为分布式预留)
    3. TaskResult 为统一输出结构, 所有 Agent 结果最终归一化为此类型

使用方式:
    from app.runtime.state import TaskState, TaskStatus, TaskPriority, TaskRequest, TaskResult
"""
from __future__ import annotations

import enum
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


# ============================================================
# 枚举定义
# ============================================================

class TaskStatus(str, enum.Enum):
    """任务状态 — 6 状态机

    状态流转:
        PENDING → RUNNING → SUCCESS        (正常完成)
        PENDING → RUNNING → FAILED → PENDING (重试)
        PENDING → RUNNING → TIMEOUT        (超时, 不可重试)
        PENDING → CANCELLED                (执行前取消)
        RUNNING → CANCELLED                 (执行中取消)
    """
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


# 合法状态转换表
VALID_TRANSITIONS: Dict[TaskStatus, set] = {
    TaskStatus.PENDING: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {
        TaskStatus.SUCCESS,
        TaskStatus.FAILED,
        TaskStatus.TIMEOUT,
        TaskStatus.CANCELLED,
    },
    TaskStatus.FAILED: {TaskStatus.PENDING},  # 重试: FAILED → PENDING
    TaskStatus.SUCCESS: set(),   # 终态
    TaskStatus.TIMEOUT: set(),   # 终态
    TaskStatus.CANCELLED: set(),  # 终态
}


class TaskPriority(enum.IntEnum):
    """任务优先级 — 值越小优先级越高"""
    URGENT = 0   # 紧急: 用户交互等待
    HIGH = 1     # 高: 关键路径
    NORMAL = 2   # 常规: 默认
    LOW = 3      # 低: 后台任务


class TaskType(str, enum.Enum):
    """任务类型 — 标识任务来源和用途"""
    AGENT = "agent"          # 单 Agent 执行
    PIPELINE = "pipeline"    # 多步骤管道
    FLOW = "flow"            # Flow 编排
    SCRIPT = "script"        # 脚本执行
    EXECUTION = "execution"  # 测试执行


# ============================================================
# 数据类
# ============================================================

@dataclass
class TaskRequest:
    """任务提交请求 — API 层构造, 传给 Dispatcher.submit()

    属性:
        agent_name:   Agent 名称 (必须在 AgentFactory 注册)
        action:       Agent 动作 (默认 "execute")
        payload:      任务参数 (Dict)
        priority:     优先级
        task_type:    任务类型
        timeout:      超时秒数 (默认 300)
        max_retries:  最大重试次数 (默认 3)
        session_id:   会话 ID (用于 Agent 实例隔离)
        user_id:      用户 ID
        metadata:     扩展元数据
    """
    agent_name: str
    action: str = "execute"
    payload: Dict[str, Any] = field(default_factory=dict)
    priority: TaskPriority = TaskPriority.NORMAL
    task_type: TaskType = TaskType.AGENT
    timeout: int = 300
    max_retries: int = 3
    session_id: Optional[str] = None
    user_id: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskState:
    """任务运行状态 — Dispatcher 管理的运行时状态对象

    特性:
        1. 6 状态机: transition() 强校验合法性
        2. 可序列化: to_dict() / from_dict() 支持跨进程恢复
        3. 事件追踪: events 列表记录执行过程中的所有事件
    """
    task_id: str
    agent_name: str
    action: str = "execute"
    payload: Dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    task_type: TaskType = TaskType.AGENT

    # 重试控制
    retry_count: int = 0
    max_retries: int = 3

    # 时间追踪
    created_at: str = field(
        default_factory=lambda: datetime.now().isoformat()
    )
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    # 执行信息
    timeout_seconds: int = 300
    worker_id: Optional[str] = None
    result: Any = None
    error: Optional[str] = None
    events: List[Dict[str, Any]] = field(default_factory=list)

    # 上下文
    session_id: Optional[str] = None
    user_id: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ---- 状态机 ----

    def transition(self, new_status: TaskStatus) -> None:
        """状态转换 (带合法性校验)

        Raises:
            ValueError: 非法状态转换
        """
        if new_status == self.status:
            return  # 幂等

        allowed = VALID_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"非法状态转换: {self.status.value} → {new_status.value} "
                f"(允许: {[s.value for s in allowed] or '终态'})"
            )

        self.status = new_status

        if new_status == TaskStatus.RUNNING:
            self.started_at = datetime.now().isoformat()
        elif new_status in (
            TaskStatus.SUCCESS,
            TaskStatus.FAILED,
            TaskStatus.TIMEOUT,
            TaskStatus.CANCELLED,
        ):
            self.completed_at = datetime.now().isoformat()

    def reset_for_retry(self) -> None:
        """重置状态以供重试 — FAILED → PENDING"""
        self.transition(TaskStatus.PENDING)
        self.retry_count += 1
        self.started_at = None
        self.completed_at = None
        self.error = None
        self.result = None
        self.events.clear()

    @property
    def can_retry(self) -> bool:
        """是否可重试

        max_retries 表示最大尝试次数 (含首次), 所以
        已用尝试次数 = retry_count + 1, 可重试条件:
            retry_count + 1 < max_retries
        """
        return (
            self.status == TaskStatus.FAILED
            and self.retry_count + 1 < self.max_retries
        )

    @property
    def is_terminal(self) -> bool:
        """是否为终态"""
        return self.status in (
            TaskStatus.SUCCESS,
            TaskStatus.TIMEOUT,
            TaskStatus.CANCELLED,
        ) or (self.status == TaskStatus.FAILED and not self.can_retry)

    @property
    def duration_ms(self) -> Optional[int]:
        """执行耗时 (毫秒)"""
        if not self.started_at:
            return None
        if not self.completed_at:
            return int((time.time() - _parse_iso(self.started_at)) * 1000)
        return int(
            (_parse_iso(self.completed_at) - _parse_iso(self.started_at)) * 1000
        )

    # ---- 序列化 ----

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典 (支持跨进程恢复)"""
        return {
            "task_id": self.task_id,
            "agent_name": self.agent_name,
            "action": self.action,
            "payload": self.payload,
            "status": self.status.value,
            "priority": int(self.priority),
            "task_type": self.task_type.value,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "timeout_seconds": self.timeout_seconds,
            "worker_id": self.worker_id,
            "result": self.result,
            "error": self.error,
            "events": self.events,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskState":
        """从字典反序列化 (跨进程恢复)"""
        return cls(
            task_id=data["task_id"],
            agent_name=data["agent_name"],
            action=data.get("action", "execute"),
            payload=data.get("payload", {}),
            status=TaskStatus(data.get("status", "pending")),
            priority=TaskPriority(data.get("priority", 2)),
            task_type=TaskType(data.get("task_type", "agent")),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
            created_at=data.get("created_at", datetime.now().isoformat()),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            timeout_seconds=data.get("timeout_seconds", 300),
            worker_id=data.get("worker_id"),
            result=data.get("result"),
            error=data.get("error"),
            events=data.get("events", []),
            session_id=data.get("session_id"),
            user_id=data.get("user_id"),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_request(cls, request: TaskRequest) -> "TaskState":
        """从 TaskRequest 创建 TaskState"""
        return cls(
            task_id=f"task-{uuid.uuid4().hex[:12]}",
            agent_name=request.agent_name,
            action=request.action,
            payload=request.payload,
            priority=request.priority,
            task_type=request.task_type,
            max_retries=request.max_retries,
            timeout_seconds=request.timeout,
            session_id=request.session_id,
            user_id=request.user_id,
            metadata=request.metadata,
        )


@dataclass
class TaskResult:
    """统一任务结果结构 — 所有 Agent 输出最终归一化为此类型

    用途:
        1. API 层返回给前端
        2. Collector 收集后推送给 SSE
        3. 持久化到数据库
    """
    task_id: str
    agent_name: str
    status: TaskStatus
    result: Any = None
    error: Optional[str] = None
    duration_ms: int = 0
    retry_count: int = 0
    events: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_state(cls, state: TaskState) -> "TaskResult":
        """从 TaskState 构建 TaskResult"""
        return cls(
            task_id=state.task_id,
            agent_name=state.agent_name,
            status=state.status,
            result=state.result,
            error=state.error,
            duration_ms=state.duration_ms or 0,
            retry_count=state.retry_count,
            events=list(state.events),
        )

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "task_id": self.task_id,
            "agent_name": self.agent_name,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "retry_count": self.retry_count,
            "events": self.events,
        }

    @property
    def is_success(self) -> bool:
        return self.status == TaskStatus.SUCCESS


# ============================================================
# 事件类型
# ============================================================

@dataclass
class TaskEvent:
    """任务执行事件 — Worker 执行过程中产生, 推送给 Collector

    事件类型:
        - start:    任务开始
        - progress: 进度更新
        - end:      任务结束 (成功)
        - error:    任务出错
        - retry:    任务重试
        - done:     流结束信号 (SSE 终止)
    """
    task_id: str
    event_type: str  # start / progress / end / error / retry / done
    agent_name: str = ""
    step: str = ""
    status: str = "running"
    message: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now().isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "event": self.event_type,
            "agent_name": self.agent_name,
            "step": self.step,
            "status": self.status,
            "message": self.message,
            "data": self.data,
            "timestamp": self.timestamp,
        }


# ============================================================
# 工具函数
# ============================================================

def _parse_iso(iso_str: str) -> float:
    """解析 ISO 时间字符串为时间戳"""
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.timestamp()
    except (ValueError, TypeError):
        return time.time()
