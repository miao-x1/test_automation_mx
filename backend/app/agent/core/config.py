"""
AgentConfig - 统一 Agent 配置模型
所有 Agent 的配置集中管理，不再散落在代码中。
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from app.core.config import settings


class AgentConfig(BaseModel):
    """
    Agent 统一配置。

    每个Agent实例创建时接受一个AgentConfig，
    包含模型、温度、超时、Memory、工具、Provider等全部可配项。
    """

    # ---- 基础信息 ----
    agent_name: str = Field(..., description="Agent唯一标识名")
    display_name: str = Field(default="", description="Agent显示名称")
    description: str = Field(default="", description="Agent功能描述")

    # ---- 模型配置 ----
    provider: str = Field(
        default_factory=lambda: settings.EMBEDDING_PROVIDER if hasattr(settings, "EMBEDDING_PROVIDER") else "dashscope",
        description="LLM提供者",
    )
    model_name: str = Field(
        default_factory=lambda: getattr(settings, "QWEN_MODEL", "qwen-plus"),
        description="模型名称",
    )
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="生成温度")
    max_tokens: int = Field(default=4096, ge=1, description="最大生成token数")
    api_key: Optional[str] = Field(default=None, description="API Key，不填则用全局配置")
    api_url: Optional[str] = Field(default=None, description="API URL，不填则用全局配置")

    # ---- Prompt 配置 ----
    system_prompt: Optional[str] = Field(default=None, description="系统提示词")
    prompt_template: Optional[str] = Field(default=None, description="用户提示词模板")

    # ---- 运行时配置 ----
    timeout: int = Field(
        default_factory=lambda: getattr(settings, "AGENT_TIMEOUT", 300),
        description="执行超时（秒）",
    )
    max_retries: int = Field(default=3, ge=0, description="最大重试次数")
    retry_interval: float = Field(default=1.0, ge=0, description="重试间隔（秒）")

    # ---- Memory 配置 ----
    memory_enabled: bool = Field(default=True, description="是否启用Memory")
    memory_type: str = Field(default="list", description="Memory类型: list/database/autogen")
    memory_max_size: int = Field(default=100, description="Memory最大条数（ListMemory用）")

    # ---- 工具配置 ----
    tools: List[str] = Field(default_factory=list, description="Agent可用工具列表")
    capabilities: List[str] = Field(default_factory=list, description="Agent能力标签")

    # ---- 扩展配置 ----
    metadata: Dict[str, Any] = Field(default_factory=dict, description="扩展元数据")

    # ---- 兼容旧 AgentFactory.AgentConfig ----
    agent_class: Optional[str] = Field(default=None, description="Agent类全限定名（用于动态导入）")

    model_config = {"arbitrary_types_allowed": True}

    def get_api_key(self) -> str:
        """获取API Key，优先用配置值，否则取全局"""
        if self.api_key:
            return self.api_key
        return getattr(settings, "QWEN_API_KEY", "")

    def get_api_url(self) -> str:
        """获取API URL，优先用配置值，否则取全局"""
        if self.api_url:
            return self.api_url
        return getattr(settings, "QWEN_URL", "")

    def to_legacy(self) -> dict:
        """转换为旧 AgentFactory.AgentConfig 兼容格式"""
        return {
            "agent_name": self.agent_name,
            "agent_class": self.agent_class,
            "model": self.model_name,
            "prompt": self.system_prompt,
            "description": self.description,
        }


def create_default_config(agent_name: str, **overrides) -> AgentConfig:
    """快速创建默认配置，可覆盖任意字段"""
    return AgentConfig(agent_name=agent_name, **overrides)
