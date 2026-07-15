"""
重排序模块

对检索召回的 Chunk 进行二次排序（rerank），
保留真正相关的 top_k，过滤噪声，提升送给 LLM 的上下文质量。

主要组件：
  - BaseReranker: 重排序器抽象基类
  - KeywordReranker: 关键词 BM25 重排序器（纯本地，不依赖外部 API）
  - LLMReranker: LLM 重排序器（自动检测 LLM，不可用时降级到关键词）
"""
from app.rag.reranker.base import BaseReranker
from app.rag.reranker.factory import (
    get_keyword_reranker,
    get_reranker,
    reset_reranker,
)
from app.rag.reranker.keyword_reranker import KeywordReranker
from app.rag.reranker.llm_reranker import LLMReranker

__all__ = [
    "BaseReranker",
    "KeywordReranker",
    "LLMReranker",
    "get_reranker",
    "get_keyword_reranker",
    "reset_reranker",
]
