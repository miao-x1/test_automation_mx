"""
AgentExecutionLog 模型 - Agent 执行记录表

记录每个 Agent 执行过程的完整信息，用于：
1. 调试 - 追踪 Agent 执行链路
2. 前端展示 - TaskDetail 页面展示 Agent 执行过程
3. 问题追踪 - 定位失败原因

与 AgentLog 的区别：
  AgentLog: 简化日志（info/success/warning/error），用于快速浏览
  AgentExecutionLog: 完整执行记录（含 input/output/duration），用于详细分析
"""
import json
from sqlalchemy import Column, String, Integer, Text, Float, Index, DateTime
from sqlalchemy.sql import func
from app.models.base import OwnedModel


class AgentExecutionLog(OwnedModel):
    """Agent 执行记录

    每个 Agent 执行步骤产生一条记录，
    包含完整的输入、输出、状态、耗时和错误信息。
    """

    __tablename__ = "agent_execution_log"

    # 关联信息
    session_id = Column(
        String(128), nullable=False, index=True,
        comment="会话ID（用于多用户隔离）"
    )
    task_id = Column(
        String(64), nullable=False, index=True,
        comment="任务ID"
    )

    # Agent 信息
    agent_name = Column(
        String(64), nullable=False, index=True,
        comment="Agent名称"
    )
    step = Column(
        String(128), nullable=True,
        comment="步骤名称（如 需求解析/RAG检索/用例生成）"
    )

    # 执行数据
    input_data = Column(
        Text, nullable=True,
        comment="输入数据(JSON)"
    )
    output_data = Column(
        Text, nullable=True,
        comment="输出数据(JSON)"
    )

    # 执行状态
    status = Column(
        String(20), nullable=False, default="running", index=True,
        comment="状态: running/success/error/timeout/skipped"
    )

    # 时间信息
    start_time = Column(
        DateTime(timezone=True), server_default=func.now(),
        comment="开始时间"
    )
    end_time = Column(
        DateTime(timezone=True), nullable=True,
        comment="结束时间"
    )
    duration = Column(
        Float, nullable=True, default=0.0,
        comment="执行耗时（秒）"
    )

    # 错误信息
    error = Column(
        Text, nullable=True,
        comment="错误信息"
    )

    # 扩展数据
    model_name = Column(
        String(64), nullable=True,
        comment="使用的模型名称"
    )
    tokens_used = Column(
        Integer, nullable=True, default=0,
        comment="Token消耗量"
    )
    extra_json = Column(
        Text, nullable=True,
        comment="额外数据(JSON)"
    )

    def get_input(self) -> dict:
        """获取输入数据"""
        if self.input_data:
            try:
                return json.loads(self.input_data)
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}

    def get_output(self) -> dict:
        """获取输出数据"""
        if self.output_data:
            try:
                return json.loads(self.output_data)
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "agent_name": self.agent_name,
            "step": self.step,
            "input_data": self.get_input(),
            "output_data": self.get_output(),
            "status": self.status,
            "start_time": str(self.start_time) if self.start_time else None,
            "end_time": str(self.end_time) if self.end_time else None,
            "duration": self.duration,
            "error": self.error,
            "model_name": self.model_name,
            "tokens_used": self.tokens_used,
        }


# 索引
Index("idx_exec_log_session", AgentExecutionLog.session_id)
Index("idx_exec_log_task", AgentExecutionLog.task_id)
Index("idx_exec_log_agent", AgentExecutionLog.agent_name)
Index("idx_exec_log_status", AgentExecutionLog.status)
Index("idx_exec_log_task_step", AgentExecutionLog.task_id, AgentExecutionLog.step)
