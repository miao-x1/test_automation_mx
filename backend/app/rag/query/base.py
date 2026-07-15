"""
查询处理器基类

定义所有查询处理器的统一抽象接口。查询处理器负责在检索前对用户查询
进行规范化与增强：查询扩展、关键词提取、过滤条件组装等。
"""
from abc import ABC, abstractmethod
from typing import List

from app.rag.models import RAGQuery


class BaseQueryProcessor(ABC):
    """查询处理器抽象基类"""

    @abstractmethod
    async def process(self, query: RAGQuery) -> RAGQuery:
        """处理查询（扩展、优化等）

        Args:
            query: 原始 RAG 查询对象

        Returns:
            处理后的 RAG 查询对象（扩展后的查询文本存放于
            query.filters["_expanded_query"]，原始 query.query 保持不变）
        """
        pass

    @abstractmethod
    async def expand_query(self, query: str) -> str:
        """查询扩展

        Args:
            query: 原始查询文本

        Returns:
            扩展后的查询文本（含同义词 / LLM 重写）
        """
        pass

    @abstractmethod
    def extract_keywords(self, query: str) -> List[str]:
        """关键词提取

        Args:
            query: 查询文本

        Returns:
            关键词列表
        """
        pass

    @abstractmethod
    def build_filter(self, source_types: List[str]) -> dict:
        """根据 source_types 构建过滤表达式

        Args:
            source_types: 来源类型列表

        Returns:
            过滤条件字典
        """
        pass
