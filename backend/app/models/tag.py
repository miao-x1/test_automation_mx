"""
Tag 模型 - 统一标签管理

支持给文档、需求、页面、接口、用例、脚本等任意实体打标签。
KnowledgeTag 为多对多关联表。
"""
import enum
from sqlalchemy import Column, String, Integer, Text, ForeignKey, Index, UniqueConstraint
from app.models.base import BaseModel, OwnedModel


class TagType(str, enum.Enum):
    """标签类型"""
    MODULE = "module"        # 模块标签
    BUSINESS = "business"    # 业务标签
    TECH = "tech"            # 技术标签
    PRIORITY = "priority"    # 优先级标签
    CUSTOM = "custom"        # 自定义标签


class Tag(OwnedModel):
    """标签表"""
    __tablename__ = "tag"

    name = Column(String(100), nullable=False, comment="标签名称")
    tag_type = Column(
        String(20), nullable=False, default=TagType.CUSTOM,
        index=True, comment="标签类型: module/business/tech/priority/custom"
    )
    color = Column(String(20), nullable=True, comment="标签颜色(十六进制)")
    description = Column(Text, nullable=True, comment="标签描述")

    __table_args__ = (
        UniqueConstraint("user_id", "name", "tag_type", name="uq_tag_user_name_type"),
    )


class KnowledgeTag(BaseModel):
    """实体-标签多对多关联表

    支持给任意实体（文档/需求/页面/接口/用例/脚本/Chunk）打标签。
    """
    __tablename__ = "knowledge_tag"

    tag_id = Column(
        Integer, ForeignKey("tag.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="标签ID"
    )
    entity_type = Column(
        String(50), nullable=False, index=True,
        comment="实体类型: document/requirement/page/api/case/script/chunk/session"
    )
    entity_id = Column(
        Integer, nullable=False, index=True,
        comment="实体ID（对应 MySQL 表的主键）"
    )

    __table_args__ = (
        UniqueConstraint("tag_id", "entity_type", "entity_id", name="uq_tag_entity"),
        Index("ix_knowledge_tag_entity", "entity_type", "entity_id"),
    )
