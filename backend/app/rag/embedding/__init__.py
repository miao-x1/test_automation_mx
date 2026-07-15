"""向量嵌入模块"""
from app.rag.embedding.base import BaseEmbedding
from app.rag.embedding.dashscope_embedding import DashScopeEmbedding
from app.rag.embedding.mock_embedding import MockEmbedding
from app.rag.embedding.factory import EmbeddingFactory, get_embedding_factory

__all__ = [
    "BaseEmbedding",
    "DashScopeEmbedding",
    "MockEmbedding",
    "EmbeddingFactory",
    "get_embedding_factory",
]
