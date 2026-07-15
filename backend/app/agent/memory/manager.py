"""
MemoryManager - Session 级 Memory 管理器
负责创建、获取、销毁各 Session 的 Memory 实例。
"""
import threading
from typing import Dict, Optional

from app.agent.memory.base import BaseMemory
from app.agent.memory.list_memory import ListMemory
from app.agent.memory.db_memory import DBMemory
from app.agent.core.types import MemoryType
from app.core.logger import log


class MemoryManager:
    """
    Memory 管理器（单例）。

    每个 Session 拥有独立 Memory，
    通过 MemoryManager 统一管理生命周期。

    后续扩展：
    - AutoGen Memory 适配
    - 分布式 Memory（Redis/Milvus）
    - Memory 持久化与恢复
    """

    _instance: Optional["MemoryManager"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._memories: Dict[str, BaseMemory] = {}
        self._mutex = threading.Lock()

    def create_memory(self, session_id: str, memory_type: str = "list",
                      max_size: int = 100) -> BaseMemory:
        """为指定 Session 创建 Memory"""
        with self._mutex:
            if session_id in self._memories:
                log.debug(f"Memory for session '{session_id}' already exists, reusing")
                return self._memories[session_id]

            if memory_type == MemoryType.DB.value or memory_type == "database":
                memory = DBMemory(session_id=session_id, max_size=max_size)
            elif memory_type == MemoryType.AUTOGEN.value or memory_type == "autogen":
                # 预留：AutoGen Memory 适配
                memory = ListMemory(session_id=session_id, max_size=max_size)
                log.info("AutoGen memory not yet implemented, using ListMemory fallback")
            else:
                memory = ListMemory(session_id=session_id, max_size=max_size)

            self._memories[session_id] = memory
            log.debug(f"Created {memory_type} memory for session '{session_id}'")
            return memory

    def get_memory(self, session_id: str) -> Optional[BaseMemory]:
        """获取指定 Session 的 Memory"""
        with self._mutex:
            return self._memories.get(session_id)

    def get_or_create(self, session_id: str, memory_type: str = "list") -> BaseMemory:
        """获取或创建 Memory"""
        memory = self.get_memory(session_id)
        if memory is None:
            memory = self.create_memory(session_id, memory_type)
        return memory

    def destroy_memory(self, session_id: str) -> None:
        """销毁指定 Session 的 Memory"""
        with self._mutex:
            memory = self._memories.pop(session_id, None)
            if memory:
                memory.clear()
                log.debug(f"Destroyed memory for session '{session_id}'")

    def list_sessions(self) -> Dict[str, dict]:
        """列出所有 Session 的 Memory 状态"""
        with self._mutex:
            return {sid: m.to_dict() for sid, m in self._memories.items()}

    def clear_all(self) -> None:
        """清空所有 Memory"""
        with self._mutex:
            for memory in self._memories.values():
                memory.clear()
            self._memories.clear()
            log.info("All memories cleared")


def get_memory_manager() -> MemoryManager:
    """获取 MemoryManager 单例"""
    return MemoryManager()
