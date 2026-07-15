"""Milvus 向量存储实现

为 RAG 系统提供专用的向量集合 `rag_knowledge_vector`，
与现有的 ui_element_vector / test_case_vector / script_vector 隔离。

支持操作：
- 集合幂等创建（IVF_FLAT 索引, COSINE 距离）
- 批量插入 Chunk 向量
- 向量相似度搜索 + 标量过滤
- 按 source_id 批量删除
- 存储统计

Milvus 不可用时所有方法优雅降级，返回空结果。
"""
import json
import logging
from typing import List, Dict, Any, Optional

from pymilvus import DataType

from app.core.config import settings
from app.db.milvus_client import get_milvus_client
from app.rag.models import Chunk, RetrievalResult
from app.rag.vector_store.base import BaseVectorStore

logger = logging.getLogger(__name__)

# RAG 专用向量集合名称（与现有集合隔离）
RAG_COLLECTION_NAME = "rag_knowledge_vector"

# 向量维度
EMBEDDING_DIM = settings.EMBEDDING_DIM

# VARCHAR 字段长度上限
MAX_TEXT_LENGTH = 8192
MAX_METADATA_LENGTH = 4096
MAX_VARCHAR_LENGTH = 256

# 批量插入大小
BATCH_SIZE = 100


class MilvusVectorStore(BaseVectorStore):
    """Milvus 向量存储

    使用 MilvusClient（Lite / Standalone 均可）管理 RAG 向量集合。
    所有方法均为 async，Milvus 不可用时返回安全默认值。
    """

    def __init__(self, collection_name: str = RAG_COLLECTION_NAME):
        self.collection_name = collection_name
        self._dim = EMBEDDING_DIM
        self._initialized = False

    # ------------------------------------------------------------------
    # 集合管理
    # ------------------------------------------------------------------

    def ensure_collection(self) -> bool:
        """幂等创建 RAG 向量集合

        Returns:
            True 表示集合可用，False 表示 Milvus 不可用或创建失败
        """
        client = get_milvus_client(allow_fail=True)
        if client is None:
            logger.warning("[MilvusVectorStore] Milvus 不可用，跳过集合创建")
            return False

        try:
            if client.has_collection(self.collection_name):
                logger.debug(f"[MilvusVectorStore] 集合 {self.collection_name} 已存在")
                self._initialized = True
                return True

            # 构建 schema（自增主键）
            schema = client.create_schema(auto_id=True, enable_dynamic_field=False)
            schema.add_field(
                field_name="id",
                datatype=DataType.INT64,
                is_primary=True,
                description="自增主键",
            )
            schema.add_field(
                field_name="source_id",
                datatype=DataType.VARCHAR,
                max_length=MAX_VARCHAR_LENGTH,
                description="知识来源ID",
            )
            schema.add_field(
                field_name="chunk_id",
                datatype=DataType.VARCHAR,
                max_length=MAX_VARCHAR_LENGTH,
                description="分块唯一ID（UUID）",
            )
            schema.add_field(
                field_name="source_type",
                datatype=DataType.VARCHAR,
                max_length=64,
                description="文档类型",
            )
            schema.add_field(
                field_name="chunk_type",
                datatype=DataType.VARCHAR,
                max_length=64,
                description="分块类型",
            )
            schema.add_field(
                field_name="chunk_index",
                datatype=DataType.INT64,
                description="分块序号",
            )
            schema.add_field(
                field_name="text",
                datatype=DataType.VARCHAR,
                max_length=MAX_TEXT_LENGTH,
                description="分块文本",
            )
            schema.add_field(
                field_name="metadata",
                datatype=DataType.VARCHAR,
                max_length=MAX_METADATA_LENGTH,
                description="分块元数据（JSON 字符串）",
            )
            schema.add_field(
                field_name="embedding",
                datatype=DataType.FLOAT_VECTOR,
                dim=self._dim,
                description="向量嵌入",
            )

            # 构建索引
            index_params = client.prepare_index_params()
            index_params.add_index(
                field_name="embedding",
                index_type="IVF_FLAT",
                metric_type="COSINE",
                index_name="rag_embedding_index",
                params={"nlist": 128},
            )

            # 创建集合
            client.create_collection(
                collection_name=self.collection_name,
                schema=schema,
                index_params=index_params,
            )
            self._initialized = True
            logger.info(
                f"[MilvusVectorStore] 集合 {self.collection_name} 创建成功 | dim={self._dim}"
            )
            return True

        except Exception as e:
            logger.error(f"[MilvusVectorStore] 创建集合失败: {e}")
            return False

    def _get_client(self):
        """获取 Milvus 客户端，确保集合存在"""
        client = get_milvus_client(allow_fail=True)
        if client is None:
            return None
        if not self._initialized:
            self.ensure_collection()
        return client

    # ------------------------------------------------------------------
    # 过滤表达式构建
    # ------------------------------------------------------------------

    @staticmethod
    def _build_filter(filters: Optional[Dict[str, Any]]) -> str:
        """将 filters 字典构建为 Milvus filter 表达式

        支持:
            {"source_type": "requirement"}  -> source_type == "requirement"
            {"source_type": ["a", "b"]}     -> source_type in ["a", "b"]
            {"chunk_type": "content", "source_type": "design"}
                                           -> chunk_type == "content" and source_type == "design"
        """
        if not filters:
            return ""

        parts = []
        for key, value in filters.items():
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                if len(value) == 0:
                    continue
                items = ", ".join(f'"{v}"' for v in value)
                parts.append(f'{key} in [{items}]')
            elif isinstance(value, (int, float)):
                parts.append(f"{key} == {value}")
            else:
                # 字符串
                escaped = str(value).replace('"', '\\"')
                parts.append(f'{key} == "{escaped}"')

        return " and ".join(parts)

    # ------------------------------------------------------------------
    # BaseVectorStore 实现
    # ------------------------------------------------------------------

    async def insert(self, chunks: List[Chunk]) -> int:
        """批量插入向量

        仅插入含有有效 embedding 的 chunk，跳过无向量或维度不符的 chunk。
        """
        if not chunks:
            return 0

        client = self._get_client()
        if client is None:
            logger.warning("[MilvusVectorStore] Milvus 不可用，跳过插入")
            return 0

        # 构建数据行
        data = []
        skipped = 0
        for chunk in chunks:
            embedding = chunk.embedding or []
            if len(embedding) != self._dim:
                logger.debug(
                    f"[MilvusVectorStore] 跳过 chunk {chunk.chunk_id}："
                    f"向量维度 {len(embedding)} != {self._dim}"
                )
                skipped += 1
                continue

            text = chunk.text or ""
            if len(text) > MAX_TEXT_LENGTH:
                text = text[:MAX_TEXT_LENGTH]

            metadata_str = json.dumps(
                {**chunk.metadata, "chunk_id": chunk.chunk_id},
                ensure_ascii=False,
            )
            if len(metadata_str) > MAX_METADATA_LENGTH:
                metadata_str = metadata_str[:MAX_METADATA_LENGTH]

            data.append(
                {
                    "source_id": str(chunk.source_id or ""),
                    "chunk_id": str(chunk.chunk_id or ""),
                    "source_type": str(chunk.metadata.get("source_type", "")),
                    "chunk_type": str(chunk.chunk_type or ""),
                    "chunk_index": int(chunk.chunk_index or 0),
                    "text": text,
                    "metadata": metadata_str,
                    "embedding": embedding,
                }
            )

        if not data:
            logger.warning(
                f"[MilvusVectorStore] 无有效向量可插入 | total={len(chunks)} skipped={skipped}"
            )
            return 0

        # 分批插入
        inserted = 0
        for i in range(0, len(data), BATCH_SIZE):
            batch = data[i : i + BATCH_SIZE]
            try:
                client.insert(collection_name=self.collection_name, data=batch)
                inserted += len(batch)
            except Exception as e:
                logger.error(
                    f"[MilvusVectorStore] 批量插入失败 | batch={i}-{i+len(batch)}: {e}"
                )

        logger.info(
            f"[MilvusVectorStore] 插入完成 | inserted={inserted} skipped={skipped}"
        )
        return inserted

    async def search(
        self,
        query_vector: List[float],
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[RetrievalResult]:
        """向量相似度搜索

        Args:
            query_vector: 查询向量
            top_k: 返回数量
            filters: 标量过滤条件

        Returns:
            检索结果列表，按相似度降序排列
        """
        client = self._get_client()
        if client is None:
            logger.warning("[MilvusVectorStore] Milvus 不可用，返回空结果")
            return []

        # 校验向量维度
        if len(query_vector) != self._dim:
            logger.error(
                f"[MilvusVectorStore] 查询向量维度不匹配: "
                f"{len(query_vector)} != {self._dim}"
            )
            return []

        # 检查集合是否为空
        try:
            stats = client.get_collection_stats(self.collection_name)
            if stats.get("row_count", 0) == 0:
                logger.debug("[MilvusVectorStore] 集合为空，返回空结果")
                return []
        except Exception as e:
            logger.warning(f"[MilvusVectorStore] 获取集合统计失败: {e}")

        # 加载集合
        try:
            client.load_collection(self.collection_name)
        except Exception:
            pass  # 可能已加载

        # 构建过滤表达式
        filter_expr = self._build_filter(filters)

        # 执行搜索
        try:
            search_kwargs = {
                "collection_name": self.collection_name,
                "data": [query_vector],
                "limit": top_k,
                "output_fields": [
                    "source_id",
                    "chunk_id",
                    "source_type",
                    "chunk_type",
                    "chunk_index",
                    "text",
                    "metadata",
                ],
                "search_params": {"metric_type": "COSINE", "params": {"nprobe": 10}},
            }
            if filter_expr:
                search_kwargs["filter"] = filter_expr

            results = client.search(**search_kwargs)
        except Exception as e:
            logger.error(f"[MilvusVectorStore] 搜索失败: {e}")
            return []

        # 解析结果
        retrieval_results: List[RetrievalResult] = []
        if not results or len(results) == 0:
            return retrieval_results

        rank = 0
        for hit in results[0]:
            rank += 1
            entity = hit.get("entity", {}) if isinstance(hit, dict) else {}
            distance = (
                hit.get("distance", 0.0) if isinstance(hit, dict) else 0.0
            )

            # 解析 metadata JSON
            metadata_raw = entity.get("metadata", "{}")
            try:
                metadata = (
                    json.loads(metadata_raw)
                    if isinstance(metadata_raw, str)
                    else (metadata_raw or {})
                )
            except (json.JSONDecodeError, TypeError):
                metadata = {}

            # 确保 chunk_id 也在 metadata 中
            chunk_id = entity.get("chunk_id", "") or metadata.get("chunk_id", "")

            retrieval_results.append(
                RetrievalResult(
                    chunk_id=chunk_id,
                    source_id=str(entity.get("source_id", "")),
                    text=entity.get("text", ""),
                    score=round(float(distance), 4),
                    rank=rank,
                    chunk_type=entity.get("chunk_type", ""),
                    metadata=metadata,
                    source_type=entity.get("source_type", ""),
                    source_name=metadata.get("source_name", ""),
                )
            )

        logger.info(
            f"[MilvusVectorStore] 搜索完成 | results={len(retrieval_results)} "
            f"top_k={top_k} has_filter={bool(filter_expr)}"
        )
        return retrieval_results

    async def delete_by_source(self, source_id: str) -> int:
        """按 source_id 删除所有相关向量

        Returns:
            删除的向量数量（尽力统计，查询失败时返回 0）
        """
        client = self._get_client()
        if client is None:
            logger.warning("[MilvusVectorStore] Milvus 不可用，跳过删除")
            return 0

        if not source_id:
            return 0

        safe_id = str(source_id).replace('"', '\\"')
        filter_expr = f'source_id == "{safe_id}"'

        # 先查询数量（尽力统计）
        count = 0
        try:
            count_result = client.query(
                collection_name=self.collection_name,
                filter=filter_expr,
                output_fields=["id"],
                limit=16384,
            )
            count = len(count_result) if count_result else 0
        except Exception as e:
            logger.debug(f"[MilvusVectorStore] 查询待删除数量失败: {e}")

        # 执行删除
        try:
            client.delete(self.collection_name, filter=filter_expr)
            logger.info(
                f"[MilvusVectorStore] 删除完成 | source_id={source_id} count={count}"
            )
        except Exception as e:
            logger.error(
                f"[MilvusVectorStore] 删除失败 | source_id={source_id}: {e}"
            )
            return 0

        return count

    async def get_stats(self) -> Dict[str, Any]:
        """获取存储统计信息"""
        client = self._get_client()
        if client is None:
            return {
                "available": False,
                "collection": self.collection_name,
                "row_count": 0,
                "dim": self._dim,
            }

        row_count = 0
        available = True
        try:
            stats = client.get_collection_stats(self.collection_name)
            row_count = stats.get("row_count", 0)
        except Exception as e:
            logger.warning(f"[MilvusVectorStore] 获取统计失败: {e}")
            available = False

        return {
            "available": available,
            "collection": self.collection_name,
            "row_count": row_count,
            "dim": self._dim,
            "index_type": "IVF_FLAT",
            "metric_type": "COSINE",
        }
