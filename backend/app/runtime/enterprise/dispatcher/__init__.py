"""
Task Dispatcher - 任务分发器

职责:
    1. 接收来自 API 层的任务请求
    2. 根据 Agent 能力分配合适的 Worker
    3. 管理任务状态 (6 状态机)
    4. 支持失败重试与任务恢复
"""
from app.runtime.enterprise.dispatcher.task_state import (
    TaskState,
    TaskStatus,
    TaskPriority,
    VALID_TRANSITIONS,
)
from app.runtime.enterprise.dispatcher.task_dispatcher import (
    TaskDispatcher,
    TaskRequest,
    TaskResult,
    DispatcherMode,
    get_task_dispatcher,
)

__all__ = [
    "TaskDispatcher", "TaskRequest", "TaskResult", "DispatcherMode", "get_task_dispatcher",
    "TaskState", "TaskStatus", "TaskPriority", "VALID_TRANSITIONS",
]
