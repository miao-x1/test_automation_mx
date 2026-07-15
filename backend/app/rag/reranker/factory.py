"""
重排序器工厂

提供重排序器单例获取，默认返回 LLMReranker（内部自动检测 LLM 可用性，
不可用时降级为关键词重排序）。遵循项目既有的单例工厂模式。
"""
import logging
from typing import Optional

from app.rag.reranker.base import BaseReranker
from app.rag.reranker.keyword_reranker import KeywordReranker
from app.rag.reranker.llm_reranker import LLMReranker

logger = logging.getLogger(__name__)

_reranker: Optional[BaseReranker] = None


def get_reranker() -> BaseReranker:
    """获取重排序器单例（默认 LLM 重排序器）

    LLMReranker 内部会自动检测 LLM API：
      - 可用时使用 LLM + 关键词融合评分
      - 不可用时降级为纯关键词 BM25 重排序

    Returns:
        BaseReranker 实例（LLMReranker）
    """
    global _reranker
    if _reranker is None:
        _reranker = LLMReranker()
        logger.info("[RerankerFactory] 已创建 LLMReranker 实例")
    return _reranker


def get_keyword_reranker() -> BaseReranker:
    """获取纯关键词重排序器单例（不依赖外部 API）"""
    global _reranker
    if _reranker is None:
        _reranker = KeywordReranker()
        logger.info("[RerankerFactory] 已创建 KeywordReranker 实例")
    return _reranker


def reset_reranker() -> None:
    """重置重排序器单例（主要用于测试）"""
    global _reranker
    _reranker = None
