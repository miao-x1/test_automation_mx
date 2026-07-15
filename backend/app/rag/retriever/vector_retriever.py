"""
向量检索器

基于向量数据库（Milvus）执行语义相似度检索：
1. 将 source_types / filters 组装为向量库过滤表达式
2. 调用 vector_store.search 召回 top_k 个结果
3. 应用 score_threshold 过滤低质量结果
4. 按 score 降序排序并设置 rank
"""
import logging
from typing import Any, Dict, List, Optional

from app.rag.models import RetrievalResult, RAGQuery
from app.rag.retriever.base import BaseRetriever

logger = logging.getLogger(__name__)


class VectorRetriever(BaseRetriever):
    """向量检索器

    通过向量数据库进行 ANN 检索，支持分数阈值过滤与来源类型过滤。
    向量存储实例通过惰性加载获取，当向量库不可用时优雅降级为空结果。
    """

    def __init__(self):
        self._vector_store = None
        self._vector_store_inited = False

    # ------------------------------------------------------------------
    # 依赖加载（惰性，支持外部服务不可用时降级）
    # ------------------------------------------------------------------
    def _get_vector_store(self):
        """惰性获取向量存储实例，不可用时返回 None"""
        if self._vector_store_inited:
            return self._vector_store
        self._vector_store_inited = True
        try:
            # 由 vector_store 子模块提供 get_vector_store()
            from app.rag.vector_store import get_vector_store

            self._vector_store = get_vector_store()
            logger.debug("[VectorRetriever] 向量存储已加载")
        except Exception as e:
            logger.warning(f"[VectorRetriever] 向量存储不可用，将返回空结果: {e}")
            self._vector_store = None
        return self._vector_store

    # ------------------------------------------------------------------
    # 过滤条件构建
    # ------------------------------------------------------------------
    def build_filter(self, rag_query: RAGQuery) -> Optional[Dict[str, Any]]:
        """根据 RAGQuery 构建 Milvus 过滤表达式

        合并 query.filters 与 source_types：
          - filters 中的键值原样保留
          - source_types 转换为 ``{"source_type": [...]}`` 过滤条件

        Args:
            rag_query: RAG 查询对象

        Returns:
            过滤条件字典；无过滤条件时返回 None
        """
        filters: Dict[str, Any] = {}
        if rag_query.filters:
            # 拷贝以避免修改入参
            for k, v in rag_query.filters.items():
                filters[k] = v
        if rag_query.source_types:
            filters["source_type"] = list(rag_query.source_types)
        return filters or None

    # ------------------------------------------------------------------
    # 检索主流程
    # ------------------------------------------------------------------
    async def retrieve(
        self, query_vector: List[float], rag_query: RAGQuery
    ) -> List[RetrievalResult]:
        """执行向量检索"""
        vector_store = self._get_vector_store()
        if vector_store is None:
            logger.warning("[VectorRetriever] 向量存储不可用，返回空结果")
            return []

        if not query_vector:
            logger.warning("[VectorRetriever] 查询向量为空，返回空结果")
            return []

        filters = self.build_filter(rag_query)
        top_k = max(rag_query.top_k, 1)

        try:
            results = await vector_store.search(
                query_vector,
                top_k=top_k,
                filters=filters,
            )
        except Exception as e:
            logger.error(f"[VectorRetriever] 向量检索失败: {e}", exc_info=True)
            return []

        # 防御性处理：保证返回的是列表
        if not results:
            return []

        # 应用 score_threshold 过滤
        threshold = rag_query.score_threshold
        filtered = [r for r in results if r.score >= threshold]

        # 按 score 降序排序并设置 rank
        filtered.sort(key=lambda x: x.score, reverse=True)
        for idx, r in enumerate(filtered):
            r.rank = idx + 1

        logger.info(
            f"[VectorRetriever] 检索完成: 召回 {len(results)} 条, "
            f"阈值过滤后 {len(filtered)} 条 (threshold={threshold}, top_k={top_k})"
        )
        return filtered
