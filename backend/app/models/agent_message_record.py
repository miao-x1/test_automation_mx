"""
AgentMessageRecord - Agent 消息持久化模型

所有通过 MessageBus 的消息都保存到此表，
支持审计、重放和分布式部署。

字段：
  message_id        - 消息唯一ID
  source_agent      - 发送方 Agent
  target_agent      - 接收方 Agent（*表示广播）
  session_id        - 会话ID
  task_id           - 任务ID
  message_type      - 消息类型（request/response/progress/error/event）
  payload           - 消息内容 JSON
  status            - 消息状态（pending/delivered/processed/failed）
  parent_message_id  - 父消息ID（用于链式追踪）
  timestamp         - 消息时间戳
  duration_ms       - 处理耗时（毫秒）
"""
import json
import enum
from sqlalchemy import Column, String, Integer, Text, ForeignKey, Index, Float
from sqlalchemy import Enum as SQLEnum
from app.models.base import BaseModel


class MessageRecordStatus(str, enum.Enum):
    """消息记录状态"""
    PENDING = "pending"
    DELIVERED = "delivered"
    PROCESSED = "processed"
    FAILED = "failed"


class AgentMessageRecord(BaseModel):
    """Agent 消息持久化记录"""
    __tablename__ = "agent_message_record"

    message_id = Column(
        String(64), nullable=False, unique=True, index=True,
        comment="消息唯一ID"
    )
    source_agent = Column(
        String(100), nullable=False, index=True,
        comment="发送方Agent名称"
    )
    target_agent = Column(
        String(100), nullable=False, default="*", index=True,
        comment="接收方Agent名称，*表示广播"
    )
    session_id = Column(
        String(64), nullable=True, index=True,
        comment="会话ID"
    )
    task_id = Column(
        String(64), nullable=True, index=True,
        comment="任务ID"
    )
    message_type = Column(
        String(20), nullable=False, default="request",
        comment="消息类型: request/response/progress/error/event"
    )
    payload = Column(
        Text, nullable=True,
        comment="消息内容JSON"
    )
    status = Column(
        String(20), nullable=False, default="pending", index=True,
        comment="消息状态: pending/delivered/processed/failed"
    )
    parent_message_id = Column(
        String(64), nullable=True,
        comment="父消息ID，用于链式追踪"
    )
    timestamp = Column(
        String(40), nullable=True,
        comment="消息时间戳ISO格式"
    )
    duration_ms = Column(
        Float, nullable=True, default=0,
        comment="处理耗时毫秒"
    )
    error_message = Column(
        Text, nullable=True,
        comment="错误信息"
    )

    def get_payload(self) -> dict:
        """获取解析后的 payload"""
        if not self.payload:
            return {}
        try:
            return json.loads(self.payload)
        except (json.JSONDecodeError, TypeError):
            return {}

    def set_payload(self, data: dict) -> None:
        """设置 payload"""
        self.payload = json.dumps(data, ensure_ascii=False, default=str)

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "message_id": self.message_id,
            "source_agent": self.source_agent,
            "target_agent": self.target_agent,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "message_type": self.message_type,
            "payload": self.get_payload(),
            "status": self.status,
            "parent_message_id": self.parent_message_id,
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
            "error_message": self.error_message,
            "created_at": str(self.created_at),
        }


Index('idx_agent_msg_source', AgentMessageRecord.source_agent)
Index('idx_agent_msg_target', AgentMessageRecord.target_agent)
Index('idx_agent_msg_session', AgentMessageRecord.session_id)
Index('idx_agent_msg_status', AgentMessageRecord.status)
Index('idx_agent_msg_task', AgentMessageRecord.task_id)
