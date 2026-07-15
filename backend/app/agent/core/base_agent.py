"""
BaseAgent - 企业级 Agent 统一基类

所有 Agent 必须继承此类。BaseAgent 提供：
- 日志（loguru 集成）
- 配置（AgentConfig 统一管理）
- 模型（LLM 调用封装）
- Memory（Session 级独立 Memory）
- Session（会话隔离）
- 工具（Tool 注册与调用）
- Prompt（系统/用户提示词管理）
- 消息发送（AgentMessage 通信）
- 公共异常（统一异常处理）

设计原则：
1. 所有 Agent 间通信通过 AgentMessage，禁止直接函数调用
2. 每个 Session 拥有独立 Memory，通过 MemoryManager 管理
3. 配置统一通过 AgentConfig，不散落在代码中
4. 向后兼容：保留 emit / on_message / execute(**kwargs) 接口
"""
import asyncio
import time
import json
from abc import ABC
from typing import Any, Dict, List, Optional, Callable

from app.agent.core.config import AgentConfig, create_default_config
from app.agent.core.message import AgentMessage
from app.agent.core.exceptions import (
    AgentError,
    AgentExecutionError,
    AgentTimeoutError,
    AgentLLMError,
    AgentValidationError,
)
from app.agent.core.types import (
    AgentStatus,
    AgentCapability,
    MessageType,
    MessageStatus,
    ExecutionResult,
)
from app.agent.memory.base import BaseMemory
from app.agent.memory.manager import get_memory_manager
from app.core.logger import log


