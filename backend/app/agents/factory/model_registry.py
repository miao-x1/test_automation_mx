"""
ModelRegistry - 模型注册表

预定义所有可用模型的配置，AgentSpec 通过模型别名引用。

支持的模型别名：
- "qwen":           通义千问通用模型（qwen-plus）
- "qwen_vl":        通义千问视觉模型（qwen-vl-max）
- "qwen_coder":     通义千问代码模型（qwen-coder-plus）
- "qwen_max":       通义千问旗舰模型（qwen-max）
- "deepseek":       DeepSeek 通用模型（deepseek-chat）
- "deepseek_coder": DeepSeek 代码模型（deepseek-coder）
- "claude":         Claude 3.5 Sonnet
- "claude_opus":    Claude 3 Opus
- "gpt4":           OpenAI GPT-4o
- "ollama":         本地 Ollama
- "mock":           测试用

使用方式：
    # 在 AgentSpec 中引用
    AgentSpec(name="requirement_agent", model=MODELS["qwen"])

    # 动态获取
    registry = get_model_registry()
    model = registry.get("qwen")
    model = registry.get_by_name("requirement_agent")  # 通过 agent_name 获取
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.agents.factory.config import ModelConfig

logger = logging.getLogger(__name__)


# ================================================================== #
#  预定义模型                                                          #
# ================================================================== #

DEFAULT_MODELS: Dict[str, ModelConfig] = {
    # --- 通义千问系列（dashscope）---
    "qwen": ModelConfig(
        provider="dashscope",
        model_name="qwen-plus",
        temperature=0.7,
        max_tokens=4096,
    ),
    "qwen_max": ModelConfig(
        provider="dashscope",
        model_name="qwen-max",
        temperature=0.5,
        max_tokens=8192,
    ),
    "qwen_vl": ModelConfig(
        provider="dashscope",
        model_name="qwen-vl-max",
        temperature=0.5,
        max_tokens=4096,
    ),
    "qwen_coder": ModelConfig(
        provider="dashscope",
        model_name="qwen-coder-plus",
        temperature=0.3,
        max_tokens=8192,
    ),

    # --- DeepSeek 系列 ---
    "deepseek": ModelConfig(
        provider="deepseek",
        model_name="deepseek-chat",
        temperature=0.3,
        max_tokens=8192,
    ),
    "deepseek_coder": ModelConfig(
        provider="deepseek",
        model_name="deepseek-coder",
        temperature=0.2,
        max_tokens=8192,
    ),

    # --- Claude 系列（anthropic）---
    "claude": ModelConfig(
        provider="anthropic",
        model_name="claude-3-5-sonnet-20241022",
        temperature=0.5,
        max_tokens=8192,
    ),
    "claude_opus": ModelConfig(
        provider="anthropic",
        model_name="claude-3-opus-20240229",
        temperature=0.5,
        max_tokens=8192,
    ),

    # --- OpenAI 系列 ---
    "gpt4": ModelConfig(
        provider="openai",
        model_name="gpt-4o",
        temperature=0.5,
        max_tokens=8192,
    ),

    # --- 本地 Ollama ---
    "ollama": ModelConfig(
        provider="ollama",
        model_name="qwen2.5:7b",
        temperature=0.7,
        max_tokens=4096,
    ),

    # --- 测试用 ---
    "mock": ModelConfig(
        provider="mock",
        model_name="mock-model",
        temperature=0.0,
        max_tokens=100,
    ),
}


class ModelRegistry:
    """
    模型注册表

    管理所有可用的模型配置。
    AgentSpec 通过模型别名引用预定义的模型配置。

    功能：
    - get(alias): 按别名获取模型配置
    - register(alias, config): 注册新模型
    - list_models(): 列出所有模型
    - get_for_agent(agent_name): 获取指定 Agent 的模型配置
    """

    def __init__(self) -> None:
        self._models: Dict[str, ModelConfig] = dict(DEFAULT_MODELS)
        # agent_name → model_alias 映射
        self._agent_model_map: Dict[str, str] = {}

    def get(self, alias: str) -> Optional[ModelConfig]:
        """按别名获取模型配置。"""
        return self._models.get(alias)

    def register(self, alias: str, config: ModelConfig) -> None:
        """注册新模型或覆盖已有模型。"""
        self._models[alias] = config
        logger.info(f"[ModelRegistry] Model registered: {alias} → {config.provider}/{config.model_name}")

    def unregister(self, alias: str) -> None:
        """移除模型。"""
        self._models.pop(alias, None)

    def list_models(self) -> List[str]:
        """列出所有模型别名。"""
        return list(self._models.keys())

    def list_models_with_config(self) -> List[Dict]:
        """列出所有模型及其配置。"""
        return [
            {"alias": alias, **config.to_dict()}
            for alias, config in self._models.items()
        ]

    def has(self, alias: str) -> bool:
        """检查模型是否存在。"""
        return alias in self._models

    # ------------------------------------------------------------------ #
    #  Agent → Model 映射                                                 #
    # ------------------------------------------------------------------ #

    def set_agent_model(self, agent_name: str, model_alias: str) -> None:
        """设置 Agent 使用的模型别名。"""
        if model_alias not in self._models:
            logger.warning(f"[ModelRegistry] Unknown model alias: {model_alias}")
        self._agent_model_map[agent_name] = model_alias
        logger.info(f"[ModelRegistry] Agent '{agent_name}' → model '{model_alias}'")

    def get_for_agent(self, agent_name: str) -> Optional[ModelConfig]:
        """获取指定 Agent 的模型配置。"""
        alias = self._agent_model_map.get(agent_name)
        if alias is None:
            return None
        return self.get(alias)

    def get_agent_model_alias(self, agent_name: str) -> str:
        """获取指定 Agent 的模型别名。"""
        return self._agent_model_map.get(agent_name, "qwen")

    def list_agent_models(self) -> Dict[str, str]:
        """列出所有 Agent 的模型映射。"""
        return dict(self._agent_model_map)


# ------------------------------------------------------------------ #
#  单例                                                                #
# ------------------------------------------------------------------ #

_model_registry: Optional[ModelRegistry] = None


def get_model_registry() -> ModelRegistry:
    """获取 ModelRegistry 单例。"""
    global _model_registry
    if _model_registry is None:
        _model_registry = ModelRegistry()
    return _model_registry
