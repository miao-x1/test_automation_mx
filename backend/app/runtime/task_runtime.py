"""
AutoGen Core Runtime - TaskRuntime (FastAPI 桥接)

负责：
1. 接收 FastAPI 请求
2. 提交任务到 Runtime（通过 RuntimeManager）
3. 等待结果并返回
4. 支持 SSE 流式返回进度
5. 支持 Pipeline 多步任务

流程：
    FastAPI Request
        ↓
    TaskRuntime.execute()
        ↓
    RuntimeManager.submit_task()
        ↓
    CoreRuntime.send_task()
        ↓
    SingleThreadedAgentRuntime.send_message()
        ↓
    Target Agent.handle_task_message()
        ↓
    Agent.execute()
        ↓
    Agent.publish_result()
        ↓
    CollectorAgent.handle_result()
        ↓
    CoreRuntime.get_result()
        ↓
    TaskRuntime 返回结果
"""
import asyncio
import json
import logging
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

from app.runtime.runtime_manager import RuntimeManager, get_runtime_manager
from app.runtime.messages import (
    TaskMessage,
    AgentRequest,
    AgentResponse,
    ProgressMessage,
    ResultMessage,
)

logger = logging.getLogger(__name__)


class TaskRuntime:
    """
    TaskRuntime - FastAPI 与 AutoGen Core Runtime 之间的桥接层

    FastAPI 路由调用 TaskRuntime 的方法，
    TaskRuntime 通过 RuntimeManager 提交任务到 Runtime，
    并等待/返回结果。

    使用方式（在 FastAPI 中）：
        task_runtime = get_task_runtime()
        result = await task_runtime.execute(
            agent_type="requirement_agent",
            action="analyze",
            payload={"requirement": "..."},
            user_id=current_user.id,
        )
    """

    def __init__(self) -> None:
        self._manager: RuntimeManager = get_runtime_manager()

    # ------------------------------------------------------------------ #
    #  单任务执行                                                          #
    # ------------------------------------------------------------------ #

    async def execute(
        self,
        agent_type: str,
        action: str = "execute",
        payload: Optional[Dict[str, Any]] = None,
        task_id: str = "",
        user_id: Optional[int] = None,
        session_id: str = "",
        timeout: float = 300,
    ) -> Dict[str, Any]:
        """
        提交任务并等待结果

        Args:
            agent_type: 目标 Agent 类型
            action: 要执行的方法名
            payload: 方法参数
            task_id: 任务ID
            user_id: 用户ID
            session_id: 会话ID
            timeout: 超时时间（秒）

        Returns:
            任务结果字典:
            {
                "task_id": "...",
                "status": "completed" / "failed" / "timeout",
                "data": {...},
                "errors": [...],
                "duration": 0.0,
                "agent_type": "...",
            }
        """
        if not task_id:
            task_id = str(uuid.uuid4())

        if payload is None:
            payload = {}

        # 提交任务
        await self._manager.submit_task(
            agent_type=agent_type,
            action=action,
            payload=payload,
            task_id=task_id,
            user_id=user_id,
            session_id=session_id,
        )

        # 确定 session_key
        session_key = self._manager.make_session_key(
            user_id, session_id or task_id[:8]
        )

        # 等待结果
        result = await self._manager.get_result(
            task_id=task_id,
            session_key=session_key,
            timeout=timeout,
        )

        if result is None:
            return {
                "task_id": task_id,
                "status": "timeout",
                "data": {},
                "errors": [{"message": f"Task timed out after {timeout}s"}],
                "duration": timeout,
                "agent_type": agent_type,
            }

        return result

    # ------------------------------------------------------------------ #
    #  SSE 流式执行                                                        #
    # ------------------------------------------------------------------ #

    async def execute_sse(
        self,
        agent_type: str,
        action: str = "execute",
        payload: Optional[Dict[str, Any]] = None,
        task_id: str = "",
        user_id: Optional[int] = None,
        session_id: str = "",
        timeout: float = 300,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        提交任务并以 SSE 方式返回进度和结果

        Yields SSE events:
        - {"event": "start", "data": {"task_id": "...", "agent_type": "..."}}
        - {"event": "progress", "data": {"step": "...", "status": "running", ...}}
        - {"event": "result", "data": {"status": "completed", "data": {...}}}
        - {"event": "error", "data": {"message": "..."}}
        - {"event": "done", "data": {}}
        """
        if not task_id:
            task_id = str(uuid.uuid4())

        if payload is None:
            payload = {}

        if not session_id:
            session_id = task_id[:8]

        session_key = self._manager.make_session_key(user_id, session_id)

        # 确保 Runtime 已启动
        await self._manager.ensure_started()

        # 发送 start 事件
        yield {
            "event": "start",
            "data": {
                "task_id": task_id,
                "agent_type": agent_type,
                "action": action,
                "session_key": session_key,
            },
        }

        # 创建结果等待任务
        result_task = asyncio.create_task(
            self._manager.get_result(task_id, session_key, timeout)
        )

        # 提交任务
        await self._manager.submit_task(
            agent_type=agent_type,
            action=action,
            payload=payload,
            task_id=task_id,
            user_id=user_id,
            session_id=session_id,
        )

        # 轮询进度（通过 CollectorAgent）
        last_progress = 0.0
        start_time = asyncio.get_event_loop().time()

        while not result_task.done():
            # 尝试获取进度
            progress = await self._get_progress(task_id, session_key)
            if progress and progress.get("progress", 0) > last_progress:
                yield {"event": "progress", "data": progress}
                last_progress = progress.get("progress", 0)

            # 检查超时
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                yield {
                    "event": "error",
                    "data": {"task_id": task_id, "message": f"Task timed out after {timeout}s"},
                }
                yield {"event": "done", "data": {}}
                return

            await asyncio.sleep(0.5)

        # 获取最终结果
        result = await result_task

        if result is None:
            yield {
                "event": "error",
                "data": {"task_id": task_id, "message": "Task failed or timed out"},
            }
        elif result.get("status") == "failed":
            yield {
                "event": "error",
                "data": {
                    "task_id": task_id,
                    "message": result.get("errors", ["Unknown error"]),
                    "result": result,
                },
            }
        else:
            yield {"event": "result", "data": result}

        yield {"event": "done", "data": {}}

    # ------------------------------------------------------------------ #
    #  Pipeline 多步执行                                                   #
    # ------------------------------------------------------------------ #

    async def execute_pipeline(
        self,
        steps: List[Dict[str, Any]],
        user_id: Optional[int] = None,
        session_id: str = "",
        timeout: float = 600,
    ) -> Dict[str, Any]:
        """
        执行多步 Pipeline（前一步的输出作为下一步的输入）

        Args:
            steps: 步骤列表
                [
                    {
                        "agent_type": "requirement_agent",
                        "action": "analyze",
                        "payload": {"requirement": "..."},
                        "output_key": "requirement_result",  # 存入上下文的 key
                    },
                    {
                        "agent_type": "case_agent",
                        "action": "generate",
                        "payload": {},  # 从上下文自动获取
                        "input_keys": ["requirement_result"],  # 从上下文取值
                    },
                ]
            user_id: 用户ID
            session_id: 会话ID
            timeout: 总超时时间

        Returns:
            {
                "status": "completed" / "failed",
                "steps": [...],  # 每步结果
                "context": {...},  # 最终上下文
                "final_data": {...},  # 最后一步的输出
            }
        """
        if not session_id:
            session_id = str(uuid.uuid4())[:8]

        session_key = self._manager.make_session_key(user_id, session_id)
        await self._manager.create_session(user_id, session_id)

        context: Dict[str, Any] = {}
        step_results: List[Dict[str, Any]] = []
        final_data: Optional[Dict[str, Any]] = None

        for i, step in enumerate(steps):
            agent_type = step["agent_type"]
            action = step.get("action", "execute")
            payload = dict(step.get("payload", {}))
            output_key = step.get("output_key")
            input_keys = step.get("input_keys", [])

            # 声明式参数映射
            param_mapping = step.get("param_mapping", {})
            extract_fields = step.get("extract_fields", {})
            defaults = step.get("defaults", {})
            pipeline_meta = context.get("__pipeline_meta__", {})

            # 从上下文注入参数（支持映射和字段提取）
            for key in input_keys:
                if key in context:
                    param_name = param_mapping.get(key, key)
                    value = context[key]
                    extract_field = extract_fields.get(key)
                    if extract_field and isinstance(value, dict):
                        value = value.get(extract_field, value)
                    payload[param_name] = value

            # 注入默认值（支持 __meta__. 引用管道元数据）
            for param_name, default_value in defaults.items():
                if param_name not in payload:
                    if isinstance(default_value, str) and default_value.startswith("__meta__."):
                        meta_key = default_value[len("__meta__."):]
                        payload[param_name] = pipeline_meta.get(meta_key, 0)
                    else:
                        payload[param_name] = default_value

            # 提取管道元数据到 context
            if "__pipeline_meta__" in payload:
                context["__pipeline_meta__"] = payload.pop("__pipeline_meta__")

            # 条件步骤检查：condition 不满足则跳过
            should_run, skip_reason = self._should_run_step(step, context)
            if not should_run:
                logger.info(f"Step {i} ({agent_type}) skipped: {skip_reason}")
                if output_key:
                    context[output_key] = {"status": "skipped", "reason": skip_reason}
                step_results.append({
                    "step": i, "agent_type": agent_type, "action": action,
                    "task_id": "", "status": "skipped",
                    "data": {"status": "skipped", "reason": skip_reason}, "duration": 0,
                })
                continue

            step_task_id = str(uuid.uuid4())

            # 执行步骤
            result = await self.execute(
                agent_type=agent_type,
                action=action,
                payload=payload,
                task_id=step_task_id,
                user_id=user_id,
                session_id=session_id,
                timeout=timeout,
            )

            step_results.append({
                "step": i,
                "agent_type": agent_type,
                "action": action,
                "task_id": step_task_id,
                "status": result.get("status"),
                "data": result.get("final_data") or result.get("data"),
                "duration": result.get("duration"),
            })

            # 检查是否失败
            if result.get("status") == "failed":
                is_required = step.get("required", True)
                if is_required:
                    return {
                        "status": "failed",
                        "failed_step": i,
                        "steps": step_results,
                        "context": context,
                        "final_data": None,
                    }
                else:
                    logger.warning(f"Step {i} ({agent_type}) failed but not required, skipping")
                    if output_key:
                        context[output_key] = {"status": "skipped", "error": str(result.get("errors", ""))}
                    continue

            # 存入上下文
            step_data = result.get("final_data") or result.get("data", {})
            if output_key:
                context[output_key] = step_data
            else:
                context[f"step_{i}_output"] = step_data

            # 自动更新 __pipeline_meta__（如脚本内容、执行ID等）
            self._update_pipeline_meta(output_key, step_data, context)

            final_data = step_data

        return {
            "status": "completed",
            "steps": step_results,
            "context": context,
            "final_data": final_data,
        }

    async def execute_pipeline_sse(
        self,
        steps: List[Dict[str, Any]],
        user_id: Optional[int] = None,
        session_id: str = "",
        timeout: float = 600,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Pipeline SSE 流式执行

        Yields:
        - {"event": "pipeline_start", "data": {"steps": [...], "session_id": "..."}}
        - {"event": "step_start", "data": {"step": 0, "agent_type": "..."}}
        - {"event": "step_progress", "data": {"step": 0, ...}}
        - {"event": "step_completed", "data": {"step": 0, "status": "completed", "data": {...}}}
        - {"event": "step_failed", "data": {"step": 0, "error": "..."}}
        - {"event": "pipeline_completed", "data": {"steps": [...], "final_data": {...}}}
        - {"event": "done", "data": {}}
        """
        if not session_id:
            session_id = str(uuid.uuid4())[:8]

        yield {
            "event": "pipeline_start",
            "data": {
                "steps": [{"agent_type": s["agent_type"], "action": s.get("action", "execute")} for s in steps],
                "session_id": session_id,
                "total_steps": len(steps),
            },
        }

        session_key = self._manager.make_session_key(user_id, session_id)
        await self._manager.create_session(user_id, session_id)

        context: Dict[str, Any] = {}
        step_results: List[Dict[str, Any]] = []
        final_data: Optional[Dict[str, Any]] = None

        for i, step in enumerate(steps):
            agent_type = step["agent_type"]
            action = step.get("action", "execute")
            payload = dict(step.get("payload", {}))
            output_key = step.get("output_key")
            input_keys = step.get("input_keys", [])

            # 声明式参数映射
            param_mapping = step.get("param_mapping", {})
            extract_fields = step.get("extract_fields", {})
            defaults = step.get("defaults", {})
            pipeline_meta = context.get("__pipeline_meta__", {})

            # 从上下文注入参数（支持映射和字段提取）
            for key in input_keys:
                if key in context:
                    param_name = param_mapping.get(key, key)
                    value = context[key]
                    extract_field = extract_fields.get(key)
                    if extract_field and isinstance(value, dict):
                        value = value.get(extract_field, value)
                    payload[param_name] = value

            # 注入默认值（支持 __meta__. 引用管道元数据）
            for param_name, default_value in defaults.items():
                if param_name not in payload:
                    if isinstance(default_value, str) and default_value.startswith("__meta__."):
                        meta_key = default_value[len("__meta__."):]
                        payload[param_name] = pipeline_meta.get(meta_key, 0)
                    else:
                        payload[param_name] = default_value

            # 提取管道元数据到 context
            if "__pipeline_meta__" in payload:
                context["__pipeline_meta__"] = payload.pop("__pipeline_meta__")

            # 条件步骤检查：condition 不满足则跳过
            should_run, skip_reason = self._should_run_step(step, context)
            if not should_run:
                logger.info(f"Step {i} ({agent_type}) skipped: {skip_reason}")
                if output_key:
                    context[output_key] = {"status": "skipped", "reason": skip_reason}
                yield {
                    "event": "step_skipped",
                    "data": {"step": i, "agent_type": agent_type, "reason": skip_reason},
                }
                step_results.append({
                    "step": i, "agent_type": agent_type, "action": action,
                    "status": "skipped",
                    "data": {"status": "skipped", "reason": skip_reason}, "duration": 0,
                })
                continue

            is_required = step.get("required", True)

            step_task_id = str(uuid.uuid4())

            yield {
                "event": "step_start",
                "data": {
                    "step": i,
                    "agent_type": agent_type,
                    "action": action,
                    "task_id": step_task_id,
                },
            }

            # 使用 SSE 执行单步
            step_result = None
            async for event in self.execute_sse(
                agent_type=agent_type,
                action=action,
                payload=payload,
                task_id=step_task_id,
                user_id=user_id,
                session_id=session_id,
                timeout=timeout,
            ):
                event_type = event.get("event")
                event_data = event.get("data", {})

                if event_type == "progress":
                    yield {
                        "event": "step_progress",
                        "data": {"step": i, **event_data},
                    }
                elif event_type == "result":
                    step_result = event_data
                    yield {
                        "event": "step_completed",
                        "data": {
                            "step": i,
                            "status": step_result.get("status", "completed"),
                            "data": step_result.get("final_data") or step_result.get("data"),
                            "duration": step_result.get("duration"),
                        },
                    }
                elif event_type == "error":
                    yield {
                        "event": "step_failed",
                        "data": {"step": i, "error": event_data},
                    }
                    if is_required:
                        yield {"event": "done", "data": {"failed_step": i}}
                        return
                    else:
                        # 非必需步骤失败，跳过继续
                        logger.warning(f"Step {i} ({agent_type}) failed but not required, skipping")
                        if output_key:
                            context[output_key] = {"status": "skipped", "error": str(event_data)}
                        step_results.append({
                            "step": i,
                            "agent_type": agent_type,
                            "status": "skipped",
                            "data": {"status": "skipped", "error": str(event_data)},
                            "duration": 0,
                        })
                        step_result = None
                        continue

            # 存入上下文
            if step_result:
                step_data = step_result.get("final_data") or step_result.get("data", {})
                if output_key:
                    context[output_key] = step_data
                else:
                    context[f"step_{i}_output"] = step_data

                # 自动更新 __pipeline_meta__（如脚本内容、执行ID等）
                self._update_pipeline_meta(output_key, step_data, context)

                final_data = step_data

                step_results.append({
                    "step": i,
                    "agent_type": agent_type,
                    "status": step_result.get("status"),
                    "data": step_data,
                    "duration": step_result.get("duration"),
                })

        yield {
            "event": "pipeline_completed",
            "data": {
                "steps": step_results,
                "context": context,
                "final_data": final_data,
                "session_id": session_id,
            },
        }

        yield {"event": "done", "data": {}}

    # ------------------------------------------------------------------ #
    #  辅助方法                                                           #
    # ------------------------------------------------------------------ #

    def _should_run_step(self, step: Dict, context: Dict) -> tuple:
        """
        检查步骤是否应该执行（基于 condition 字段）

        Returns:
            (should_run, reason)
        """
        condition = step.get("condition")
        if not condition:
            return True, ""

        context_key = condition.get("context_key", "")
        field = condition.get("field", "status")
        op = condition.get("op", "equals")
        expected = condition.get("value")

        if not context_key or context_key not in context:
            return True, f"condition context_key '{context_key}' not in context, running by default"

        actual_value = context[context_key]
        if isinstance(actual_value, dict) and field:
            actual_value = actual_value.get(field)
        elif isinstance(actual_value, str) and field:
            actual_value = actual_value  # 字符串直接比较

        if op == "equals":
            should_run = actual_value == expected
        elif op == "not_equals":
            should_run = actual_value != expected
        elif op == "contains":
            should_run = expected in (actual_value or [])
        elif op == "gt":
            try:
                should_run = float(actual_value or 0) > float(expected)
            except (ValueError, TypeError):
                should_run = False
        elif op == "lt":
            try:
                should_run = float(actual_value or 0) < float(expected)
            except (ValueError, TypeError):
                should_run = False
        else:
            should_run = True

        reason = "" if should_run else f"condition not met: {context_key}.{field} {op} {expected}, actual={actual_value}"
        return should_run, reason

    def _update_pipeline_meta(self, output_key: str, step_data: Any, context: Dict) -> None:
        """
        步骤完成后，自动更新 __pipeline_meta__ 中的关键字段

        当 output_key 为特定值时，将数据提取到 __pipeline_meta__ 中：
        - test_script → script_content
        - execution_result → execution_id（如有）
        """
        if not isinstance(step_data, dict):
            return

        meta = context.setdefault("__pipeline_meta__", {})
        if not isinstance(meta, dict):
            return

        if output_key == "test_script":
            script_content = step_data.get("script_content", "")
            if not script_content and "script" in step_data:
                script_content = step_data["script"]
            if script_content:
                meta["script_content"] = script_content
                logger.debug(f"[Pipeline] __pipeline_meta__.script_content updated ({len(script_content)} chars)")

        if output_key == "execution_result":
            exec_id = step_data.get("execution_id", 0)
            if exec_id:
                meta["execution_id"] = exec_id
                logger.debug(f"[Pipeline] __pipeline_meta__.execution_id updated ({exec_id})")

    async def _get_progress(self, task_id: str, session_key: str) -> Optional[Dict[str, Any]]:
        """获取任务进度（从 CollectorAgent）。"""
        collector = await self._manager.get_core_runtime().get_collector(session_key)
        if collector is None:
            return None

        result = collector.get_result(task_id)
        if result is None:
            return None

        # 获取最后一个进度
        if result.results:
            last = result.results[-1]
            return {
                "task_id": task_id,
                "agent_type": last.get("agent_type"),
                "status": last.get("status"),
                "progress": 1.0 if last.get("is_final") else 0.5,
                "step": last.get("agent_type"),
                "data": last.get("data"),
            }
        return None

    # ------------------------------------------------------------------ #
    #  状态查询                                                           #
    # ------------------------------------------------------------------ #

    async def list_agents(self) -> List[Dict[str, Any]]:
        """列出所有已注册的 Agent。"""
        await self._manager.ensure_started()
        registry = self._manager.get_registry()
        return registry.get_info()

    async def list_sessions(self, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """列出活跃会话。"""
        sessions = await self._manager.list_sessions(user_id)
        return [s.to_dict() for s in sessions]

    def get_stats(self) -> Dict[str, Any]:
        """获取系统状态。"""
        return self._manager.get_stats()

    async def ensure_started(self) -> None:
        """确保 Runtime 已启动。"""
        await self._manager.ensure_started()


# ------------------------------------------------------------------ #
#  单例                                                                #
# ------------------------------------------------------------------ #

_task_runtime: Optional[TaskRuntime] = None


def get_task_runtime() -> TaskRuntime:
    """获取 TaskRuntime 单例。"""
    global _task_runtime
    if _task_runtime is None:
        _task_runtime = TaskRuntime()
    return _task_runtime