class BaseAgent(ABC):
    """
    企业级 Agent 统一基类。

    使用方式：
        class MyAgent(BaseAgent):
            agent_name = "my_agent"
            capabilities = [AgentCapability.CASE_GENERATE]

            def __init__(self, config=None, runtime=None, **kwargs):
                super().__init__(config, runtime, **kwargs)

            async def execute(self, **kwargs) -> Any:
                # 实现业务逻辑
                pass

    通过 Runtime 执行：
        result = await runtime.run_agent("my_agent", message)

    向后兼容旧接口：
        agent = MyAgent()
        result = agent.execute(**kwargs)  # 旧调用方式仍然可用
    """

    # ---- 类级属性（子类覆盖） ----
    agent_name: str = "base_agent"
    display_name: str = "Base Agent"
    description: str = "Base Agent - all agents inherit from this"
    capabilities: List[AgentCapability] = []

    # ---- 初始化 ----
    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        runtime: Optional[Any] = None,
        session_id: Optional[str] = None,
        **kwargs,
    ):
        # 配置
        if config is None:
            config = create_default_config(
                agent_name=self.agent_name,
                description=self.description,
            )
        self.config: AgentConfig = config

        # Runtime 引用（由 Runtime 注入）
        self._runtime = runtime

        # Session
        self.session_id: str = session_id or ""

        # Memory（由 Runtime 创建时注入，或按需获取）
        self._memory: Optional[BaseMemory] = None

        # 状态
        self._status: AgentStatus = AgentStatus.IDLE
        self._status_lock = None  # 延迟初始化，在需要时创建

        # 工具
        self._tools: Dict[str, Callable] = {}

        # 日志
        self._logger = log.bind(agent=self.agent_name)

        # 兼容旧 MessageBus（保持旧 emit/on_message 接口可用）
        self._bus = None
        self._agent_type = kwargs.get("agent_type", self.agent_name)

        # 扩展存储
        self._context: Dict[str, Any] = {}

    # ================================================================
    # 属性
    # ================================================================

    @property
    def logger(self):
        """获取绑定的 logger"""
        return self._logger

    @property
    def status(self) -> AgentStatus:
        return self._status

    @property
    def model(self) -> str:
        return self.config.model_name

    @model.setter
    def model(self, value: str) -> None:
        """允许子类直接设置 model（向后兼容旧 Agent 的 self.model = ... 赋值）"""
        if value:
            self.config.model_name = value

    @property
    def memory(self) -> Optional[BaseMemory]:
        """获取 Memory（优先使用注入的，否则从 MemoryManager 获取）"""
        if self._memory is not None:
            return self._memory
        if self.session_id:
            mgr = get_memory_manager()
            mem = mgr.get_memory(self.session_id)
            if mem is not None:
                self._memory = mem
            return mem
        return None

    @memory.setter
    def memory(self, value: BaseMemory):
        self._memory = value

    @property
    def bus(self):
        """兼容旧 MessageBus"""
        if self._bus is None:
            try:
                from app.agent.core.message_bus import MessageBus
                self._bus = MessageBus()
            except Exception:
                pass
        return self._bus

    @property
    def runtime(self):
        return self._runtime

    @runtime.setter
    def runtime(self, value):
        self._runtime = value

    # ================================================================
    # 状态管理
    # ================================================================

    async def _set_status(self, status: AgentStatus):
        self._status = status
        self.logger.debug(f"Status -> {status.value}")

    def _set_status_sync(self, status: AgentStatus):
        self._status = status

    # ================================================================
    # 执行入口（子类覆盖）
    # ================================================================

    async def execute(self, **kwargs) -> Any:
        """
        Agent 执行入口（子类应覆盖此方法）。

        支持两种覆盖方式：
        - async def execute(self, **kwargs): ...  (推荐，新架构)
        - def execute(self, **kwargs): ...        (兼容旧 Agent)

        新架构中通过 run(message) 调用，
        run() 内部会调用 execute() 并自动处理同步/异步。

        向后兼容：旧代码可以直接调用 agent.execute(**kwargs)。
        """
        raise NotImplementedError(
            f"Agent '{self.agent_name}' must implement execute()"
        )

    # ================================================================
    # 新架构入口：run(message)
    # ================================================================

    async def run(self, message: AgentMessage) -> AgentMessage:
        """
        新架构统一入口。

        通过 Runtime 调用：
            result = await runtime.run_agent("agent_name", message)

        内部流程：
        1. 设置状态 RUNNING
        2. 记录开始时间
        3. 调用 execute(**message.payload)
        4. 构造响应 AgentMessage
        5. 写入 Memory
        6. 设置状态 COMPLETED
        7. 返回响应

        异常处理：
        - AgentExecutionError → 状态 FAILED，返回错误消息
        - AgentTimeoutError → 状态 FAILED，返回超时消息
        - 其他异常 → 包装为 AgentExecutionError
        """
        start_time = time.time()
        await self._set_status(AgentStatus.RUNNING)

        try:
            self.logger.info(f"Agent '{self.agent_name}' started, task_id={message.task_id}")

            # 记录输入消息到 Memory
            if self.memory:
                self.memory.add(message)

            # 调用子类 execute
            output = await self._execute_with_timeout(message)

            # 构造响应
            duration = time.time() - start_time
            response = AgentMessage.create_response(
                request=message,
                payload={
                    "output": output if isinstance(output, (dict, list, str, int, float, bool, type(None))) else str(output),
                    "duration": round(duration, 3),
                    "agent_name": self.agent_name,
                },
                status=MessageStatus.COMPLETED,
            )

            # 记录输出消息到 Memory
            if self.memory:
                self.memory.add(response)

            await self._set_status(AgentStatus.COMPLETED)
            self.logger.info(f"Agent '{self.agent_name}' completed in {duration:.3f}s")

            return response

        except AgentTimeoutError as e:
            duration = time.time() - start_time
            self.logger.error(f"Agent '{self.agent_name}' timeout: {e}")
            await self._set_status(AgentStatus.FAILED)
            return self._build_error_response(message, str(e), duration, "TIMEOUT")

        except AgentError as e:
            duration = time.time() - start_time
            self.logger.error(f"Agent '{self.agent_name}' error: {e}")
            await self._set_status(AgentStatus.FAILED)
            return self._build_error_response(message, str(e), duration, e.code)

        except Exception as e:
            duration = time.time() - start_time
            self.logger.error(f"Agent '{self.agent_name}' unexpected error: {e}", exc_info=True)
            await self._set_status(AgentStatus.FAILED)
            return self._build_error_response(message, str(e), duration, "UNEXPECTED_ERROR")

    async def _execute_with_timeout(self, message: AgentMessage) -> Any:
        """带超时执行（自动处理同步/异步 execute）"""
        # 调用子类 execute
        result = self.execute(**message.payload)

        # 如果 execute 是同步方法，结果不是协程，直接返回
        if not asyncio.iscoroutine(result):
            return result

        # 异步 execute，带超时等待
        if self.config.timeout <= 0:
            return await result

        try:
            return await asyncio.wait_for(result, timeout=self.config.timeout)
        except asyncio.TimeoutError:
            raise AgentTimeoutError(self.agent_name, self.config.timeout)

    def _build_error_response(self, request: AgentMessage, error: str,
                              duration: float, code: str) -> AgentMessage:
        """构造错误响应"""
        response = AgentMessage.create_response(
            request=request,
            payload={
                "error": error,
                "code": code,
                "duration": round(duration, 3),
                "agent_name": self.agent_name,
            },
            status=MessageStatus.FAILED,
        )
        if self.memory:
            self.memory.add(response)
        return response

    # ================================================================
    # LLM 调用封装
    # ================================================================

    async def call_llm(self, system_prompt: str, user_prompt: str,
                       temperature: Optional[float] = None,
                       max_tokens: Optional[int] = None) -> str:
        """
        统一 LLM 调用接口。

        根据 config.provider 选择对应 LLM：
        - dashscope: 通义千问
        - deepseek: DeepSeek
        - ollama: 本地 Ollama
        - mock: 返回模拟数据

        返回 LLM 生成的文本。
        """
        provider = self.config.provider or "dashscope"
        temp = temperature if temperature is not None else self.config.temperature
        tokens = max_tokens or self.config.max_tokens

        if provider == "mock":
            return '{"status": "mock", "message": "Mock LLM response"}'

        # 构建请求
        api_key = self.config.get_api_key()
        api_url = self.config.get_api_url()

        if not api_key or not api_url:
            self.logger.warning("No API key or URL configured, returning empty response")
            return ""

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.config.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temp,
            "max_tokens": tokens,
        }

        try:
            import httpx
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                resp = await client.post(api_url, headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()
                return data.get("choices", [{}])[0].get("message", {}).get("content", "")
        except Exception as exc:
            if "TimeoutStatusError" in type(exc).__name__ or "timeout" in str(exc).lower():
                raise AgentTimeoutError(self.agent_name, self.config.timeout)
            if "HTTPStatusError" in type(exc).__name__:
                raise AgentLLMError(
                    f"LLM API error: {exc}",
                    agent_name=self.agent_name,
                )
        except Exception as e:
            raise AgentLLMError(f"LLM call failed: {e}", agent_name=self.agent_name)

    def call_llm_sync(self, system_prompt: str, user_prompt: str,
                      temperature: Optional[float] = None) -> str:
        """同步 LLM 调用（兼容旧 Agent 的 _call_llm 接口）"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 在事件循环中，用 run_until
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(
                        asyncio.run,
                        self.call_llm(system_prompt, user_prompt, temperature),
                    ).result()
            else:
                return loop.run_until_complete(
                    self.call_llm(system_prompt, user_prompt, temperature)
                )
        except RuntimeError:
            return asyncio.run(self.call_llm(system_prompt, user_prompt, temperature))

    # ================================================================
    # 消息发送（新架构 AgentMessage）
    # ================================================================

    async def send_message(self, receiver: str, payload: Dict[str, Any],
                           message_type: MessageType = MessageType.REQUEST,
                           task_id: str = "") -> Optional[AgentMessage]:
        """
        通过 Runtime 发送消息到指定 Agent。

        如果 Agent 绑定了 Runtime，则通过 Runtime 路由消息；
        否则返回 None（降级为无通信）。
        """
        message = AgentMessage.create_request(
            session_id=self.session_id,
            sender=self.agent_name,
            receiver=receiver,
            payload=payload,
            task_id=task_id or self._context.get("task_id", ""),
            message_type=message_type,
        )

        if self.memory:
            self.memory.add(message)

        if self._runtime is not None:
            return await self._runtime.route_message(message)

        self.logger.debug(f"No runtime bound, message to '{receiver}' not delivered")
        return None

    def emit_progress(self, progress: float, message: str = "", **extra):
        """发送进度消息"""
        if self._runtime is not None:
            msg = AgentMessage.create_progress(
                session_id=self.session_id,
                sender=self.agent_name,
                payload={"progress": progress, "message": message, **extra},
                task_id=self._context.get("task_id", ""),
            )
            if self.memory:
                self.memory.add(msg)

    # ================================================================
    # 兼容旧 MessageBus 接口
    # ================================================================

    def emit(self, event: str, data: Any) -> None:
        """兼容旧 MessageBus.publish 接口"""
        topic = f"{self.agent_name}.{event}"
        if self.bus:
            try:
                self.bus.publish(topic=topic, source=self.agent_name, data=data)
            except Exception as e:
                self.logger.debug(f"emit to bus failed: {e}")

        # 同时发送到新架构（如果 Runtime 存在）
        if self._runtime is not None and self.session_id:
            try:
                msg = AgentMessage.create_progress(
                    session_id=self.session_id,
                    sender=self.agent_name,
                    payload={"event": event, "data": data},
                    task_id=self._context.get("task_id", ""),
                )
                if self.memory:
                    self.memory.add(msg)
            except Exception:
                pass

    def on_message(self, topic: str, handler: Callable) -> None:
        """兼容旧 MessageBus.subscribe 接口"""
        if self.bus:
            self.bus.subscribe(topic, handler)

    def off_message(self, topic: str, handler: Callable) -> None:
        """兼容旧 MessageBus.unsubscribe 接口"""
        if self.bus:
            self.bus.unsubscribe(topic, handler)

    # ================================================================
    # 工具管理
    # ================================================================

    def register_tool(self, name: str, func: Callable) -> None:
        """注册工具函数"""
        self._tools[name] = func
        self.logger.debug(f"Tool '{name}' registered")

    def unregister_tool(self, name: str) -> None:
        """注销工具函数"""
        self._tools.pop(name, None)

    def get_tool(self, name: str) -> Optional[Callable]:
        """获取工具函数"""
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        """列出所有工具"""
        return list(self._tools.keys())

    # ================================================================
    # Context 管理
    # ================================================================

    def set_context(self, key: str, value: Any) -> None:
        """设置上下文变量"""
        self._context[key] = value

    def get_context(self, key: str, default: Any = None) -> Any:
        """获取上下文变量"""
        return self._context.get(key, default)

    # ================================================================
    # 信息与序列化
    # ================================================================

    def info(self) -> dict:
        """返回 Agent 信息"""
        return {
            "agent_name": self.agent_name,
            "display_name": self.display_name,
            "description": self.description,
            "capabilities": [c.value for c in self.capabilities],
            "model": self.config.model_name,
            "provider": self.config.provider,
            "status": self._status.value,
            "session_id": self.session_id,
            "has_memory": self.memory is not None,
            "has_runtime": self._runtime is not None,
            "tools": self.list_tools(),
        }

    def to_dict(self) -> dict:
        """序列化 Agent 状态"""
        return self.info()

    # ================================================================
    # Memory 便捷方法
    # ================================================================

    def get_memory_context(self, limit: int = 10) -> str:
        """获取 Memory 的 Prompt 上下文"""
        if self.memory:
            return self.memory.to_prompt_context(limit)
        return ""

    def clear_memory(self) -> None:
        """清空 Memory"""
        if self.memory:
            self.memory.clear()

    # ================================================================
    # 生命周期
    # ================================================================

    async def on_start(self) -> None:
        """Agent 启动时回调（子类可覆盖）"""
        pass

    async def on_stop(self) -> None:
        """Agent 停止时回调（子类可覆盖）"""
        pass

    async def cleanup(self) -> None:
        """清理资源"""
        self._tools.clear()
        self._context.clear()
        await self._set_status(AgentStatus.IDLE)
