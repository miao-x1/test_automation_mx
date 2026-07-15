"""
DBMemory - 数据库持久化 Memory（Cache Aside Pattern）

架构：
  读取流程（Cache Aside）：
    1. 查询内存缓存
    2. 缓存命中 → 返回
    3. 缓存未命中 → 查询 MySQL
    4. 查询成功 → 写入缓存
    5. 返回数据

  写入流程：
    1. 写入内存缓存
    2. 写入 MySQL

适合长会话、审计和分布式部署场景。
"""
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.agent.memory.base import BaseMemory
from app.agent.core.message import AgentMessage
from app.agent.core.types import MessageType, MessageStatus
from app.agent.core.exceptions import MemoryError
from app.core.logger import log


class DBMemory(BaseMemory):
    """
    数据库 Memory 实现（Cache Aside Pattern）。

    使用 SessionEvent 表持久化消息，
    支持 Agent 间上下文跨进程传递和审计。

    缓存策略：
      - 首次读取时从 MySQL 加载到内存缓存
      - 后续读取直接从缓存返回
      - 写入时同时更新缓存和 MySQL
      - 支持 invalidate() 手动刷新缓存
    """

    def __init__(self, session_id: str, max_size: int = 500,
                 db_session_factory=None):
        super().__init__(session_id, max_size)
        self._db_session_factory = db_session_factory
        self._cache: List[AgentMessage] = []
        self._cache_loaded: bool = False  # 标记缓存是否已从DB加载
        self._cache_loaded_at: float = 0  # 缓存加载时间戳
        self._cache_ttl: float = 30.0  # 缓存TTL（秒），空缓存30秒后自动失效重查

    def _get_db(self):
        """获取数据库会话（保留用于向后兼容）

        新代码应使用 ContextRouter（读）和 StorageRouter（写）。
        """
        if self._db_session_factory:
            return self._db_session_factory()
        return None

    # ------------------------------------------------------------------
    # Cache Aside: 从数据库加载到缓存
    # ------------------------------------------------------------------

    def _load_from_db(self) -> List[AgentMessage]:
        """从 MySQL 加载历史消息到缓存（通过 ContextRouter）

        Returns:
            从数据库加载的消息列表
        """
        from app.services.context_router import get_context_router, ContextType

        db_start = time.time()
        messages: List[AgentMessage] = []

        try:
            # session_id 必须是数字才能查询数据库
            if not self.session_id or not self.session_id.isdigit():
                log.debug(
                    f"DBMemory | 跳过DB加载 | session_id={self.session_id} "
                    f"非数字ID，仅使用内存缓存"
                )
                return messages

            sid = int(self.session_id)
            router = get_context_router()
            result = router.query(
                "",
                ContextType.SESSION_EVENT,
                top_k=self.max_size,
                filters={"session_id": sid},
            )
            rows = result.get("results", [])

            # ContextRouter 返回按 id desc 排序，需要反转为 asc
            rows = list(reversed(rows))

            for row in rows:
                msg = self._deserialize_event(row)
                if msg:
                    messages.append(msg)

            db_elapsed = int((time.time() - db_start) * 1000)
            log.info(
                f"DBMemory | DB查询完成 | session_id={self.session_id} | "
                f"加载 {len(messages)} 条消息 | 耗时={db_elapsed}ms"
            )

        except Exception as e:
            db_elapsed = int((time.time() - db_start) * 1000)
            log.warning(
                f"DBMemory | DB查询失败 | session_id={self.session_id} | "
                f"耗时={db_elapsed}ms | error={e}"
            )

        return messages

    def _deserialize_event(self, row) -> Optional[AgentMessage]:
        """将 SessionEvent 行（dict 或 ORM 对象）反序列化为 AgentMessage"""
        try:
            # 兼容 dict（来自 ContextRouter）和 ORM 对象
            if isinstance(row, dict):
                payload_str = row.get("payload") or "{}"
                row_id = row.get("id")
            else:
                payload_str = getattr(row, "payload", None) or "{}"
                row_id = getattr(row, "id", None)

            data = json.loads(payload_str)

            # 兼容：如果 payload 本身就是 AgentMessage 的序列化格式
            if "message_id" in data:
                # 解析 message_type 枚举
                msg_type_str = data.get("message_type", "request")
                try:
                    msg_type = MessageType(msg_type_str)
                except ValueError:
                    msg_type = MessageType.REQUEST

                # 解析 status 枚举
                status_str = data.get("status", "pending")
                try:
                    status = MessageStatus(status_str)
                except ValueError:
                    status = MessageStatus.PENDING

                # 解析时间戳
                timestamp_str = data.get("timestamp", "")
                try:
                    if timestamp_str:
                        timestamp = datetime.fromisoformat(timestamp_str)
                    else:
                        timestamp = datetime.now(timezone.utc)
                except Exception:
                    timestamp = datetime.now(timezone.utc)

                return AgentMessage(
                    message_id=data.get("message_id", str(row_id)),
                    session_id=data.get("session_id", self.session_id),
                    task_id=data.get("task_id", ""),
                    message_type=msg_type,
                    sender=data.get("sender", "unknown"),
                    receiver=data.get("receiver", "*"),
                    payload=data.get("payload", {}),
                    timestamp=timestamp,
                    status=status,
                    parent_message_id=data.get("parent_message_id"),
                    metadata=data.get("metadata", {}),
                )
            else:
                # 兼容旧格式：payload 直接是消息内容
                return AgentMessage(
                    session_id=self.session_id,
                    sender="system",
                    message_type=MessageType.EVENT,
                    payload=data,
                )
        except Exception as e:
            log.warning(f"DBMemory | 反序列化失败 | event_id={row_id if isinstance(row, dict) else getattr(row, 'id', None)} | error={e}")
            return None

    def _ensure_cache_loaded(self) -> None:
        """确保缓存已从数据库加载（Cache Aside 核心逻辑）

        如果缓存尚未从DB加载过，执行加载。
        加载后标记 _cache_loaded=True，避免重复查询。

        修复：空缓存使用 TTL 机制，30秒后自动失效重查 DB，
        避免首次查询为空后永久跳过 DB 的问题。
        """
        if self._cache_loaded:
            # 非空缓存 → 永久有效（写入时自动更新）
            if self._cache:
                return
            # 空缓存 → 检查 TTL 是否过期
            elapsed = time.time() - self._cache_loaded_at
            if elapsed < self._cache_ttl:
                return
            # TTL 过期 → 重新查询 DB
            log.info(
                f"DBMemory | 空缓存TTL过期，重新查询DB | "
                f"session_id={self.session_id} | elapsed={elapsed:.1f}s"
            )
            self._cache_loaded = False

        cache_start = time.time()
        db_messages = self._load_from_db()

        if db_messages:
            self._cache = db_messages[-self.max_size:]
            cache_elapsed = int((time.time() - cache_start) * 1000)
            log.info(
                f"DBMemory | 缓存未命中 → DB加载完成 | session_id={self.session_id} | "
                f"写入缓存 {len(self._cache)} 条 | 总耗时={cache_elapsed}ms"
            )
        else:
            cache_elapsed = int((time.time() - cache_start) * 1000)
            log.info(
                f"DBMemory | 缓存未命中 → DB无数据 | session_id={self.session_id} | "
                f"总耗时={cache_elapsed}ms | TTL={self._cache_ttl}s后重查"
            )

        self._cache_loaded = True
        self._cache_loaded_at = time.time()

    # ------------------------------------------------------------------
    # Cache Aside: 写入
    # ------------------------------------------------------------------

    def add(self, message: AgentMessage) -> None:
        # 1. 写入内存缓存
        self._cache.append(message)
        if len(self._cache) > self.max_size:
            self._cache = self._cache[-self.max_size:]
        self._cache_loaded = True  # 标记缓存已加载

        # 2. 写入数据库（通过 StorageRouter）
        try:
            from app.services.context_router.storage_router import get_storage_router

            sid = int(self.session_id) if self.session_id.isdigit() else None
            if sid:
                storage = get_storage_router()
                storage.mysql_save("SessionEvent", {
                    "session_id": sid,
                    "event_type": message.message_type.value,
                    "payload": json.dumps(message.to_dict(), ensure_ascii=False, default=str),
                    "step_index": 0,
                })
            else:
                # session_id 非数字时仅存内存
                pass
        except Exception as e:
            log.warning(f"DBMemory add failed, fallback to cache only: {e}")

    # ------------------------------------------------------------------
    # Cache Aside: 读取
    # ------------------------------------------------------------------

    def get_all(self) -> List[AgentMessage]:
        """获取全部消息（Cache Aside）

        1. 查询内存缓存
        2. 缓存命中 → 返回
        3. 缓存未命中 → 查询 MySQL
        4. 查询成功 → 写入缓存
        5. 返回数据
        """
        if self._cache_loaded:
            log.debug(
                f"DBMemory | 缓存命中 | session_id={self.session_id} | "
                f"count={len(self._cache)}"
            )
            return list(self._cache)

        # 缓存未命中
        log.info(
            f"DBMemory | 缓存未命中 | session_id={self.session_id} | "
            f"从DB加载..."
        )
        self._ensure_cache_loaded()
        return list(self._cache)

    def get_recent(self, limit: int = 10) -> List[AgentMessage]:
        """获取最近 N 条消息（Cache Aside）"""
        messages = self.get_all()
        if limit < len(messages):
            result = messages[-limit:]
        else:
            result = list(messages)

        log.debug(
            f"DBMemory | get_recent | session_id={self.session_id} | "
            f"requested={limit} | returned={len(result)}"
        )
        return result

    def search(self, query: str, limit: int = 5) -> List[AgentMessage]:
        """搜索消息（Cache Aside - 先加载缓存再搜索）"""
        messages = self.get_all()
        query_lower = query.lower()
        results = []
        for msg in reversed(messages):
            payload_str = str(msg.payload).lower()
            if query_lower in payload_str:
                results.append(msg)
                if len(results) >= limit:
                    break
        return results

    # ------------------------------------------------------------------
    # 缓存管理
    # ------------------------------------------------------------------

    def invalidate(self) -> None:
        """手动失效缓存，下次读取时重新从 DB 加载

        适用场景：
          - 数据库新增了外部数据，需要刷新缓存
          - 手动触发缓存重建
        """
        log.info(
            f"DBMemory | 缓存失效 | session_id={self.session_id} | "
            f"清空 {len(self._cache)} 条缓存，下次读取从DB加载"
        )
        self._cache = []
        self._cache_loaded = False
        self._cache_loaded_at = 0

    def refresh(self) -> int:
        """立即从 DB 重新加载缓存

        Returns:
            加载的消息数量
        """
        self._cache = []
        self._cache_loaded = False
        self._ensure_cache_loaded()
        return len(self._cache)

    def clear(self) -> None:
        """清空缓存（仅内存，不删DB数据）"""
        self._cache.clear()
        self._cache_loaded = False

    def count(self) -> int:
        """获取消息数量"""
        if not self._cache_loaded:
            self._ensure_cache_loaded()
        return len(self._cache)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "type": "database",
            "count": self.count(),
            "cache_loaded": self._cache_loaded,
            "messages": [m.to_dict() for m in self.get_recent(20)],
        }
