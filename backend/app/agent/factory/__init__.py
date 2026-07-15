"""
Factory 模块 - Agent 工厂

负责：
- Agent 注册与注销
- 根据名称获取 Agent
- 根据能力获取 Agent
- 支持后续多个模型 Provider
- Agent 自动注册

所有 Agent 在启动时通过 AgentRegistry 自动注册到 AgentFactory，
后续新增 Agent 无需修改其它代码。
"""
from app.agent.factory.agent_factory import AgentFactory
from app.agent.factory.registry import AgentRegistry, auto_register_agents
from app.agent.core.config import AgentConfig

__all__ = [
    "AgentFactory",
    "AgentConfig",
    "AgentRegistry",
    "auto_register_agents",
]
