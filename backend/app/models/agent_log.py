"""
AgentLog 模型 - Agent 日志表

独立于 AgentEvent，用于记录 Agent 运行日志。
AgentEvent 记录全量事件（含 Prompt/Token/Model），
AgentLog 记录简化日志（用于 TaskDetail 页面展示）。

关系：
  AgentEvent (全量事件，含 LLM 详情)
    ↓ 摘要
  AgentLog (简化日志，用于前端展示)
"""
from sqlalchemy import Column, String, Integer, Text, Float, Index
from app.models.base import OwnedModel


class AgentLog(OwnedModel):
    """Agent 日志

    用于 TaskDetail 页面展示 Agent 执行日志。
    替代直接 SSE 打印，前端轮询数据库获取日志。
    """
    __tablename__ = "agent_log"

    # 关联信息
    task_id = Column(
        String(64), nullable=False, index=True,
        comment="任务ID"
    )
    session_key = Column(
        String(128), nullable=False, default="default", index=True,
        comment="会话标识"
    )

    # Agent 信息
    agent_name = Column(
        String(64), nullable=False, index=True,
        comment="Agent名称"
    )
    agent_type = Column(
        String(64), nullable=True,
        comment="Agent类型"
    )

    # 日志内容
    log_level = Column(
        String(20), nullable=False, default="info",
        comment="日志级别: debug/info/warning/error/critical"
    )
    step = Column(
        String(64), nullable=True, index=True,
        comment="步骤名"
    )
    message = Column(
        Text, nullable=False,
        comment="日志内容"
    )
    module = Column(
        String(128), nullable=True,
        comment="模块名"
    )

    # 执行信息
    status = Column(
        String(20), nullable=False, default="info",
        comment="状态: info/success/warning/error"
    )
    duration = Column(
        Float, nullable=True, default=0.0,
        comment="耗时（秒）"
    )

    # 额外数据
    extra_json = Column(
        Text, nullable=True,
        comment="额外数据(JSON)"
    )


# 索引
Index('idx_agent_log_task_step', AgentLog.task_id, AgentLog.step)
Index('idx_agent_log_session_agent', AgentLog.session_key, AgentLog.agent_name)
Index('idx_agent_log_level', AgentLog.log_level)
