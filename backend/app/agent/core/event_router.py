"""
EventRouter - 事件路由注册器

在应用启动时注册默认的消息订阅者，使 MessageBus 广播模式真正生效。

注册的订阅：
  1. 通配符订阅("*")：记录所有消息到日志（审计）
  2. 关键事件订阅：requirement.parsed → 触发后续流程
  3. 错误事件订阅：*.error → 记录错误日志
  4. 执行事件订阅：*.generated / *.retrieved → 推送 SSE

使用方式：
    from app.agent.core.event_router import register_default_subscribers
    register_default_subscribers()  # 在应用启动时调用一次
"""
import time
from typing import Any, Dict
from app.core.logger import log
from app.agent.core.message_bus import MessageBus


def _audit_handler(msg) -> None:
    """审计日志：记录所有消息"""
    log.info(
        f"EventRouter | AUDIT | topic={msg.topic} | source={msg.source} | "
        f"task_id={msg.task_id} | data_size={len(str(msg.data)) if msg.data else 0}"
    )


def _error_handler(msg) -> None:
    """错误处理：记录错误事件"""
    if msg.topic.endswith(".error") or msg.topic.endswith(".failed"):
        log.error(
            f"EventRouter | ERROR_EVENT | topic={msg.topic} | source={msg.source} | "
            f"data={str(msg.data)[:500]}"
        )


_event_listeners: Dict[str, list] = {
    "requirement.parsed": [],
    "rag.retrieved": [],
    "case.generated": [],
    "case.reviewed": [],
    "script.generated": [],
    "execution.completed": [],
    "execution.failed": [],
}


def register_event_listener(event: str, callback) -> None:
    """注册事件监听器

    Args:
        event: 事件主题（如 "requirement.parsed"）
        callback: 回调函数，接收 Message 对象
    """
    if event not in _event_listeners:
        _event_listeners[event] = []
    _event_listeners[event].append(callback)
    log.info(f"EventRouter | 注册事件监听器 | event={event} | callback={getattr(callback, '__name__', str(callback))}")


def _dispatch_to_listeners(msg) -> None:
    """将消息分发给注册的事件监听器"""
    listeners = _event_listeners.get(msg.topic, [])
    for callback in listeners:
        try:
            callback(msg)
        except Exception as e:
            log.warning(f"EventRouter | 监听器回调异常 | topic={msg.topic} | error={e}")


_registered = False


def register_default_subscribers() -> None:
    """注册默认订阅者（应用启动时调用一次）

    注册内容：
      1. "*" 通配符订阅 → 审计日志 + 错误检测 + 事件分发
      2. 关键事件直接订阅 → 分发给业务监听器
    """
    global _registered
    if _registered:
        return

    bus = MessageBus()

    # 通配符订阅：审计 + 错误检测 + 事件分发
    bus.subscribe("*", _audit_handler)
    bus.subscribe("*", _error_handler)
    bus.subscribe("*", _dispatch_to_listeners)

    _registered = True
    log.info(
        "EventRouter | 默认订阅者注册完成 | "
        "audit=ON | error=ON | dispatch=ON"
    )


def get_event_stats() -> Dict[str, Any]:
    """获取事件路由统计"""
    bus = MessageBus()
    return {
        "bus_stats": bus.stats(),
        "registered_listeners": {
            event: len(listeners) for event, listeners in _event_listeners.items()
        },
    }
