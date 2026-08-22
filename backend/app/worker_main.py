"""
独立 Agent Worker 进程入口

在分布式模式下,Worker 进程从 Redis 队列 BRPOP 取任务,
通过 AgentFactory 创建 Agent 并执行,结果写回数据库 + Redis。

启动方式:
    python -m app.worker_main --worker-id w-001 --concurrency 4

环境变量:
    REDIS_HOST / REDIS_PORT / REDIS_PASSWORD / REDIS_DB
    DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME
    MILVUS_HOST / NEO4J_URI / ...
    WORKER_ID (可选,默认自动生成)
    WORKER_CONCURRENCY (可选,默认 4)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

# 确保能 import app.*
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

logger = logging.getLogger("worker_main")

# ============================================================
# 分布式队列常量 (与 task_dispatcher.py 保持一致)
# ============================================================

_QUEUE_PREFIX = "runtime:task_queue"
_PRIORITY_KEYS = [
    f"{_QUEUE_PREFIX}:urgent",
    f"{_QUEUE_PREFIX}:high",
    f"{_QUEUE_PREFIX}:normal",
    f"{_QUEUE_PREFIX}:low",
]
_RESULT_KEY_PREFIX = "runtime:task_result"
_HEARTBEAT_KEY = "runtime:worker:heartbeat"
_BRPOP_TIMEOUT = 1  # 秒


class StandaloneWorker:
    """独立 Agent Worker

    生命周期:
        1. init()  — 初始化 (注册 Agent, 连接 Redis, 初始化 DB)
        2. start() — 启动并发协程, 循环 BRPOP + 执行
        3. stop()  — 优雅停止 (等待当前任务完成)

    并发模型:
        - 启动 N 个 asyncio 协程 (WORKER_CONCURRENCY)
        - 每个协程独立 BRPOP → execute → complete
        - 共享同一个 Redis 连接和 AgentFactory
    """

    def __init__(
        self,
        worker_id: Optional[str] = None,
        concurrency: int = 4,
    ) -> None:
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.concurrency = concurrency
        self._redis = None
        self._running = False
        self._tasks_done = 0
        self._tasks_failed = 0
        self._total_duration_ms = 0
        self._active_tasks: set = set()

    # ----------------------------------------------------------
    # 初始化
    # ----------------------------------------------------------

    async def init(self) -> None:
        """初始化 Worker"""
        logger.info(f"[Worker {self.worker_id}] 初始化中...")

        # 1. 初始化数据库 (建表兜底)
        from app.db.database import init_db
        init_db()

        # 2. 注册所有 Agent
        from app.agents.factory import AgentRegistry
        AgentRegistry.auto_register()
        logger.info(
            f"[Worker {self.worker_id}] Agent 注册完成: "
            f"{len(AgentRegistry.list_agents())} 个"
        )

        # 3. 初始化 Providers (LLM Gateway 等)
        from app.core.providers import init_providers
        init_providers()

        # 4. 连接 Redis
        import redis
        from app.core.config import settings
        self._redis = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
        )
        self._redis.ping()
        logger.info(f"[Worker {self.worker_id}] Redis 连接成功: {settings.redis_url}")

        # 5. 注册 MessageBus 订阅者
        try:
            from app.agent.core.event_router import register_default_subscribers
            register_default_subscribers()
        except Exception as e:
            logger.warning(f"[Worker {self.worker_id}] MessageBus 注册失败 (忽略): {e}")

        # 6. 注册 Pipeline 事件
        try:
            from app.services.case.pipeline import CasePipeline
            CasePipeline.register_pipeline_events()
        except Exception as e:
            logger.warning(f"[Worker {self.worker_id}] Pipeline 注册失败 (忽略): {e}")

        logger.info(
            f"[Worker {self.worker_id}] 初始化完成 | "
            f"并发数: {self.concurrency}"
        )

    # ----------------------------------------------------------
    # 主循环
    # ----------------------------------------------------------

    async def start(self) -> None:
        """启动 Worker"""
        self._running = True
        logger.info(f"[Worker {self.worker_id}] 启动 {self.concurrency} 个协程")

        # 启动心跳协程
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        # 启动 N 个消费协程
        worker_tasks = []
        for i in range(self.concurrency):
            task = asyncio.create_task(self._consume_loop(f"coroutine-{i}"))
            worker_tasks.append(task)

        # 等待所有协程 (正常不会退出)
        await asyncio.gather(heartbeat_task, *worker_tasks)

    async def stop(self) -> None:
        """优雅停止"""
        logger.info(f"[Worker {self.worker_id}] 正在停止...")
        self._running = False

        # 等待活跃任务完成 (最多 30 秒)
        timeout = 30
        start = time.time()
        while self._active_tasks and (time.time() - start) < timeout:
            logger.info(
                f"[Worker {self.worker_id}] 等待 {len(self._active_tasks)} 个活跃任务完成..."
            )
            await asyncio.sleep(1)

        logger.info(
            f"[Worker {self.worker_id}] 已停止 | "
            f"完成: {self._tasks_done} | 失败: {self._tasks_failed}"
        )

    # ----------------------------------------------------------
    # 心跳
    # ----------------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        """每 10 秒发送心跳到 Redis"""
        while self._running:
            try:
                key = f"{_HEARTBEAT_KEY}:{self.worker_id}"
                self._redis.setex(
                    key,
                    30,  # 30 秒过期
                    json.dumps({
                        "worker_id": self.worker_id,
                        "timestamp": datetime.now().isoformat(),
                        "active_tasks": len(self._active_tasks),
                        "tasks_done": self._tasks_done,
                        "tasks_failed": self._tasks_failed,
                        "concurrency": self.concurrency,
                    }),
                )
            except Exception as e:
                logger.warning(f"[Worker {self.worker_id}] 心跳失败: {e}")
            await asyncio.sleep(10)

    # ----------------------------------------------------------
    # 消费循环
    # ----------------------------------------------------------

    async def _consume_loop(self, coroutine_name: str) -> None:
        """单个消费协程的主循环"""
        logger.info(f"[Worker {self.worker_id}#{coroutine_name}] 消费循环启动")

        while self._running:
            try:
                # BRPOP 从 Redis 取任务 (按优先级顺序)
                result = await asyncio.to_thread(
                    self._redis.brpop,
                    _PRIORITY_KEYS,
                    _BRPOP_TIMEOUT,
                )

                if result is None:
                    continue  # 超时,继续轮询

                _, payload = result
                task_data = json.loads(payload)
                state = self._rebuild_state(task_data)

                # 执行任务
                self._active_tasks.add(state.task_id)
                await self._execute_task(state)
                self._active_tasks.discard(state.task_id)

            except asyncio.CancelledError:
                logger.info(f"[Worker {self.worker_id}#{coroutine_name}] 收到取消信号")
                break
            except Exception as e:
                logger.error(
                    f"[Worker {self.worker_id}#{coroutine_name}] 消费循环异常: {e}",
                    exc_info=True,
                )
                await asyncio.sleep(2)  # 错误后短暂等待

        logger.info(f"[Worker {self.worker_id}#{coroutine_name}] 消费循环结束")

    # ----------------------------------------------------------
    # 任务执行
    # ----------------------------------------------------------

    async def _execute_task(self, state: Any) -> None:
        """执行单个任务

        步骤:
            1. 状态转移 PENDING → RUNNING
            2. 通过 AgentFactory 创建 Agent
            3. 调用 Agent.execute() (带超时)
            4. 结果写回数据库 + Redis
        """
        from app.runtime.enterprise.dispatcher.task_state import TaskStatus

        start_time = time.time()
        state.worker_id = self.worker_id
        state.transition(TaskStatus.RUNNING)

        logger.info(
            f"[Worker {self.worker_id}] 开始执行 | "
            f"task={state.task_id} | agent={state.agent_name} | "
            f"action={state.action}"
        )

        result: Any = None
        error: Optional[str] = None
        final_status = TaskStatus.SUCCESS

        try:
            # 通过 AgentFactory 创建 Agent 并执行
            result = await asyncio.wait_for(
                self._invoke_agent(state),
                timeout=state.timeout_seconds,
            )

            # 检查 Agent 是否返回错误
            if isinstance(result, dict) and result.get("status") == "error":
                error = result.get("message") or result.get("error") or "Agent 返回错误"
                final_status = TaskStatus.FAILED

        except asyncio.TimeoutError:
            final_status = TaskStatus.TIMEOUT
            error = f"任务超时 ({state.timeout_seconds}s)"
            logger.warning(
                f"[Worker {self.worker_id}] 任务超时 | task={state.task_id}"
            )
        except asyncio.CancelledError:
            final_status = TaskStatus.CANCELLED
            error = "任务被取消"
            raise
        except Exception as e:
            final_status = TaskStatus.FAILED
            error = f"{type(e).__name__}: {e}"
            logger.error(
                f"[Worker {self.worker_id}] 任务异常 | task={state.task_id} | error={e}",
                exc_info=True,
            )

        # 计算耗时
        duration_ms = int((time.time() - start_time) * 1000)
        self._tasks_done += 1
        self._total_duration_ms += duration_ms
        if final_status == TaskStatus.FAILED:
            self._tasks_failed += 1

        # 完成回调 (写回 DB + Redis)
        await self._complete(
            state=state,
            status=final_status,
            result=result if final_status == TaskStatus.SUCCESS else None,
            error=error,
            duration_ms=duration_ms,
        )

        logger.info(
            f"[Worker {self.worker_id}] 任务完成 | "
            f"task={state.task_id} | status={final_status.value} | "
            f"耗时={duration_ms}ms"
        )

    async def _invoke_agent(self, state: Any) -> Any:
        """通过 AgentFactory 创建 Agent 并执行"""
        from app.agents.factory import AgentFactory

        agent = AgentFactory.create(
            name=state.agent_name,
            session_key=state.session_id or state.task_id,
        )

        if agent is None:
            raise ValueError(f"Agent 不存在: {state.agent_name}")

        # 调用 Agent 的 execute 方法
        if hasattr(agent, "execute"):
            result = agent.execute(state.payload)
            if asyncio.iscoroutine(result):
                result = await result
            return result
        elif hasattr(agent, "run"):
            result = agent.run(state.payload)
            if asyncio.iscoroutine(result):
                result = await result
            return result
        else:
            raise ValueError(
                f"Agent {state.agent_name} 无 execute/run 方法"
            )

    # ----------------------------------------------------------
    # 完成回调
    # ----------------------------------------------------------

    async def _complete(
        self,
        state: Any,
        status: Any,
        result: Any = None,
        error: Optional[str] = None,
        duration_ms: int = 0,
    ) -> None:
        """任务完成回调

        1. 持久化更新到数据库
        2. 发布结果到 Redis (供 API 层查询)
        """
        # 状态转移
        state.transition(status)
        state.result = result
        state.error = error

        # 1. 持久化到数据库
        try:
            from app.services.runtime_persistence import get_runtime_persistence
            persistence = get_runtime_persistence()
            if persistence.enabled:
                persistence.update_task(
                    task_id=state.task_id,
                    status=status.value,
                    completed_at=datetime.now().isoformat()
                    if status != state.status.RUNNING
                    else None,
                    duration_ms=duration_ms,
                    worker_id=self.worker_id,
                    result=result,
                    error=error,
                    events_count=len(state.events) if hasattr(state, "events") else 0,
                )
        except Exception as e:
            logger.debug(f"[Worker {self.worker_id}] 持久化更新失败 (忽略): {e}")

        # 2. 发布结果到 Redis
        try:
            result_key = f"{_RESULT_KEY_PREFIX}:{state.task_id}"
            self._redis.setex(
                result_key,
                3600,  # 1 小时过期
                json.dumps({
                    "task_id": state.task_id,
                    "status": status.value,
                    "result": result if isinstance(result, (str, int, float, bool, list, dict, type(None))) else str(result),
                    "error": error,
                    "duration_ms": duration_ms,
                    "worker_id": self.worker_id,
                    "completed_at": datetime.now().isoformat(),
                }, ensure_ascii=False, default=str),
            )
        except Exception as e:
            logger.warning(f"[Worker {self.worker_id}] Redis 结果发布失败: {e}")

    # ----------------------------------------------------------
    # 工具方法
    # ----------------------------------------------------------

    @staticmethod
    def _rebuild_state(data: Dict[str, Any]) -> Any:
        """从字典重建 TaskState (跨进程恢复)"""
        from app.runtime.enterprise.dispatcher.task_state import (
            TaskState,
            TaskStatus,
            TaskPriority,
        )

        return TaskState(
            task_id=data["task_id"],
            task_type=data.get("task_type", "agent"),
            agent_name=data.get("agent_name", ""),
            action=data.get("action", "execute"),
            payload=data.get("payload", {}),
            status=TaskStatus(data.get("status", "pending")),
            priority=TaskPriority(data.get("priority", "normal")),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
            created_at=data.get("created_at", datetime.now().isoformat()),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            user_id=data.get("user_id"),
            session_id=data.get("session_id"),
            timeout_seconds=data.get("timeout_seconds", 300),
            worker_id=data.get("worker_id"),
        )

    def get_stats(self) -> Dict[str, Any]:
        """获取 Worker 统计"""
        return {
            "worker_id": self.worker_id,
            "concurrency": self.concurrency,
            "active_tasks": len(self._active_tasks),
            "tasks_done": self._tasks_done,
            "tasks_failed": self._tasks_failed,
            "total_duration_ms": self._total_duration_ms,
            "running": self._running,
        }


# ============================================================
# 入口
# ============================================================

async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Agent Worker 独立进程")
    parser.add_argument(
        "--worker-id",
        default=os.environ.get("WORKER_ID", ""),
        help="Worker ID (默认自动生成)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=int(os.environ.get("WORKER_CONCURRENCY", "4")),
        help="并发协程数 (默认 4)",
    )
    args = parser.parse_args()

    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    worker_id = args.worker_id or f"worker-{uuid.uuid4().hex[:8]}"
    worker = StandaloneWorker(worker_id=worker_id, concurrency=args.concurrency)

    # 信号处理 (优雅停止)
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler():
        logger.info(f"收到停止信号, 正在优雅停止 Worker {worker_id}...")
        asyncio.create_task(worker.stop())
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows 不支持 add_signal_handler
            signal.signal(sig, lambda s, f: _signal_handler())

    # 初始化并启动
    await worker.init()
    logger.info("=" * 60)
    logger.info(f"Agent Worker 启动 | ID={worker_id} | 并发={args.concurrency}")
    logger.info(f"队列: {_PRIORITY_KEYS}")
    logger.info("=" * 60)

    try:
        await worker.start()
    except KeyboardInterrupt:
        pass
    finally:
        logger.info(f"Worker {worker_id} 已退出")
        logger.info(f"统计: {worker.get_stats()}")


if __name__ == "__main__":
    asyncio.run(main())
