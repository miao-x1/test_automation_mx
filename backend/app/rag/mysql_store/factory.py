"""
MySQL 存储工厂

单例模式管理 MySQLStore 实例，
与 embedding / chunker / vector_store 工厂保持一致。
"""
import logging
from typing import Optional

from app.rag.mysql_store.store import MySQLStore

logger = logging.getLogger(__name__)

_mysql_store: Optional[MySQLStore] = None


def get_mysql_store() -> MySQLStore:
    """获取 MySQL 存储单例实例"""
    global _mysql_store
    if _mysql_store is None:
        _mysql_store = MySQLStore()
        logger.info("[MySQLStoreFactory] 已创建 MySQLStore 实例")
    return _mysql_store


def reset_mysql_store() -> None:
    """重置 MySQL 存储单例（用于测试）"""
    global _mysql_store
    _mysql_store = None
