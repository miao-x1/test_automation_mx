"""
Memory 模块 - Session 级独立 Memory

支持三种 Memory 后端：
- ListMemory: 内存列表，适合短会话
- DBMemory: 数据库持久化，适合长会话和审计
- AutoGenMemory: AutoGen 兼容接口（预留）

每个 Session 拥有独立 Memory，通过 MemoryManager 管理。
"""
from app.agent.memory.base import BaseMemory
from app.agent.memory.list_memory import ListMemory
from app.agent.memory.db_memory import DBMemory
from app.agent.memory.manager import MemoryManager, get_memory_manager

__all__ = [
    "BaseMemory",
    "ListMemory",
    "DBMemory",
    "MemoryManager",
    "get_memory_manager",
]
