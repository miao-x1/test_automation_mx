"""
Agent 生命周期管理器

管理 Agent 从注册到销毁的完整生命周期：
  register → initialize → execute → shutdown

状态机：
  registered → initialized → running → stopped
                ↓               ↓
              error           error

使用方式：
    manager = get_lifecycle_manager()

    # 注册
    await manager.register("my_agent", spec)

    # 初始化
    await manager.initialize("my_agent", runtime)

    # 执行（由 TaskRuntime 调用，不直接调用）
    result = await manager.execute("my_agent", action="analyze", payload={...})

    # 关闭
    await manager.shutdown("my_agent")

    # 全局关闭
    await manager.shutdown_all()
"""
import asyncio
import logging
from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime

from app.agents.factory.config import AgentSpec
from app.agents.factory.factory import AgentFactory, get_agent_factory

logger = logging.getLogger(__name__)


class AgentLifecycleState(str, Enum):
    """Agent 生命周期状态"""
    REGISTERED = "registered"       # 已注册
    INITIALIZED = "initialized"     # 已初始化
    RUNNING = "running"             # 运行中
    STOPPED = "stopped"             # 已停止
    ERROR = "error"                 # 错误


class AgentLifecycleManager:
    """Agent 生命周期管理器

    管理 Agent 实例的状态转换和资源清理。
    与 AgentFactory 协作：Factory 负责创建，Lifecycle 负责状态管理。
    """

    def __init__(self) -> None:
        self._states: Dict[str, AgentLifecycleState] = {}
        self._error_info: Dict[str, str] = {}
        self._shutdown_hooks: Dict[str, list] = {}
        self._lock = asyncio.Lock()
        self._factory: AgentFactory = get_agent_factory()
        self._initialized_at: Dict[str, datetime] = {}
        self._last_executed_at: Dict[str, datetime] = {}

    # ------------------------------------------------------------------ #
    #  状态查询                                                           #
    # ------------------------------------------------------------------ #

    def get_state(self, agent_name: str) -> AgentLifecycleState:
        """获取 Agent 当前状态"""
        return self._states.get(agent_name, AgentLifecycleState.REGISTERED)

    def get_all_states(self) -> Dict[str, Dict[str, Any]]:
        """获取所有 Agent 的生命周期状态"""
        result: Dict[str, Dict[str, Any]] = {}
        for name, state in self._states.items():
            result[name] = {
                "state": state.value,
                "error": self._error_info.get(name),
                "initialized_at": str(self._initialized_at.get(name, "")),
                "last_executed_at": str(self._last_executed_at.get(name, "")),
            }
        return result

    def is_ready(self, agent_name: str) -> bool:
        """检查 Agent 是否就绪（可执行）"""
        state = self.get_state(agent_name)
        return state in (AgentLifecycleState.INITIALIZED, AgentLifecycleState.RUNNING)

    # ------------------------------------------------------------------ #
    #  生命周期阶段                                                       #
    # ------------------------------------------------------------------ #

    async def register(self, agent_name: str, spec: AgentSpec) -> bool:
        """注册阶段：将 Agent 添加到工厂并标记状态

        Args:
            agent_name: Agent 名称
            spec: Agent 规格

        Returns:
            是否成功
        """
        async with self._lock:
            try:
                self._factory.register(spec)
                self._states[agent_name] = AgentLifecycleState.REGISTERED
                self._error_info.pop(agent_name, None)
                logger.info(
                    f"[Lifecycle] Agent registered: {agent_name} "
                    f"(model={spec.model.model_name if spec.model else 'none'})"
                )
                return True
            except Exception as e:
                self._states[agent_name] = AgentLifecycleState.ERROR
                self._error_info[agent_name] = str(e)
                logger.error(f"[Lifecycle] Failed to register '{agent_name}': {e}")
                return False

    async def initialize(self, agent_name: str, runtime: Any = None) -> bool:
        """初始化阶段：预加载 Agent 类并创建实例

        Args:
            agent_name: Agent 名称
            runtime: AutoGen Core Runtime 实例

        Returns:
            是否成功
        """
        async with self._lock:
            if not self._factory.exists(agent_name):
                logger.error(f"[Lifecycle] Cannot initialize: agent '{agent_name}' not registered")
                return False

            try:
                # 预加载 Agent 实例
                instance = await self._factory.create(agent_name, runtime=runtime)
                if instance is None:
                    raise RuntimeError("Factory returned None")

                # 如果 Agent 有 initialize 方法，调用它
                if hasattr(instance, "initialize") and callable(getattr(instance, "initialize")):
                    init_method = instance.initialize
                    if asyncio.iscoroutinefunction(init_method):
                        await init_method()
                    else:
                        init_method()

                self._states[agent_name] = AgentLifecycleState.INITIALIZED
                self._initialized_at[agent_name] = datetime.now()
                self._error_info.pop(agent_name, None)

                logger.info(f"[Lifecycle] Agent initialized: {agent_name}")
                return True

            except Exception as e:
                self._states[agent_name] = AgentLifecycleState.ERROR
                self._error_info[agent_name] = str(e)
                logger.error(f"[Lifecycle] Failed to initialize '{agent_name}': {e}", exc_info=True)
                return False

    async def execute(
        self,
        agent_name: str,
        action: str = "execute",
        payload: Optional[Dict[str, Any]] = None,
        runtime: Any = None,
    ) -> Any:
        """执行阶段：调用 Agent 的 execute 方法

        Args:
            agent_name: Agent 名称
            action: 执行动作
            payload: 输入数据
            runtime: Runtime 实例

        Returns:
            Agent 执行结果
        """
        if not self.is_ready(agent_name):
            state = self.get_state(agent_name)
            raise RuntimeError(
                f"Agent '{agent_name}' is not ready (state={state.value}). "
                f"Please initialize it first."
            )

        self._states[agent_name] = AgentLifecycleState.RUNNING
        self._last_executed_at[agent_name] = datetime.now()

        try:
            instance = await self._factory.get(agent_name)
            if instance is None:
                raise RuntimeError(f"Agent instance not found: {agent_name}")

            result = await instance.execute(action=action, payload=payload or {})

            # 执行完成后恢复到 initialized 状态
            self._states[agent_name] = AgentLifecycleState.INITIALIZED
            return result

        except Exception as e:
            self._states[agent_name] = AgentLifecycleState.ERROR
            self._error_info[agent_name] = str(e)
            logger.error(f"[Lifecycle] Execution failed for '{agent_name}': {e}", exc_info=True)
            raise

    async def shutdown(self, agent_name: str) -> bool:
        """关闭阶段：清理 Agent 资源

        调用 Agent 的 cleanup/shutdown/on_stop 方法，
        然后从工厂缓存中移除。

        Args:
            agent_name: Agent 名称

        Returns:
            是否成功
        """
        async with self._lock:
            try:
                instance = self._factory._instances.get((agent_name, "default"))
                if instance is not None:
                    # 调用 cleanup 方法
                    for method_name in ("shutdown", "cleanup", "on_stop"):
                        method = getattr(instance, method_name, None)
                        if method is not None and callable(method):
                            try:
                                if asyncio.iscoroutinefunction(method):
                                    await method()
                                else:
                                    method()
                                logger.info(f"[Lifecycle] Called {method_name}() on '{agent_name}'")
                                break
                            except Exception as e:
                                logger.warning(f"[Lifecycle] {method_name}() failed on '{agent_name}': {e}")

                # 从工厂缓存移除
                keys_to_remove = [k for k in self._factory._instances if k[0] == agent_name]
                for k in keys_to_remove:
                    del self._factory._instances[k]

                self._states[agent_name] = AgentLifecycleState.STOPPED
                self._error_info.pop(agent_name, None)

                logger.info(f"[Lifecycle] Agent shutdown: {agent_name}")
                return True

            except Exception as e:
                self._states[agent_name] = AgentLifecycleState.ERROR
                self._error_info[agent_name] = str(e)
                logger.error(f"[Lifecycle] Failed to shutdown '{agent_name}': {e}")
                return False

    async def shutdown_all(self) -> int:
        """关闭所有已初始化的 Agent

        Returns:
            成功关闭的数量
        """
        agent_names = [
            name for name, state in self._states.items()
            if state in (AgentLifecycleState.INITIALIZED, AgentLifecycleState.RUNNING)
        ]

        results = await asyncio.gather(
            *[self.shutdown(name) for name in agent_names],
            return_exceptions=True,
        )

        success_count = sum(1 for r in results if r is True)
        logger.info(f"[Lifecycle] Shutdown {success_count}/{len(agent_names)} agents")
        return success_count

    # ------------------------------------------------------------------ #
    #  批量操作                                                           #
    # ------------------------------------------------------------------ #

    async def initialize_all(self, runtime: Any = None) -> Dict[str, bool]:
        """初始化所有已注册的 Agent

        Args:
            runtime: AutoGen Core Runtime 实例

        Returns:
            Dict[agent_name → success]
        """
        agent_names = list(self._factory._specs.keys())
        results: Dict[str, bool] = {}

        for name in agent_names:
            try:
                results[name] = await self.initialize(name, runtime)
            except Exception as e:
                logger.error(f"[Lifecycle] Failed to initialize '{name}': {e}")
                results[name] = False

        initialized = sum(1 for v in results.values() if v)
        logger.info(f"[Lifecycle] Initialized {initialized}/{len(results)} agents")
        return results

    def get_stats(self) -> Dict[str, Any]:
        """获取生命周期统计信息"""
        state_counts: Dict[str, int] = {}
        for state in self._states.values():
            state_counts[state.value] = state_counts.get(state.value, 0) + 1

        return {
            "total_tracked": len(self._states),
            "states": state_counts,
            "factory_stats": self._factory.get_stats(),
        }


# ------------------------------------------------------------------ #
#  单例                                                                #
# ------------------------------------------------------------------ #

_lifecycle_manager: Optional[AgentLifecycleManager] = None


def get_lifecycle_manager() -> AgentLifecycleManager:
    """获取 AgentLifecycleManager 单例。"""
    global _lifecycle_manager
    if _lifecycle_manager is None:
        _lifecycle_manager = AgentLifecycleManager()
    return _lifecycle_manager
