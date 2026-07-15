"""
ListMemory - 内存列表 Memory
适合短会话和开发环境，消息存储在内存中。
"""
from typing import Any, Dict, List
from collections import deque

from app.agent.memory.base import BaseMemory
from app.agent.core.message import AgentMessage


class ListMemory(BaseMemory):
    """内存列表 Memory 实现"""

    def __init__(self, session_id: str, max_size: int = 100):
        super().__init__(session_id, max_size)
        self._messages: deque = deque(maxlen=max_size)

    def add(self, message: AgentMessage) -> None:
        self._messages.append(message)

    def get_all(self) -> List[AgentMessage]:
        return list(self._messages)

    def get_recent(self, limit: int = 10) -> List[AgentMessage]:
        messages = list(self._messages)
        return messages[-limit:] if limit < len(messages) else messages

    def search(self, query: str, limit: int = 5) -> List[AgentMessage]:
        query_lower = query.lower()
        results = []
        for msg in reversed(self._messages):
            payload_str = str(msg.payload).lower()
            if query_lower in payload_str:
                results.append(msg)
                if len(results) >= limit:
                    break
        return results

    def clear(self) -> None:
        self._messages.clear()

    def count(self) -> int:
        return len(self._messages)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "type": "list",
            "count": self.count(),
            "messages": [m.to_dict() for m in self.get_recent(20)],
        }
