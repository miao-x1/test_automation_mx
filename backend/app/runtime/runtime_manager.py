"""
AutoGen Core Runtime - 生命周期管理器

负责：
1. 管理 CoreRuntime 单例的生命周期（start / stop / close）
2. 管理用户会话（create_session / close_session / list_sessions）
3. 在首次使用时自动初始化 Runtime + 注册所有 Agent
4. 提供 session_key 生成（多用户隔离）
5. 清理过期会话

支持：
- 多用户：每个用户的 session_key 不同
- 多 Session：同一用户可有多个 session
- 并发任务：SingleThreadedAgentRuntime 内部排队，但外层 asyncio 并发
- 资源回收：过期 session 自动清理

使用方式：
    manager = get_runtime_manager()
    await manager.ensure_started()           # 确保 Runtime 已启动
    session_key = manager.create_session(user_id=1, session_id="abc")
    # ... 发送任务 ...
    manager.close_session(session_key)
"""
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.runtime.runtime import CoreRuntime, get_core_runtime
from app.runtime.agent_registry import AgentRegistry, get_agent_registry

logger = logging.getLogger(__name__)


@dataclass
class SessionInfo:
    """会话信息"""
    session_key: str                         # AgentId key（如 "user_1_session_abc"）
    user_id: Optional[int]                   # 用户ID
    session_id: str                          # 会话ID
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    task_count: int = 0                     # 该 session 提交的任务数
    is_active: bool = True                   # 是否活跃

    def touch(self) -> None:
        """更新最后活跃时间。"""
        self.last_active = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_key": self.session_key,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "task_count": self.task_count,
            "is_active": self.is_active,
        }


