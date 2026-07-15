"""
RAG 服务工厂

单例模式管理 RAGPipeline 实例。
"""
import logging
from typing import Optional

from app.rag.service.pipeline import RAGPipeline

logger = logging.getLogger(__name__)

_rag_service: Optional[RAGPipeline] = None


def get_rag_service() -> RAGPipeline:
    """获取 RAG 管道服务单例"""
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGPipeline()
        logger.info("[RAGServiceFactory] 已创建 RAGPipeline 实例")
    return _rag_service


def reset_rag_service() -> None:
    """重置 RAG 服务单例（用于测试）"""
    global _rag_service
    _rag_service = None
