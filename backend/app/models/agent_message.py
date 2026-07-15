"""
AgentMessage 模型 - Agent消息日志表

记录所有Agent之间的消息通信，用于追踪执行过程。
每条消息记录发送方、接收方、消息类型、内容和状态。

关系：
    task_id → 关联任务
    session_key → 关联会话
"""
from sqlalchemy import Column, String, Text, Integer, Float, Boolean, Index
from app.models.base import BaseModel


class AgentMessage(BaseModel):
    """Agent消息日志

    记录Agent间的消息通信，包括：
    - 消息类型（TaskMessage/AgentRequest/AgentResponse等）
    - 发送方和接收方
    - 消息内容（JSON）
    - 处理状态和耗时

    用于前端展示Agent执行过程。
    """
    __tablename__ = "agent_message"

    # 关联信息
    task_id = Column(
        String(64), nullable=False, index=True,
        comment="任务ID"
    )
    session_key = Column(
        String(128), nullable=False, default="default", index=True,
        comment="会话标识"
    )

    # 消息信息
    message_type = Column(
        String(64), nullable=False, index=True,
        comment="消息类型: TaskMessage/AgentRequest/AgentResponse/FlowMessage等"
    )
    sender = Column(
        String(64), nullable=False,
        comment="发送方Agent名称"
    )
    receiver = Column(
        String(64), nullable=True,
        comment="接收方Agent名称（广播为空）"
    )
    action = Column(
        String(64), nullable=True,
        comment="操作名称: execute/retrieve/review/save等"
    )

    # 消息内容
    content = Column(
        Text, nullable=True,
        comment="消息内容(JSON)"
    )
    result = Column(
        Text, nullable=True,
        comment="处理结果(JSON)"
    )

    # 状态
    status = Column(
        String(20), nullable=False, default="pending",
        comment="状态: pending/processing/success/error/timeout"
    )
    error = Column(
        Text, nullable=True,
        comment="错误信息"
    )

    # 性能指标
    duration = Column(
        Float, nullable=True, default=0.0,
        comment="处理耗时（秒）"
    )
    tokens_used = Column(
        Integer, nullable=True, default=0,
        comment="Token消耗"
    )

    # 步骤
    step = Column(
        String(64), nullable=True, index=True,
        comment="流程步骤名: requirement/testpoint/generate/review/storage"
    )


# 索引
Index("idx_agent_msg_task", AgentMessage.task_id)
Index("idx_agent_msg_session", AgentMessage.session_key)
Index("idx_agent_msg_type", AgentMessage.message_type)
Index("idx_agent_msg_status", AgentMessage.status)
Index("idx_agent_msg_task_step", AgentMessage.task_id, AgentMessage.step)
