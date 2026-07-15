"""
AutoGen Core Runtime - Agent 注册表

负责：
1. 定义所有 Agent 类型的元数据（类型名、模块路径、类名、工厂函数）
2. 在 Runtime 启动时自动注册所有 Agent
3. 支持懒加载（首次使用时才 import Agent 类）
4. 新增 Agent 只需在 AGENT_DEFINITIONS 中添加一条记录

设计原则：
- Runtime 不需要知道具体 Agent 类
- Agent 类在首次使用时才被 import（懒加载）
- 支持运行时动态注册自定义 Agent
"""
import importlib
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type

from autogen_core import RoutedAgent

logger = logging.getLogger(__name__)


@dataclass
class AgentDefinition:
    """
    Agent 定义（配置驱动注册）

    Attributes:
        agent_type: Agent 类型名（唯一标识，用于 AgentId.type）
        module_path: 模块路径（懒加载用）
        class_name: 类名
        display_name: 显示名
        capabilities: 能力标签列表
        factory_params: 工厂函数参数（传给构造函数）
    """
    agent_type: str
    module_path: str
    class_name: str
    display_name: str = ""
    capabilities: List[str] = field(default_factory=list)
    factory_params: Dict[str, Any] = field(default_factory=dict)


# ================================================================== #
#  Agent 定义表                                                         #
#  统一从 DEFAULT_AGENT_SPECS 自动生成，消除双重维护                     #
#  新增 Agent 只需在 agents/factory/definitions.py 中添加 AgentSpec      #
# ================================================================== #

def _build_definitions_from_specs() -> List[AgentDefinition]:
    """
    从 DEFAULT_AGENT_SPECS 自动生成 AGENT_DEFINITIONS

    AgentSpec 是 AgentDefinition 的超集：
    - AgentSpec.name        → AgentDefinition.agent_type
    - AgentSpec.module_path → AgentDefinition.module_path
    - AgentSpec.class_name  → AgentDefinition.class_name
    - AgentSpec.display_name → AgentDefinition.display_name
    - AgentSpec.capabilities → AgentDefinition.capabilities
    """
    from app.agents.factory.definitions import DEFAULT_AGENT_SPECS

    definitions = []
    for spec in DEFAULT_AGENT_SPECS:
        # 跳过禁用的 Agent
        if not spec.enabled:
            continue
        definitions.append(AgentDefinition(
            agent_type=spec.name,
            module_path=spec.module_path,
            class_name=spec.class_name,
            display_name=spec.display_name,
            capabilities=spec.capabilities,
        ))
    return definitions


# 自动从 DEFAULT_AGENT_SPECS 生成
AGENT_DEFINITIONS: List[AgentDefinition] = _build_definitions_from_specs()


