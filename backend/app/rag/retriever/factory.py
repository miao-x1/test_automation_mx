"""
检索器工厂

提供检索器单例获取，默认返回混合检索器（HybridRetriever）。
遵循项目既有的单例工厂模式。
"""
import logging
from typing import Optional

from app.rag.retriever.base import BaseRetriever
from app.rag.retriever.hybrid_retriever import HybridRetriever
from app.rag.retriever.vector_retriever import VectorRetriever

logger = logging.getLogger(__name__)

_retriever: Optional[BaseRetriever] = None


def get_retriever() -> BaseRetriever:
    """获取检索器单例（默认混合检索器）

    Returns:
        BaseRetriever 实例（HybridRetriever）
    """
    global _retriever
    if _retriever is None:
        _retriever = HybridRetriever()
        logger.info("[RetrieverFactory] 已创建 HybridRetriever 实例")
    return _retriever


def get_vector_retriever() -> BaseRetriever:
    """获取纯向量检索器单例

    在不需要图检索的场景下使用。
    """
    global _retriever
    if _retriever is None:
        _retriever = VectorRetriever()
        logger.info("[RetrieverFactory] 已创建 VectorRetriever 实例")
    return _retriever


def reset_retriever() -> None:
    """重置检索器单例（主要用于测试）"""
    global _retriever
    _retriever = None
