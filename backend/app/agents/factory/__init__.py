"""
Agent Factory 模块

统一 Agent 注册、创建、管理。

使用方式：
  from app.agents.factory import AgentRegistry, AgentFactory

  # 启动时自动注册
  AgentRegistry.auto_register()

  # 通过 Factory 创建
  agent = AgentFactory.create_agent("requirement_agent")

  # 或通过 Registry 创建
  agent = AgentRegistry.create("requirement_agent")

  # 查询
  AgentRegistry.list_agents()
  AgentRegistry.get_config("case_agent")
"""
from app.agents.factory.config import AgentSpec, ModelConfig
from app.agents.factory.definitions import DEFAULT_AGENT_SPECS
from app.agents.factory.model_registry import (
    ModelRegistry,
    DEFAULT_MODELS,
    get_model_registry,
)
from app.agents.factory.factory import AgentFactory, get_agent_factory
from app.agents.factory.registry import AgentRegistry, auto_register_agents
from app.agents.factory.lifecycle import AgentLifecycleManager, get_lifecycle_manager
from app.agents.factory.models import AgentMetadataStore

__all__ = [
    "AgentSpec",
    "ModelConfig",
    "DEFAULT_AGENT_SPECS",
    "ModelRegistry",
    "DEFAULT_MODELS",
    "get_model_registry",
    "AgentFactory",
    "get_agent_factory",
    "AgentRegistry",
    "auto_register_agents",
    "AgentLifecycleManager",
    "get_lifecycle_manager",
    "AgentMetadataStore",
]
