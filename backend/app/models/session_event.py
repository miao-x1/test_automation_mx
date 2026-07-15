"""
SessionEvent模型 - 事件溯源

Session通过事件记录完整生命周期，支持：
  - 事件回放恢复状态
  - 审计追踪
  - 断点续传

事件类型：
  upload / chunk / rag / generate / review / publish / execute
"""
from sqlalchemy import Column, String, Integer, Text, ForeignKey, Index
from app.models.base import BaseModel


class SessionEvent(BaseModel):
    """会话事件"""
    __tablename__ = "session_event"

    session_id = Column(
        Integer, ForeignKey("session.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="会话ID"
    )
    event_type = Column(
        String(30), nullable=False, index=True,
        comment="事件类型: upload/chunk/rag/generate/review/publish/execute/error"
    )
    payload = Column(
        Text, nullable=True,
        comment="事件数据(JSON)"
    )
    step_index = Column(
        Integer, default=0,
        comment="步骤序号（用于排序）"
    )

    # 事件类型常量
    UPLOAD = "upload"
    CHUNK = "chunk"
    RAG = "rag"
    GENERATE = "generate"
    REVIEW = "review"
    PUBLISH = "publish"
    EXECUTE = "execute"
    ERROR = "error"


Index('idx_session_event_session_type', SessionEvent.session_id, SessionEvent.event_type)
