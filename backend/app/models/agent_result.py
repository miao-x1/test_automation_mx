"""
AgentResult模型 - Agent执行结果

存储每个Agent步骤的结构化输出，支持：
  - 结果回看
  - 断点续传
  - 结果下载
"""
from sqlalchemy import Column, String, Integer, Float, Text, ForeignKey, Index
from app.models.base import OwnedModel


class AgentResult(OwnedModel):
    """Agent执行结果"""
    __tablename__ = "agent_result"

    session_id = Column(
        Integer, ForeignKey("session.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="会话ID"
    )
    agent = Column(
        String(50), nullable=False, index=True,
        comment="Agent名称: Requirement/APIExtraction/RAG/CaseGenerate/Review"
    )
    result_json = Column(
        Text, nullable=True,
        comment="结果数据(JSON)"
    )
    cost = Column(
        Float, nullable=True,
        comment="Token消耗"
    )
    duration = Column(
        Float, nullable=True,
        comment="耗时(秒)"
    )
    status = Column(
        String(20), nullable=False, default="success",
        comment="状态: success/error"
    )
    error_message = Column(
        Text, nullable=True,
        comment="错误信息"
    )


Index('idx_agent_result_session_agent', AgentResult.session_id, AgentResult.agent)
