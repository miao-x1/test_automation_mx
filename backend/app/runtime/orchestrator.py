"""
统一任务编排器

这是所有用户操作的唯一入口。
任何 API 请求都不能直接调用 Agent，必须通过 Orchestrator。

架构流程：
  用户请求 → API → Orchestrator.execute(flow_name, payload)
                              ↓
                    创建 TaskContext
                              ↓
                    从 FlowRegistry 加载流程定义
                              ↓
                    逐步执行：
                      ┌──────────────────────────────┐
                      │  1. 检查条件（condition）     │
                      │  2. AgentFactory.create()     │
                      │  3. AgentFactory.dispatch()   │
                      │  4. TaskContext.add_output()  │
                      │  5. MessageBus.publish()      │
                      │  6. DB TaskState 更新          │
                      └──────────────────────────────┘
                              ↓
                    返回最终结果

支持：
  - SSE 流式（execute → async generator）
  - 同步执行（execute_sync → dict）
  - 条件跳过
  - 异常处理（abort / continue）
  - 步骤间数据传递（input_from）
  - 状态持久化（TaskState）
  - 执行监控（AgentExecutionMonitor）
"""
from __future__ import annotations

import asyncio
import time
import uuid
import logging
from typing import Any, AsyncGenerator, Dict, Optional

