"""向量存储基类

定义向量存储的统一抽象接口，支持插入、搜索、删除与统计。
具体实现由 MilvusVectorStore 等子类完成。
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

from app.rag.models import Chunk, RetrievalResult


class BaseVectorStore(ABC):
    """向量存储抽象基类

    所有向量存储后端（Milvus、FAISS 等）均需实现此接口。
    方法均为 async，便于在异步管道中调用。
    """

    @abstractmethod
    async def insert(self, chunks: List[Chunk]) -> int:
        """插入向量数据

        Args:
            chunks: 分块列表，每个 chunk 应包含 embedding 字段

        Returns:
            成功插入的数量
        """
        pass

    @abstractmethod
    async def search(
        self,
        query_vector: List[float],
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[RetrievalResult]:
        """向量相似度搜索

        Args:
            query_vector: 查询向量
            top_k: 返回结果数量
            filters: 过滤条件，如 {"source_type": "requirement", "chunk_type": "content"}

        Returns:
            检索结果列表，按相似度降序排列
        """
        pass

    @abstractmethod
    async def delete_by_source(self, source_id: str) -> int:
        """删除指定文档的所有向量

        Args:
            source_id: 文档来源ID

        Returns:
            删除的向量数量
        """
        pass

    @abstractmethod
    async def get_stats(self) -> Dict[str, Any]:
        """获取存储统计信息

        Returns:
            统计字典，包含行数、可用性等信息
        """
        pass
