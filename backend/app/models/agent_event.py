"""
AgentEvent 模型 - AI 执行过程全量事件记录

记录所有关键节点：
  - 开始 / 结束
  - Prompt 内容
  - 模型名称
  - Token 消耗
  - 耗时
  - 错误
  - 重试
  - 最终结果

前端查看 AI 过程全部来自此表。
"""
from sqlalchemy import Column, String, Integer, Float, Text, Index, Boolean
from app.models.base import OwnedModel


class AgentEvent(OwnedModel):
    """Agent 执行事件 - 每一个关键节点都记录一条"""
    __tablename__ = "agent_event"

    # ===== 任务关联 =====
    task_id = Column(
        String(64), nullable=False, index=True,
        comment="任务ID"
    )
    session_key = Column(
        String(128), nullable=False, index=True,
        comment="会话标识（多用户隔离）"
    )

    # ===== Agent 信息 =====
    agent_type = Column(
        String(80), nullable=False, index=True,
        comment="Agent 类型（注册名）"
    )
    agent_name = Column(
        String(80), nullable=False,
        comment="Agent 显示名称"
    )

    # ===== 事件类型 =====
    event_type = Column(
        String(30), nullable=False, index=True,
        comment="事件类型: start/end/prompt/model/token/error/retry/result/progress"
    )
    step = Column(
        String(50), nullable=False, default="",
        comment="流程步骤名称"
    )

    # ===== 状态 =====
    status = Column(
        String(20), nullable=False, default="info",
        comment="状态: info/success/warning/error"
    )

    # ===== LLM 详细信息 =====
    model_name = Column(
        String(100), nullable=True,
        comment="使用的模型名称"
    )
    prompt = Column(
        Text, nullable=True,
        comment="System Prompt 摘要"
    )
    user_prompt = Column(
        Text, nullable=True,
        comment="User Prompt 摘要"
    )
    prompt_tokens = Column(
        Integer, nullable=True,
        comment="输入 Token 数"
    )
    completion_tokens = Column(
        Integer, nullable=True,
        comment="输出 Token 数"
    )
    total_tokens = Column(
        Integer, nullable=True,
        comment="总 Token 数"
    )

    # ===== 耗时 =====
    duration = Column(
        Float, nullable=True,
        comment="耗时(秒)"
    )

    # ===== 数据 =====
    input_json = Column(
        Text, nullable=True,
        comment="输入数据(JSON)"
    )
    output_json = Column(
        Text, nullable=True,
        comment="输出结果(JSON)"
    )
    message = Column(
        Text, nullable=True,
        comment="事件消息文本"
    )
    error_message = Column(
        Text, nullable=True,
        comment="错误信息"
    )
    error_traceback = Column(
        Text, nullable=True,
        comment="错误堆栈"
    )

    # ===== 重试 =====
    retry_count = Column(
        Integer, nullable=True, default=0,
        comment="重试次数"
    )
    is_retry = Column(
        Boolean, nullable=False, default=False,
        comment="是否为重试事件"
    )

    # ===== 消息类型标记 =====
    message_type = Column(
        String(50), nullable=True,
        comment="触发此事件的消息类型"
    )

    # ===== 是否最终结果 =====
    is_final = Column(
        Boolean, nullable=False, default=False,
        comment="是否为最终结果"
    )


# 复合索引
Index('idx_agent_event_task_type', AgentEvent.task_id, AgentEvent.event_type)
Index('idx_agent_event_session_type', AgentEvent.session_key, AgentEvent.event_type)
Index('idx_agent_event_task_step', AgentEvent.task_id, AgentEvent.step)
