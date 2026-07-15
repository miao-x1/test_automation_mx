"""
MessageBus - Agent消息总线

所有Agent通过消息通信，不直接互相调用。

支持：
- publish(topic, message): 发布消息到指定主题
- subscribe(topic, handler): 订阅指定主题的消息
- unsubscribe(topic, handler): 取消订阅
- 自动转发到 Runtime MessageBus（DB持久化 + SSE推送）

消息格式：
{
    "topic": "requirement.parsed",
    "source": "requirement_agent",
    "timestamp": 1718000000.0,
    "data": { ... }
}

主题命名规范：
    {agent}.{event}
    例如：requirement.parsed, rag.retrieved, case.generated
"""
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional
from app.core.logger import log


class Message:
    """消息对象"""

    def __init__(self, topic: str, source: str, data: Any = None,
                 task_id: Optional[int] = None, agent_type: Optional[str] = None,
                 source_type: Optional[str] = None, payload: Optional[Dict[str, Any]] = None,
                 context: Optional[Dict[str, Any]] = None, status: str = "pending"):
        self.message_id = str(uuid.uuid4())
        self.topic = topic
        self.source = source
        self.timestamp = time.time()
        self.data = data
        self.task_id = task_id
        self.agent_type = agent_type
        self.source_type = source_type
        self.payload = payload
        self.context = context
        self.status = status

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "topic": self.topic,
            "source": self.source,
            "timestamp": self.timestamp,
            "data": self.data,
            "task_id": self.task_id,
            "agent_type": self.agent_type,
            "source_type": self.source_type,
            "payload": self.payload,
            "context": self.context,
            "status": self.status,
        }

    def __repr__(self):
        return f"Message(message_id={self.message_id}, topic={self.topic}, source={self.source}, task_id={self.task_id})"


class MessageBus:
    """
    Agent消息总线（单例）

    线程安全的发布/订阅模式，所有Agent通过消息通信。
    发布的消息自动转发到 Runtime MessageBus 进行 DB 持久化。
    """

    _instance: Optional["MessageBus"] = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._subscribers: Dict[str, List[Callable]] = {}
                cls._instance._history: List[Message] = []
                cls._instance._max_history = 200
                cls._instance._runtime_bus = None  # 延迟绑定 Runtime MessageBus
                cls._instance._runtime_bound = False
            return cls._instance

    def _ensure_runtime_bridge(self) -> None:
        """延迟绑定 Runtime MessageBus（用于 DB 持久化）"""
        if self._runtime_bound:
            return
        try:
            from app.runtime.message_bus import get_message_bus
            self._runtime_bus = get_message_bus()
            self._runtime_bound = True
            log.info("MessageBus | 已绑定 Runtime MessageBus（DB持久化 + SSE推送）")
        except Exception:
            # Runtime 不可用时静默降级
            pass

    def _persist_to_db(self, msg: Message) -> None:
        """将消息持久化到数据库（通过 Runtime MessageBus）"""
        try:
            self._ensure_runtime_bridge()
            if self._runtime_bus is None:
                return
            self._runtime_bus._persist_message(
                message_id=msg.message_id,
                source_agent=msg.source,
                target_agent="*",
                session_id=str(msg.task_id or ""),
                task_id=str(msg.task_id or ""),
                message_type=msg.topic,
                payload={"data": str(msg.data)[:4000]} if msg.data else {},
                status="delivered",
                timestamp=msg.timestamp,
            )
        except Exception:
            pass

    def publish(self, topic: str, source: str, data: Any = None,
                task_id: int = None, agent_type: str = None, source_type: str = None,
                payload: Dict[str, Any] = None, context: Dict[str, Any] = None,
                status: str = "pending") -> None:
        """
        发布消息

        Args:
            topic: 消息主题，格式 {agent}.{event}
            source: 发布者名称
            data: 消息数据
            task_id: 关联的case_task ID
            agent_type: Agent类型 (parser/generator/review/mindmap等)
            source_type: 来源类型 (pdf/doc/swagger/url/text等)
            payload: 结构化数据载荷
            context: 执行上下文
            status: 消息状态 (pending/processing/completed/failed)
        """
        msg = Message(topic=topic, source=source, data=data,
                      task_id=task_id, agent_type=agent_type, source_type=source_type,
                      payload=payload, context=context, status=status)

        # 记录历史
        self._history.append(msg)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        # 持久化到数据库（通过 Runtime MessageBus 桥接）
        self._persist_to_db(msg)

        # 通知订阅者
        handlers = self._subscribers.get(topic, [])
        wildcard_handlers = self._subscribers.get("*", [])

        for handler in handlers + wildcard_handlers:
            try:
                handler(msg)
            except Exception as e:
                log.warning(f"MessageBus | 消息处理异常 | topic={topic}, handler={getattr(handler, '__name__', str(handler))}, error={e}")

        log.debug(f"MessageBus | publish | topic={topic}, source={source}, subscribers={len(handlers)}")

    def subscribe(self, topic: str, handler: Callable[[Message], None]) -> None:
        """
        订阅消息

        Args:
            topic: 消息主题，支持通配符 "*" 订阅所有消息
            handler: 消息处理函数，接收Message对象
        """
        if topic not in self._subscribers:
            self._subscribers[topic] = []
        if handler not in self._subscribers[topic]:
            self._subscribers[topic].append(handler)
            log.info(f"MessageBus | subscribe | topic={topic}, handler={getattr(handler, '__name__', str(handler))}")

    def unsubscribe(self, topic: str, handler: Callable[[Message], None]) -> None:
        """
        取消订阅

        Args:
            topic: 消息主题
            handler: 要移除的处理函数
        """
        if topic in self._subscribers:
            self._subscribers[topic] = [
                h for h in self._subscribers[topic] if h != handler
            ]

    def get_history(self, topic: Optional[str] = None, limit: int = 50) -> List[Message]:
        """
        获取消息历史

        Args:
            topic: 可选，按主题过滤
            limit: 返回最大数量

        Returns:
            消息列表
        """
        messages = self._history
        if topic:
            messages = [m for m in messages if m.topic == topic]
        return messages[-limit:]

    def clear(self) -> None:
        """清空历史和订阅（主要用于测试）"""
        self._subscribers.clear()
        self._history.clear()

    def stats(self) -> Dict[str, Any]:
        """获取消息总线统计信息"""
        return {
            "topics": list(self._subscribers.keys()),
            "total_subscribers": sum(len(v) for v in self._subscribers.values()),
            "history_count": len(self._history),
            "runtime_bound": self._runtime_bound,
        }
