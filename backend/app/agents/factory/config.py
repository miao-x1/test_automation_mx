"""
AgentSpec - Agent 规格定义

每个 Agent 拥有独立的配置：
- 模型配置（provider / model_name / api_key / api_url / temperature）
- Prompt 配置（system_prompt / prompt_template）
- 工具列表
- 能力标签
- 启用/禁用状态

支持不同 Agent 使用不同模型：
    RequirementAgent → Qwen (dashscope)
    CaseAgent         → DeepSeek
    ReviewAgent       → Claude (anthropic)
    ScriptAgent       → QwenCoder (dashscope)
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ModelConfig:
    """
    模型配置

    定义 LLM 提供者、模型名、API Key、温度等。

    支持的 provider:
    - dashscope:  通义千问（Qwen / QwenCoder / Qwen-VL）
    - deepseek:   DeepSeek（deepseek-chat / deepseek-coder）
    - anthropic:  Claude（claude-3.5-sonnet / claude-3-opus）
    - ollama:     本地 Ollama
    - openai:     OpenAI GPT
    - mock:       测试用
    """
    provider: str = "dashscope"
    model_name: str = "qwen-plus"
    api_key: str = ""                     # 留空则用环境变量
    api_url: str = ""                    # 留空则用默认 URL
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: int = 120
    # 扩展参数（如 top_p / frequency_penalty 等）
    extra_params: Dict[str, Any] = field(default_factory=dict)

    def get_api_key(self) -> str:
        """获取 API Key（空则从环境变量读取）。"""
        import os
        if self.api_key:
            return self.api_key

        key_map = {
            "dashscope": "DASHSCOPE_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
        }
        env_var = key_map.get(self.provider, "")
        return os.getenv(env_var, "")

    def get_api_url(self) -> str:
        """获取 API URL（空则用默认）。"""
        if self.api_url:
            return self.api_url

        url_map = {
            "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            "deepseek": "https://api.deepseek.com/v1/chat/completions",
            "anthropic": "https://api.anthropic.com/v1/messages",
            "openai": "https://api.openai.com/v1/chat/completions",
            "ollama": "http://localhost:11434/v1/chat/completions",
        }
        return url_map.get(self.provider, "")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model_name": self.model_name,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "has_api_key": bool(self.get_api_key()),
        }


@dataclass
class AgentSpec:
    """
    Agent 规格定义

    定义一个 Agent 的全部元数据，AgentFactory 根据此规格创建 Agent。

    Attributes:
        name:         Agent 唯一标识名（如 "requirement_agent"）
        display_name: 显示名（如 "需求解析Agent"）
        description:  功能描述
        agent_type:   Agent 类型分类
                      - "llm":       需要 LLM 的 Agent（有模型配置）
                      - "tool":      纯工具 Agent（如 EmbeddingAgent）
                      - "runtime":    运行时 Agent（如 CollectorAgent）
                      - "adapter":    旧 Agent 适配
        module_path:  Python 模块路径（懒加载用）
        class_name:   类名
        model:        模型配置（agent_type=="llm" 时必填）
        system_prompt:  系统提示词
        prompt_template: 用户提示词模板（支持 {variable} 占位符）
        tools:        工具列表（Agent 可调用的外部工具名）
        capabilities: 能力标签列表
        enabled:      是否启用
        metadata:     扩展元数据

    示例：
        AgentSpec(
            name="requirement_agent",
            display_name="需求解析Agent",
            description="解析自然语言需求，提取意图和步骤",
            agent_type="llm",
            module_path="app.agent.requirement.requirement_agent",
            class_name="RequirementAgent",
            model=ModelConfig(provider="dashscope", model_name="qwen-plus"),
            system_prompt="你是一个需求分析专家...",
            capabilities=["requirement_parse"],
            enabled=True,
        )
    """
    name: str
    display_name: str = ""
    description: str = ""
    agent_type: str = "llm"               # llm / tool / runtime / adapter
    module_path: str = ""
    class_name: str = ""
    model: Optional[ModelConfig] = None
    system_prompt: str = ""
    prompt_template: str = ""
    tools: List[str] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "agent_type": self.agent_type,
            "module_path": self.module_path,
            "class_name": self.class_name,
            "model": self.model.to_dict() if self.model else None,
            "system_prompt": self.system_prompt[:200] + "..." if len(self.system_prompt) > 200 else self.system_prompt,
            "has_prompt_template": bool(self.prompt_template),
            "tools": self.tools,
            "capabilities": self.capabilities,
            "enabled": self.enabled,
        }
