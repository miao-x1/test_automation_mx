"""
检索模块

从向量库/图库/关系库中检索与查询相关的 Chunk，
融合多路召回结果，输出 RetrievalResult 列表。

主要组件：
  - BaseRetriever: 检索器抽象基类
  - VectorRetriever: 纯向量检索器（基于 Milvus）
  - HybridRetriever: 混合检索器（向量 + 图，自动降级）
"""
from app.rag.retriever.base import BaseRetriever
from app.rag.retriever.factory import (
    get_retriever,
    get_vector_retriever,
    reset_retriever,
)
from app.rag.retriever.hybrid_retriever import HybridRetriever
from app.rag.retriever.vector_retriever import VectorRetriever

__all__ = [
    "BaseRetriever",
    "VectorRetriever",
    "HybridRetriever",
    "get_retriever",
    "get_vector_retriever",
    "reset_retriever",
]