from app.runtime.event import TaskEvent, EventType
from app.runtime.task_context import TaskContext
from app.runtime.message_bus import get_message_bus
from app.runtime.flow_registry import get_flow, is_flow_exists, list_flows
from app.runtime.agent_factory import AgentFactory

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    统一任务编排器

    使用方式：
        orch = Orchestrator()

        # SSE 流式
        async for event in orch.execute("unified_test_flow", payload):
            yield event  # 推送到前端

        # 同步
        result = orch.execute_sync("image_test_flow", payload)
    """

    def __init__(self):
        self._bus = get_message_bus()

    # ── 查询接口 ──

    @staticmethod
    def list_flows() -> list:
        """列出所有可用流程"""
        return list_flows()

    @staticmethod
    def is_flow_exists(flow_name: str) -> bool:
        """检查流程是否存在"""
        return is_flow_exists(flow_name)

    # ── SSE 流式执行 ──

    async def execute(
        self,
        flow_name: str,
        payload: Dict[str, Any],
        task_id: Optional[int] = None,
        session_id: Optional[str] = None,
        user_id: int = 0,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """执行任务流程（SSE 流式）

        Args:
            flow_name: 流程名称
            payload: 输入参数
            task_id: 任务ID（关联 DB Task 表）
            session_id: 会话ID
            user_id: 用户ID

        Yields:
            SSE 事件字典：
              {"event": "flow_start", ...}
              {"event": "step_start", ...}
              {"event": "step_success", ...}
              {"event": "step_failed", ...}
              {"event": "step_skipped", ...}
              {"event": "flow_success", "result": ...}
              {"event": "flow_failed", "error": ...}
              {"event": "done"}
        """
        # 验证流程存在
        flow = get_flow(flow_name)
        if flow is None:
            yield {
                "event": EventType.FLOW_FAILED.value,
                "flow_name": flow_name,
                "error": f"流程 '{flow_name}' 不存在",
            }
            yield {"event": EventType.DONE.value}
            return

        # 确保 AgentFactory 已初始化
        AgentFactory.initialize()

        # 创建 TaskContext
        ctx = TaskContext(
            task_id=str(task_id) if task_id else "",
            session_id=str(session_id) if session_id else "",
            flow_name=flow_name,
            user_id=user_id,
            payload=payload,
            total_steps=len(flow.steps),
        )
        ctx.status = "running"

        # 创建 TaskState 记录
        state_id = self._create_task_state(
            task_id=task_id or 0,
            session_id=session_id,
            flow_name=flow_name,
            total_steps=len(flow.steps),
            request_id=ctx.request_id,
        )

        # 发布 flow_start 事件
        await self._publish_event(ctx, EventType.FLOW_START, data={
            "description": flow.description,
            "total_steps": len(flow.steps),
        })
        yield self._make_sse(ctx, EventType.FLOW_START, data={
            "description": flow.description,
            "total_steps": len(flow.steps),
        })

        logger.info(
            f"Orchestrator | 开始执行 | "
            f"request_id={ctx.request_id} | flow={flow_name} | "
            f"task_id={task_id} | steps={len(flow.steps)}"
        )

        # 逐步执行
        failed = False
        error_message = ""

        for i, step in enumerate(flow.steps):
            # 条件检查
            if not ctx.eval_condition(step.condition):
                ctx.skip_step(step.step_name)
                await self._publish_event(ctx, EventType.STEP_SKIPPED,
                    step_name=step.step_name,
                    agent_name=step.agent_name,
                    step_index=i,
                    data={"reason": f"条件不满足: {step.condition}"},
                )
                yield self._make_sse(ctx, EventType.STEP_SKIPPED,
                    step_name=step.step_name,
                    agent_name=step.agent_name,
                    step_index=i,
                    progress=int((i + 1) / len(flow.steps) * 100),
                    data={"reason": f"条件不满足: {step.condition}"},
                )
                continue

            # 更新 TaskState
            if state_id:
                self._update_task_state(state_id, current_agent=step.agent_name, step_index=i)

            # 发布 step_start 事件
            ctx.start_step(step.step_name, step.agent_name, step.action)
            await self._publish_event(ctx, EventType.STEP_START,
                step_name=step.step_name,
                agent_name=step.agent_name,
                step_index=i,
                data={"action": step.action, "description": step.description},
            )
            yield self._make_sse(ctx, EventType.STEP_START,
                step_name=step.step_name,
                agent_name=step.agent_name,
                step_index=i,
                progress=int(i / len(flow.steps) * 100),
                data={"action": step.action, "description": step.description},
            )

            logger.info(
                f"Orchestrator | 步骤 {i+1}/{len(flow.steps)} | "
                f"step={step.step_name} | agent={step.agent_name}"
            )

            # 执行 Agent
            start_time = time.time()
            try:
                # 合并输入：payload + 前序步骤输出
                step_input = ctx.merge_input()

                # 通过 AgentFactory 创建并执行 Agent
                output = await self._execute_agent(
                    agent_name=step.agent_name,
                    action=step.action,
                    input_data=step_input,
                    ctx=ctx,
                )

                duration_ms = int((time.time() - start_time) * 1000)
                ctx.finish_step(step.step_name, output, duration_ms)

                # 更新 TaskState
                if state_id:
                    self._update_task_state(state_id, step_record={
                        "step_name": step.step_name,
                        "agent_name": step.agent_name,
                        "status": "success",
                        "duration_ms": duration_ms,
                    })

                # 发布 step_success 事件
                await self._publish_event(ctx, EventType.STEP_SUCCESS,
                    step_name=step.step_name,
                    agent_name=step.agent_name,
                    step_index=i,
                    data={"output": _safe(output), "duration_ms": duration_ms},
                )
                yield self._make_sse(ctx, EventType.STEP_SUCCESS,
                    step_name=step.step_name,
                    agent_name=step.agent_name,
                    step_index=i,
                    progress=int((i + 1) / len(flow.steps) * 100),
                    data={"output": _safe(output), "duration_ms": duration_ms},
                )

                logger.info(
                    f"Orchestrator | 步骤成功 | "
                    f"step={step.step_name} | duration={duration_ms}ms"
                )

            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                ctx.fail_step(step.step_name, str(e), duration_ms)
                error_message = f"步骤 '{step.step_name}' 失败: {e}"

                logger.error(
                    f"Orchestrator | 步骤失败 | "
                    f"step={step.step_name} | error={e}",
                    exc_info=True,
                )

                # 更新 TaskState
                if state_id:
                    self._update_task_state(state_id, step_record={
                        "step_name": step.step_name,
                        "agent_name": step.agent_name,
                        "status": "failed",
                        "error": str(e),
                        "duration_ms": duration_ms,
                    })

                # 发布 step_failed 事件
                await self._publish_event(ctx, EventType.STEP_FAILED,
                    step_name=step.step_name,
                    agent_name=step.agent_name,
                    step_index=i,
                    error=str(e),
                    data={"required": step.required},
                )
                yield self._make_sse(ctx, EventType.STEP_FAILED,
                    step_name=step.step_name,
                    agent_name=step.agent_name,
                    step_index=i,
                    error=str(e),
                    data={"required": step.required},
                )

                # 判断是否终止
                if step.required and step.on_failure == "abort":
                    failed = True
                    break
                else:
                    # 非必需步骤失败，继续
                    continue

        # 流程结束
        ctx.finished_at = time.time()

        if failed:
            ctx.status = "failed"
            ctx.error = error_message

            if state_id:
                self._update_task_state(
                    state_id, status="failed",
                    error_message=error_message,
                    result=ctx.to_result(),
                )

            await self._publish_event(ctx, EventType.FLOW_FAILED,
                error=error_message,
                data={"completed_steps": len(ctx.step_records)},
            )
            yield self._make_sse(ctx, EventType.FLOW_FAILED,
                error=error_message,
                data={
                    "completed_steps": len(ctx.step_records),
                    "total_steps": len(flow.steps),
                },
            )
        else:
            ctx.status = "success"

            if state_id:
                self._update_task_state(
                    state_id, status="success",
                    result=ctx.to_result(),
                )

            result = ctx.to_result()
            await self._publish_event(ctx, EventType.FLOW_SUCCESS,
                data={"result": _safe(result)},
            )
            yield self._make_sse(ctx, EventType.FLOW_SUCCESS,
                data={"result": _safe(result)},
            )

        logger.info(
            f"Orchestrator | 执行完成 | "
            f"flow={flow_name} | status={'failed' if failed else 'success'}"
        )

        yield {"event": EventType.DONE.value}

    # ── 同步执行 ──

    def execute_sync(
        self,
        flow_name: str,
        payload: Dict[str, Any],
        task_id: Optional[int] = None,
        session_id: Optional[str] = None,
        user_id: int = 0,
    ) -> Dict[str, Any]:
        """同步执行任务流程（非流式）

        Returns:
            {"status": "success"|"failed", "result": ..., "error": ...}
        """
        async def _run():
            events = []
            async for event in self.execute(
                flow_name, payload, task_id, session_id, user_id
            ):
                events.append(event)
            return events

        try:
            # 尝试在已有事件循环中运行
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 已有事件循环，使用新线程
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run, _run()
                    )
                    events = future.result()
            else:
                events = loop.run_until_complete(_run())
        except RuntimeError:
            events = asyncio.run(_run())

        result = {"status": "unknown", "result": {}, "error": ""}
        for event in events:
            if event.get("event") == EventType.FLOW_SUCCESS.value:
                result["status"] = "success"
                result["result"] = event.get("data", {}).get("result", {})
            elif event.get("event") == EventType.FLOW_FAILED.value:
                result["status"] = "failed"
                result["error"] = event.get("error", "")
        return result

    # ── Agent 执行 ──

    async def _execute_agent(
        self,
        agent_name: str,
        action: str,
        input_data: Dict[str, Any],
        ctx: TaskContext,
    ) -> Any:
        """通过 AgentFactory 创建 Agent 并执行

        集成 AgentExecutionMonitor 记录执行详情。
        """
        from app.services.monitor import get_execution_monitor

        monitor = get_execution_monitor()
        monitor_log_id = monitor.record_start(
            agent_name=agent_name,
            step=ctx.step_records[-1].step_name if ctx.step_records else action,
            input_data=input_data,
            task_id=ctx.task_id,
            session_id=ctx.session_id,
            flow_name=ctx.flow_name,
        )

        # 通过 AgentFactory 创建 Agent
        agent = AgentFactory.create(agent_name)
        start = time.time()

        try:
            # 通过 AgentFactory 分发 action
            output = await AgentFactory.dispatch_action(agent, action, input_data)

            duration_ms = int((time.time() - start) * 1000)
            monitor.record_success(
                log_id=monitor_log_id,
                output=output,
                duration_ms=duration_ms,
            )
            return output

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            monitor.record_failure(
                log_id=monitor_log_id,
                error=str(e),
                duration_ms=duration_ms,
            )
            raise

    # ── MessageBus 发布 ──

    async def _publish_event(
        self,
        ctx: TaskContext,
        event_type: EventType,
        step_name: str = "",
        agent_name: str = "",
        step_index: int = 0,
        error: str = "",
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """发布事件到 MessageBus"""
        event = TaskEvent(
            event=event_type.value,
            request_id=ctx.request_id,
            task_id=ctx.task_id,
            flow_name=ctx.flow_name,
            step_name=step_name,
            agent_name=agent_name,
            step_index=step_index,
            total_steps=ctx.total_steps,
            progress=int((step_index + 1) / max(ctx.total_steps, 1) * 100),
            data=data or {},
            error=error,
        )
        await self._bus.publish(event)

    # ── SSE 事件构建 ──

    @staticmethod
    def _make_sse(
        ctx: TaskContext,
        event_type: EventType,
        step_name: str = "",
        agent_name: str = "",
        step_index: int = 0,
        progress: int = 0,
        error: str = "",
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """构建 SSE 事件字典"""
        return {
            "event": event_type.value,
            "request_id": ctx.request_id,
            "task_id": ctx.task_id,
            "flow_name": ctx.flow_name,
            "step_name": step_name,
            "agent_name": agent_name,
            "step_index": step_index,
            "total_steps": ctx.total_steps,
            "progress": progress,
            "data": _safe(data or {}),
            "error": error,
        }

    # ── DB TaskState 管理 ──

    @staticmethod
    def _create_task_state(
        task_id: int,
        session_id: Optional[str],
        flow_name: str,
        total_steps: int,
        request_id: str = "",
    ) -> Optional[int]:
        """创建 TaskState 记录，返回 state_id"""
        try:
            from app.db.database import SessionLocal
            from app.models.task_state import TaskState

            db = SessionLocal()
            try:
                state = TaskState(
                    task_id=task_id,
                    session_id=int(session_id) if session_id and str(session_id).isdigit() else None,
                    flow_name=flow_name,
                    status="running",
                    step_index=0,
                    total_steps=total_steps,
                )
                db.add(state)
                db.commit()
                db.refresh(state)
                logger.debug(
                    f"Orchestrator | TaskState 创建 | "
                    f"id={state.id} | flow={flow_name}"
                )
                return state.id
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Orchestrator | 创建 TaskState 失败: {e}")
            return None

    @staticmethod
    def _update_task_state(
        state_id: int,
        current_agent: Optional[str] = None,
        status: Optional[str] = None,
        step_index: Optional[int] = None,
        result: Optional[dict] = None,
        error_message: Optional[str] = None,
        step_record: Optional[dict] = None,
    ) -> None:
        """更新 TaskState 记录"""
        try:
            from app.db.database import SessionLocal
            from app.models.task_state import TaskState

            db = SessionLocal()
            try:
                state = db.query(TaskState).filter(TaskState.id == state_id).first()
                if state is None:
                    return

                if current_agent is not None:
                    state.current_agent = current_agent
                if status is not None:
                    state.status = status
                if step_index is not None:
                    state.step_index = step_index
                if result is not None:
                    state.set_result(result)
                if error_message is not None:
                    state.error_message = error_message
                if step_record is not None:
                    state.append_step(step_record)

                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Orchestrator | 更新 TaskState 失败: {e}")


# ── 单例 ──

_orchestrator: Optional[Orchestrator] = None


def get_orchestrator() -> Orchestrator:
    """获取全局 Orchestrator 单例"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


# ── 工具函数 ──

def _safe(obj: Any) -> Any:
    """安全序列化"""
    import json
    try:
        json.dumps(obj, ensure_ascii=False, default=str)
        return obj
    except (TypeError, ValueError):
        return str(obj)
