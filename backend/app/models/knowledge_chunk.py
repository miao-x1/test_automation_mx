"""
KnowledgeChunk - 知识分片模型

记录知识文档切分后的 chunk 元数据。实际向量存储在 Milvus 中。
"""
import datetime
from sqlalchemy import Column, Integer, BigInteger, String, Text, DateTime, ForeignKey, JSON, Index
from sqlalchemy.sql import func
from app.models.base import BaseModel


class KnowledgeChunk(BaseModel):
    """知识分片元数据"""
    __tablename__ = "knowledge_chunk"

    id = Column(Integer, primary_key=True, autoincrement=True)
    knowledge_source_id = Column(
        Integer,
        ForeignKey("knowledge_source.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    milvus_id = Column(BigInteger, nullable=False)  # 对应 Milvus 主键

    # Chunk 内容（冗余存储便于调试）
    chunk_type = Column(String(32), nullable=True, index=True)  # narrative/api/entity/flow/constraint/page
    text = Column(Text, nullable=True)
    locator = Column(String(200), nullable=True)  # 定位符
    page = Column(String(64), nullable=True)
    chunk_metadata = Column("metadata", JSON, nullable=True)

    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        Index("ix_chunk_type", "chunk_type"),
    )
