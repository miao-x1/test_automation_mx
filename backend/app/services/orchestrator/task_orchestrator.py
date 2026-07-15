"""
TaskOrchestrator - 统一任务编排器

所有业务流程必须经过 TaskOrchestrator。
禁止 API 层直接调用 Agent。

架构：
  FastAPI
    ↓
  TaskOrchestrator.execute(flow_name, payload)
    ↓
  TaskFlow（从 YAML 加载步骤定义）
    ↓
  逐步执行 Agent（通过 AgentRegistry 创建）
    ↓
  状态保存到 TaskState（DB）
    ↓
  SSE 事件推送给前端

支持：
  - 顺序执行
  - 异常处理（abort / continue）
  - 状态保存（task_id / session_id / current_agent / status / result）
  - 步骤间数据传递（input_from）
  - SSE 流式进度
  - 日志记录
"""
import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional

from app.core.logger import log


# ------------------------------------------------------------------
# 数据结构
# ------------------------------------------------------------------

@dataclass
class FlowStep:
    """单个流程步骤"""
    step_name: str
    agent_name: str
    action: str
    description: str = ""
    required: bool = True
    on_failure: str = "abort"        # abort | continue
    input_from: Optional[str] = None  # 从哪个步骤的输出获取输入
    condition: Optional[str] = None   # 条件表达式（None=始终执行）


@dataclass
class TaskFlow:
    """任务流程定义"""
    flow_name: str
    description: str = ""
    steps: List[FlowStep] = field(default_factory=list)


@dataclass
class StepResult:
    """单步执行结果"""
    step_name: str
    agent_name: str
    action: str
    status: str = "pending"         # pending / running / success / failed / skipped
    output: Any = None
    error: Optional[str] = None
    duration_ms: int = 0


# ------------------------------------------------------------------
# TaskOrchestrator
# ------------------------------------------------------------------

