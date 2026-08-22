"""
Agent Worker - 单个任务执行器

每个 AgentWorker 实例负责:
    1. 接收一个 TaskState
    2. 通过 AgentFactory 创建 Agent
    3. 调用 Agent.execute() (带超时)
    4. 捕获事件 (通过 ResponseCollector 订阅)
    5. 将结果回传给 TaskDispatcher.complete()

不维护自身状态,每次执行都是一个独立的 async 调用。
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
import traceback
from typing import Any, Dict, List, Optional

from app.runtime.enterprise.dispatcher.task_state import TaskState, TaskStatus

logger = logging.getLogger(__name__)


class AgentWorker:
    """单个 Agent 任务执行器

    使用方式 (通常由 WorkerPool 调用):
        worker = AgentWorker(worker_id="w-001", worker_pool=pool)
        await worker.execute(state, dispatcher)
    """

    def __init__(
        self,
        worker_id: Optional[str] = None,
        worker_pool: Any = None,
    ) -> None:
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.worker_pool = worker_pool
        self._current_task: Optional[str] = None
        self._busy = False
        self._tasks_done = 0
        self._tasks_failed = 0
        self._total_duration_ms = 0

    @property
    def is_busy(self) -> bool:
        return self._busy

    @property
    def current_task(self) -> Optional[str]:
        return self._current_task

    # ----------------------------------------------------------
    # 执行任务
    # ----------------------------------------------------------

    async def execute(
        self,
        state: TaskState,
        dispatcher: Any,
    ) -> None:
        """执行单个任务

        步骤:
            1. 标记状态为 RUNNING
            2. 通过 AgentFactory 创建 Agent
            3. 调用 Agent.execute() (带超时)
            4. 收集结果与事件
            5. 回调 dispatcher.complete()

        Args:
            state: 任务状态
            dispatcher: TaskDispatcher 实例 (用于回调)
        """
        # 注: busy 状态由 WorkerPool 管理,这里不再检查
        self._current_task = state.task_id
        start_time = time.time()
        events: List[Dict[str, Any]] = []

        # 获取 Collector (用于事后收集事件,不订阅)
        collector = await self._get_collector()

        # 状态转移: PENDING → RUNNING
        if not state.transition(TaskStatus.RUNNING):
            logger.warning(
                f"[AgentWorker {self.worker_id}] 状态转移失败: "
                f"{state.status} → RUNNING (task={state.task_id})"
            )
            await dispatcher.complete(
                task_id=state.task_id,
                status=TaskStatus.FAILED,
                error=f"非法状态: {state.status.value}",
                worker_id=self.worker_id,
            )
            self._reset()
            return

        state.worker_id = self.worker_id
        logger.info(
            f"[AgentWorker {self.worker_id}] 开始执行 | "
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
                logger.warning(
                    f"[AgentWorker {self.worker_id}] Agent 返回错误 | "
                    f"task={state.task_id} | error={error}"
                )

        except asyncio.TimeoutError:
            final_status = TaskStatus.TIMEOUT
            error = f"任务超时 ({state.timeout_seconds}s)"
            logger.warning(
                f"[AgentWorker {self.worker_id}] 任务超时 | "
                f"task={state.task_id} | timeout={state.timeout_seconds}s"
            )
        except asyncio.CancelledError:
            final_status = TaskStatus.CANCELLED
            error = "任务被取消"
            logger.info(f"[AgentWorker {self.worker_id}] 任务取消: {state.task_id}")
            raise
        except Exception as e:
            final_status = TaskStatus.FAILED
            error = f"{type(e).__name__}: {e}"
            error_tb = traceback.format_exc()
            logger.error(
                f"[AgentWorker {self.worker_id}] 任务异常 | "
                f"task={state.task_id} | error={e}\n{error_tb}"
            )
            events.append({
                "type": "error",
                "step": "agent_execute",
                "message": str(e),
                "traceback": error_tb,
                "timestamp": time.time(),
            })

        # 计算耗时
        duration_ms = int((time.time() - start_time) * 1000)
        self._tasks_done += 1
        self._total_duration_ms += duration_ms
        if final_status == TaskStatus.FAILED:
            self._tasks_failed += 1

        # 收集最终事件
        if collector:
            final_events = await collector.collect(state.task_id)
            events.extend(final_events)

        # 回调 Dispatcher
        await dispatcher.complete(
            task_id=state.task_id,
            status=final_status,
            result=result if final_status == TaskStatus.SUCCESS else None,
            error=error,
            events=events,
            duration_ms=duration_ms,
            worker_id=self.worker_id,
        )

        self._reset()

        logger.info(
            f"[AgentWorker {self.worker_id}] 执行完成 | "
            f"task={state.task_id} | status={final_status.value} | "
            f"duration={duration_ms}ms"
        )

    # ----------------------------------------------------------
    # 内部: 调用 Agent
    # ----------------------------------------------------------

    async def _invoke_agent(self, state: TaskState) -> Any:
        """通过 AgentFactory 创建 Agent 并调用

        优先使用 BaseRoutedAgent.execute() 直接调用,
        兼容旧式 Agent 的 dispatch_action()。
        """
        from app.agents.factory.factory import get_agent_factory

        factory = get_agent_factory()
        session_key = state.session_id or "default"

        # 创建 Agent 实例
        agent = await factory.create(
            name=state.agent_name,
            runtime=None,  # BaseRoutedAgent 不需要 runtime
            session_key=session_key,
        )

        # 构造 payload (注入 task_id)
        payload = dict(state.payload)
        payload.setdefault("task_id", state.task_id)
        payload.setdefault("action", state.action)

        # 调用 Agent
        if hasattr(agent, "execute"):
            # BaseRoutedAgent: execute(payload, ctx)
            # 构造一个合法的 MessageContext (Agent 直接调用模式)
            import uuid as _uuid
            from autogen_core import MessageContext, CancellationToken
            ctx = MessageContext(
                sender=None,
                topic_id=None,
                is_rpc=False,
                cancellation_token=CancellationToken(),
                message_id=str(_uuid.uuid4()),
            )
            result = await agent.execute(payload, ctx)
            return result

        # 兼容旧式 Agent: dispatch_action
        if hasattr(agent, "dispatch_action"):
            return await agent.dispatch_action(state.action, payload)

        # 最后手段: 直接调用
        if hasattr(agent, state.action):
            method = getattr(agent, state.action)
            if asyncio.iscoroutinefunction(method):
                return await method(**payload)
            return method(**payload)

        raise RuntimeError(
            f"Agent '{state.agent_name}' 没有可调用的方法 "
            f"(execute / dispatch_action / {state.action})"
        )

    # ----------------------------------------------------------
    # 内部: 获取 ResponseCollector
    # ----------------------------------------------------------

    async def _get_collector(self) -> Any:
        """获取 ResponseCollector (可选)"""
        try:
            from app.runtime.enterprise.collector.response_collector import get_response_collector
            return get_response_collector()
        except Exception:
            return None

    def _reset(self) -> None:
        """重置 Worker 状态"""
        self._busy = False
        self._current_task = None

    # ----------------------------------------------------------
    # 状态查询
    # ----------------------------------------------------------

    def stats(self) -> Dict[str, Any]:
        """获取 Worker 统计信息"""
        return {
            "worker_id": self.worker_id,
            "is_busy": self._busy,
            "current_task": self._current_task,
            "tasks_done": self._tasks_done,
            "tasks_failed": self._tasks_failed,
            "total_duration_ms": self._total_duration_ms,
            "avg_duration_ms": (
                self._total_duration_ms / self._tasks_done
                if self._tasks_done > 0 else 0
            ),
        }
