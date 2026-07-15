"""
Milvus向量检索器

从Milvus向量数据库检索语义相似的数据。
支持跨集合检索和实体类型过滤。

流程：
    查询文本 → Embedding → Milvus ANN搜索 → 过滤 → 返回结果
"""
import logging
from typing import Any, Dict, List

from app.rag.retrieval_engine.base import BaseRetriever, RetrievalResult

logger = logging.getLogger(__name__)


class MilvusRetriever(BaseRetriever):
    """Milvus向量语义检索器

    根据查询计划从Milvus检索语义相似的数据。
    支持多集合查询和TopK过滤。
    """

    def __init__(self):
        super().__init__("milvus")

    def search(self, query: Dict[str, Any]) -> RetrievalResult:
        """
        从Milvus检索语义相似数据

        Args:
            query: {
                queries: ["登录测试", "密码错误"],      # 查询文本列表
                collections: ["test_case_vector"],       # 集合名
                entity_types: ["case", "script"],        # 实体类型过滤
                top_k: 10,
                score_threshold: 0.3
            }

        Returns:
            RetrievalResult: {
                data: {collection_name: [results]},
                count: total
            }
        """
        queries = query.get("queries", [])
        collections = query.get("collections", [])
        entity_types = query.get("entity_types", [])
        top_k = query.get("top_k", 10)
        score_threshold = query.get("score_threshold", 0.3)

        if not queries or not collections:
            return RetrievalResult(source="milvus", success=True, data={}, count=0)

        results = {}
        total_count = 0

        try:
            # 获取MultiVectorStore（统一管理5个集合）
            from app.rag.vector_store.multi_vector_store import get_multi_vector_store
            store = get_multi_vector_store()

            # 获取Embedding工厂
            from app.rag.embedding.factory import get_embedding_factory
            embedding_factory = get_embedding_factory()
            embedding_model = embedding_factory.get_embedding()

            for query_text in queries:
                if not query_text:
                    continue

                # 生成查询向量
                query_vector = embedding_model.embed(query_text)
                if not query_vector:
                    logger.warning(f"[milvus] 无法生成查询向量: {query_text[:50]}")
                    continue

                # 在每个集合中搜索
                for collection in collections:
                    try:
                        search_results = self._search_collection(
                            store=store,
                            collection_name=collection,
                            query_vector=query_vector,
                            query_text=query_text,
                            entity_types=entity_types,
                            top_k=top_k,
                            score_threshold=score_threshold,
                        )

                        if collection not in results:
                            results[collection] = []
                        results[collection].extend(search_results)
                        total_count += len(search_results)

                    except Exception as e:
                        logger.error(f"[milvus] 集合 {collection} 搜索失败: {e}")

            # 去重和排序
            for collection in results:
                results[collection] = self._deduplicate_and_sort(results[collection], top_k)

        except Exception as e:
            logger.error(f"[milvus] 检索失败: {e}")
            return RetrievalResult(
                source="milvus",
                success=False,
                error=str(e),
                data={},
                count=0,
            )

        return RetrievalResult(
            source="milvus",
            success=True,
            data=results,
            count=total_count,
        )

    def _search_collection(
        self,
        store,
        collection_name: str,
        query_vector: List[float],
        query_text: str,
        entity_types: List[str],
        top_k: int,
        score_threshold: float,
    ) -> List[Dict[str, Any]]:
        """在单个集合中搜索"""
        try:
            # 构建过滤表达式
            filter_expr = ""
            if entity_types:
                type_list = ", ".join([f'"{t}"' for t in entity_types])
                filter_expr = f'entity_type in [{type_list}]'

            # 调用store的搜索方法
            results = store.search(
                collection_name=collection_name,
                query_vector=query_vector,
                top_k=top_k,
                filter_expr=filter_expr if filter_expr else None,
            )

            # 过滤低分结果
            filtered = []
            for r in results:
                score = r.get("score", r.get("distance", 0))
                if score >= score_threshold:
                    r["query"] = query_text[:100]
                    filtered.append(r)

            return filtered

        except Exception as e:
            logger.error(f"[milvus] 集合搜索异常 {collection_name}: {e}")
            return []

    def _deduplicate_and_sort(self, results: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
        """去重和排序"""
        seen = set()
        unique = []
        for r in results:
            text = r.get("text", r.get("content", ""))[:200]
            if text not in seen:
                seen.add(text)
                unique.append(r)

        # 按score降序
        unique.sort(key=lambda x: x.get("score", x.get("distance", 0)), reverse=True)
        return unique[:top_k]
