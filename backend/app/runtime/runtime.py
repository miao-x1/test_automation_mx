"""
AutoGen Core Runtime - SingleThreadedAgentRuntime 创建

负责创建和配置整个 AutoGen Core Runtime 实例。

核心职责：
1. 创建 SingleThreadedAgentRuntime 实例
2. 注册所有 Agent 类型到 Runtime
3. 启动 / 停止 Runtime
4. 提供消息发送接口

设计原则：
- Runtime 不感知具体 Agent 类型（通过 AgentRegistry 注册）
- Runtime 支持 AgentId key 实现多用户/多 Session 隔离
- 新增 Agent 不需要修改 Runtime 代码
"""
import asyncio
import logging
from typing import Any, Dict, Optional

from autogen_core import (
    SingleThreadedAgentRuntime,
    AgentId,
)

from app.runtime.collector import CollectorAgent

logger = logging.getLogger(__name__)


class CoreRuntime:
    """
    AutoGen Core Runtime 封装

    管理一个 SingleThreadedAgentRuntime 实例的生命周期。
    提供消息发送、结果获取等接口。

    使用方式：
        runtime = CoreRuntime()
        await runtime.start()
        result = await runtime.send_task("requirement_agent", "execute", {...}, session_key="user_1_session_a")
        await runtime.stop()
    """

    def __init__(self) -> None:
        self._runtime: Optional[SingleThreadedAgentRuntime] = None
        self._collector: Optional[CollectorAgent] = None
        self._started: bool = False
        self._agent_types: Dict[str, bool] = {}  # agent_type → registered
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    #  Runtime 生命周期                                                    #
    # ------------------------------------------------------------------ #

    async def initialize(self) -> None:
        """
        初始化 Runtime：
        1. 创建 SingleThreadedAgentRuntime
        2. 注册 CollectorAgent
        """
        async with self._lock:
            if self._runtime is not None:
                logger.warning("[CoreRuntime] Already initialized")
                return

            logger.info("[CoreRuntime] Creating SingleThreadedAgentRuntime...")
            self._runtime = SingleThreadedAgentRuntime()

            # 注册 CollectorAgent（每个 session key 一个实例）
            await CollectorAgent.register(
                self._runtime,
                "collector",
                lambda: CollectorAgent(),
            )
            self._agent_types["collector"] = True
            logger.info("[CoreRuntime] CollectorAgent registered")

            logger.info("[CoreRuntime] Runtime initialized successfully")

    async def start(self) -> None:
        """启动 Runtime 后台消息处理。"""
        if self._runtime is None:
            await self.initialize()
        if not self._started and self._runtime is not None:
            self._runtime.start()
            self._started = True
            logger.info("[CoreRuntime] Runtime started")

    async def stop(self) -> None:
        """停止 Runtime（立即停止，不等待空闲）。"""
        if self._runtime and self._started:
            await self._runtime.stop()
            self._started = False
            logger.info("[CoreRuntime] Runtime stopped")

    async def stop_when_idle(self) -> None:
        """等待所有消息处理完毕后停止。"""
        if self._runtime and self._started:
            await self._runtime.stop_when_idle()
            self._started = False
            logger.info("[CoreRuntime] Runtime stopped (idle)")

    async def close(self) -> None:
        """关闭 Runtime 并释放资源。"""
        if self._runtime:
            if self._started:
                await self.stop()
            await self._runtime.close()
            self._runtime = None
            logger.info("[CoreRuntime] Runtime closed")

    # ------------------------------------------------------------------ #
    #  Agent 注册                                                          #
    # ------------------------------------------------------------------ #

    async def register_agent_type(
        self,
        agent_type: str,
        agent_class: type,
        factory: Optional[callable] = None,
    ) -> None:
        """
        注册 Agent 类型到 Runtime

        Args:
            agent_type: Agent 类型名（唯一标识）
            agent_class: Agent 类（必须继承 RoutedAgent / BaseRoutedAgent）
            factory: 工厂函数，用于创建实例。默认为 agent_class()
        """
        if self._runtime is None:
            await self.initialize()

        if agent_type in self._agent_types:
            logger.debug(f"[CoreRuntime] Agent type '{agent_type}' already registered")
            return

        if factory is None:
            factory = lambda: agent_class()

        await agent_class.register(self._runtime, agent_type, factory)
        self._agent_types[agent_type] = True
        logger.info(f"[CoreRuntime] Agent type registered: {agent_type}")

    def is_registered(self, agent_type: str) -> bool:
        """检查 Agent 类型是否已注册。"""
        return agent_type in self._agent_types

    def list_agent_types(self) -> list:
        """列出所有已注册的 Agent 类型。"""
        return list(self._agent_types.keys())

    # ------------------------------------------------------------------ #
    #  消息发送                                                            #
    # ------------------------------------------------------------------ #

    async def send_message(
        self,
        message: Any,
        target: AgentId,
    ) -> Any:
        """
        发送消息到指定 Agent（直接消息）

        Args:
            message: 消息对象（Pydantic BaseModel）
            target: 目标 AgentId (type, key)

        Returns:
            目标 Agent 的响应（如果有）
        """
        if self._runtime is None or not self._started:
            await self.start()
        return await self._runtime.send_message(message, target)

    async def send_task(
        self,
        agent_type: str,
        action: str,
        payload: Dict[str, Any],
        task_id: str = "",
        session_key: str = "default",
        reply_to: str = "collector",
    ) -> None:
        """
        发送 TaskMessage 到指定 Agent

        Args:
            agent_type: 目标 Agent 类型
            action: 要执行的方法名
            payload: 方法参数
            task_id: 任务ID
            session_key: 会话标识（AgentId key）
            reply_to: 结果投递目标
        """
        from app.runtime.messages import TaskMessage

        if not task_id:
            import uuid
            task_id = str(uuid.uuid4())

        msg = TaskMessage(
            task_id=task_id,
            task_type=agent_type,
            action=action,
            payload=payload,
            session_id=session_key,
            reply_to=reply_to,
        )

        target = AgentId(agent_type, session_key)
        logger.info(f"[CoreRuntime] send_task: {agent_type}:{session_key}, action={action}, task={task_id}")
        await self.send_message(msg, target)

    # ------------------------------------------------------------------ #
    #  结果获取                                                            #
    # ------------------------------------------------------------------ #

    async def get_collector(self, session_key: str = "default") -> Optional[CollectorAgent]:
        """
        获取指定 session 的 CollectorAgent 实例

        CollectorAgent 的结果按 task_id 聚合，
        可通过 collector.get_result(task_id) 获取。
        """
        if self._runtime is None:
            return None

        try:
            agent_id = AgentId("collector", session_key)
            collector = await self._runtime.try_get_underlying_agent_instance(
                agent_id,
                type=CollectorAgent,
            )
            return collector
        except Exception as e:
            logger.warning(f"[CoreRuntime] Failed to get collector for {session_key}: {e}")
            return None

    async def get_result(self, task_id: str, session_key: str = "default", timeout: float = 300) -> Optional[Dict]:
        """
        获取任务结果（阻塞等待完成）

        Args:
            task_id: 任务ID
            session_key: 会话标识
            timeout: 超时时间（秒）

        Returns:
            任务结果字典，或 None（超时/未找到）
        """
        collector = await self.get_collector(session_key)
        if collector is None:
            return None

        result = await collector.wait_for_result(task_id, timeout=timeout)
        if result is None:
            return None

        return result.to_dict()

    # ------------------------------------------------------------------ #
    #  状态                                                                #
    # ------------------------------------------------------------------ #

    @property
    def is_started(self) -> bool:
        return self._started

    @property
    def runtime(self) -> Optional[SingleThreadedAgentRuntime]:
        return self._runtime

    def get_stats(self) -> Dict[str, Any]:
        return {
            "started": self._started,
            "agent_types": list(self._agent_types.keys()),
            "agent_count": len(self._agent_types),
        }


# ------------------------------------------------------------------ #
#  单例                                                                #
# ------------------------------------------------------------------ #

_core_runtime: Optional[CoreRuntime] = None


def get_core_runtime() -> CoreRuntime:
    """获取 CoreRuntime 单例。"""
    global _core_runtime
    if _core_runtime is None:
        _core_runtime = CoreRuntime()
    return _core_runtime
