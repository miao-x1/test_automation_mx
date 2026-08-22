"""
AutoGen Core Runtime - 统一 Agent 基类

BaseRoutedAgent 继承自 autogen_core.RoutedAgent，
通过 @message_handler 装饰器接收消息，
通过 runtime.send_message() 调用其它 Agent。

核心能力：
1. 接收 TaskMessage / AgentRequest，自动路由到 execute() 或指定 action 方法
2. 通过 send_request() 调用其它 Agent（禁止直接 new）
3. 通过 publish_progress() 推送进度
4. 通过 publish_result() 投递最终结果给 CollectorAgent
5. 统一 call_llm() 集成（dashscope/deepseek/ollama/mock）
6. 会话级上下文管理
7. 异常处理与错误通知
"""
import asyncio
import json
import os
import time
import traceback
import logging
from typing import Any, Dict, Optional, Callable, Set

from autogen_core import (
    RoutedAgent,
    message_handler,
    MessageContext,
    AgentId,
    AgentRuntime,
    CancellationToken,
)

from app.runtime.messages import (
    TaskMessage,
    AgentRequest,
    AgentResponse,
    ProgressMessage,
    ResultMessage,
    ErrorMessage,
    AgentEventMessage,
)

logger = logging.getLogger(__name__)


class BaseRoutedAgent(RoutedAgent):
    """
    企业级 AutoGen Core Agent 基类

    所有业务 Agent 继承此类，实现 execute() 或注册自定义 action 方法。

    使用方式：
        class RequirementAgent(BaseRoutedAgent):
            def __init__(self):
                super().__init__("requirement_agent", "需求解析Agent")

            async def execute(self, payload: Dict, ctx: MessageContext) -> Dict:
                # 业务逻辑
                return {"status": "success", "data": {...}}

            @action_handler("custom_action")
            async def handle_custom(self, payload: Dict, ctx: MessageContext) -> Dict:
                return {"data": "custom result"}

    通信方式：
        # 调用其它 Agent（禁止直接 new）
        response = await self.send_request("rag_agent", "retrieve", {"query": "..."})

        # 推送进度
        self.publish_progress(task_id, step="解析需求", progress=0.5)

        # 投递最终结果
        self.publish_result(task_id, {"result": "..."})
    """

    def __init__(
        self,
        description: str = "",
        display_name: str = "",
        capabilities: Optional[list] = None,
    ) -> None:
        super().__init__(description)
        self._display_name = display_name or self.__class__.__name__
        self._capabilities = capabilities or []
        self._action_handlers: Dict[str, Callable] = {}
        self._context: Dict[str, Any] = {}
        self._start_time: Optional[float] = None
        self._fallback_agent_type: str = self.__class__.__name__
        self._fallback_agent_key: str = "default"
        # 跟踪 fire-and-forget task 引用，防止被 GC 回收
        self._pending_tasks: Set[asyncio.Task] = set()
        # 注册默认 action handlers
        self._register_default_actions()

    @property
    def _agent_type(self) -> str:
        """安全获取 agent type（兼容 GraphFlow 容器）"""
        try:
            return self.id.type
        except (AttributeError, RuntimeError):
            return self._fallback_agent_type

    @property
    def _agent_key(self) -> str:
        """安全获取 agent key（兼容 GraphFlow 容器）"""
        try:
            return self.id.key
        except (AttributeError, RuntimeError):
            return self._fallback_agent_key

    # ------------------------------------------------------------------ #
    #  默认 action 注册                                                   #
    # ------------------------------------------------------------------ #

    def _register_default_actions(self) -> None:
        """注册默认的 action handlers。子类可通过 @action_handler 覆盖。"""
        self._action_handlers["execute"] = self.execute
        self._action_handlers["default"] = self.execute

    def register_action(self, action: str, handler: Callable) -> None:
        """注册自定义 action handler。"""
        self._action_handlers[action] = handler

    # ------------------------------------------------------------------ #
    #  消息处理（AutoGen Core @message_handler）                         #
    # ------------------------------------------------------------------ #

    @message_handler
    async def handle_task_message(self, message: TaskMessage, ctx: MessageContext) -> None:
        """
        处理 TaskMessage（来自 FastAPI / TaskRuntime）

        根据 message.action 路由到对应方法，执行后将结果投递给 CollectorAgent。
        """
        self._start_time = time.time()
        task_id = message.task_id
        action = message.action or "execute"
        logger.info(f"[{self._agent_type}] TaskMessage received: task={task_id}, action={action}")

        try:
            # 推送进度：开始
            await self._publish_progress(
                task_id=task_id,
                step=f"{self._agent_type} 启动",
                status="running",
                progress=0.0,
                message=f"{self._display_name} 开始处理任务",
            )

            # 路由到 action handler
            handler = self._action_handlers.get(action)
            if handler is None:
                raise ValueError(f"Unknown action: {action}. Available: {list(self._action_handlers.keys())}")

            result = await self._invoke_handler(handler, message.payload, ctx)

            duration = time.time() - self._start_time

            # 推送进度：完成
            await self._publish_progress(
                task_id=task_id,
                step=f"{self._agent_type} 完成",
                status="completed",
                progress=1.0,
                message=f"{self._display_name} 任务完成",
                data={"duration": duration},
            )

            # 投递最终结果
            await self._publish_result(
                task_id=task_id,
                data=result if isinstance(result, dict) else {"result": result},
                duration=duration,
            )

        except Exception as e:
            duration = time.time() - (self._start_time or time.time())
            error_tb = traceback.format_exc()
            logger.error(f"[{self._agent_type}] Task failed: {e}\n{error_tb}")

            # 推送错误进度
            await self._publish_progress(
                task_id=task_id,
                step=f"{self._agent_type} 错误",
                status="failed",
                progress=1.0,
                message=str(e),
            )

            # 投递错误结果
            await self._publish_result(
                task_id=task_id,
                status="error",
                error=str(e),
                data={"traceback": error_tb},
                duration=duration,
            )

    @message_handler
    async def handle_agent_request(self, message: AgentRequest, ctx: MessageContext) -> AgentResponse:
        """
        处理 AgentRequest（来自其它 Agent 的调用）

        根据 target_action 路由到对应方法，返回 AgentResponse。
        """
        self._start_time = time.time()
        action = message.target_action or "execute"
        sender_info = f"{message.sender_type}:{message.sender_key}"
        logger.info(f"[{self._agent_type}] AgentRequest from {sender_info}: action={action}")

        try:
            handler = self._action_handlers.get(action)
            if handler is None:
                raise ValueError(f"Unknown action: {action}. Available: {list(self._action_handlers.keys())}")

            result = await self._invoke_handler(handler, message.payload, ctx)
            duration = time.time() - self._start_time

            return AgentResponse(
                request_id=message.request_id,
                sender_type=self._agent_type,
                status="success",
                data=result if isinstance(result, dict) else {"result": result},
                duration=duration,
            )

        except Exception as e:
            duration = time.time() - (self._start_time or time.time())
            logger.error(f"[{self._agent_type}] AgentRequest failed: {e}")
            return AgentResponse(
                request_id=message.request_id,
                sender_type=self._agent_type,
                status="error",
                error=str(e),
                duration=duration,
            )

    # ------------------------------------------------------------------ #
    #  核心：子类需实现的方法                                              #
    # ------------------------------------------------------------------ #

    async def execute(self, payload: Dict[str, Any], ctx: MessageContext) -> Any:
        """
        默认 action handler。子类必须实现此方法。

        Args:
            payload: 任务参数
            ctx: 消息上下文（含 cancellation_token）

        Returns:
            任意可序列化的结果
        """
        raise NotImplementedError(f"{self.__class__.__name__} must implement execute()")

    # ------------------------------------------------------------------ #
    #  Agent 间通信（禁止直接 new 其它 Agent）                            #
    # ------------------------------------------------------------------ #

    async def send_request(
        self,
        target_agent_type: str,
        action: str = "execute",
        payload: Optional[Dict] = None,
        target_key: Optional[str] = None,
    ) -> AgentResponse:
        """
        调用另一个 Agent（通过消息机制，禁止直接实例化）

        Args:
            target_agent_type: 目标 Agent 类型名（注册名）
            action: 要调用的方法名
            payload: 方法参数
            target_key: 目标 Agent 实例 key（默认使用自己的 key，即同会话）

        Returns:
            AgentResponse: 目标 Agent 的响应
        """
        key = target_key or self._agent_key
        request = AgentRequest(
            sender_type=self._agent_type,
            sender_key=self._agent_key,
            target_action=action,
            payload=payload or {},
        )
        target_id = AgentId(target_agent_type, key)
        logger.info(f"[{self._agent_type}] → send_request to {target_agent_type}:{key}, action={action}")
        response = await self.send_message(request, target_id)
        return response

    # ------------------------------------------------------------------ #
    #  进度推送 & 结果投递                                                 #
    # ------------------------------------------------------------------ #

    async def _publish_progress(
        self,
        task_id: str,
        step: str = "",
        status: str = "running",
        progress: float = 0.0,
        message: str = "",
        data: Optional[Dict] = None,
    ) -> None:
        """推送进度消息（通过 topic 发布，TaskRuntime 订阅后转发 SSE）。"""
        msg = ProgressMessage(
            task_id=task_id,
            agent_type=self._agent_type,
            step=step,
            status=status,
            progress=progress,
            message=message,
            data=data or {},
        )
        try:
            from autogen_core import DefaultTopicId
            await self.publish_message(msg, DefaultTopicId())
        except Exception as e:
            logger.warning(f"[{self._agent_type}] publish_progress failed: {e}")

    async def _publish_result(
        self,
        task_id: str,
        data: Optional[Dict] = None,
        status: str = "success",
        error: Optional[str] = None,
        duration: float = 0.0,
        is_final: bool = True,
    ) -> None:
        """投递最终结果给 CollectorAgent。"""
        msg = ResultMessage(
            task_id=task_id,
            agent_type=self._agent_type,
            agent_key=self._agent_key,
            status=status,
            data=data or {},
            error=error or "",
            duration=duration,
            is_final=is_final,
        )
        try:
            collector_id = AgentId("collector", self._agent_key)
            await self.send_message(msg, collector_id)
        except Exception as e:
            logger.warning(f"[{self._agent_type}] send to collector failed: {e}")

    # 同步兼容方法（供非异步上下文使用）
    def publish_progress(self, **kwargs) -> None:
        """同步兼容：推送进度（非阻塞，可能丢失）。建议使用 await _publish_progress()。"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                task = asyncio.create_task(self._publish_progress(**kwargs))
                self._pending_tasks.add(task)
                task.add_done_callback(self._pending_tasks.discard)
            else:
                logger.warning(f"[{self._agent_type}] No running event loop for publish_progress")
        except RuntimeError:
            logger.warning(f"[{self._agent_type}] publish_progress: no event loop")

    def publish_result(self, **kwargs) -> None:
        """同步兼容：投递结果（非阻塞，可能丢失）。建议使用 await _publish_result()。"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                task = asyncio.create_task(self._publish_result(**kwargs))
                self._pending_tasks.add(task)
                task.add_done_callback(self._pending_tasks.discard)
            else:
                logger.warning(f"[{self._agent_type}] No running event loop for publish_result")
        except RuntimeError:
            logger.warning(f"[{self._agent_type}] publish_result: no event loop")

    # ------------------------------------------------------------------ #
    #  事件投递（AgentEventMessage → CollectorAgent）                     #
    # ------------------------------------------------------------------ #

    async def emit_event(
        self,
        task_id: str,
        event_type: str,
        step: str = "",
        status: str = "info",
        message: str = "",
        data: Optional[Dict] = None,
        model_name: str = "",
        prompt: str = "",
        user_prompt: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        duration: float = 0.0,
        error_message: str = "",
        error_traceback: str = "",
        is_retry: bool = False,
        retry_count: int = 0,
        message_type: str = "",
        is_final: bool = False,
        session_key: str = "",
    ) -> None:
        """
        发送 AgentEventMessage 给 CollectorAgent

        记录所有关键节点：开始/结束/Prompt/模型/Token/耗时/错误/重试/最终结果
        CollectorAgent 收到后：保存DB + 记录日志 + 推送SSE + 推送WebSocket
        """
        msg = AgentEventMessage(
            task_id=task_id,
            session_key=session_key or self._agent_key,
            agent_type=self._agent_type,
            agent_name=self._display_name,
            event_type=event_type,
            step=step,
            status=status,
            message=message,
            data=data or {},
            model_name=model_name,
            prompt=prompt,
            user_prompt=user_prompt,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            duration=duration,
            error_message=error_message,
            error_traceback=error_traceback,
            is_retry=is_retry,
            retry_count=retry_count,
            message_type=message_type,
            is_final=is_final,
        )
        try:
            collector_id = AgentId("collector", self._agent_key)
            await self.send_message(msg, collector_id)
        except Exception as e:
            # GraphFlow 环境中 send_message 可能失败，降级为直接处理
            logger.debug(f"[{self._agent_type}] send_message failed, fallback: {e}")
            try:
                from app.runtime.collector import CollectorAgent
                from app.db.database import SessionLocal
                from app.models.agent_event import AgentEvent as AgentEventModel
                import json as _json
                db = SessionLocal()
                try:
                    event = AgentEventModel(
                        task_id=task_id,
                        session_key=session_key or self._agent_key,
                        agent_type=self._agent_type,
                        agent_name=self._display_name,
                        event_type=event_type,
                        step=step,
                        status=status,
                        model_name=model_name or None,
                        prompt=prompt[:2000] if prompt else None,
                        user_prompt=user_prompt[:2000] if user_prompt else None,
                        prompt_tokens=prompt_tokens or None,
                        completion_tokens=completion_tokens or None,
                        total_tokens=total_tokens or None,
                        duration=duration or None,
                        input_json=_json.dumps(data, ensure_ascii=False, default=str) if data else None,
                        message=message or None,
                        error_message=error_message or None,
                        error_traceback=error_traceback or None,
                        retry_count=retry_count,
                        is_retry=is_retry,
                        message_type=message_type or "AgentEventMessage",
                        is_final=is_final,
                    )
                    db.add(event)
                    db.commit()
                finally:
                    db.close()
            except Exception as db_err:
                logger.warning(f"[{self._agent_type}] emit_event fallback failed: {db_err}")

    async def emit_start(
        self, task_id: str, step: str = "", message: str = "",
        session_key: str = "",
    ) -> None:
        """发送开始事件"""
        await self.emit_event(
            task_id=task_id,
            event_type="start",
            step=step,
            status="info",
            message=message or f"{self._display_name} 开始处理",
            session_key=session_key,
        )

    async def emit_end(
        self, task_id: str, step: str = "", duration: float = 0.0,
        output: Optional[Dict] = None, session_key: str = "",
    ) -> None:
        """发送结束事件"""
        await self.emit_event(
            task_id=task_id,
            event_type="end",
            step=step,
            status="success",
            message=f"{self._display_name} 处理完成",
            duration=duration,
            data=output or {},
            session_key=session_key,
        )

    async def emit_error(
        self, task_id: str, step: str = "", error: str = "",
        traceback_str: str = "", session_key: str = "",
    ) -> None:
        """发送错误事件"""
        await self.emit_event(
            task_id=task_id,
            event_type="error",
            step=step,
            status="error",
            message=error,
            error_message=error,
            error_traceback=traceback_str,
            session_key=session_key,
        )

    async def emit_retry(
        self, task_id: str, step: str = "", retry_count: int = 0,
        reason: str = "", session_key: str = "",
    ) -> None:
        """发送重试事件"""
        await self.emit_event(
            task_id=task_id,
            event_type="retry",
            step=step,
            status="warning",
            message=f"第 {retry_count} 次重试: {reason}",
            is_retry=True,
            retry_count=retry_count,
            session_key=session_key,
        )

    # ------------------------------------------------------------------ #
    #  LLM 调用（增强版 - 自动追踪 Prompt/Model/Token/Duration）         #
    # ------------------------------------------------------------------ #

    async def call_llm(
        self,
        system_prompt: str = "",
        user_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        task_id: str = "",
        step: str = "",
        session_key: str = "",
    ) -> str:
        """
        统一 LLM 调用(通过 LLMGateway,禁止直连模型 API)

        自动通过 emit_event 将以下信息发送给 CollectorAgent:
        - System Prompt 内容
        - User Prompt 内容
        - 模型名称
        - Token 消耗(prompt_tokens / completion_tokens / total_tokens)
        - 耗时
        - 错误信息

        调用链:
            Agent → LLMGateway → ModelRouter → Provider → 模型供应商
            失败时按 fallback chain 自动切换:qwen → deepseek → ollama → mock

        Prompt 来源优先级:
        1. 调用方显式传入的 system_prompt(最高优先级)
        2. PromptManager 管理的活跃版本(支持版本管理/AB测试/回滚)
        3. Factory 注入的 _system_prompt / get_context("system_prompt")
        """
        start_time = time.time()

        # Prompt 多源回退:显式传入 > PromptManager > Factory 注入
        if not system_prompt:
            # 尝试从 PromptManager 获取(Agent 内部 Prompt 版本管理)
            try:
                from app.services.prompt_manager import PromptManager
                agent_name = getattr(self, "_display_name", "") or self.__class__.__name__
                # 使用 spec.name 作为 agent_name(如果可用)
                spec = getattr(self, "_spec", None)
                if spec and hasattr(spec, "name"):
                    agent_name = spec.name
                managed_prompt = PromptManager.get_prompt(agent_name, "system_prompt")
                if managed_prompt:
                    system_prompt = managed_prompt
            except Exception:
                pass  # PromptManager 不可用时静默回退

            # 仍为空,回退到 Factory 注入的值
            if not system_prompt:
                system_prompt = (
                    self.get_context("system_prompt")
                    if hasattr(self, "get_context")
                    else ""
                ) or getattr(self, "_system_prompt", "")

        # 获取 Agent 标识(用于路由与统计)
        agent_name = getattr(self, "_display_name", "") or self.__class__.__name__
        spec = getattr(self, "_spec", None)
        if spec and hasattr(spec, "name"):
            agent_name = spec.name

        # 通过 LLMGateway 调用(统一入口)
        try:
            from app.llm import get_gateway
            gateway = get_gateway()

            # 从 AgentSpec 提取优先模型/供应商(覆盖路由)
            preferred_model = ""
            preferred_provider = ""
            if spec and spec.model:
                preferred_model = spec.model.model_name or ""
                preferred_provider = spec.model.provider or ""

            resp = await gateway.chat_with_response(
                agent_name=agent_name,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                task_id=task_id,
                step=step,
                session_key=session_key,
                preferred_model=preferred_model,
                preferred_provider=preferred_provider,
            )

            duration = time.time() - start_time

            if resp.success:
                # 发送成功事件给 CollectorAgent(SSE/WebSocket 推送)
                if task_id:
                    await self.emit_event(
                        task_id=task_id,
                        event_type="prompt",
                        step=step or "llm_call",
                        status="success",
                        message=f"LLM 调用完成: {resp.model}" + (
                            f"(切换自 {resp.requested_model})" if resp.fallback_used else ""
                        ),
                        model_name=resp.model,
                        prompt=system_prompt[:500],
                        user_prompt=user_prompt[:500],
                        prompt_tokens=resp.prompt_tokens,
                        completion_tokens=resp.completion_tokens,
                        total_tokens=resp.total_tokens,
                        duration=resp.duration,
                        message_type="LLMCall",
                        session_key=session_key,
                    )
                return resp.content

            # 失败(所有供应商都失败)
            duration = time.time() - start_time
            error_tb = traceback.format_exc()
            if task_id:
                await self.emit_event(
                    task_id=task_id,
                    event_type="error",
                    step=step or "llm_call",
                    status="error",
                    message=f"LLM 调用失败(所有供应商): {resp.error}",
                    model_name=resp.model or "unknown",
                    prompt=system_prompt[:500],
                    user_prompt=user_prompt[:500],
                    duration=duration,
                    error_message=str(resp.error),
                    error_traceback=error_tb,
                    message_type="LLMCall",
                    session_key=session_key,
                )
            raise RuntimeError(f"LLM 调用失败: {resp.error}")

        except RuntimeError:
            raise
        except Exception as e:
            # Gateway 不可用时降级(不应发生,但保持健壮)
            duration = time.time() - start_time
            error_tb = traceback.format_exc()
            if task_id:
                await self.emit_event(
                    task_id=task_id,
                    event_type="error",
                    step=step or "llm_call",
                    status="error",
                    message=f"LLM Gateway 异常: {e}",
                    prompt=system_prompt[:500],
                    user_prompt=user_prompt[:500],
                    duration=duration,
                    error_message=str(e),
                    error_traceback=error_tb,
                    message_type="LLMCall",
                    session_key=session_key,
                )
            raise

    async def call_llm_json(
        self,
        system_prompt: str = "",
        user_prompt: str = "",
        temperature: float = 0.3,
        task_id: str = "",
        step: str = "",
        session_key: str = "",
    ) -> Dict[str, Any]:
        """调用 LLM 并解析 JSON 结果（自动追踪）。"""
        raw = await self.call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            task_id=task_id,
            step=step,
            session_key=session_key,
        )
        # 尝试提取 JSON
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # 尝试从 markdown 代码块中提取
            import re
            match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw)
            if match:
                return json.loads(match.group(1))
            # 尝试找到第一个 { 和最后一个 }
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1 and end > start:
                return json.loads(raw[start:end + 1])
            return {"error": "Failed to parse JSON", "raw": raw[:500]}

    # ------------------------------------------------------------------ #
    #  辅助方法                                                           #
    # ------------------------------------------------------------------ #

    async def _invoke_handler(self, handler: Callable, payload: Dict, ctx: MessageContext) -> Any:
        """调用 handler，支持同步和异步方法。"""
        if asyncio.iscoroutinefunction(handler):
            return await handler(payload, ctx)
        else:
            # 同步方法在线程池中运行
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, handler, payload, ctx)

    def set_context(self, key: str, value: Any) -> None:
        """设置上下文。"""
        self._context[key] = value

    def get_context(self, key: str, default: Any = None) -> Any:
        """获取上下文。"""
        return self._context.get(key, default)

    def to_dict(self) -> Dict[str, Any]:
        """Agent 元信息。"""
        return {
            "agent_type": self._agent_type if self.id else self.__class__.__name__,
            "agent_key": self._agent_key if self.id else "",
            "display_name": self._display_name,
            "capabilities": self._capabilities,
            "actions": list(self._action_handlers.keys()),
        }


# ------------------------------------------------------------------ #
#  装饰器：注册自定义 action handler                                    #
# ------------------------------------------------------------------ #

def action_handler(action_name: str):
    """
    装饰器：为 BaseRoutedAgent 子类注册自定义 action handler

    用法：
        class MyAgent(BaseRoutedAgent):
            @action_handler("analyze")
            async def handle_analyze(self, payload: Dict, ctx: MessageContext) -> Dict:
                return {"result": "..."}

    这样外部可以通过 send_request("my_agent", "analyze", {...}) 调用。
    """
    def decorator(func: Callable):
        # 标记方法为 action handler，在 __init__ 中注册
        func._action_handler_name = action_name
        return func
    return decorator
