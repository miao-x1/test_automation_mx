"""向量存储工厂

单例模式管理 MilvusVectorStore 实例，
与 embedding / chunker 工厂保持一致的 get_xxx() 风格。
"""
from typing import Optional

from app.rag.vector_store.base import BaseVectorStore
from app.rag.vector_store.milvus_store import MilvusVectorStore


_vector_store: Optional[BaseVectorStore] = None


def get_vector_store() -> BaseVectorStore:
    """获取向量存储单例实例

    返回 MilvusVectorStore，Milvus 不可用时实例仍然创建，
    但所有方法会优雅降级。
    """
    global _vector_store
    if _vector_store is None:
        _vector_store = MilvusVectorStore()
    return _vector_store


def reset_vector_store() -> None:
    """重置向量存储单例（用于测试或强制重建）"""
    global _vector_store
    _vector_store = None
