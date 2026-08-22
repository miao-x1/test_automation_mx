"""
LLM Gateway - 统一的大模型调用网关

架构:
    Agent → LLMGateway → ModelRouter → Provider → 模型供应商

职责:
- 所有 Agent 统一通过 LLMGateway.chat() 调用大模型,禁止直连模型 API
- ModelRouter 负责模型选择、失败切换、熔断、健康检查
- 四类供应商:Qwen(DashScope) / DeepSeek / OpenAI / 本地(Ollama) + Mock
- 每次调用落库 llm_call_log,记录 token 用量与费用
- 提供 Token 与费用统计 API

公开接口:
    from app.llm import LLMGateway, LLMResponse
    gateway = LLMGateway.instance()
    content = await gateway.chat(agent_name="case_agent", system_prompt=..., user_prompt=...)
"""
from app.llm.types import LLMResponse, LLMCallContext, ProviderHealth
from app.llm.cost_calculator import CostCalculator, get_cost_calculator
from app.llm.providers.base import BaseProvider
from app.llm.providers.factory import ProviderFactory, get_provider_factory
from app.llm.model_router import ModelRouter, get_model_router
from app.llm.gateway import LLMGateway, get_gateway

__all__ = [
    "LLMGateway",
    "get_gateway",
    "LLMResponse",
    "LLMCallContext",
    "ProviderHealth",
    "CostCalculator",
    "get_cost_calculator",
    "BaseProvider",
    "ProviderFactory",
    "get_provider_factory",
    "ModelRouter",
    "get_model_router",
]
