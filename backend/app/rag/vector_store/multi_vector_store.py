"""
多类型向量存储

统一管理 RAG 系统中的所有向量集合：
  - rag_knowledge_vector:  知识文档 Chunk 向量
  - requirement_vector:    需求向量
  - page_vector:           页面向量
  - mv_case_vector:        测试用例向量（统一 Schema，与 milvus_client 的 test_case_vector 分离）
  - mv_script_vector:      脚本向量（统一 Schema，与 milvus_client 的 script_vector 分离）

每种集合使用统一的 schema 结构（source_id, entity_type, text, metadata, embedding）。
case/script 使用独立集合名，避免与 milvus_client.py 的特定 Schema 集合冲突。

Milvus 不可用时优雅降级。
"""
import json
import logging
from typing import List, Dict, Any, Optional

from pymilvus import DataType

from app.core.config import settings
from app.db.milvus_client import get_milvus_client
from app.rag.models import RetrievalResult
from app.rag.vector_store.milvus_store import MilvusVectorStore

logger = logging.getLogger(__name__)

# ===== 集合名称定义（从统一常量文件导入）=====
from app.db.collection_constants import (
    RAG_KNOWLEDGE_COLLECTION as RAG_COLLECTION,
    REQUIREMENT_COLLECTION as REQUIREMENT_COLLECTION,
    PAGE_COLLECTION as PAGE_COLLECTION,
    MV_CASE_COLLECTION as CASE_COLLECTION,
    MV_SCRIPT_COLLECTION as SCRIPT_COLLECTION,
)

# 向量维度
EMBEDDING_DIM = settings.EMBEDDING_DIM

# VARCHAR 限制
MAX_TEXT_LENGTH = 8192
MAX_METADATA_LENGTH = 4096
MAX_VARCHAR_LENGTH = 256


