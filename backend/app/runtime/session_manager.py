"""
SessionManager - 独立会话管理器

职责：
  1. 会话生命周期管理：创建 / 恢复 / 暂停 / 取消 / 继续
  2. 多用户隔离：每个用户拥有独立 Session
  3. Agent 状态追踪：记录每个 Session 内 Agent 的运行状态
  4. 消息历史：维护会话内所有消息记录
  5. 日志关联：会话与 AgentLog 关联

设计原则：
  - SessionManager 是无状态的协调器（状态存储在数据库）
  - 支持分布式部署（Session 可跨节点恢复）
  - 会话超时自动清理

与 RuntimeManager 的关系：
  - RuntimeManager 管理 CoreRuntime 的生命周期
  - SessionManager 管理业务会话的状态
  - SessionManager 被 RuntimeManager 调用
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SessionStatus(str, Enum):
    """会话状态"""
    CREATED = "created"           # 已创建
    RUNNING = "running"           # 运行中
    PAUSED = "paused"             # 已暂停
    COMPLETED = "completed"       # 已完成
    FAILED = "failed"             # 失败
    CANCELLED = "cancelled"       # 已取消
    EXPIRED = "expired"           # 已过期


@dataclass
class SessionState:
    """会话状态信息"""
    session_key: str                         # 会话标识（格式: user_{uid}_session_{sid}）
    session_id: str                          # 数据库 Session ID
    user_id: int = 0                         # 用户 ID
    status: SessionStatus = SessionStatus.CREATED
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    task_count: int = 0                      # 任务总数
    completed_tasks: int = 0                 # 已完成任务数
    failed_tasks: int = 0                   # 失败任务数
    agent_states: Dict[str, Dict] = field(default_factory=dict)  # Agent 状态
    message_count: int = 0                   # 消息总数
    last_error: str = ""                     # 最后一次错误
    metadata: Dict[str, Any] = field(default_factory=dict)        # 元数据

    def touch(self) -> None:
        """更新最后活跃时间"""
        self.last_active = time.time()

    def is_expired(self, timeout: int = 3600) -> bool:
        """检查是否超时"""
        return time.time() - self.last_active > timeout

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "session_key": self.session_key,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "task_count": self.task_count,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": self.failed_tasks,
            "agent_count": len(self.agent_states),
            "message_count": self.message_count,
            "last_error": self.last_error,
            "metadata": self.metadata,
        }


class SessionManager:
    """会话管理器

    管理所有活跃会话的生命周期。
    支持多用户隔离、会话恢复、暂停/继续。

    使用示例：
        mgr = get_session_manager()

        # 创建会话
        session = await mgr.create_session(user_id=1, session_id="abc123")

        # 获取会话
        session = mgr.get_session("user_1_session_abc123")

        # 暂停会话
        await mgr.pause_session("user_1_session_abc123")

        # 恢复会话
        await mgr.resume_session("user_1_session_abc123")

        # 关闭会话
        await mgr.close_session("user_1_session_abc123")
    """

    def __init__(self):
        self._sessions: Dict[str, SessionState] = {}
        self._lock = asyncio.Lock()
        self._session_timeout = 3600          # 默认超时 1 小时
        self._cleanup_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # 会话创建与销毁
    # ------------------------------------------------------------------

    @staticmethod
    def make_session_key(user_id: int, session_id: str) -> str:
        """生成会话标识"""
        return f"user_{user_id}_session_{session_id}"

    async def create_session(
        self,
        user_id: int,
        session_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SessionState:
        """创建新会话"""
        session_key = self.make_session_key(user_id, session_id)

        async with self._lock:
            if session_key in self._sessions:
                logger.warning(f"[SessionManager] 会话已存在: {session_key}，将覆盖")
                # 保留旧会话的任务计数
                old = self._sessions[session_key]
                logger.info(f"[SessionManager] 旧会话任务数: {old.task_count}")

            session = SessionState(
                session_key=session_key,
                session_id=session_id,
                user_id=user_id,
                status=SessionStatus.CREATED,
                metadata=metadata or {},
            )
            self._sessions[session_key] = session

        logger.info(f"[SessionManager] 创建会话: {session_key} (user={user_id})")

        # 启动清理任务
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        return session

    async def close_session(self, session_key: str) -> bool:
        """关闭会话"""
        async with self._lock:
            session = self._sessions.get(session_key)
            if session is None:
                return False

            session.status = SessionStatus.COMPLETED
            session.touch()

            # 保留会话信息一段时间（用于查询）
            # 实际删除由清理任务处理
            logger.info(f"[SessionManager] 关闭会话: {session_key}")
            return True

    # ------------------------------------------------------------------
    # 会话查询
    # ------------------------------------------------------------------

    def get_session(self, session_key: str) -> Optional[SessionState]:
        """获取会话状态"""
        session = self._sessions.get(session_key)
        if session:
            session.touch()
        return session

    def list_sessions(
        self,
        user_id: Optional[int] = None,
        status: Optional[SessionStatus] = None,
    ) -> List[Dict[str, Any]]:
        """列出会话"""
        sessions = list(self._sessions.values())
        if user_id is not None:
            sessions = [s for s in sessions if s.user_id == user_id]
        if status is not None:
            sessions = [s for s in sessions if s.status == status]
        sessions.sort(key=lambda s: s.last_active, reverse=True)
        return [s.to_dict() for s in sessions]

    # ------------------------------------------------------------------
    # 会话控制
    # ------------------------------------------------------------------

    async def pause_session(self, session_key: str) -> bool:
        """暂停会话"""
        async with self._lock:
            session = self._sessions.get(session_key)
            if session is None or session.status != SessionStatus.RUNNING:
                return False
            session.status = SessionStatus.PAUSED
            session.touch()
            logger.info(f"[SessionManager] 暂停会话: {session_key}")
            return True

    async def resume_session(self, session_key: str) -> bool:
        """恢复会话"""
        async with self._lock:
            session = self._sessions.get(session_key)
            if session is None or session.status != SessionStatus.PAUSED:
                return False
            session.status = SessionStatus.RUNNING
            session.touch()
            logger.info(f"[SessionManager] 恢复会话: {session_key}")
            return True

    async def cancel_session(self, session_key: str) -> bool:
        """取消会话"""
        async with self._lock:
            session = self._sessions.get(session_key)
            if session is None:
                return False
            session.status = SessionStatus.CANCELLED
            session.touch()
            logger.info(f"[SessionManager] 取消会话: {session_key}")
            return True

    # ------------------------------------------------------------------
    # Agent 状态管理
    # ------------------------------------------------------------------

    def update_agent_state(
        self,
        session_key: str,
        agent_type: str,
        state: Dict[str, Any],
    ) -> None:
        """更新会话内 Agent 状态"""
        session = self._sessions.get(session_key)
        if session:
            session.agent_states[agent_type] = state
            session.touch()

    def get_agent_states(self, session_key: str) -> Dict[str, Dict]:
        """获取会话内所有 Agent 状态"""
        session = self._sessions.get(session_key)
        if session:
            return session.agent_states
        return {}

    # ------------------------------------------------------------------
    # 任务计数
    # ------------------------------------------------------------------

    def record_task_start(self, session_key: str) -> None:
        """记录任务开始"""
        session = self._sessions.get(session_key)
        if session:
            session.task_count += 1
            session.status = SessionStatus.RUNNING
            session.touch()

    def record_task_complete(self, session_key: str, success: bool = True) -> None:
        """记录任务完成"""
        session = self._sessions.get(session_key)
        if session:
            if success:
                session.completed_tasks += 1
            else:
                session.failed_tasks += 1
                session.last_error = "Task failed"
            session.touch()

            # 检查是否所有任务都完成
            if session.completed_tasks + session.failed_tasks >= session.task_count:
                session.status = SessionStatus.COMPLETED if session.failed_tasks == 0 else SessionStatus.FAILED

    # ------------------------------------------------------------------
    # 消息计数
    # ------------------------------------------------------------------

    def record_message(self, session_key: str) -> None:
        """记录消息（计数）"""
        session = self._sessions.get(session_key)
        if session:
            session.message_count += 1

    # ------------------------------------------------------------------
    # 会话恢复
    # ------------------------------------------------------------------

    async def restore_session(self, session_key: str) -> bool:
        """从数据库恢复会话

        从 agent_event 表和 flow_result 表恢复会话状态。
        """
        try:
            from app.db.database import SessionLocal
            from app.models.agent_event import AgentEvent
            from app.models.flow_result import FlowResult
            from sqlalchemy import func

            db = SessionLocal()
            try:
                # 查询会话的所有事件
                events = db.query(AgentEvent).filter(
                    AgentEvent.session_key == session_key
                ).order_by(AgentEvent.created_at).all()

                if not events:
                    logger.warning(f"[SessionManager] 会话 {session_key} 无历史记录")
                    return False

                # 重建会话状态
                session = SessionState(
                    session_key=session_key,
                    session_id=session_key.split("session_")[-1] if "session_" in session_key else "",
                    user_id=events[0].user_id if events else 0,
                    status=SessionStatus.RUNNING,
                    created_at=events[0].created_at.timestamp() if events[0].created_at else time.time(),
                    last_active=events[-1].created_at.timestamp() if events[-1].created_at else time.time(),
                    message_count=len(events),
                )

                # 统计任务
                flow_results = db.query(FlowResult).filter(
                    FlowResult.session_key == session_key
                ).all()
                session.task_count = len(set(r.task_id for r in flow_results))
                session.completed_tasks = len([r for r in flow_results if r.status == "success"])
                session.failed_tasks = len([r for r in flow_results if r.status == "error"])

                # 恢复 Agent 状态
                agent_types = set(e.agent_type for e in events if e.agent_type)
                for at in agent_types:
                    agent_events = [e for e in events if e.agent_type == at]
                    last_event = agent_events[-1]
                    session.agent_states[at] = {
                        "event_count": len(agent_events),
                        "last_event_type": last_event.event_type,
                        "last_status": last_event.status,
                    }

                async with self._lock:
                    self._sessions[session_key] = session

                logger.info(f"[SessionManager] 恢复会话: {session_key} "
                          f"(events={len(events)}, agents={len(agent_types)})")
                return True

            finally:
                db.close()

        except Exception as e:
            logger.error(f"[SessionManager] 恢复会话失败: {session_key}: {e}")
            return False

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------

    async def _cleanup_loop(self) -> None:
        """定期清理过期会话"""
        while True:
            try:
                await asyncio.sleep(300)  # 每 5 分钟检查一次
                await self.cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[SessionManager] 清理任务异常: {e}")

    async def cleanup_expired(self) -> int:
        """清理过期会话"""
        expired_keys = []
        for key, session in self._sessions.items():
            if session.is_expired(self._session_timeout) and session.status in (
                SessionStatus.COMPLETED, SessionStatus.FAILED,
                SessionStatus.CANCELLED, SessionStatus.CREATED,
            ):
                expired_keys.append(key)

        async with self._lock:
            for key in expired_keys:
                session = self._sessions.pop(key, None)
                if session:
                    session.status = SessionStatus.EXPIRED
                    logger.info(f"[SessionManager] 清理过期会话: {key}")

        if expired_keys:
            logger.info(f"[SessionManager] 清理 {len(expired_keys)} 个过期会话")

        return len(expired_keys)

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """获取会话统计"""
        sessions = list(self._sessions.values())
        by_status = {}
        for s in sessions:
            by_status[s.status.value] = by_status.get(s.status.value, 0) + 1
        return {
            "total_sessions": len(sessions),
            "active_sessions": len([s for s in sessions if s.status == SessionStatus.RUNNING]),
            "by_status": by_status,
            "total_tasks": sum(s.task_count for s in sessions),
            "total_messages": sum(s.message_count for s in sessions),
        }


# ===== 单例 =====
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """获取会话管理器单例"""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
