"""
WorkflowEvent模型 - 工作流事件溯源

替代SSE流式推送，所有工作流步骤通过事件记录到DB，
前端通过轮询 /workflow/status 和 /workflow/events 获取进度。
"""
import enum
from sqlalchemy import Column, String, Integer, Float, Text, ForeignKey, Index
from app.models.base import BaseModel


class WorkflowEventType(str, enum.Enum):
    """工作流事件类型"""
    START = "START"         # 步骤开始
    SUCCESS = "SUCCESS"     # 步骤成功
    ERROR = "ERROR"         # 步骤失败
    PROGRESS = "PROGRESS"   # 步骤进度


class WorkflowEvent(BaseModel):
    """工作流事件"""
    __tablename__ = "workflow_event"

    session_id = Column(
        Integer, ForeignKey("session.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="会话ID"
    )
    agent = Column(
        String(50), nullable=False, index=True,
        comment="Agent名称: Requirement/APIExtraction/RAG/CaseGenerate/Review/Workflow"
    )
    event_type = Column(
        String(20), nullable=False, index=True,
        comment="事件类型: START/SUCCESS/ERROR/PROGRESS"
    )
    message = Column(
        Text, nullable=True,
        comment="事件消息"
    )
    cost = Column(
        Float, nullable=True,
        comment="Token消耗"
    )
    duration = Column(
        Float, nullable=True,
        comment="耗时(秒)"
    )


Index('idx_workflow_event_session_agent', WorkflowEvent.session_id, WorkflowEvent.agent)
Index('idx_workflow_event_session_type', WorkflowEvent.session_id, WorkflowEvent.event_type)
