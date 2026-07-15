"""
FlowResult 模型 - 业务流程每一步的执行结果

存储每个 Agent 步骤的输入输出，支持：
  - 结果回看
  - 断点续传
  - 流程审计
"""
from sqlalchemy import Column, String, Integer, Float, Text, Index
from app.models.base import OwnedModel


class FlowResult(OwnedModel):
    """业务流程步骤结果"""
    __tablename__ = "flow_result"

    task_id = Column(
        String(64), nullable=False, index=True,
        comment="任务ID"
    )
    session_key = Column(
        String(128), nullable=False, index=True,
        comment="会话标识（多用户隔离）"
    )
    step = Column(
        String(50), nullable=False, index=True,
        comment="流程步骤: requirement/page/case/review/script/export"
    )
    agent_name = Column(
        String(50), nullable=False, index=True,
        comment="Agent名称"
    )
    status = Column(
        String(20), nullable=False, default="success",
        comment="状态: success/error"
    )
    input_json = Column(
        Text, nullable=True,
        comment="输入数据(JSON)"
    )
    output_json = Column(
        Text, nullable=True,
        comment="输出结果(JSON)"
    )
    duration = Column(
        Float, nullable=True,
        comment="耗时(秒)"
    )
    error_message = Column(
        Text, nullable=True,
        comment="错误信息"
    )
    message_type = Column(
        String(50), nullable=True,
        comment="消息类型（用于事件溯源）"
    )


Index('idx_flow_result_task_step', FlowResult.task_id, FlowResult.step)
Index('idx_flow_result_session_step', FlowResult.session_key, FlowResult.step)
