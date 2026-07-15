"""
检索器基类

定义所有检索器的统一抽象接口。检索器负责从向量库 / 图库 / 关系库中
召回与查询相关的 Chunk，输出 RetrievalResult 列表。
"""
from abc import ABC, abstractmethod
from typing import List

from app.rag.models import RetrievalResult, RAGQuery


class BaseRetriever(ABC):
    """检索器抽象基类"""

    @abstractmethod
    async def retrieve(
        self, query_vector: List[float], rag_query: RAGQuery
    ) -> List[RetrievalResult]:
        """执行检索

        Args:
            query_vector: 查询文本对应的向量
            rag_query: RAG 查询对象（含 top_k、score_threshold、filters 等）

        Returns:
            检索结果列表（已按相关性降序排序，并设置 rank）
        """
        pass
