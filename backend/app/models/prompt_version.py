"""
PromptVersion 模型 - Prompt 版本管理表

管理 Agent 内部 Prompt 的版本化存储,支持:
1. 版本管理 - 每个 Agent 的 Prompt 可有多个版本
2. A/B 测试 - 同一 Agent 可同时运行多个 Prompt 版本按流量分配
3. Prompt 回滚 - 快速切换回历史活跃版本
4. 版本比较 - 对比两个版本的 diff
5. 权限控制 - 核心 Prompt 不允许普通用户修改,仅开发人员可管理

核心字段: agent_name / prompt_version / content / status
"""
import enum
from sqlalchemy import Column, String, Text, Boolean, Float, Integer, Enum as SQLEnum, Index
from sqlalchemy.dialects import mysql
from app.models.base import BaseModel


class PromptStatus(str, enum.Enum):
    """Prompt 版本状态"""
    DRAFT = "draft"          # 草稿(开发中)
    ACTIVE = "active"        # 活跃(当前使用)
    ARCHIVED = "archived"    # 已归档(历史版本)
    TESTING = "testing"      # 测试中(A/B 测试)


class PromptVersion(BaseModel):
    """Prompt 版本表

    每个 Agent 的每种 Prompt(system_prompt / user_prompt_template 等)
    都可以有多个版本,同一 agent_name + prompt_key 同时只能有一个 ACTIVE。

    A/B 测试时,可以同时有一个 ACTIVE + 一个或多个 TESTING,
    按 ab_test_ratio 分配流量。
    """
    __tablename__ = "prompt_version"

    # 关联
    agent_name = Column(
        String(64), nullable=False, index=True,
        comment="Agent 名称(关联 agent_registry.agent_name)",
    )
    prompt_key = Column(
        String(64), nullable=False, default="system_prompt",
        comment="Prompt 标识: system_prompt / user_prompt_template / custom_xxx",
    )

    # 版本
    version = Column(
        String(32), nullable=False,
        comment="版本号: v1 / v2 / 1.0.0 等",
    )
    content = Column(
        mysql.MEDIUMTEXT(), nullable=False,
        comment="Prompt 内容",
    )
    description = Column(
        Text, nullable=True,
        comment="版本描述/变更说明",
    )

    # 状态
    status = Column(
        SQLEnum(PromptStatus, values_callable=lambda x: [e.value for e in x]),
        default=PromptStatus.DRAFT, nullable=False, index=True,
        comment="状态: draft/active/archived/testing",
    )

    # A/B 测试
    ab_test_group = Column(
        String(16), nullable=True,
        comment="A/B 测试分组: A / B / C 等",
    )
    ab_test_ratio = Column(
        Float, nullable=True, default=0.0,
        comment="A/B 测试流量比例 (0.0-1.0)",
    )

    # 元数据
    change_type = Column(
        String(20), nullable=True,
        comment="变更类型: new/modify/rollback",
    )
    parent_version = Column(
        String(32), nullable=True,
        comment="父版本号(回滚时指向被回滚的版本)",
    )
    tags = Column(
        Text, nullable=True,
        comment="标签 JSON 数组",
    )

    # 统计(运行时更新)
    usage_count = Column(
        Integer, default=0, nullable=False,
        comment="使用次数",
    )
    success_count = Column(
        Integer, default=0, nullable=False,
        comment="成功次数",
    )

    __table_args__ = (
        # 唯一约束:同一 Agent + Prompt Key + 版本号 唯一
        Index("idx_prompt_version_unique", "agent_name", "prompt_key", "version", unique=True),
        # 查询索引:按 Agent + Key 查活跃版本
        Index("idx_prompt_agent_key_status", "agent_name", "prompt_key", "status"),
        # 查询索引:按状态查
        Index("idx_prompt_status_created", "status", "created_at"),
    )

    def to_dict(self) -> dict:
        """转换为字典"""
        import json
        return {
            "id": self.id,
            "agent_name": self.agent_name,
            "prompt_key": self.prompt_key,
            "version": self.version,
            "content": self.content,
            "description": self.description or "",
            "status": self.status.value if hasattr(self.status, 'value') else self.status,
            "ab_test_group": self.ab_test_group,
            "ab_test_ratio": self.ab_test_ratio,
            "change_type": self.change_type,
            "parent_version": self.parent_version,
            "tags": json.loads(self.tags) if self.tags else [],
            "usage_count": self.usage_count,
            "success_count": self.success_count,
            "created_at": str(self.created_at) if self.created_at else None,
            "updated_at": str(self.updated_at) if self.updated_at else None,
        }
