"""
Agent Runtime — 企业级 Agent 运行时环境

架构:
    API Layer
      ↓
    TaskDispatcher (接收任务, 分配 Agent, 管理状态)
      ↓
    AgentWorker (调用 Agent, 收集结果)
      ↓
    ResponseCollector (收集输出, SSE/WebSocket 推送)
      ↓
    TaskScheduler (定时/优先级调度)

支持:
    1. 单机运行模式 (asyncio.Queue + 进程内 Worker)
    2. 分布式运行模式 (Redis 队列 + 跨进程 Worker)

设计原则:
    - API 层禁止直接调用 Agent,统一通过 TaskDispatcher
    - 所有 Agent 通过 AgentFactory 创建
    - 任务状态统一管理 (6 状态机)
    - 实时推送 SSE + WebSocket
"""

# ============================================================
# 导出公共 API
# ============================================================

from app.runtime.enterprise.dispatcher.task_dispatcher import (
    TaskDispatcher,
    TaskRequest,
    TaskResult,
    DispatcherMode,
    get_task_dispatcher,
)
from app.runtime.enterprise.dispatcher.task_state import (
    TaskState,
    TaskStatus,
    TaskPriority,
)
from app.runtime.enterprise.worker.agent_worker import AgentWorker
from app.runtime.enterprise.worker.worker_pool import WorkerPool, get_worker_pool
from app.runtime.enterprise.collector.response_collector import (
    ResponseCollector,
    get_response_collector,
)
from app.runtime.enterprise.collector.stream_publisher import (
    StreamPublisher,
    get_stream_publisher,
)
from app.runtime.enterprise.scheduler.task_scheduler import (
    TaskScheduler,
    get_task_scheduler,
)

__all__ = [
    # Dispatcher
    "TaskDispatcher", "TaskRequest", "TaskResult", "DispatcherMode", "get_task_dispatcher",
    # TaskState
    "TaskState", "TaskStatus", "TaskPriority",
    # Worker
    "AgentWorker", "WorkerPool", "get_worker_pool",
    # Collector
    "ResponseCollector", "get_response_collector",
    "StreamPublisher", "get_stream_publisher",
    # Scheduler
    "TaskScheduler", "get_task_scheduler",
]
