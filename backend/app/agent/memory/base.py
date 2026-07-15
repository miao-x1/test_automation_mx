"""
BaseMemory - Memory 抽象基类
定义 Memory 的统一接口，所有 Memory 实现必须继承此类。
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from app.agent.core.message import AgentMessage


class BaseMemory(ABC):
    """
    Memory 抽象基类。

    每个 Session 拥有独立 Memory，
    Agent 在执行过程中可以读写 Memory，
    实现 Agent 间的上下文传递。
    """

    def __init__(self, session_id: str, max_size: int = 100):
        self.session_id = session_id
        self.max_size = max_size

    @abstractmethod
    def add(self, message: AgentMessage) -> None:
        """添加消息到 Memory"""
        pass

    @abstractmethod
    def get_all(self) -> List[AgentMessage]:
        """获取全部消息"""
        pass

    @abstractmethod
    def get_recent(self, limit: int = 10) -> List[AgentMessage]:
        """获取最近 N 条消息"""
        pass

    @abstractmethod
    def search(self, query: str, limit: int = 5) -> List[AgentMessage]:
        """搜索 Memory（简单关键词匹配或向量检索）"""
        pass

    @abstractmethod
    def clear(self) -> None:
        """清空 Memory"""
        pass

    @abstractmethod
    def count(self) -> int:
        """获取消息数量"""
        pass

    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """序列化 Memory 内容"""
        pass

    def get_by_sender(self, sender: str, limit: int = 10) -> List[AgentMessage]:
        """按发送者过滤"""
        return [m for m in self.get_all() if m.sender == sender][-limit:]

    def get_by_type(self, message_type: str, limit: int = 10) -> List[AgentMessage]:
        """按消息类型过滤"""
        return [m for m in self.get_all() if m.message_type.value == message_type][-limit:]

    def to_prompt_context(self, limit: int = 10) -> str:
        """将 Memory 转为 Prompt 上下文文本"""
        messages = self.get_recent(limit)
        if not messages:
            return ""
        lines = []
        for msg in messages:
            sender = msg.sender
            payload_str = str(msg.payload)[:200]
            lines.append(f"[{sender}]: {payload_str}")
        return "\n".join(lines)
