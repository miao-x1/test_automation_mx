"""
TaskState模型 - 任务编排状态追踪

记录每个经过 TaskOrchestrator 的任务的完整生命周期。

字段：
  task_id       - 任务ID（关联 Task 表）
  session_id    - 会话ID（关联 Session 表）
  flow_name     - TaskFlow 名称（如 image_test_flow）
  current_agent - 当前执行的 Agent 名称
  status        - 任务状态（pending/running/success/failed/cancelled）
  result        - 最终结果 JSON
  error_message - 错误信息
  step_index    - 当前步骤序号
  total_steps   - 总步骤数
  step_history  - 每步执行历史 JSON
"""
import json
import enum
from sqlalchemy import Column, String, Integer, Text, ForeignKey, Index
from app.models.base import BaseModel


class TaskStatus(str, enum.Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskState(BaseModel):
    """任务编排状态"""
    __tablename__ = "task_state"

    task_id = Column(
        Integer, ForeignKey("task.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="任务ID"
    )
    session_id = Column(
        Integer, ForeignKey("session.id", ondelete="CASCADE"),
        nullable=True, index=True, comment="会话ID"
    )
    flow_name = Column(
        String(100), nullable=False, index=True,
        comment="TaskFlow名称（如 image_test_flow, requirement_test_flow）"
    )
    current_agent = Column(
        String(100), nullable=True,
        comment="当前执行的Agent名称"
    )
    status = Column(
        String(20), nullable=False, default="pending", index=True,
        comment="任务状态: pending/running/success/failed/cancelled"
    )
    result = Column(
        Text, nullable=True,
        comment="最终结果JSON"
    )
    error_message = Column(
        Text, nullable=True,
        comment="错误信息"
    )
    step_index = Column(
        Integer, nullable=False, default=0,
        comment="当前步骤序号（从0开始）"
    )
    total_steps = Column(
        Integer, nullable=False, default=0,
        comment="总步骤数"
    )
    step_history = Column(
        Text, nullable=True,
        comment="每步执行历史JSON"
    )

    def get_step_history(self) -> list:
        """获取步骤历史"""
        if not self.step_history:
            return []
        try:
            return json.loads(self.step_history)
        except (json.JSONDecodeError, TypeError):
            return []

    def append_step(self, step_record: dict) -> None:
        """追加步骤记录"""
        history = self.get_step_history()
        history.append(step_record)
        self.step_history = json.dumps(history, ensure_ascii=False, default=str)

    def get_result(self) -> dict:
        """获取解析后的结果"""
        if not self.result:
            return {}
        try:
            return json.loads(self.result)
        except (json.JSONDecodeError, TypeError):
            return {}

    def set_result(self, data: dict) -> None:
        """设置结果"""
        self.result = json.dumps(data, ensure_ascii=False, default=str)

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "flow_name": self.flow_name,
            "current_agent": self.current_agent,
            "status": self.status,
            "result": self.get_result(),
            "error_message": self.error_message,
            "step_index": self.step_index,
            "total_steps": self.total_steps,
            "step_history": self.get_step_history(),
            "created_at": str(self.created_at),
            "updated_at": str(self.updated_at),
        }


Index('idx_task_state_task', TaskState.task_id)
Index('idx_task_state_status', TaskState.status)
Index('idx_task_state_flow', TaskState.flow_name)
