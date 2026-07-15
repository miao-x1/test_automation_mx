"""
重排序器基类

定义所有重排序器的统一抽象接口。重排序器负责对检索召回的 Chunk
进行二次排序（rerank），保留真正相关的 top_k，过滤噪声，提升
送给 LLM 的上下文质量。
"""
from abc import ABC, abstractmethod
from typing import List

from app.rag.models import RetrievalResult


class BaseReranker(ABC):
    """重排序器抽象基类"""

    @abstractmethod
    async def rerank(
        self,
        query: str,
        results: List[RetrievalResult],
        top_k: int = 5,
    ) -> List[RetrievalResult]:
        """对检索结果重排序

        Args:
            query: 用户查询文本
            results: 检索召回的结果列表
            top_k: 重排序后保留的数量

        Returns:
            重排序后的结果列表（已按相关性降序排序，并设置 score / rank）
        """
        pass