class MultiVectorStore:
    """多类型向量存储管理器

    统一管理 Chunk/Requirement/Page/Case/Script 五种向量集合。
    每种集合使用相同的 schema 结构，但通过 entity_type 区分。

    集合 schema：
      - id: 自增主键
      - source_id: 来源实体ID
      - entity_type: 实体类型 (chunk/requirement/page/case/script)
      - text: 文本内容
      - metadata: 元数据 JSON
      - embedding: 向量
    """

    # 所有集合类型
    COLLECTION_TYPES = ["chunk", "requirement", "page", "case", "script"]

    def __init__(self):
        self._rag_store = MilvusVectorStore(RAG_COLLECTION)
        self._collections: Dict[str, str] = {
            "chunk": RAG_COLLECTION,
            "requirement": REQUIREMENT_COLLECTION,
            "page": PAGE_COLLECTION,
            "case": CASE_COLLECTION,
            "script": SCRIPT_COLLECTION,
        }
        self._initialized: Dict[str, bool] = {}

    # ------------------------------------------------------------------
    # 集合管理
    # ------------------------------------------------------------------

    def _get_collection_name(self, entity_type: str) -> str:
        return self._collections.get(entity_type, RAG_COLLECTION)

    def ensure_collection(self, entity_type: str = "chunk") -> bool:
        """幂等创建指定类型的向量集合"""
        if entity_type == "chunk":
            return self._rag_store.ensure_collection()

        collection_name = self._get_collection_name(entity_type)
        if self._initialized.get(entity_type):
            return True

        client = get_milvus_client(allow_fail=True)
        if client is None:
            return False

        try:
            if client.has_collection(collection_name):
                self._initialized[entity_type] = True
                return True

            # 使用统一 schema
            schema = client.create_schema(auto_id=True, enable_dynamic_field=False)
            schema.add_field("id", DataType.INT64, is_primary=True, description="主键")
            schema.add_field("source_id", DataType.VARCHAR, max_length=MAX_VARCHAR_LENGTH, description="来源ID")
            schema.add_field("entity_type", DataType.VARCHAR, max_length=64, description="实体类型")
            schema.add_field("text", DataType.VARCHAR, max_length=MAX_TEXT_LENGTH, description="文本内容")
            schema.add_field("metadata", DataType.VARCHAR, max_length=MAX_METADATA_LENGTH, description="元数据JSON")
            schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM, description="向量")

            index_params = client.prepare_index_params()
            index_params.add_index(
                field_name="embedding",
                index_type="IVF_FLAT",
                metric_type="COSINE",
                index_name=f"{entity_type}_embedding_index",
                params={"nlist": 128},
            )

            client.create_collection(
                collection_name=collection_name,
                schema=schema,
                index_params=index_params,
            )
            self._initialized[entity_type] = True
            logger.info(f"[MultiVectorStore] 集合 {collection_name} 创建成功")
            return True
        except Exception as e:
            logger.error(f"[MultiVectorStore] 创建集合 {collection_name} 失败: {e}")
            return False

    def ensure_all_collections(self):
        """创建所有类型的集合"""
        for et in self.COLLECTION_TYPES:
            self.ensure_collection(et)

    # ------------------------------------------------------------------
    # 通用操作
    # ------------------------------------------------------------------

    async def insert_vector(
        self,
        entity_type: str,
        source_id: str,
        text: str,
        embedding: List[float],
        metadata: Optional[Dict] = None,
    ) -> int:
        """插入单条向量

        Args:
            entity_type: 实体类型 chunk/requirement/page/case/script
            source_id: 来源ID
            text: 文本内容
            embedding: 向量
            metadata: 元数据

        Returns:
            1 成功, 0 失败
        """
        if entity_type == "chunk":
            # chunk 使用 MilvusVectorStore
            from app.rag.models import Chunk
            chunk = Chunk(
                source_id=source_id,
                text=text,
                embedding=embedding,
                metadata=metadata or {},
            )
            return await self._rag_store.insert([chunk])

        collection_name = self._get_collection_name(entity_type)
        client = get_milvus_client(allow_fail=True)
        if client is None:
            logger.warning(f"[MultiVectorStore] Milvus 不可用，跳过插入 {entity_type}")
            return 0

        self.ensure_collection(entity_type)

        if len(embedding) != EMBEDDING_DIM:
            logger.warning(
                f"[MultiVectorStore] 向量维度不匹配: {len(embedding)} != {EMBEDDING_DIM}"
            )
            return 0

        truncated_text = (text or "")[:MAX_TEXT_LENGTH]
        meta_str = json.dumps(metadata or {}, ensure_ascii=False)[:MAX_METADATA_LENGTH]

        try:
            client.insert(
                collection_name=collection_name,
                data=[{
                    "source_id": str(source_id),
                    "entity_type": entity_type,
                    "text": truncated_text,
                    "metadata": meta_str,
                    "embedding": embedding,
                }],
            )
            logger.info(f"[MultiVectorStore] 插入 {entity_type} 向量 source_id={source_id}")
            return 1
        except Exception as e:
            logger.error(f"[MultiVectorStore] 插入失败 {entity_type}: {e}")
            return 0

    async def search(
        self,
        query_vector: List[float],
        entity_types: Optional[List[str]] = None,
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[RetrievalResult]:
        """跨集合向量搜索

        Args:
            query_vector: 查询向量
            entity_types: 要搜索的实体类型列表（None=全部）
            top_k: 每种类型返回数量
            filters: 过滤条件

        Returns:
            合并后的检索结果列表
        """
        types_to_search = entity_types or self.COLLECTION_TYPES
        all_results: List[RetrievalResult] = []

        for et in types_to_search:
            if et == "chunk":
                results = await self._rag_store.search(query_vector, top_k, filters)
                all_results.extend(results)
            else:
                results = await self._search_single_collection(et, query_vector, top_k, filters)
                all_results.extend(results)

        # 按 score 降序排序
        all_results.sort(key=lambda x: x.score, reverse=True)
        for i, r in enumerate(all_results):
            r.rank = i + 1

        logger.info(
            f"[MultiVectorStore] 跨集合搜索完成 types={types_to_search} "
            f"total={len(all_results)}"
        )
        return all_results[:top_k * len(types_to_search)]

    async def _search_single_collection(
        self,
        entity_type: str,
        query_vector: List[float],
        top_k: int,
        filters: Optional[Dict],
    ) -> List[RetrievalResult]:
        """搜索单个集合"""
        collection_name = self._get_collection_name(entity_type)
        client = get_milvus_client(allow_fail=True)
        if client is None:
            return []

        self.ensure_collection(entity_type)

        if len(query_vector) != EMBEDDING_DIM:
            return []

        try:
            # 检查集合是否为空
            stats = client.get_collection_stats(collection_name)
            if stats.get("row_count", 0) == 0:
                return []
        except Exception:
            pass

        try:
            client.load_collection(collection_name)
        except Exception:
            pass

        filter_expr = ""
        if filters:
            parts = []
            for k, v in filters.items():
                if isinstance(v, str):
                    parts.append(f'{k} == "{v}"')
            filter_expr = " and ".join(parts)

        search_kwargs = {
            "collection_name": collection_name,
            "data": [query_vector],
            "limit": top_k,
            "output_fields": ["source_id", "entity_type", "text", "metadata"],
            "search_params": {"metric_type": "COSINE", "params": {"nprobe": 10}},
        }
        if filter_expr:
            search_kwargs["filter"] = filter_expr

        try:
            results = client.search(**search_kwargs)
        except Exception as e:
            logger.error(f"[MultiVectorStore] 搜索 {entity_type} 失败: {e}")
            return []

        retrieval_results: List[RetrievalResult] = []
        if not results or len(results) == 0:
            return retrieval_results

        for hit in results[0]:
            entity = hit.get("entity", {}) if isinstance(hit, dict) else {}
            distance = hit.get("distance", 0.0) if isinstance(hit, dict) else 0.0
            metadata_raw = entity.get("metadata", "{}")
            try:
                metadata = json.loads(metadata_raw) if isinstance(metadata_raw, str) else (metadata_raw or {})
            except Exception:
                metadata = {}

            retrieval_results.append(RetrievalResult(
                chunk_id=metadata.get("chunk_id", ""),
                source_id=str(entity.get("source_id", "")),
                text=entity.get("text", ""),
                score=round(float(distance), 4),
                rank=0,
                chunk_type=entity_type,
                metadata=metadata,
                source_type=entity_type,
            ))

        return retrieval_results

    # ------------------------------------------------------------------
    # 删除
    # ------------------------------------------------------------------

    async def delete_by_source(self, entity_type: str, source_id: str) -> int:
        """删除指定实体的所有向量"""
        if entity_type == "chunk":
            return await self._rag_store.delete_by_source(source_id)

        collection_name = self._get_collection_name(entity_type)
        client = get_milvus_client(allow_fail=True)
        if client is None:
            return 0

        safe_id = str(source_id).replace('"', '\\"')
        filter_expr = f'source_id == "{safe_id}"'
        try:
            client.delete(collection_name, filter=filter_expr)
            logger.info(f"[MultiVectorStore] 删除 {entity_type} source_id={source_id}")
            return 1
        except Exception as e:
            logger.error(f"[MultiVectorStore] 删除失败: {e}")
            return 0

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    async def get_stats(self) -> Dict[str, Any]:
        """获取所有集合的统计"""
        stats: Dict[str, Any] = {}
        for et in self.COLLECTION_TYPES:
            collection_name = self._get_collection_name(et)
            client = get_milvus_client(allow_fail=True)
            if client is None:
                stats[et] = {"available": False, "row_count": 0}
                continue
            try:
                s = client.get_collection_stats(collection_name)
                stats[et] = {
                    "available": True,
                    "collection": collection_name,
                    "row_count": s.get("row_count", 0),
                }
            except Exception as e:
                stats[et] = {"available": False, "error": str(e)}
        return stats


# ===== 单例 =====
_multi_vector_store: Optional[MultiVectorStore] = None


def get_multi_vector_store() -> MultiVectorStore:
    global _multi_vector_store
    if _multi_vector_store is None:
        _multi_vector_store = MultiVectorStore()
    return _multi_vector_store
