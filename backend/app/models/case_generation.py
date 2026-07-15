"""
CaseGeneration - 用例生成任务模型

记录每次用例生成的完整信息，支持版本管理和重生成。
"""
import enum
import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON, Index
from sqlalchemy.sql import func
from app.models.base import BaseModel


class CaseGenerationStatus(str, enum.Enum):
    PENDING = "pending"
    PARSING = "parsing"
    RAG_QUERYING = "rag_querying"
    GENERATING = "generating"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"


class CaseGeneration(BaseModel):
    """用例生成任务记录"""
    __tablename__ = "case_generation"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(64), nullable=False, index=True)
    case_task_id = Column(Integer, ForeignKey("case_task.id", ondelete="CASCADE"), nullable=False, index=True)

    # 版本与追溯
    version = Column(Integer, nullable=False, default=1)
    parent_generation_id = Column(Integer, ForeignKey("case_generation.id", ondelete="SET NULL"), nullable=True)

    # 输入快照
    requirement_context = Column(JSON, nullable=True)
    retrieved_context = Column(JSON, nullable=True)  # RAG 结果快照
    retrieved_chunk_ids = Column(JSON, nullable=True)  # 引用的 chunk ID 列表

    # 状态
    status = Column(String(20), nullable=False, default=CaseGenerationStatus.PENDING)
    error_message = Column(Text, nullable=True)

    # 输出
    case_set = Column(JSON, nullable=True)  # 最终 CaseSet
    case_count = Column(Integer, nullable=False, default=0)

    # 配置与统计
    config = Column(JSON, nullable=True)  # CaseGenerationConfig
    llm_usage = Column(JSON, nullable=True)  # token 消耗
    latency_ms = Column(Integer, nullable=False, default=0)

    # 时间
    created_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_gen_task_version", "case_task_id", "version"),
        Index("ix_gen_project_status", "project_id", "status"),
    )
