"""
查询处理器工厂

提供查询处理器与上下文构建器的单例获取，遵循项目既有的单例工厂模式。
"""
import logging
from typing import Optional

from app.rag.query.base import BaseQueryProcessor
from app.rag.query.context_builder import ContextBuilder
from app.rag.query.query_processor import QueryProcessor

logger = logging.getLogger(__name__)

_query_processor: Optional[BaseQueryProcessor] = None
_context_builder: Optional[ContextBuilder] = None


def get_query_processor() -> BaseQueryProcessor:
    """获取查询处理器单例

    Returns:
        BaseQueryProcessor 实例（QueryProcessor）
    """
    global _query_processor
    if _query_processor is None:
        _query_processor = QueryProcessor()
        logger.info("[QueryFactory] 已创建 QueryProcessor 实例")
    return _query_processor


def get_context_builder() -> ContextBuilder:
    """获取上下文构建器单例

    Returns:
        ContextBuilder 实例
    """
    global _context_builder
    if _context_builder is None:
        _context_builder = ContextBuilder()
        logger.info("[QueryFactory] 已创建 ContextBuilder 实例")
    return _context_builder


def reset_query_factory() -> None:
    """重置查询处理器与上下文构建器单例（主要用于测试）"""
    global _query_processor, _context_builder
    _query_processor = None
    _context_builder = None
