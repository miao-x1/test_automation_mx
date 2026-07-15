"""
AgentMessage - 统一消息对象
所有 Agent 之间的通信统一采用 AgentMessage，禁止直接函数调用。
消息必须可以 JSON 序列化。
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from app.agent.core.types import MessageType, MessageStatus


class AgentMessage(BaseModel):
    """
    统一 Agent 消息对象。

    所有 Agent 之间的通信必须使用此对象，
    确保消息可序列化、可追踪、可审计。
    """

    # ---- 消息标识 ----
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="消息唯一ID")

    # ---- 会话与任务 ----
    session_id: str = Field(..., description="Session ID，用于隔离")
    task_id: str = Field(default="", description="Task ID，用于追踪")

    # ---- 消息路由 ----
    message_type: MessageType = Field(default=MessageType.REQUEST, description="消息类型")
    sender: str = Field(..., description="发送者Agent名称")
    receiver: str = Field(default="*", description="接收者Agent名称，*表示广播")

    # ---- 消息内容 ----
    payload: Dict[str, Any] = Field(default_factory=dict, description="消息负载，可序列化字典")

    # ---- 时间与状态 ----
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="时间戳")
    status: MessageStatus = Field(default=MessageStatus.PENDING, description="消息状态")

    # ---- 扩展 ----
    parent_message_id: Optional[str] = Field(default=None, description="父消息ID，用于链式追踪")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="扩展元数据")

    model_config = {"arbitrary_types_allowed": True}

    def to_dict(self) -> dict:
        """序列化为普通字典（JSON 兼容）"""
        return {
            "message_id": self.message_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "message_type": self.message_type.value,
            "sender": self.sender,
            "receiver": self.receiver,
            "payload": self.payload,
            "timestamp": self.timestamp.isoformat(),
            "status": self.status.value,
            "parent_message_id": self.parent_message_id,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """序列化为JSON字符串"""
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

    @classmethod
    def create_request(cls, session_id: str, sender: str, receiver: str,
                       payload: Optional[Dict[str, Any]] = None,
                       task_id: str = "", **kwargs) -> "AgentMessage":
        """快捷创建请求消息"""
        return cls(
            session_id=session_id,
            task_id=task_id,
            message_type=MessageType.REQUEST,
            sender=sender,
            receiver=receiver,
            payload=payload or {},
            **kwargs,
        )

    @classmethod
    def create_response(cls, request: "AgentMessage", payload: Dict[str, Any],
                        status: MessageStatus = MessageStatus.COMPLETED) -> "AgentMessage":
        """快捷创建响应消息"""
        return cls(
            session_id=request.session_id,
            task_id=request.task_id,
            message_type=MessageType.RESPONSE,
            sender=request.receiver,
            receiver=request.sender,
            payload=payload,
            status=status,
            parent_message_id=request.message_id,
        )

    @classmethod
    def create_progress(cls, session_id: str, sender: str, payload: Dict[str, Any],
                        task_id: str = "") -> "AgentMessage":
        """快捷创建进度消息"""
        return cls(
            session_id=session_id,
            task_id=task_id,
            message_type=MessageType.PROGRESS,
            sender=sender,
            receiver="*",
            payload=payload,
        )

    @classmethod
    def create_error(cls, session_id: str, sender: str, error_message: str,
                     task_id: str = "", details: Optional[dict] = None) -> "AgentMessage":
        """快捷创建错误消息"""
        return cls(
            session_id=session_id,
            task_id=task_id,
            message_type=MessageType.ERROR,
            sender=sender,
            receiver="*",
            payload={"error": error_message, "details": details or {}},
            status=MessageStatus.FAILED,
        )
