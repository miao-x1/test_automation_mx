"""
KnowledgeSource - 知识文档模型

记录上传的知识资料（PDF/Word/Swagger等），支持版本追踪和重生成。
"""
import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, JSON, Index
from sqlalchemy.sql import func
from app.models.base import BaseModel


class KnowledgeSourceStatus(str, enum.Enum):
    PENDING = "pending"
    INDEXING = "indexing"
    INDEXED = "indexed"
    FAILED = "failed"


class KnowledgeSource(BaseModel):
    """知识文档（一个上传文件 = 一条记录）"""
    __tablename__ = "knowledge_source"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(64), nullable=False, index=True)
    source_type = Column(String(32), nullable=False, index=True)

    # 文件信息
    file_path = Column(String(500), nullable=True)
    source_url = Column(String(2000), nullable=True)
    raw_text = Column(Text, nullable=True)
    requirement_context = Column(JSON, nullable=True)  # 序列化的 RequirementContext

    # 状态
    status = Column(String(20), nullable=False, default=KnowledgeSourceStatus.PENDING)
    error_message = Column(Text, nullable=True)
    chunk_count = Column(Integer, nullable=False, default=0)

    # 版本与追溯
    version = Column(Integer, nullable=False, default=1)
    parent_knowledge_id = Column(Integer, ForeignKey("knowledge_source.id", ondelete="SET NULL"), nullable=True)

    # 用户与时间
    created_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    indexed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_knowledge_project_status", "project_id", "status"),
    )
