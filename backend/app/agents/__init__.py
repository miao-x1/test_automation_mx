"""
Agent 工厂模块 - 企业级 Agent 创建与管理

核心组件：
- AgentFactory: 统一注册、创建、管理所有 Agent
- AgentSpec: Agent 规格定义（名称、模型、Prompt、工具、描述等）
- ModelRegistry: 模型注册表（支持不同 Agent 使用不同模型）
- DEFAULT_AGENT_SPECS: 全部 Agent 默认定义

设计原则：
1. 所有 Agent 通过 AgentFactory 统一创建
2. 每个 Agent 可配置不同的模型（Qwen / DeepSeek / Claude / QwenCoder 等）
3. 新增 Agent 只需在 DEFAULT_AGENT_SPECS 添加一条记录
4. Factory 自动创建并注入配置，业务代码无需感知
5. Agent 禁止直接 new 其它 Agent，统一通过消息机制通信
"""
from app.agents.factory.config import AgentSpec, ModelConfig
from app.agents.factory.definitions import DEFAULT_AGENT_SPECS
from app.agents.factory.model_registry import ModelRegistry, DEFAULT_MODELS, get_model_registry
from app.agents.factory.factory import AgentFactory, get_agent_factory

__all__ = [
    "AgentSpec",
    "ModelConfig",
    "DEFAULT_AGENT_SPECS",
    "ModelRegistry",
    "DEFAULT_MODELS",
    "get_model_registry",
    "AgentFactory",
    "get_agent_factory",
]
