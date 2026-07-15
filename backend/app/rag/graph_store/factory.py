"""
图存储工厂

单例模式管理 Neo4jGraphStore 实例。
"""
import logging
from typing import Optional

from app.rag.graph_store.store import Neo4jGraphStore

logger = logging.getLogger(__name__)

_graph_store: Optional[Neo4jGraphStore] = None


def get_graph_store() -> Neo4jGraphStore:
    """获取图存储单例实例

    Neo4j 不可用时实例仍然创建，但所有方法会优雅降级。
    """
    global _graph_store
    if _graph_store is None:
        _graph_store = Neo4jGraphStore()
        logger.info("[GraphStoreFactory] 已创建 Neo4jGraphStore 实例")
    return _graph_store


def reset_graph_store() -> None:
    """重置图存储单例（用于测试）"""
    global _graph_store
    _graph_store = None