class TaskOrchestrator:
    """
    统一任务编排器

    从 task_flows.yaml 加载流程定义，
    逐步执行 Agent，保存状态到 DB，
    通过 SSE 推送进度。

    使用方式：
      orchestrator = TaskOrchestrator()
      async for event in orchestrator.execute("image_test_flow", payload={"image_path": "..."}):
          print(event)
    """

    _flows: Dict[str, TaskFlow] = {}
    _loaded: bool = False

    # ------------------------------------------------------------------
    # YAML 加载
    # ------------------------------------------------------------------

    @classmethod
    def _ensure_loaded(cls) -> None:
        """确保 YAML 已加载"""
        if cls._loaded:
            return

        yaml_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "task_flows.yaml"
        )
        if not os.path.isfile(yaml_path):
            log.warning(f"TaskOrchestrator | YAML 不存在: {yaml_path}")
            cls._loaded = True
            return

        try:
            import yaml
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            for flow_data in data.get("flows", []):
                flow_name = flow_data.get("flow_name", "")
                if not flow_name:
                    continue

                steps = []
                for step_data in flow_data.get("steps", []):
                    steps.append(FlowStep(
                        step_name=step_data.get("step_name", ""),
                        agent_name=step_data.get("agent_name", ""),
                        action=step_data.get("action", ""),
                        description=step_data.get("description", ""),
                        required=step_data.get("required", True),
                        on_failure=step_data.get("on_failure", "abort"),
                        input_from=step_data.get("input_from"),
                        condition=step_data.get("condition"),
                    ))

                flow = TaskFlow(
                    flow_name=flow_name,
                    description=flow_data.get("description", ""),
                    steps=steps,
                )
                cls._flows[flow_name] = flow
                log.info(
                    f"TaskOrchestrator | 加载流程 | "
                    f"name={flow_name} | steps={len(steps)}"
                )

            cls._loaded = True
            log.info(
                f"TaskOrchestrator | YAML 加载完成 | "
                f"共 {len(cls._flows)} 个流程"
            )

        except Exception as e:
            log.error(f"TaskOrchestrator | 加载 YAML 失败: {e}")
            cls._loaded = True

    @classmethod
    def reload(cls) -> None:
        """重新加载 YAML（运行时刷新）"""
        cls._flows = {}
        cls._loaded = False
        cls._ensure_loaded()

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    @classmethod
    def list_flows(cls) -> List[Dict[str, Any]]:
        """列出所有可用流程"""
        cls._ensure_loaded()
        results = []
        for name, flow in cls._flows.items():
            results.append({
                "flow_name": name,
                "description": flow.description,
                "step_count": len(flow.steps),
                "steps": [
                    {
                        "step_name": s.step_name,
                        "agent_name": s.agent_name,
                        "action": s.action,
                        "description": s.description,
                        "required": s.required,
                    }
                    for s in flow.steps
                ],
            })
        return results

    @classmethod
    def get_flow(cls, flow_name: str) -> Optional[TaskFlow]:
        """获取流程定义"""
        cls._ensure_loaded()
        return cls._flows.get(flow_name)

    @classmethod
    def is_flow_exists(cls, flow_name: str) -> bool:
        """检查流程是否存在"""
        cls._ensure_loaded()
        return flow_name in cls._flows

    # ------------------------------------------------------------------
    # 状态管理
    # ------------------------------------------------------------------

    def _create_task_state(
        self,
        task_id: int,
        session_id: Optional[int],
        flow_name: str,
        total_steps: int,
    ) -> Any:
        """创建 TaskState 记录"""
        try:
            from app.db.database import SessionLocal
            from app.models.task_state import TaskState

            db = SessionLocal()
            try:
                state = TaskState(
                    task_id=task_id,
                    session_id=session_id,
                    flow_name=flow_name,
                    status="pending",
                    step_index=0,
                    total_steps=total_steps,
                )
                db.add(state)
                db.commit()
                db.refresh(state)
                return state
            finally:
                db.close()
        except Exception as e:
            log.warning(f"TaskOrchestrator | 创建 TaskState 失败: {e}")
            return None

    def _update_task_state(
        self,
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
            log.warning(f"TaskOrchestrator | 更新 TaskState 失败: {e}")

    # ------------------------------------------------------------------
    # 执行入口（SSE 流式）
    # ------------------------------------------------------------------

    async def execute(
        self,
        flow_name: str,
        payload: Dict[str, Any],
        task_id: Optional[int] = None,
        session_id: Optional[int] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """执行任务流程（SSE 流式）

        Args:
            flow_name: 流程名称
            payload: 输入参数
            task_id: 任务ID（关联 Task 表）
            session_id: 会话ID

        Yields:
            SSE 事件字典：
              {"event": "flow_start", "flow_name": ..., "total_steps": ...}
              {"event": "step_start", "step_name": ..., "agent_name": ..., "step_index": ...}
              {"event": "step_success", "step_name": ..., "duration_ms": ..., "output": ...}
              {"event": "step_failed", "step_name": ..., "error": ...}
              {"event": "step_skipped", "step_name": ..., "reason": ...}
              {"event": "flow_success", "result": ...}
              {"event": "flow_failed", "error": ...}
              {"event": "done"}
        """
        TaskOrchestrator._ensure_loaded()

        # 验证流程存在
        flow = TaskOrchestrator._flows.get(flow_name)
        if flow is None:
            yield {
                "event": "flow_failed",
                "flow_name": flow_name,
                "error": f"流程 '{flow_name}' 不存在。可用: {list(TaskOrchestrator._flows.keys())}",
            }
            yield {"event": "done"}
            return

        # 生成 task_id（如果未提供）
        if task_id is None:
            task_id = abs(hash(f"{flow_name}:{uuid.uuid4().hex}")) % (2**31)

        request_id = f"flow_{uuid.uuid4().hex[:12]}"
        log.info(
            f"TaskOrchestrator | 开始执行 | "
            f"request_id={request_id} | flow={flow_name} | "
            f"task_id={task_id} | steps={len(flow.steps)}"
        )

        # 创建 TaskState
        state = self._create_task_state(
            task_id=task_id,
            session_id=session_id,
            flow_name=flow_name,
            total_steps=len(flow.steps),
        )
        state_id = state.id if state else None

        # 更新状态为 running
        if state_id:
            self._update_task_state(state_id, status="running")

        # 发送 flow_start 事件
        yield {
            "event": "flow_start",
            "request_id": request_id,
            "flow_name": flow_name,
            "description": flow.description,
            "total_steps": len(flow.steps),
            "task_id": task_id,
        }

        # 逐步执行
        step_outputs: Dict[str, Any] = {}
        final_result: Dict[str, Any] = {}
        failed = False
        error_message = ""

        for i, step in enumerate(flow.steps):
            step_result = StepResult(
                step_name=step.step_name,
                agent_name=step.agent_name,
                action=step.action,
            )

            # 条件检查：如果 condition 不满足，跳过此步骤
            if step.condition is not None:
                # 构建条件上下文：payload + 已有步骤输出
                ctx = dict(payload)
                ctx.update(step_outputs)
                if not self._eval_condition(step.condition, ctx):
                    step_result.status = "skipped"
                    log.info(
                        f"TaskOrchestrator | 步骤跳过（条件不满足）| "
                        f"step={step.step_name} | condition={step.condition}"
                    )
                    yield {
                        "event": "step_skipped",
                        "step_name": step.step_name,
                        "agent_name": step.agent_name,
                        "step_index": i,
                        "reason": f"条件不满足: {step.condition}",
                        "progress": int((i + 1) / len(flow.steps) * 100),
                    }
                    continue

            # 更新 TaskState
            if state_id:
                self._update_task_state(
                    state_id,
                    current_agent=step.agent_name,
                    step_index=i,
                )

            # 发送 step_start 事件
            yield {
                "event": "step_start",
                "step_name": step.step_name,
                "agent_name": step.agent_name,
                "action": step.action,
                "description": step.description,
                "step_index": i,
                "total_steps": len(flow.steps),
                "progress": int(i / len(flow.steps) * 100),
            }

            log.info(
                f"TaskOrchestrator | 步骤 {i+1}/{len(flow.steps)} | "
                f"step={step.step_name} | agent={step.agent_name}"
            )

            try:
                # 构建步骤输入：合并 payload + 所有已完成步骤的输出
                step_input = dict(payload)
                for prev_output in step_outputs.values():
                    if isinstance(prev_output, dict):
                        step_input.update(prev_output)

                # 通过 AgentRegistry 创建 Agent 并执行
                output = await self._execute_agent(
                    step.agent_name,
                    step.action,
                    step_input,
                    task_id=str(task_id) if task_id else "",
                    session_id=str(session_id) if session_id else "",
                    flow_name=flow_name,
                    step_name=step.step_name,
                )

                step_result.status = "success"
                step_result.output = output
                step_outputs[step.step_name] = output

                # 更新 final_result
                final_result[step.step_name] = output

                # 更新 TaskState
                if state_id:
                    self._update_task_state(
                        state_id,
                        step_record={
                            "step_name": step.step_name,
                            "agent_name": step.agent_name,
                            "status": "success",
                            "duration_ms": step_result.duration_ms,
                        },
                    )

                # 发送 step_success 事件
                yield {
                    "event": "step_success",
                    "step_name": step.step_name,
                    "agent_name": step.agent_name,
                    "step_index": i,
                    "progress": int((i + 1) / len(flow.steps) * 100),
                    "output": self._safe_serialize(output),
                }

                log.info(
                    f"TaskOrchestrator | 步骤成功 | "
                    f"step={step.step_name} | duration={step_result.duration_ms}ms"
                )

            except Exception as e:
                step_result.status = "failed"
                step_result.error = str(e)
                error_message = f"步骤 '{step.step_name}' 失败: {e}"

                log.error(
                    f"TaskOrchestrator | 步骤失败 | "
                    f"step={step.step_name} | error={e}",
                    exc_info=True,
                )

                # 更新 TaskState
                if state_id:
                    self._update_task_state(
                        state_id,
                        step_record={
                            "step_name": step.step_name,
                            "agent_name": step.agent_name,
                            "status": "failed",
                            "error": str(e),
                            "duration_ms": step_result.duration_ms,
                        },
                    )

                # 发送 step_failed 事件
                yield {
                    "event": "step_failed",
                    "step_name": step.step_name,
                    "agent_name": step.agent_name,
                    "step_index": i,
                    "error": str(e),
                    "required": step.required,
                }

                # 判断是否终止
                if step.required and step.on_failure == "abort":
                    failed = True
                    break
                else:
                    # 非必需步骤失败，继续执行
                    log.info(
                        f"TaskOrchestrator | 非必需步骤失败，继续 | "
                        f"step={step.step_name}"
                    )
                    continue

        # 流程结束
        if failed:
            if state_id:
                self._update_task_state(
                    state_id,
                    status="failed",
                    error_message=error_message,
                    result=final_result,
                )

            yield {
                "event": "flow_failed",
                "flow_name": flow_name,
                "error": error_message,
                "completed_steps": len(step_outputs),
                "total_steps": len(flow.steps),
            }
        else:
            if state_id:
                self._update_task_state(
                    state_id,
                    status="success",
                    result=final_result,
                )

            yield {
                "event": "flow_success",
                "flow_name": flow_name,
                "result": self._safe_serialize(final_result),
                "completed_steps": len(step_outputs),
                "total_steps": len(flow.steps),
            }

        log.info(
            f"TaskOrchestrator | 执行完成 | "
            f"flow={flow_name} | status={'failed' if failed else 'success'}"
        )

        yield {"event": "done"}

    # ------------------------------------------------------------------
    # 同步执行（非 SSE）
    # ------------------------------------------------------------------

    @staticmethod
    def _eval_condition(condition: str, ctx: Dict[str, Any]) -> bool:
        """评估条件表达式

        支持的条件语法（简单键值判断，非完整表达式引擎）：
          - "has:image_paths"          → ctx.get("image_paths") 非空
          - "no:image_paths"           → ctx.get("image_paths") 为空
          - "has:target_url"          → ctx 中 target_url 非空
          - "no:target_url"            → ctx 中 target_url 为空
          - "enable_knowledge_graph"   → ctx.get("enable_knowledge_graph") == True
          - "enable_human_review"      → ctx.get("enable_human_review") == True
          - "enable_reuse_check"       → ctx.get("enable_reuse_check") == True
          - "and:has:image_paths,has:target_url" → 多条件 AND
        """
        condition = condition.strip()

        # AND 多条件
        if condition.startswith("and:"):
            parts = condition[4:].split(",")
            return all(TaskOrchestrator._eval_condition(p.strip(), ctx) for p in parts)

        # has: 检查非空
        if condition.startswith("has:"):
            key = condition[4:].strip()
            val = ctx.get(key)
            if val is None:
                return False
            if isinstance(val, (list, str, dict)):
                return len(val) > 0
            return bool(val)

        # no: 检查为空
        if condition.startswith("no:"):
            key = condition[3:].strip()
            val = ctx.get(key)
            if val is None:
                return True
            if isinstance(val, (list, str, dict)):
                return len(val) == 0
            return not bool(val)

        # 布尔标志
        return bool(ctx.get(condition, False))

    def execute_sync(
        self,
        flow_name: str,
        payload: Dict[str, Any],
        task_id: Optional[int] = None,
        session_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """同步执行任务流程（非流式）

        Returns:
            {"status": "success"|"failed", "result": ..., "error": ...}
        """
        async def _run():
            events = []
            async for event in self.execute(flow_name, payload, task_id, session_id):
                events.append(event)
            return events

        events = asyncio.run(_run())

        result = {"status": "unknown", "result": {}, "error": ""}
        for event in events:
            if event.get("event") == "flow_success":
                result["status"] = "success"
                result["result"] = event.get("result", {})
            elif event.get("event") == "flow_failed":
                result["status"] = "failed"
                result["error"] = event.get("error", "")
        return result

    async def _collect_events(
        self,
        flow_name: str,
        payload: Dict[str, Any],
        task_id: Optional[int],
        session_id: Optional[int],
    ) -> AsyncGenerator:
        """收集所有 SSE 事件"""
        async for event in self.execute(flow_name, payload, task_id, session_id):
            yield event

    # ------------------------------------------------------------------
    # Agent 执行
    # ------------------------------------------------------------------

    async def _execute_agent(
        self,
        agent_name: str,
        action: str,
        input_data: Dict[str, Any],
        task_id: str = "",
        session_id: str = "",
        flow_name: str = "",
        step_name: str = "",
    ) -> Any:
        """通过 AgentRegistry 创建 Agent 并执行

        Agent 通过 AgentRegistry.create() 获取，
        禁止直接 new Agent。

        集成 AgentExecutionMonitor 记录执行详情：
          - record_start() 在执行前调用
          - record_success() 在成功后调用
          - record_failure() 在异常时调用
        """
        from app.agents.factory import AgentRegistry
        from app.services.monitor import get_execution_monitor

        # 确保 Agent 已注册
        if not AgentRegistry.is_registered(agent_name):
            # 触发自动注册（如果尚未注册）
            if not AgentRegistry._registered:
                AgentRegistry.auto_register()

        if not AgentRegistry.is_registered(agent_name):
            raise ValueError(f"Agent '{agent_name}' 未注册")

        # 记录执行开始
        monitor = get_execution_monitor()
        monitor_log_id = monitor.record_start(
            agent_name=agent_name,
            step=step_name or action,
            input_data=input_data,
            task_id=str(task_id) if task_id else "",
            session_id=str(session_id) if session_id else "",
            flow_name=flow_name,
        )

        agent = AgentRegistry.create(agent_name)
        start = time.time()

        try:
            # 根据 action 调用对应的 Agent 方法
            output = await self._dispatch_action(agent, agent_name, action, input_data)

            duration_ms = int((time.time() - start) * 1000)

            # 记录执行成功
            monitor.record_success(
                log_id=monitor_log_id,
                output=output,
                duration_ms=duration_ms,
            )

            log.info(
                f"TaskOrchestrator | Agent 执行完成 | "
                f"agent={agent_name} | action={action} | "
                f"duration={duration_ms}ms"
            )

            return output

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)

            # 记录执行失败
            monitor.record_failure(
                log_id=monitor_log_id,
                error=str(e),
                duration_ms=duration_ms,
            )

            log.error(
                f"TaskOrchestrator | Agent 执行失败 | "
                f"agent={agent_name} | action={action} | "
                f"duration={duration_ms}ms | error={e}",
                exc_info=True,
            )
            raise

    async def _dispatch_action(
        self,
        agent: Any,
        agent_name: str,
        action: str,
        input_data: Dict[str, Any],
    ) -> Any:
        """根据 action 分发到 Agent 的对应方法

        支持 action 映射：
          - analyze → agent.analyze(input_data) 或 agent.execute(**input_data)
          - generate → agent.generate(**input_data) 或 agent.execute(**input_data)
          - review → agent.review(input_data)
          - execute → agent.execute(**input_data)
          - retrieve → agent.retrieve(input_data)
          - parse → agent.parse(input_data)
          - embed → agent.embed(input_data)
          - store → agent.store(input_data)
          - classify → agent.classify(input_data)
          - infer → agent.infer(input_data)
          - build → agent.build(input_data)
          - update → agent.update(input_data)
          - sync → agent.sync(input_data)

        参数传递策略：
          - execute 动作：优先 **kwargs 解包（兼容管道 payload 键名）
          - generate 动作：先尝试 **kwargs，TypeError 后降级为 dict 参数
          - 其他动作：传递 dict 参数
        """
        # action -> method 映射
        action_map = {
            "analyze": ["analyze", "execute", "process"],
            "generate": ["generate", "generate_cases", "generate_script", "execute"],
            "review": ["review", "execute"],
            "execute": ["execute", "run", "run_script"],
            "retrieve": ["retrieve", "search", "execute"],
            "parse": ["parse", "execute", "process"],
            "embed": ["embed", "embed_elements", "execute"],
            "store": ["store", "save", "execute"],
            "classify": ["classify", "classify_sync", "execute"],
            "infer": ["infer", "find_related_pages", "execute"],
            "build": ["build", "build_full_graph", "execute"],
            "update": ["update", "execute"],
            "sync": ["sync", "execute"],
        }

        method_names = action_map.get(action, [action, "execute"])

        for method_name in method_names:
            method = getattr(agent, method_name, None)
            if method is None:
                continue

            # 调用方法：先尝试 **kwargs 解包，再尝试 dict 传参，最后无参降级
            try:
                if asyncio.iscoroutinefunction(method):
                    try:
                        return await method(**input_data) if isinstance(input_data, dict) else await method(input_data)
                    except TypeError:
                        return await method(input_data)
                else:
                    try:
                        return await asyncio.to_thread(method, **input_data) if isinstance(input_data, dict) else await asyncio.to_thread(method, input_data)
                    except TypeError:
                        return await asyncio.to_thread(method, input_data)
            except TypeError:
                # 参数不匹配，尝试无参调用
                try:
                    if asyncio.iscoroutinefunction(method):
                        return await method()
                    else:
                        return await asyncio.to_thread(method)
                except Exception:
                    continue
            except Exception:
                continue

        # 所有方法都失败，返回输入数据（降级）
        log.warning(
            f"TaskOrchestrator | Agent '{agent_name}' 无可用方法 | "
            f"action={action} | 降级返回输入数据"
        )
        return input_data

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_serialize(obj: Any) -> Any:
        """安全序列化对象为 JSON 可序列化格式"""
        try:
            json.dumps(obj, ensure_ascii=False, default=str)
            return obj
        except (TypeError, ValueError):
            return str(obj)


# ------------------------------------------------------------------
# 单例
# ------------------------------------------------------------------

_orchestrator: Optional[TaskOrchestrator] = None


def get_task_orchestrator() -> TaskOrchestrator:
    """获取 TaskOrchestrator 单例"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = TaskOrchestrator()
    return _orchestrator
