"""
AgentRegistry 模型 - Agent 注册信息表

持久化 Agent 元数据到数据库，支持：
1. 运行时动态注册/移除 Agent（不重启）
2. Agent 版本管理和配置追踪
3. 管理界面展示 Agent 清单
"""
from sqlalchemy import Column, String, Text, Boolean, Integer, Index
from app.models.base import BaseModel


class AgentRegistry(BaseModel):
    """Agent 注册信息

    每个 Agent 在系统中的元数据记录。
    与内存中的 AgentSpec 对应，提供 DB 持久化能力。
    """

    __tablename__ = "agent_registry"

    agent_name = Column(
        String(64), nullable=False, unique=True, index=True,
        comment="Agent 唯一名称（如 requirement_agent）"
    )
    agent_type = Column(
        String(32), nullable=False, default="llm",
        comment="Agent 类型: llm/tool/runtime/adapter"
    )
    display_name = Column(
        String(128), nullable=True,
        comment="显示名称"
    )
    description = Column(
        Text, nullable=True,
        comment="Agent 描述"
    )
    module_path = Column(
        String(256), nullable=False,
        comment="Python 模块路径（如 app.agent.requirement.requirement_agent）"
    )
    class_name = Column(
        String(64), nullable=False,
        comment="类名（如 RequirementAgent）"
    )
    model_name = Column(
        String(64), nullable=True,
        comment="使用的模型名称（如 qwen-plus）"
    )
    model_provider = Column(
        String(32), nullable=True,
        comment="模型提供商（如 dashscope）"
    )
    prompt_path = Column(
        String(256), nullable=True,
        comment="Prompt 模板路径"
    )
    system_prompt = Column(
        Text, nullable=True,
        comment="系统 Prompt 内容"
    )
    tools = Column(
        Text, nullable=True,
        comment="工具列表(JSON 数组)"
    )
    capabilities = Column(
        Text, nullable=True,
        comment="能力列表(JSON 数组，如 [\"requirement_parse\", \"rag_retrieve\"])"
    )
    status = Column(
        String(20), nullable=False, default="registered", index=True,
        comment="状态: registered/initialized/running/stopped/error"
    )
    enabled = Column(
        Boolean, nullable=False, default=True, index=True,
        comment="是否启用"
    )
    version = Column(
        String(32), nullable=False, default="1.0.0",
        comment="Agent 版本号"
    )
    metadata_json = Column(
        Text, nullable=True,
        comment="额外元数据(JSON)"
    )

    def to_dict(self) -> dict:
        """转换为字典"""
        import json
        return {
            "id": self.id,
            "agent_name": self.agent_name,
            "agent_type": self.agent_type,
            "display_name": self.display_name,
            "description": self.description,
            "module_path": self.module_path,
            "class_name": self.class_name,
            "model_name": self.model_name,
            "model_provider": self.model_provider,
            "prompt_path": self.prompt_path,
            "system_prompt": self.system_prompt,
            "tools": json.loads(self.tools) if self.tools else [],
            "capabilities": json.loads(self.capabilities) if self.capabilities else [],
            "status": self.status,
            "enabled": self.enabled,
            "version": self.version,
            "metadata": json.loads(self.metadata_json) if self.metadata_json else {},
            "created_at": str(self.created_at) if self.created_at else None,
            "updated_at": str(self.updated_at) if self.updated_at else None,
        }


# 索引
Index("idx_agent_registry_name", AgentRegistry.agent_name)
Index("idx_agent_registry_type", AgentRegistry.agent_type)
Index("idx_agent_registry_status", AgentRegistry.status)
Index("idx_agent_registry_enabled", AgentRegistry.enabled)
