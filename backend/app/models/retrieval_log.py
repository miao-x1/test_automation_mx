"""
RetrievalLog - 检索日志模型

记录每次 RAG 检索的详细信息，用于可观测性和回溯。
"""
import datetime
from sqlalchemy import Column, Integer, BigInteger, String, Text, Float, DateTime, ForeignKey, JSON, Index
from sqlalchemy.sql import func
from app.models.base import BaseModel


class RetrievalLog(BaseModel):
    """检索日志"""
    __tablename__ = "retrieval_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(64), nullable=False, index=True)
    task_id = Column(String(64), nullable=True, index=True)
    case_generation_id = Column(Integer, ForeignKey("case_generation.id", ondelete="SET NULL"), nullable=True)

    # 查询参数
    query_text = Column(Text, nullable=True)
    query_vector_id = Column(BigInteger, nullable=True)
    top_k = Column(Integer, nullable=False, default=10)
    score_threshold = Column(Float, nullable=False, default=0.6)
    filters = Column(JSON, nullable=True)

    # 结果
    results = Column(JSON, nullable=True)  # 检索到的 chunks 列表
    total_results = Column(Integer, nullable=False, default=0)
    avg_score = Column(Float, nullable=False, default=0.0)
    latency_ms = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime, default=func.now(), index=True)

    __table_args__ = (
        Index("ix_retrieval_task", "task_id"),
        Index("ix_retrieval_project_time", "project_id", "created_at"),
    )
