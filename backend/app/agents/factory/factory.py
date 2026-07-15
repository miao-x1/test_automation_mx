"""
AgentFactory - 企业级 Agent 工厂

职责：
1. 统一注册所有 Agent（基于 AgentSpec）
2. 懒加载创建 Agent 实例（首次使用时才 import 类）
3. 管理每个 Agent 的模型配置、Prompt、工具列表
4. 支持动态注册/移除 Agent
5. 支持运行时修改 Agent 配置（模型、Prompt、启停）

核心 API：
- register(spec)       注册 Agent 规格
- unregister(name)     移除 Agent
- get(name)            获取 Agent 规格
- create(name)         创建 Agent 实例（懒加载）
- list()               列出所有 Agent
- get_model(name)      获取 Agent 的模型配置
- enable(name)/disable(name)  启用/禁用 Agent

设计原则：
1. Agent 类在首次 create() 时才被 import（懒加载）
2. Agent 实例创建后缓存，重复 create() 返回同一实例
3. 支持不同 Agent 使用不同模型（通过 AgentSpec.model）
4. 新增 Agent 只需在 DEFAULT_AGENT_SPECS 添加记录，Factory 自动注册
5. Agent 禁止直接 new 其它 Agent，统一通过 Factory + Runtime 消息通信

使用方式：
    factory = get_agent_factory()

    # 获取 Agent 规格
    spec = factory.get("requirement_agent")

    # 创建 Agent 实例
    agent = await factory.create("requirement_agent", runtime, session_key="user_1")

    # 获取模型配置
    model = factory.get_model("requirement_agent")  # → ModelConfig(provider=dashscope, model=qwen-plus)

    # 列出所有 Agent
    agents = factory.list()

    # 动态注册新 Agent
    factory.register(AgentSpec(name="my_new_agent", ...))
"""
import asyncio
import importlib
import logging
from typing import Any, Dict, List, Optional, Type

from app.agents.factory.config import AgentSpec, ModelConfig
from app.agents.factory.definitions import DEFAULT_AGENT_SPECS
from app.agents.factory.model_registry import ModelRegistry, get_model_registry

logger = logging.getLogger(__name__)


