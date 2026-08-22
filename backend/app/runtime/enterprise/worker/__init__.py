"""
Agent Worker - 任务执行器

职责:
    1. 从 TaskDispatcher 接收任务
    2. 通过 AgentFactory 创建 Agent 实例
    3. 调用 Agent.execute() 执行任务
    4. 收集执行事件
    5. 将结果回传给 TaskDispatcher

特性:
    - 并发执行 (每个 Worker 一个 asyncio.Task)
    - 超时控制
    - 异常捕获
    - 事件追踪
"""
from app.runtime.enterprise.worker.agent_worker import AgentWorker
from app.runtime.enterprise.worker.worker_pool import WorkerPool, get_worker_pool

__all__ = ["AgentWorker", "WorkerPool", "get_worker_pool"]
