"""Embedding 工厂"""
import os
from typing import Optional
from app.rag.embedding.base import BaseEmbedding
from app.rag.embedding.dashscope_embedding import DashScopeEmbedding
from app.rag.embedding.mock_embedding import MockEmbedding


class EmbeddingFactory:
    """Embedding 工厂"""
    
    def __init__(self):
        self._provider = os.getenv("EMBEDDING_PROVIDER", "dashscope").lower()
        self._embedding: Optional[BaseEmbedding] = None
    
    def get_embedding(self) -> BaseEmbedding:
        """获取 Embedding 实例"""
        if self._embedding is not None:
            return self._embedding
        if self._provider == "mock":
            self._embedding = MockEmbedding()
        elif self._provider == "dashscope":
            ds = DashScopeEmbedding()
            if ds.can_handle():
                self._embedding = ds
            else:
                # 降级到 Mock
                self._embedding = MockEmbedding()
        else:
            self._embedding = MockEmbedding()
        return self._embedding
    
    def set_provider(self, provider: str):
        """设置 provider"""
        self._provider = provider.lower()
        self._embedding = None  # 重置


_embedding_factory: Optional[EmbeddingFactory] = None

def get_embedding_factory() -> EmbeddingFactory:
    global _embedding_factory
    if _embedding_factory is None:
        _embedding_factory = EmbeddingFactory()
    return _embedding_factory
