"""
混合检索器

结合向量检索与图检索（知识图谱）：
1. 向量检索：基于查询向量召回语义相似的 chunk
2. 图检索：基于查询文本在知识图谱中搜索关联实体 / chunk
3. 合并去重：以 chunk_id 为键，保留较高分数
4. 图扩展：对排名靠前的 chunk，通过 graph_store.get_related_chunks
   查找其关联 chunk，提升关联 chunk 的分数
5. 按 score 降序排序并设置 rank

当 graph_store 不可用时，自动降级为纯向量检索。
"""
import logging
from typing import Any, Dict, List, Set

from app.rag.models import RetrievalResult, RAGQuery
from app.rag.retriever.base import BaseRetriever
from app.rag.retriever.vector_retriever import VectorRetriever

logger = logging.getLogger(__name__)


class HybridRetriever(BaseRetriever):
    """混合检索器（向量 + 图）"""

    def __init__(self):
        self._vector_retriever = VectorRetriever()
        self._graph_store = None
        self._graph_store_inited = False
        # 图扩展带来的分数提升（叠加到原 score 上，封顶 1.0）
        self._graph_boost = 0.15
        # 图扩展深度
        self._graph_expansion_depth = 1
        # 图检索默认召回数量
        self._graph_search_limit = 10

    # ------------------------------------------------------------------
    # 依赖加载（惰性）
    # ------------------------------------------------------------------
    def _get_graph_store(self):
        """惰性获取图存储实例，不可用时返回 None"""
        if self._graph_store_inited:
            return self._graph_store
        self._graph_store_inited = True
        try:
            from app.rag.graph_store import get_graph_store

            self._graph_store = get_graph_store()
            logger.debug("[HybridRetriever] 图存储已加载")
        except Exception as e:
            logger.info(f"[HybridRetriever] 图存储不可用，降级为纯向量检索: {e}")
            self._graph_store = None
        return self._graph_store

    # ------------------------------------------------------------------
    # 检索主流程
    # ------------------------------------------------------------------
    async def retrieve(
        self, query_vector: List[float], rag_query: RAGQuery
    ) -> List[RetrievalResult]:
        """执行混合检索"""
        # 1. 向量检索
        vector_results = await self._vector_retriever.retrieve(
            query_vector, rag_query
        )

        graph_store = self._get_graph_store()
        if graph_store is None or not vector_results:
            # 降级：纯向量检索结果
            logger.debug("[HybridRetriever] 使用纯向量检索结果")
            return vector_results

        # 2. 图检索：基于查询文本搜索知识图谱
        graph_results = await self._graph_search(rag_query, graph_store)

        # 3. 合并去重（保留较高分数）
        merged = self._merge_results(vector_results, graph_results)

        # 4. 图扩展：提升关联 chunk 分数
        boosted = await self._boost_with_graph(merged, rag_query, graph_store)

        # 5. 按 score 降序排序并设置 rank
        boosted.sort(key=lambda x: x.score, reverse=True)
        for idx, r in enumerate(boosted):
            r.rank = idx + 1

        # 限制返回数量为 top_k
        final = boosted[: max(rag_query.top_k, 1)]
        logger.info(
            f"[HybridRetriever] 混合检索完成: 向量召回 {len(vector_results)} 条, "
            f"图召回 {len(graph_results)} 条, 合并后 {len(merged)} 条, "
            f"图扩展后 {len(boosted)} 条, 返回 {len(final)} 条"
        )
        return final

    # ------------------------------------------------------------------
    # 图检索
    # ------------------------------------------------------------------
    async def _graph_search(
        self, rag_query: RAGQuery, graph_store
    ) -> List[RetrievalResult]:
        """基于查询文本在知识图谱中搜索关联 chunk"""
        if not rag_query.query:
            return []
        try:
            graph_dicts = await graph_store.search_graph(
                rag_query.query, limit=self._graph_search_limit
            )
        except Exception as e:
            logger.warning(f"[HybridRetriever] 图检索失败: {e}", exc_info=True)
            return []

        results: List[RetrievalResult] = []
        for item in graph_dicts or []:
            if not isinstance(item, dict):
                continue
            try:
                r = RetrievalResult(
                    chunk_id=str(item.get("chunk_id", "")),
                    source_id=str(item.get("source_id", "")),
                    text=str(item.get("text", "")),
                    score=float(item.get("score", 0.5)),
                    chunk_type=str(item.get("chunk_type", "")),
                    metadata=item.get("metadata", {}) or {},
                    source_type=str(item.get("source_type", "")),
                    source_name=str(item.get("source_name", "")),
                )
                results.append(r)
            except Exception as e:
                logger.debug(f"[HybridRetriever] 图结果转换失败: {e}")
                continue
        return results

    # ------------------------------------------------------------------
    # 合并去重
    # ------------------------------------------------------------------
    def _merge_results(
        self,
        vector_results: List[RetrievalResult],
        graph_results: List[RetrievalResult],
    ) -> List[RetrievalResult]:
        """合并多路召回结果并去重

        以 chunk_id 为键：
          - 同一 chunk_id 保留较高分数
          - 无 chunk_id 的结果使用唯一键保留
        """
        merged: Dict[str, RetrievalResult] = {}
        fallback_idx = 0

        for r in vector_results + graph_results:
            key = r.chunk_id
            if not key:
                # 无 chunk_id 时用唯一键保留，避免丢弃
                key = f"__no_id_{fallback_idx}"
                fallback_idx += 1
            existing = merged.get(key)
            if existing is None or r.score > existing.score:
                merged[key] = r
        return list(merged.values())

    # ------------------------------------------------------------------
    # 图扩展（分数提升）
    # ------------------------------------------------------------------
    async def _boost_with_graph(
        self,
        results: List[RetrievalResult],
        rag_query: RAGQuery,
        graph_store,
    ) -> List[RetrievalResult]:
        """通过图关系提升关联 chunk 的分数

        对排名靠前的 chunk（受 rerank_top_k 限制以控制开销），
        查找其在知识图谱中的关联 chunk_id：
          - 若关联 chunk 已在结果中，提升其分数（叠加 boost，封顶 1.0）
        """
        id_to_result: Dict[str, RetrievalResult] = {
            r.chunk_id: r for r in results if r.chunk_id
        }
        # 仅对靠前的 chunk 做扩展，避免图查询开销过大
        expand_candidates = results[: min(len(results), max(rag_query.rerank_top_k, 1))]

        for r in expand_candidates:
            if not r.chunk_id:
                continue
            try:
                related_ids = await graph_store.get_related_chunks(
                    r.chunk_id, self._graph_expansion_depth
                )
            except Exception as e:
                logger.debug(
                    f"[HybridRetriever] 图扩展失败 chunk={r.chunk_id}: {e}"
                )
                continue

            for rid in related_ids or []:
                if not rid:
                    continue
                target = id_to_result.get(rid)
                if target is not None:
                    # 提升（被图关系确认相关的）chunk 分数
                    target.score = min(target.score + self._graph_boost, 1.0)

        return list(id_to_result.values())
