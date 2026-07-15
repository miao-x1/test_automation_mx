"""
RequirementChunk模型 - 大需求文档分块处理

支持滚动摘要：chunk1~6 → summary_1 → summary_1 + chunk7~12 → summary_2 → ...
"""
from sqlalchemy import Column, String, Integer, Text, Boolean, ForeignKey
from app.models.base import BaseModel


class RequirementChunk(BaseModel):
    """需求分块"""
    session_id = Column(Integer, ForeignKey("session.id", ondelete="CASCADE"), nullable=False, index=True, comment="会话ID")
    chunk_index = Column(Integer, nullable=False, comment="分块序号(0-based)")
    content = Column(Text, nullable=False, comment="分块原始内容")
    summary = Column(Text, nullable=True, comment="该分块及之前所有分块的滚动摘要")
    char_count = Column(Integer, default=0, comment="字符数")
    is_processed = Column(Boolean, default=False, comment="是否已处理")