class RuntimeManager:
    """
    Runtime 生命周期管理器

    单例，管理整个应用的 AutoGen Core Runtime。

    核心功能：
    1. ensure_started() - 确保 Runtime 已初始化并启动（幂等）
    2. create_session() - 创建用户会话，返回 session_key
    3. close_session() - 关闭会话，清理资源
    4. get_session_key() - 获取指定用户+会话的 key
    5. list_sessions() - 列出所有活跃会话
    6. cleanup_expired() - 清理过期会话
    """

    # 会话过期时间（默认 1 小时）
    SESSION_EXPIRE_SECONDS = 3600

    def __init__(self) -> None:
        self._core_runtime: CoreRuntime = get_core_runtime()
        self._registry: AgentRegistry = get_agent_registry()
        self._sessions: Dict[str, SessionInfo] = {}  # session_key → SessionInfo
        self._initialized: bool = False
        self._init_lock = asyncio.Lock()
        self._session_lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    #  Runtime 初始化                                                      #
    # ------------------------------------------------------------------ #

    async def ensure_started(self) -> None:
        """
        确保 Runtime 已初始化并启动（幂等）

        首次调用时：
        1. 创建 SingleThreadedAgentRuntime
        2. 注册 CollectorAgent
        3. 注册所有 Agent 类型（通过 AgentRegistry）
        4. 启动 Runtime 后台消息处理

        后续调用直接返回。
        """
        if self._initialized:
            return

        async with self._init_lock:
            if self._initialized:
                return

            logger.info("[RuntimeManager] Initializing AutoGen Core Runtime...")

            # 初始化 Runtime（创建 SingleThreadedAgentRuntime + 注册 CollectorAgent）
            await self._core_runtime.initialize()

            # 注册所有 Agent 类型
            await self._registry.register_all(self._core_runtime)

            # 启动 Runtime
            await self._core_runtime.start()

            self._initialized = True
            logger.info(
                f"[RuntimeManager] Runtime started. "
                f"Registered agents: {self._core_runtime.list_agent_types()}"
            )

    async def stop(self) -> None:
        """停止 Runtime。"""
        if self._initialized:
            await self._core_runtime.stop()
            self._initialized = False
            logger.info("[RuntimeManager] Runtime stopped")

    async def close(self) -> None:
        """关闭 Runtime 并释放所有资源。"""
        if self._initialized:
            await self._core_runtime.close()
            self._initialized = False
        async with self._session_lock:
            self._sessions.clear()
        logger.info("[RuntimeManager] Runtime closed, all sessions cleared")

    # ------------------------------------------------------------------ #
    #  会话管理                                                            #
    # ------------------------------------------------------------------ #

    def make_session_key(self, user_id: Optional[int], session_id: str) -> str:
        """
        生成 session_key（AgentId key）

        格式: user_{user_id}_session_{session_id}
        用于 AgentId key，实现多用户/多 Session 隔离。

        AgentId = (agent_type, session_key)
        同一 session_key 的 Agent 实例共享上下文。
        不同 session_key 的 Agent 实例完全隔离。
        """
        uid = user_id if user_id is not None else "anonymous"
        return f"user_{uid}_session_{session_id}"

    async def create_session(
        self,
        user_id: Optional[int] = None,
        session_id: str = "",
    ) -> str:
        """
        创建用户会话

        Args:
            user_id: 用户ID（None 表示匿名）
            session_id: 会话ID（不传则自动生成）

        Returns:
            session_key: 会话标识（用作 AgentId key）
        """
        await self.ensure_started()

        if not session_id:
            session_id = str(uuid.uuid4())[:8]

        session_key = self.make_session_key(user_id, session_id)

        async with self._session_lock:
            if session_key in self._sessions:
                # 会话已存在，标记为活跃
                self._sessions[session_key].touch()
                self._sessions[session_key].is_active = True
                logger.info(f"[RuntimeManager] Session resumed: {session_key}")
            else:
                self._sessions[session_key] = SessionInfo(
                    session_key=session_key,
                    user_id=user_id,
                    session_id=session_id,
                )
                logger.info(f"[RuntimeManager] Session created: {session_key}")

        return session_key

    async def close_session(self, session_key: str) -> None:
        """关闭会话。"""
        async with self._session_lock:
            if session_key in self._sessions:
                self._sessions[session_key].is_active = False
                logger.info(f"[RuntimeManager] Session closed: {session_key}")

    async def get_session(self, session_key: str) -> Optional[SessionInfo]:
        """获取会话信息。"""
        async with self._session_lock:
            return self._sessions.get(session_key)

    async def list_sessions(self, user_id: Optional[int] = None) -> List[SessionInfo]:
        """列出会话（可按用户过滤）。"""
        async with self._session_lock:
            sessions = list(self._sessions.values())
        if user_id is not None:
            sessions = [s for s in sessions if s.user_id == user_id]
        return sessions

    async def touch_session(self, session_key: str) -> None:
        """更新会话活跃时间。"""
        async with self._session_lock:
            if session_key in self._sessions:
                self._sessions[session_key].touch()
                self._sessions[session_key].task_count += 1

    # ------------------------------------------------------------------ #
    #  任务提交                                                            #
    # ------------------------------------------------------------------ #

    async def submit_task(
        self,
        agent_type: str,
        action: str,
        payload: Dict[str, Any],
        task_id: str = "",
        user_id: Optional[int] = None,
        session_id: str = "",
        session_key: str = "",
    ) -> str:
        """
        提交任务到 Runtime

        Args:
            agent_type: 目标 Agent 类型
            action: 要执行的方法名（默认 "execute"）
            payload: 方法参数
            task_id: 任务ID（不传则自动生成）
            user_id: 用户ID
            session_id: 会话ID
            session_key: 直接指定 session_key（优先于 user_id + session_id）

        Returns:
            task_id: 任务ID
        """
        await self.ensure_started()

        if not task_id:
            task_id = str(uuid.uuid4())

        # 确定 session_key
        if not session_key:
            if not session_id:
                session_id = task_id[:8]
            session_key = self.make_session_key(user_id, session_id)
            # 自动创建会话
            await self.create_session(user_id, session_id)

        # 更新会话活跃时间
        await self.touch_session(session_key)

        # 发送任务
        await self._core_runtime.send_task(
            agent_type=agent_type,
            action=action,
            payload=payload,
            task_id=task_id,
            session_key=session_key,
        )

        logger.info(
            f"[RuntimeManager] Task submitted: task={task_id}, "
            f"agent={agent_type}, action={action}, session={session_key}"
        )

        return task_id

    async def get_result(
        self,
        task_id: str,
        session_key: str = "default",
        timeout: float = 300,
    ) -> Optional[Dict[str, Any]]:
        """
        获取任务结果（阻塞等待）

        Args:
            task_id: 任务ID
            session_key: 会话标识
            timeout: 超时时间（秒）

        Returns:
            任务结果字典
        """
        await self.ensure_started()
        return await self._core_runtime.get_result(task_id, session_key, timeout)

    # ------------------------------------------------------------------ #
    #  清理                                                               #
    # ------------------------------------------------------------------ #

    async def cleanup_expired(self) -> int:
        """
        清理过期会话

        清理超过 SESSION_EXPIRE_SECONDS 未活跃的会话。

        Returns:
            清理的会话数量
        """
        now = time.time()
        expired_keys = []

        async with self._session_lock:
            for key, session in self._sessions.items():
                if not session.is_active:
                    expired_keys.append(key)
                elif now - session.last_active > self.SESSION_EXPIRE_SECONDS:
                    session.is_active = False
                    expired_keys.append(key)

            for key in expired_keys:
                del self._sessions[key]

        if expired_keys:
            logger.info(f"[RuntimeManager] Cleaned up {len(expired_keys)} expired sessions")

        return len(expired_keys)

    # ------------------------------------------------------------------ #
    #  状态                                                               #
    # ------------------------------------------------------------------ #

    @property
    def is_started(self) -> bool:
        return self._initialized and self._core_runtime.is_started

    def get_stats(self) -> Dict[str, Any]:
        return {
            "runtime": self._core_runtime.get_stats(),
            "sessions": {
                "total": len(self._sessions),
                "active": sum(1 for s in self._sessions.values() if s.is_active),
                "inactive": sum(1 for s in self._sessions.values() if not s.is_active),
            },
            "agents": {
                "total_definitions": len(self._registry.list_agent_types()),
                "registered": sum(1 for t in self._registry.list_agent_types()
                                   if self._registry.is_registered(t)),
            },
        }

    def get_core_runtime(self) -> CoreRuntime:
        """获取 CoreRuntime 实例。"""
        return self._core_runtime

    def get_registry(self) -> AgentRegistry:
        """获取 AgentRegistry 实例。"""
        return self._registry


# ------------------------------------------------------------------ #
#  单例                                                                #
# ------------------------------------------------------------------ #

_runtime_manager: Optional[RuntimeManager] = None


def get_runtime_manager() -> RuntimeManager:
    """获取 RuntimeManager 单例。"""
    global _runtime_manager
    if _runtime_manager is None:
        _runtime_manager = RuntimeManager()
    return _runtime_manager
