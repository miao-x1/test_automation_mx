"""
查询模块

负责 RAGQuery 的构建、查询扩展、过滤条件组装等，
在检索前对用户查询进行规范化与增强。

主要组件：
  - BaseQueryProcessor: 查询处理器抽象基类
  - QueryProcessor: 查询处理器实现（同义词扩展 + LLM 重写）
  - ContextBuilder: 上下文构建器（检索结果 -> LLM 上下文文本）
"""
from app.rag.query.base import BaseQueryProcessor
from app.rag.query.context_builder import ContextBuilder
from app.rag.query.factory import (
    get_context_builder,
    get_query_processor,
    reset_query_factory,
)
from app.rag.query.query_processor import QueryProcessor

__all__ = [
    "BaseQueryProcessor",
    "QueryProcessor",
    "ContextBuilder",
    "get_query_processor",
    "get_context_builder",
    "reset_query_factory",
]
