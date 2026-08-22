"""
Runtime v2 — 统一 Agent 运行时

架构:
    API → Dispatcher → WorkerPool → AgentWorker → RoutedAgent → Collector → SSE/WebSocket

模块职责:
    - state:      任务状态机 + 数据结构 (TaskState/TaskResult/TaskEvent)
    - dispatcher: 任务调度器 (接收/入队/分配/重试/恢复)
    - worker:     任务执行器 (AgentFactory创建/执行/超时/异常/重试)
    - collector:  结果收集器 (事件聚合/SSE推送/WebSocket)
    - scheduler:  定时调度器 (立即/延迟/cron/依赖)

设计原则:
    1. 所有 Agent 必须通过 AgentFactory 创建, 禁止直接 new
    2. API 层禁止直接调用 Agent, 必须通过 Dispatcher.submit()
    3. Agent 间通信通过 Runtime 编排
    4. 支持单机 (STANDALONE) 和分布式 (DISTRIBUTED) 两种模式
    5. Worker 不管理 Agent 生命周期 (AgentFactory 管理缓存)

快速使用:
    from app.runtime.v2 import (
        get_dispatcher, get_worker_pool,
        get_collector, get_publisher,
        get_scheduler, start_runtime, stop_runtime,
    )

    # 启动 Runtime
    await start_runtime()

    # 提交任务
    from app.runtime.v2.state import TaskRequest, TaskPriority
    task_id = await get_dispatcher().submit(
        TaskRequest(agent_name="requirement_agent", payload={...})
    )

    # SSE 推送
    async for event in get_publisher().sse_stream(task_id):
        yield event

    # 停止 Runtime
    await stop_runtime()
"""
from app.runtime.v2.state import (
    TaskStatus,
    TaskPriority,
    TaskType,
    TaskRequest,
    TaskState,
    TaskResult,
    TaskEvent,
    VALID_TRANSITIONS,
)
from app.runtime.v2.dispatcher import (
    TaskDispatcher,
    DispatcherMode,
    get_dispatcher,
    reset_dispatcher,
)
from app.runtime.v2.worker import (
    AgentWorker,
    WorkerPool,
    get_worker_pool,
    reset_worker_pool,
)
from app.runtime.v2.collector import (
    ResponseCollector,
    StreamPublisher,
    get_collector,
    get_publisher,
    reset_collector,
)
from app.runtime.v2.scheduler import (
    TaskScheduler,
    ScheduleType,
    CronParser,
    get_scheduler,
    reset_scheduler,
)
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ============================================================
# Runtime 生命周期管理
# ============================================================

_runtime_started = False


async def start_runtime(
    worker_count: int = 4,
    mode: Optional[DispatcherMode] = None,
) -> None:
    """启动 Runtime v2 全部组件

    启动顺序:
        1. ResponseCollector + StreamPublisher (事件收集 + 推送)
        2. WorkerPool (任务执行)
        3. TaskDispatcher (任务调度, 绑定 WorkerPool + Collector)
        4. TaskScheduler (定时调度, 绑定 Dispatcher)

    Args:
        worker_count: Worker 数量
        mode: 运行模式 (None=自动选择)
    """
    global _runtime_started
    if _runtime_started:
        logger.warning("Runtime v2 已在运行")
        return

    logger.info("=" * 60)
    logger.info("启动 Runtime v2")
    logger.info("=" * 60)

    # 1. Collector + Publisher
    collector = get_collector()
    publisher = get_publisher()
    collector.set_stream_publisher(publisher)
    logger.info("✓ ResponseCollector + StreamPublisher 就绪")

    # 2. WorkerPool
    pool = get_worker_pool(size=worker_count)
    await pool.start()
    logger.info(f"✓ WorkerPool 就绪 | size={worker_count}")

    # 3. Dispatcher
    dispatcher = get_dispatcher(mode=mode)
    dispatcher.set_worker_pool(pool)
    dispatcher.set_response_collector(collector)
    await dispatcher.start()
    logger.info("✓ TaskDispatcher 就绪")

    # 4. Scheduler
    scheduler = get_scheduler(dispatcher=dispatcher)
    scheduler.set_dispatcher(dispatcher)
    await scheduler.start()
    logger.info("✓ TaskScheduler 就绪")

    _runtime_started = True
    logger.info("=" * 60)
    logger.info("Runtime v2 启动完成")
    logger.info("=" * 60)


async def stop_runtime() -> None:
    """停止 Runtime v2 全部组件"""
    global _runtime_started
    if not _runtime_started:
        return

    logger.info("停止 Runtime v2...")

    scheduler = get_scheduler()
    await scheduler.stop()

    dispatcher = get_dispatcher()
    await dispatcher.stop()

    pool = get_worker_pool()
    await pool.stop()

    _runtime_started = False
    logger.info("Runtime v2 已停止")


def is_runtime_started() -> bool:
    """Runtime 是否已启动"""
    return _runtime_started


__all__ = [
    # 状态
    "TaskStatus",
    "TaskPriority",
    "TaskType",
    "TaskRequest",
    "TaskState",
    "TaskResult",
    "TaskEvent",
    "VALID_TRANSITIONS",
    # Dispatcher
    "TaskDispatcher",
    "DispatcherMode",
    "get_dispatcher",
    "reset_dispatcher",
    # Worker
    "AgentWorker",
    "WorkerPool",
    "get_worker_pool",
    "reset_worker_pool",
    # Collector
    "ResponseCollector",
    "StreamPublisher",
    "get_collector",
    "get_publisher",
    "reset_collector",
    # Scheduler
    "TaskScheduler",
    "ScheduleType",
    "CronParser",
    "get_scheduler",
    "reset_scheduler",
    # 生命周期
    "start_runtime",
    "stop_runtime",
    "is_runtime_started",
]