class AgentFactory:
    """
    Agent 工厂

    管理所有 Agent 的注册、创建、配置。

    属性：
    - _specs:       Dict[agent_name → AgentSpec]
    - _instances:    Dict[(agent_name, session_key) → agent_instance]  实例缓存
    - _loaded_classes: Dict[agent_name → class]  懒加载的类缓存
    - _model_registry: ModelRegistry  模型注册表
    """

    def __init__(self) -> None:
        self._specs: Dict[str, AgentSpec] = {}
        self._instances: Dict[tuple, Any] = {}  # (agent_name, session_key) → instance
        self._loaded_classes: Dict[str, Type] = {}
        self._model_registry: ModelRegistry = get_model_registry()
        self._lock = asyncio.Lock()

        # 自动加载默认 Agent 定义
        for spec in DEFAULT_AGENT_SPECS:
            self._specs[spec.name] = spec
            # 将 Agent → 模型映射注册到 ModelRegistry
            if spec.model:
                alias = f"{spec.name}_model"
                self._model_registry.register(alias, spec.model)
                self._model_registry.set_agent_model(spec.name, alias)

        logger.info(
            f"[AgentFactory] Initialized with {len(self._specs)} agent specs"
        )

    # ------------------------------------------------------------------ #
    #  注册 / 移除                                                         #
    # ------------------------------------------------------------------ #

    def register(self, spec: AgentSpec) -> None:
        """
        注册 Agent 规格

        如果已存在同名 Agent，将覆盖。

        Args:
            spec: Agent 规格定义
        """
        self._specs[spec.name] = spec

        # 注册模型到 ModelRegistry
        if spec.model:
            alias = f"{spec.name}_model"
            self._model_registry.register(alias, spec.model)
            self._model_registry.set_agent_model(spec.name, alias)

        # 清除缓存的类和实例
        self._loaded_classes.pop(spec.name, None)
        keys_to_remove = [k for k in self._instances if k[0] == spec.name]
        for k in keys_to_remove:
            del self._instances[k]

        logger.info(f"[AgentFactory] Agent registered: {spec.name} ({spec.display_name})")

    def unregister(self, name: str) -> bool:
        """
        移除 Agent

        Args:
            name: Agent 名称

        Returns:
            是否成功移除
        """
        if name not in self._specs:
            logger.warning(f"[AgentFactory] Agent not found: {name}")
            return False

        spec = self._specs.pop(name)
        self._loaded_classes.pop(name, None)
        keys_to_remove = [k for k in self._instances if k[0] == name]
        for k in keys_to_remove:
            del self._instances[k]

        logger.info(f"[AgentFactory] Agent unregistered: {name} ({spec.display_name})")
        return True

    # ------------------------------------------------------------------ #
    #  查询                                                               #
    # ------------------------------------------------------------------ #

    def get(self, name: str) -> Optional[AgentSpec]:
        """
        获取 Agent 规格

        Args:
            name: Agent 名称

        Returns:
            AgentSpec 或 None（不存在）
        """
        return self._specs.get(name)

    def list(self, enabled_only: bool = False) -> List[AgentSpec]:
        """
        列出所有 Agent 规格

        Args:
            enabled_only: 仅返回启用的 Agent

        Returns:
            AgentSpec 列表
        """
        specs = list(self._specs.values())
        if enabled_only:
            specs = [s for s in specs if s.enabled]
        return specs

    def list_names(self, enabled_only: bool = False) -> List[str]:
        """列出所有 Agent 名称。"""
        if enabled_only:
            return [name for name, spec in self._specs.items() if spec.enabled]
        return list(self._specs.keys())

    def exists(self, name: str) -> bool:
        """检查 Agent 是否存在。"""
        return name in self._specs

    def count(self) -> int:
        """获取已注册 Agent 数量。"""
        return len(self._specs)

    def get_by_capability(self, capability: str) -> List[str]:
        """按能力查询 Agent 名称。"""
        return [
            name for name, spec in self._specs.items()
            if capability in spec.capabilities and spec.enabled
        ]

    # ------------------------------------------------------------------ #
    #  模型配置                                                           #
    # ------------------------------------------------------------------ #

    def get_model(self, name: str) -> Optional[ModelConfig]:
        """
        获取 Agent 的模型配置

        Args:
            name: Agent 名称

        Returns:
            ModelConfig 或 None（Agent 不需要模型）
        """
        spec = self._specs.get(name)
        if spec is None:
            return None
        return spec.model

    def set_model(self, name: str, model: ModelConfig) -> bool:
        """
        修改 Agent 的模型配置（运行时切换模型）

        Args:
            name: Agent 名称
            model: 新的模型配置

        Returns:
            是否成功
        """
        spec = self._specs.get(name)
        if spec is None:
            return False
        spec.model = model
        # 更新 ModelRegistry
        alias = f"{name}_model"
        self._model_registry.register(alias, model)
        self._model_registry.set_agent_model(name, alias)
        # 清除缓存的实例（需要用新模型重建）
        keys_to_remove = [k for k in self._instances if k[0] == name]
        for k in keys_to_remove:
            del self._instances[k]
        logger.info(f"[AgentFactory] Model updated for '{name}': {model.provider}/{model.model_name}")
        return True

    # ------------------------------------------------------------------ #
    #  启用 / 禁用                                                        #
    # ------------------------------------------------------------------ #

    def enable(self, name: str) -> bool:
        """启用 Agent。"""
        spec = self._specs.get(name)
        if spec is None:
            return False
        spec.enabled = True
        logger.info(f"[AgentFactory] Agent enabled: {name}")
        return True

    def disable(self, name: str) -> bool:
        """禁用 Agent。"""
        spec = self._specs.get(name)
        if spec is None:
            return False
        spec.enabled = False
        # 清除缓存的实例
        keys_to_remove = [k for k in self._instances if k[0] == name]
        for k in keys_to_remove:
            del self._instances[k]
        logger.info(f"[AgentFactory] Agent disabled: {name}")
        return True

    def is_enabled(self, name: str) -> bool:
        """检查 Agent 是否启用。"""
        spec = self._specs.get(name)
        return spec.enabled if spec else False

    # ------------------------------------------------------------------ #
    #  创建 Agent 实例（懒加载）                                           #
    # ------------------------------------------------------------------ #

    def _load_class(self, name: str) -> Optional[Type]:
        """
        懒加载 Agent 类

        通过 importlib 动态导入模块，获取类。
        首次加载后缓存，后续直接返回缓存。

        Args:
            name: Agent 名称

        Returns:
            Agent 类，或 None（加载失败）
        """
        if name in self._loaded_classes:
            return self._loaded_classes[name]

        spec = self._specs.get(name)
        if spec is None:
            logger.error(f"[AgentFactory] Unknown agent: {name}")
            return None

        if not spec.module_path or not spec.class_name:
            logger.error(f"[AgentFactory] Missing module_path or class_name for '{name}'")
            return None

        try:
            module = importlib.import_module(spec.module_path)
            cls = getattr(module, spec.class_name, None)
            if cls is None:
                logger.error(
                    f"[AgentFactory] Class '{spec.class_name}' not found in {spec.module_path}"
                )
                return None

            self._loaded_classes[name] = cls
            logger.info(f"[AgentFactory] Class loaded: {name} → {cls.__name__}")
            return cls

        except ImportError as e:
            logger.warning(f"[AgentFactory] Failed to import {spec.module_path}: {e}")
            return None
        except Exception as e:
            logger.error(f"[AgentFactory] Error loading {name}: {e}")
            return None

    async def create(
        self,
        name: str,
        runtime: Any = None,
        session_key: str = "default",
        **kwargs,
    ) -> Any:
        """
        创建 Agent 实例

        懒加载策略：
        1. 首次调用时 import Agent 类
        2. 创建实例并注入模型配置、Prompt、工具
        3. 缓存实例，后续调用返回同一实例（同 session_key）

        Args:
            name: Agent 名称
            runtime: AutoGen Core Runtime 实例
            session_key: 会话标识（不同 session_key 创建独立实例）
            **kwargs: 额外构造参数

        Returns:
            Agent 实例

        Raises:
            ValueError: Agent 不存在或未启用
            RuntimeError: Agent 类加载失败
        """
        spec = self._specs.get(name)
        if spec is None:
            raise ValueError(f"Agent not found: {name}")

        if not spec.enabled:
            raise ValueError(f"Agent is disabled: {name}")

        # 检查缓存
        cache_key = (name, session_key)
        if cache_key in self._instances:
            return self._instances[cache_key]

        async with self._lock:
            # 双重检查
            if cache_key in self._instances:
                return self._instances[cache_key]

            # 懒加载类
            cls = self._load_class(name)
            if cls is None:
                raise RuntimeError(f"Failed to load agent class: {name}")

            # 创建实例
            instance = await self._instantiate(cls, spec, runtime, session_key, **kwargs)

            # 缓存
            self._instances[cache_key] = instance

            logger.info(
                f"[AgentFactory] Agent created: {name} (session={session_key}, "
                f"model={spec.model.model_name if spec.model else 'none'})"
            )

            return instance

    async def _instantiate(
        self,
        cls: Type,
        spec: AgentSpec,
        runtime: Any,
        session_key: str,
        **kwargs,
    ) -> Any:
        """
        创建 Agent 实例并注入配置

        支持多种 Agent 类型：
        1. BaseRoutedAgent（新架构）：直接构造，注入 spec
        2. LegacyAgentAdapter（旧架构）：包装旧 Agent
        3. 旧 BaseAgent：通过适配器包装

        注入策略：
        - 如果 Agent 有 `configure(spec, model_config, ...)` 方法，调用它
        - 否则尝试将配置作为构造参数传递
        """
        # 检查是否是 BaseRoutedAgent（新架构）
        from app.runtime.base_agent import BaseRoutedAgent

        if issubclass(cls, BaseRoutedAgent):
            # 新架构 Agent：直接创建，然后注入配置
            try:
                instance = cls()
            except TypeError:
                instance = cls(**kwargs)
            # 注入 AgentSpec 配置
            if hasattr(instance, "_spec"):
                instance._spec = spec
            if hasattr(instance, "_model_config"):
                instance._model_config = spec.model
            if hasattr(instance, "_display_name"):
                instance._display_name = spec.display_name or spec.name
            if hasattr(instance, "_capabilities"):
                instance._capabilities = spec.capabilities
            if hasattr(instance, "_system_prompt"):
                instance._system_prompt = spec.system_prompt
            if hasattr(instance, "_tools"):
                instance._tools = spec.tools
            # 设置模型配置到 BaseRoutedAgent
            if spec.model and hasattr(instance, "set_context"):
                instance.set_context("model_config", spec.model)
                instance.set_context("system_prompt", spec.system_prompt)
                instance.set_context("prompt_template", spec.prompt_template)
            return instance

        # 检查是否是 RoutedAgent（AutoGen Core 原生）
        from autogen_core import RoutedAgent
        if issubclass(cls, RoutedAgent):
            try:
                instance = cls()
            except TypeError:
                instance = cls(**kwargs)
            return instance

        # 旧架构 Agent：通过 LegacyAgentAdapter 包装
        from app.runtime.adapter import LegacyAgentAdapter
        try:
            instance = LegacyAgentAdapter(cls, **kwargs)
        except TypeError:
            instance = LegacyAgentAdapter(cls)
        # 注入配置到 adapter
        if hasattr(instance, "_spec"):
            instance._spec = spec
        if hasattr(instance, "_model_config"):
            instance._model_config = spec.model

        return instance

    # ------------------------------------------------------------------ #
    #  注册到 AutoGen Core Runtime                                       #
    # ------------------------------------------------------------------ #

    async def register_to_runtime(self, runtime: Any) -> Dict[str, bool]:
        """
        将所有启用的 Agent 注册到 AutoGen Core Runtime

        Args:
            runtime: CoreRuntime 实例

        Returns:
            Dict[agent_name → success]
        """
        results: Dict[str, bool] = {}

        for name, spec in self._specs.items():
            if not spec.enabled:
                results[name] = False
                continue

            try:
                cls = self._load_class(name)
                if cls is None:
                    results[name] = False
                    continue

                # 创建工厂函数
                def make_factory(agent_cls=cls, agent_spec=spec):
                    async def factory():
                        instance = await self._instantiate(
                            agent_cls, agent_spec, None, "default"
                        )
                        return instance
                    return factory

                # 检查是否是 RoutedAgent 子类
                from autogen_core import RoutedAgent
                if issubclass(cls, RoutedAgent):
                    await runtime.register_agent_type(
                        agent_type=name,
                        agent_class=cls,
                        factory=lambda cls=cls: cls(),
                    )
                else:
                    # 旧 Agent → 适配器
                    from app.runtime.adapter import LegacyAgentAdapter
                    await runtime.register_agent_type(
                        agent_type=name,
                        agent_class=LegacyAgentAdapter,
                        factory=lambda c=cls: LegacyAgentAdapter(c),
                    )

                results[name] = True
                logger.info(f"[AgentFactory] Registered to runtime: {name}")

            except Exception as e:
                logger.warning(f"[AgentFactory] Failed to register {name}: {e}")
                results[name] = False

        registered = sum(1 for v in results.values() if v)
        logger.info(
            f"[AgentFactory] Runtime registration: "
            f"{registered}/{len(results)} agents registered"
        )

        return results

    # ------------------------------------------------------------------ #
    #  工具管理                                                           #
    # ------------------------------------------------------------------ #

    def get_tools(self, name: str) -> List[str]:
        """获取 Agent 的工具列表。"""
        spec = self._specs.get(name)
        return spec.tools if spec else []

    def add_tool(self, name: str, tool_name: str) -> bool:
        """为 Agent 添加工具。"""
        spec = self._specs.get(name)
        if spec is None:
            return False
        if tool_name not in spec.tools:
            spec.tools.append(tool_name)
        return True

    def remove_tool(self, name: str, tool_name: str) -> bool:
        """移除 Agent 的工具。"""
        spec = self._specs.get(name)
        if spec is None:
            return False
        if tool_name in spec.tools:
            spec.tools.remove(tool_name)
        return True

    # ------------------------------------------------------------------ #
    #  状态                                                               #
    # ------------------------------------------------------------------ #

    def get_stats(self) -> Dict[str, Any]:
        """获取工厂统计信息。"""
        enabled = sum(1 for s in self._specs.values() if s.enabled)
        llm_agents = sum(1 for s in self._specs.values() if s.agent_type == "llm" and s.enabled)
        tool_agents = sum(1 for s in self._specs.values() if s.agent_type == "tool" and s.enabled)
        return {
            "total_specs": len(self._specs),
            "enabled": enabled,
            "disabled": len(self._specs) - enabled,
            "llm_agents": llm_agents,
            "tool_agents": tool_agents,
            "loaded_classes": len(self._loaded_classes),
            "cached_instances": len(self._instances),
            "models": self._model_registry.list_models(),
        }

    def get_info(self) -> List[Dict[str, Any]]:
        """获取所有 Agent 信息（用于API返回）。"""
        return [spec.to_dict() for spec in self._specs.values()]

    def get_model_registry(self) -> ModelRegistry:
        """获取 ModelRegistry 实例。"""
        return self._model_registry

    def clear_cache(self) -> None:
        """清除所有缓存的实例（不影响规格定义）。"""
        self._instances.clear()
        self._loaded_classes.clear()
        logger.info("[AgentFactory] Instance cache cleared")


# ------------------------------------------------------------------ #
#  单例                                                                #
# ------------------------------------------------------------------ #

_agent_factory: Optional[AgentFactory] = None


def get_agent_factory() -> AgentFactory:
    """获取 AgentFactory 单例。"""
    global _agent_factory
    if _agent_factory is None:
        _agent_factory = AgentFactory()
    return _agent_factory