class AgentRegistry:
    """
    Agent 注册表

    在 Runtime 启动时自动注册所有 Agent 定义。
    支持懒加载：Agent 类在首次使用时才被 import。
    """

    def __init__(self) -> None:
        self._definitions: Dict[str, AgentDefinition] = {}
        self._loaded_classes: Dict[str, Type] = {}  # agent_type → class (懒加载缓存)
        self._registered: Dict[str, bool] = {}  # agent_type → registered to runtime
        # 加载默认定义
        for definition in AGENT_DEFINITIONS:
            self._definitions[definition.agent_type] = definition

    def add_definition(self, definition: AgentDefinition) -> None:
        """添加自定义 Agent 定义。"""
        self._definitions[definition.agent_type] = definition
        logger.info(f"[AgentRegistry] Definition added: {definition.agent_type}")

    def remove_definition(self, agent_type: str) -> None:
        """移除 Agent 定义。"""
        self._definitions.pop(agent_type, None)
        self._loaded_classes.pop(agent_type, None)
        self._registered.pop(agent_type, None)

    def get_definition(self, agent_type: str) -> Optional[AgentDefinition]:
        """获取 Agent 定义。"""
        return self._definitions.get(agent_type)

    def list_definitions(self) -> List[AgentDefinition]:
        """列出所有 Agent 定义。"""
        return list(self._definitions.values())

    def list_agent_types(self) -> List[str]:
        """列出所有 Agent 类型名。"""
        return list(self._definitions.keys())

    def _load_agent_class(self, agent_type: str) -> Optional[Type]:
        """
        懒加载 Agent 类

        通过 importlib 动态导入模块，获取类。
        首次加载后缓存，后续直接返回缓存。
        """
        if agent_type in self._loaded_classes:
            return self._loaded_classes[agent_type]

        definition = self._definitions.get(agent_type)
        if definition is None:
            logger.error(f"[AgentRegistry] Unknown agent type: {agent_type}")
            return None

        try:
            module = importlib.import_module(definition.module_path)
            cls = getattr(module, definition.class_name, None)
            if cls is None:
                logger.error(
                    f"[AgentRegistry] Class '{definition.class_name}' not found in {definition.module_path}"
                )
                return None

            self._loaded_classes[agent_type] = cls
            logger.info(f"[AgentRegistry] Class loaded: {agent_type} → {cls.__name__}")
            return cls

        except ImportError as e:
            logger.warning(f"[AgentRegistry] Failed to import {definition.module_path}: {e}")
            return None
        except Exception as e:
            logger.error(f"[AgentRegistry] Error loading {agent_type}: {e}")
            return None

    def _create_factory(self, agent_type: str) -> Optional[Callable]:
        """
        创建 Agent 工厂函数

        工厂函数在首次被调用时懒加载 Agent 类并创建实例。
        """
        definition = self._definitions.get(agent_type)
        if definition is None:
            return None

        def factory():
            cls = self._load_agent_class(agent_type)
            if cls is None:
                raise RuntimeError(f"Failed to load agent class: {agent_type}")

            # 尝试使用 factory_params 创建实例
            try:
                if definition.factory_params:
                    return cls(**definition.factory_params)
                else:
                    return cls()
            except TypeError:
                # 如果构造函数需要参数，尝试无参创建
                # Agent 类可能在 __init__ 中需要特殊参数
                # 这里返回一个 adapter wrapper
                logger.warning(
                    f"[AgentRegistry] {agent_type} requires constructor args, wrapping in adapter"
                )
                from app.runtime.adapter import LegacyAgentAdapter
                return LegacyAgentAdapter(cls)

        return factory

    async def register_all(self, runtime) -> None:
        """
        将所有 Agent 定义注册到 Runtime

        Args:
            runtime: CoreRuntime 实例
        """
        registered_count = 0
        failed_count = 0

        for agent_type, definition in self._definitions.items():
            try:
                factory = self._create_factory(agent_type)
                if factory is None:
                    failed_count += 1
                    continue

                # 先尝试加载类，如果失败则跳过
                cls = self._load_agent_class(agent_type)
                if cls is None:
                    failed_count += 1
                    continue

                # 检查是否是 RoutedAgent 子类
                from autogen_core import RoutedAgent
                if not issubclass(cls, RoutedAgent):
                    # 对于非 RoutedAgent 类，使用适配器包装
                    from app.runtime.adapter import LegacyAgentAdapter
                    await runtime.register_agent_type(
                        agent_type=agent_type,
                        agent_class=LegacyAgentAdapter,
                        factory=lambda: LegacyAgentAdapter(cls),
                    )
                else:
                    await runtime.register_agent_type(
                        agent_type=agent_type,
                        agent_class=cls,
                        factory=factory,
                    )

                self._registered[agent_type] = True
                registered_count += 1

            except Exception as e:
                logger.warning(f"[AgentRegistry] Failed to register {agent_type}: {e}")
                failed_count += 1

        logger.info(
            f"[AgentRegistry] Registration complete: "
            f"{registered_count} registered, {failed_count} failed, "
            f"{len(self._definitions)} total"
        )

    def is_registered(self, agent_type: str) -> bool:
        """检查 Agent 是否已注册。"""
        return self._registered.get(agent_type, False)

    def get_info(self) -> List[Dict[str, Any]]:
        """获取所有 Agent 信息。"""
        return [
            {
                "agent_type": d.agent_type,
                "display_name": d.display_name,
                "capabilities": d.capabilities,
                "module_path": d.module_path,
                "class_name": d.class_name,
                "registered": self._registered.get(d.agent_type, False),
                "loaded": d.agent_type in self._loaded_classes,
            }
            for d in self._definitions.values()
        ]

    def get_by_capability(self, capability: str) -> List[str]:
        """按能力查询 Agent 类型。"""
        return [
            d.agent_type
            for d in self._definitions.values()
            if capability in d.capabilities
        ]


# ------------------------------------------------------------------ #
#  单例                                                                #
# ------------------------------------------------------------------ #

_agent_registry: Optional[AgentRegistry] = None


def get_agent_registry() -> AgentRegistry:
    """获取 AgentRegistry 单例。"""
    global _agent_registry
    if _agent_registry is None:
        _agent_registry = AgentRegistry()
    return _agent_registry
