"""
Redis 执行队列

当 REDIS_ENABLED=True 时使用 Redis 作为执行队列，
否则降级为 asyncio.Queue（默认）

Redis 队列优势：
- 持久化：重启不丢任务
- 分布式：多Worker跨进程
- 可监控：可视化队列状态
"""
import asyncio
import json
import time as _time
from typing import Any, Dict, List, Optional
from app.core.config import settings
from app.core.logger import log


class RedisExecutionQueue:
    """Redis 执行队列"""

    QUEUE_KEY = "execution_queue"
    RESULT_KEY_PREFIX = "execution_result:"

    def __init__(self):
        self._redis = None
        self._workers = []
        self._running = False

    def _get_redis(self):
        """获取Redis连接（连接池 + keepalive + 多连接支持并发Worker）"""
        if self._redis is None:
            try:
                import redis
                pool = redis.ConnectionPool.from_url(
                    settings.redis_url,
                    max_connections=10,
                    decode_responses=True,
                    socket_timeout=30,
                    socket_connect_timeout=5,
                    socket_keepalive=True,
                    health_check_interval=30,
                )
                self._redis = redis.Redis(connection_pool=pool)
                self._redis.ping()
                log.info(f"RedisExecutionQueue | 连接成功 | {settings.REDIS_HOST}:{settings.REDIS_PORT}")
            except Exception as e:
                log.error(f"RedisExecutionQueue | 连接失败: {e}")
                self._redis = None
        return self._redis

    async def start(self, worker_count: int = 3) -> None:
        """启动Worker"""
        r = self._get_redis()
        if r is None:
            log.warning("RedisExecutionQueue | Redis不可用，跳过启动")
            return

        self._running = True
        for i in range(worker_count):
            worker = asyncio.create_task(self._worker_loop(i))
            self._workers.append(worker)

        log.info(f"RedisExecutionQueue | 启动 | workers={worker_count}")

    async def stop(self) -> None:
        """停止"""
        self._running = False
        for w in self._workers:
            w.cancel()
        self._workers.clear()
        if self._redis:
            try:
                self._redis.close()
            except Exception:
                pass
            self._redis = None
        log.info("RedisExecutionQueue | 停止")

    async def submit(
        self,
        execution_id: int,
        cases: List[Dict[str, Any]],
        context_config: Dict[str, Any],
    ) -> None:
        """提交任务到Redis队列"""
        r = self._get_redis()
        if r is None:
            raise RuntimeError("Redis不可用")

        task = json.dumps({
            "execution_id": execution_id,
            "cases": cases,
            "context_config": context_config,
        }, ensure_ascii=False)

        r.lpush(self.QUEUE_KEY, task)

        # 更新状态
        from app.services.execution.result_writer import ResultWriter
        ResultWriter.update_execution(execution_id, status="waiting")
        log.info(f"RedisExecutionQueue | 任务入队 | execution_id={execution_id}")

    async def _worker_loop(self, worker_id: int) -> None:
        """Worker循环"""
        r = self._get_redis()
        if r is None:
            return

        log.info(f"RedisExecutionQueue | Worker-{worker_id} 启动")

        while self._running:
            try:
                # BRPOP 阻塞式获取（1秒超时）— 用 to_thread 避免阻塞事件循环
                result = await asyncio.to_thread(r.brpop, self.QUEUE_KEY, 1)
                if result is None:
                    continue

                _, task_json = result
                task = json.loads(task_json)
                await self._execute_task(task, worker_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"RedisExecutionQueue | Worker-{worker_id} 异常: {e}")
                await asyncio.sleep(1)

        log.info(f"RedisExecutionQueue | Worker-{worker_id} 停止")

    async def _execute_task(self, task: Dict[str, Any], worker_id: int) -> None:
        """执行任务（复用 ExecutionQueue 逻辑）"""
        from app.services.execution.execution_queue import ExecutionQueue
        eq = ExecutionQueue()
        await eq._execute_task(task, worker_id)

    def get_queue_size(self) -> int:
        """获取队列大小"""
        r = self._get_redis()
        if r is None:
            return -1
        return r.llen(self.QUEUE_KEY)


def get_execution_queue():
    """
    获取执行队列实例（单例）

    根据 REDIS_ENABLED 配置自动选择：
    - True: RedisExecutionQueue
    - False: ExecutionQueue（asyncio.Queue）
    """
    if settings.REDIS_ENABLED:
        return _get_redis_queue_instance()
    else:
        from app.services.execution.execution_queue import ExecutionQueue
        return ExecutionQueue()


# 单例实例
_redis_queue_instance: Optional[RedisExecutionQueue] = None


def _get_redis_queue_instance() -> RedisExecutionQueue:
    """获取 RedisExecutionQueue 单例，避免每次调用创建新实例导致 worker 泄漏。"""
    global _redis_queue_instance
    if _redis_queue_instance is None:
        _redis_queue_instance = RedisExecutionQueue()
    return _redis_queue_instance
