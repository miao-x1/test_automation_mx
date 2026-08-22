"""
KnowledgeCenterService - 知识中心服务

提供知识库管理功能：
  - 集合管理：列出/统计/清空向量集合
  - 文档管理：列表/详情/删除
  - Chunk查看：按文档查看分片
  - Embedding状态：检查向量化状态
  - Graph查看：查看Neo4j图谱节点和关系
  - 重建Embedding：重新向量化文档
  - 重新分块：重新切分文档
  - 重新索引：完整重建（分块+向量化+图谱）
  - 搜索测试：全文检索/语义检索/混合检索
"""
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from app.db.database import SessionLocal
from app.models.knowledge_source import KnowledgeSource, KnowledgeSourceStatus
from app.models.knowledge_chunk import KnowledgeChunk
from app.rag.mysql_store.store import MySQLStore
from app.rag.vector_store.multi_vector_store import get_multi_vector_store
from app.rag.graph_store.extended_store import get_extended_graph_store
from app.db.neo4j_client import is_available as neo4j_is_available
from app.rag.embedding.factory import get_embedding_factory

logger = logging.getLogger(__name__)


class KnowledgeCenterService:
    """知识中心服务"""

    def __init__(self):
        self._mysql = MySQLStore()
        self._vector_store = get_multi_vector_store()
        self._graph = get_extended_graph_store()

    # ------------------------------------------------------------------
    # 集合管理
    # ------------------------------------------------------------------

    async def list_collections(self) -> Dict[str, Any]:
        """列出所有向量集合及其状态"""
        collections = []
        collection_types = self._vector_store.COLLECTION_TYPES
        for ct in collection_types:
            coll_name = self._vector_store._get_collection_name(ct)
            info = {
                "entity_type": ct,
                "collection_name": coll_name,
                "available": False,
                "row_count": 0,
            }
            try:
                client = self._vector_store._rag_store.client if ct == "chunk" else None
                if client is None:
                    from app.db.milvus_client import get_milvus_client
                    client = get_milvus_client(allow_fail=True)
                if client is not None:
                    info["available"] = True
                    if client.has_collection(coll_name):
                        stats = client.get_collection_stats(coll_name)
                        info["row_count"] = stats.get("row_count", 0)
            except Exception as e:
                info["error"] = str(e)
            collections.append(info)

        return {
            "status": "success",
            "collections": collections,
            "total": len(collections),
        }

    async def get_collection_detail(self, entity_type: str) -> Dict[str, Any]:
        """获取单个集合详情"""
        coll_name = self._vector_store._get_collection_name(entity_type)
        info = {
            "entity_type": entity_type,
            "collection_name": coll_name,
            "available": False,
            "row_count": 0,
            "entities": [],
        }
        try:
            from app.db.milvus_client import get_milvus_client
            client = get_milvus_client(allow_fail=True)
            if client is not None:
                info["available"] = True
                if client.has_collection(coll_name):
                    stats = client.get_collection_stats(coll_name)
                    info["row_count"] = stats.get("row_count", 0)
                    # 尝试获取部分数据
                    try:
                        results = client.query(coll_name, "", limit=20, output_fields=["source_id", "entity_type", "text"])
                        info["entities"] = [
                            {
                                "source_id": r.get("source_id", ""),
                                "text": (r.get("text", "") or "")[:200],
                            }
                            for r in results
                        ]
                    except Exception:
                        pass
        except Exception as e:
            info["error"] = str(e)

        return info

    async def clear_collection(self, entity_type: str) -> Dict[str, Any]:
        """清空指定集合"""
        coll_name = self._vector_store._get_collection_name(entity_type)
        try:
            from app.db.milvus_client import get_milvus_client
            client = get_milvus_client(allow_fail=True)
            if client is None:
                return {"status": "error", "message": "Milvus不可用"}
            if client.has_collection(coll_name):
                client.drop_collection(coll_name)
                # 重新创建空集合
                self._vector_store._initialized[entity_type] = False
                self._vector_store.ensure_collection(entity_type)
                return {"status": "success", "message": f"集合 {coll_name} 已清空"}
            return {"status": "not_found", "message": f"集合 {coll_name} 不存在"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ------------------------------------------------------------------
    # 文档管理
    # ------------------------------------------------------------------

    async def list_documents(
        self,
        project_id: str = "",
        source_type: str = "",
        status: str = "",
        keyword: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """文档列表"""
        sources = self._mysql.get_sources(
            project_id=project_id or None,
            source_type=source_type or None,
            status=status or None,
            limit=limit,
            offset=offset,
        )
        # 关键词过滤
        if keyword:
            kw_lower = keyword.lower()
            sources = [
                s for s in sources
                if kw_lower in (s.get("source_type", "")).lower()
                or kw_lower in (s.get("file_path", "") or "").lower()
                or kw_lower in (s.get("raw_text", "") or "").lower()
            ]
        return {
            "status": "success",
            "documents": sources,
            "total": len(sources),
        }

    async def get_document_detail(self, source_id: int) -> Dict[str, Any]:
        """文档详情（含 chunk 列表）"""
        source = self._mysql.get_source(source_id)
        if source is None:
            return {"status": "not_found", "message": f"文档 {source_id} 不存在"}
        chunks = self._mysql.get_chunks(source_id)
        return {
            "status": "success",
            "document": source,
            "chunks": chunks,
            "chunk_count": len(chunks),
        }

    async def delete_document(self, source_id: int) -> Dict[str, Any]:
        """删除文档（三库联动）"""
        source = self._mysql.get_source(source_id)
        if source is None:
            return {"status": "not_found", "message": f"文档 {source_id} 不存在"}

        errors = []

        # 1. 删除 Milvus 向量
        try:
            deleted = await self._vector_store.delete_by_source("chunk", str(source_id))
            logger.info(f"[KnowledgeCenter] Milvus删除: {deleted} 条")
        except Exception as e:
            errors.append(f"Milvus删除失败: {e}")

        # 2. 删除 Neo4j 节点
        try:
            if neo4j_is_available():
                await self._graph.delete_entity("KnowledgeDocument", str(source_id))
                logger.info(f"[KnowledgeCenter] Neo4j节点已删除")
        except Exception as e:
            errors.append(f"Neo4j删除失败: {e}")

        # 3. 删除 MySQL 记录
        try:
            self._mysql.delete_source(source_id)
            logger.info(f"[KnowledgeCenter] MySQL记录已删除")
        except Exception as e:
            errors.append(f"MySQL删除失败: {e}")

        return {
            "status": "success" if not errors else "partial",
            "message": f"文档 {source_id} 已删除",
            "errors": errors,
        }

    # ------------------------------------------------------------------
    # Chunk 查看
    # ------------------------------------------------------------------

    async def list_chunks(
        self,
        source_id: int,
        chunk_type: str = "",
        limit: int = 100,
    ) -> Dict[str, Any]:
        """查看文档的分片列表"""
        chunks = self._mysql.get_chunks(source_id)
        if chunk_type:
            chunks = [c for c in chunks if c.get("chunk_type") == chunk_type]
        chunks = chunks[:limit]
        return {
            "status": "success",
            "chunks": chunks,
            "total": len(chunks),
        }

    async def get_chunk_detail(self, chunk_id: int) -> Dict[str, Any]:
        """单个 chunk 详情"""
        db = SessionLocal()
        try:
            chunk = db.query(KnowledgeChunk).filter_by(id=chunk_id).first()
            if chunk is None:
                return {"status": "not_found", "message": f"Chunk {chunk_id} 不存在"}
            return {
                "status": "success",
                "chunk": {
                    "id": chunk.id,
                    "knowledge_source_id": chunk.knowledge_source_id,
                    "milvus_id": chunk.milvus_id,
                    "chunk_type": chunk.chunk_type,
                    "text": chunk.text,
                    "metadata": chunk.chunk_metadata if isinstance(chunk.chunk_metadata, dict) else {},
                    "created_at": chunk.created_at.isoformat() if chunk.created_at else None,
                },
            }
        finally:
            db.close()

    # ------------------------------------------------------------------
    # Embedding 状态
    # ------------------------------------------------------------------

    async def get_embedding_status(self, source_id: int) -> Dict[str, Any]:
        """检查文档的 Embedding 状态"""
        source = self._mysql.get_source(source_id)
        if source is None:
            return {"status": "not_found", "message": f"文档 {source_id} 不存在"}

        chunks = self._mysql.get_chunks(source_id)
        total_chunks = len(chunks)
        embedded_count = sum(1 for c in chunks if c.get("milvus_id", 0) > 0)
        unembedded = [c for c in chunks if c.get("milvus_id", 0) == 0]

        return {
            "status": "success",
            "source_id": source_id,
            "document_status": source.get("status"),
            "total_chunks": total_chunks,
            "embedded_count": embedded_count,
            "unembedded_count": len(unembedded),
            "embedding_progress": f"{embedded_count}/{total_chunks}" if total_chunks > 0 else "0/0",
            "embedding_ratio": round(embedded_count / total_chunks, 2) if total_chunks > 0 else 0,
            "unembedded_chunks": [{"id": c["id"], "chunk_type": c.get("chunk_type", "")} for c in unembedded[:20]],
        }

    # ------------------------------------------------------------------
    # Graph 查看
    # ------------------------------------------------------------------

    async def get_graph_overview(self) -> Dict[str, Any]:
        """Neo4j 图谱总览"""
        try:
            if not neo4j_is_available():
                return {"status": "unavailable", "message": "Neo4j不可用"}
            stats = await self._graph.get_full_stats()
            return {
                "status": "success",
                "stats": stats,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def get_graph_nodes(
        self,
        label: str = "",
        limit: int = 50,
    ) -> Dict[str, Any]:
        """查看图谱节点"""
        try:
            if not neo4j_is_available():
                return {"status": "unavailable", "message": "Neo4j不可用"}

            from app.db.neo4j_client import get_driver
            driver = get_driver()
            if driver is None:
                return {"status": "unavailable", "message": "Neo4j驱动不可用"}

            with driver.session() as session:
                if label:
                    query = f"MATCH (n:{label}) RETURN n LIMIT $limit"
                    result = session.run(query, limit=limit)
                else:
                    query = "MATCH (n) RETURN labels(n) as labels, count(n) as count"
                    result = session.run(query)
                    counts = []
                    for record in result:
                        labels = record["labels"]
                        count = record["count"]
                        counts.append({"label": labels[0] if labels else "Unknown", "count": count})
                    return {"status": "success", "node_counts": counts}

            # 获取具体节点
            nodes = []
            for record in result:
                node = record["n"]
                nodes.append({
                    "id": node.id,
                    "labels": list(node.labels),
                    "properties": dict(node),
                })

            return {
                "status": "success",
                "nodes": nodes,
                "total": len(nodes),
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def get_graph_relations(
        self,
        label: str,
        entity_id: str,
        depth: int = 2,
    ) -> Dict[str, Any]:
        """查看实体的关系图"""
        try:
            if not neo4j_is_available():
                return {"status": "unavailable", "message": "Neo4j不可用"}

            relations = await self._graph.get_entity_relations(label, entity_id, depth=depth)
            return {
                "status": "success",
                "relations": relations,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ------------------------------------------------------------------
    # 重建操作
    # ------------------------------------------------------------------

    async def rebuild_embedding(self, source_id: int) -> Dict[str, Any]:
        """重建文档的 Embedding

        1. 获取所有 chunk
        2. 重新生成向量
        3. 重新插入 Milvus
        4. 更新 chunk 的 milvus_id
        """
        start_time = time.time()
        source = self._mysql.get_source(source_id)
        if source is None:
            return {"status": "not_found", "message": f"文档 {source_id} 不存在"}

        chunks = self._mysql.get_chunks(source_id)
        if not chunks:
            return {"status": "empty", "message": "文档无分片"}

        # 删除旧向量
        try:
            await self._vector_store.delete_by_source("chunk", str(source_id))
        except Exception as e:
            logger.warning(f"[KnowledgeCenter] 删除旧向量失败: {e}")

        # 重新生成向量
        embedding_model = get_embedding_factory().get_embedding()
        embedded_count = 0
        errors = []

        db = SessionLocal()
        try:
            for chunk in chunks:
                text = chunk.get("text", "")
                if not text:
                    continue
                try:
                    # 生成向量
                    vector = await embedding_model.embed(text)

                    # 插入 Milvus
                    milvus_id = await self._vector_store.insert_vector(
                        entity_type="chunk",
                        source_id=str(source_id),
                        text=text[:8192],
                        embedding=vector,
                        metadata={
                            "source_id": str(source_id),
                            "chunk_type": chunk.get("chunk_type", ""),
                        },
                    )

                    if milvus_id > 0:
                        # 更新 MySQL chunk 的 milvus_id
                        kc = db.query(KnowledgeChunk).filter_by(id=chunk["id"]).first()
                        if kc:
                            kc.milvus_id = milvus_id
                            db.commit()
                        embedded_count += 1
                except Exception as e:
                    errors.append(f"Chunk {chunk['id']} embedding失败: {e}")
        finally:
            db.close()

        duration = time.time() - start_time
        return {
            "status": "success" if not errors else "partial",
            "source_id": source_id,
            "total_chunks": len(chunks),
            "embedded_count": embedded_count,
            "errors": errors,
            "duration": round(duration, 2),
        }

    async def rechunk_document(self, source_id: int, chunk_size: int = 500) -> Dict[str, Any]:
        """重新分块文档"""
        start_time = time.time()
        source = self._mysql.get_source(source_id)
        if source is None:
            return {"status": "not_found", "message": f"文档 {source_id} 不存在"}

        # 获取原始文本
        raw_text = source.get("raw_text", "")
        if not raw_text:
            file_path = source.get("file_path", "")
            if file_path and os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    raw_text = f.read()
        if not raw_text:
            return {"status": "empty", "message": "文档无文本内容"}

        # 删除旧 chunks
        db = SessionLocal()
        try:
            db.query(KnowledgeChunk).filter(
                KnowledgeChunk.knowledge_source_id == source_id
            ).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()

        # 重新分块
        from app.rag.chunker.factory import get_chunker
        chunker = get_chunker("recursive")
        from app.rag.models import Chunk
        chunks: List[Chunk] = chunker.chunk(raw_text, chunk_size=chunk_size, overlap=50)

        # 保存到 MySQL
        created_ids = self._mysql.create_chunks(source_id, chunks)

        # 更新文档状态
        self._mysql.update_source_status(source_id, KnowledgeSourceStatus.INDEXED, chunk_count=len(chunks))

        duration = time.time() - start_time
        return {
            "status": "success",
            "source_id": source_id,
            "chunk_count": len(chunks),
            "chunk_ids": created_ids,
            "duration": round(duration, 2),
        }

    async def reindex_document(self, source_id: int, chunk_size: int = 500) -> Dict[str, Any]:
        """完整重新索引（分块 + Embedding + 图谱）"""
        start_time = time.time()
        errors = []

        # 1. 重新分块
        try:
            rechunk_result = await self.rechunk_document(source_id, chunk_size)
            if rechunk_result.get("status") != "success":
                errors.append(f"重新分块失败: {rechunk_result.get('message', '')}")
        except Exception as e:
            errors.append(f"重新分块异常: {e}")
            rechunk_result = {"chunk_count": 0}

        # 2. 重建 Embedding
        try:
            embed_result = await self.rebuild_embedding(source_id)
            if embed_result.get("status") not in ("success", "partial"):
                errors.append(f"重建Embedding失败: {embed_result.get('message', '')}")
        except Exception as e:
            errors.append(f"重建Embedding异常: {e}")
            embed_result = {"embedded_count": 0}

        # 3. 更新 Neo4j 图谱
        try:
            if neo4j_is_available():
                source = self._mysql.get_source(source_id)
                if source:
                    await self._graph.create_node(
                        "KnowledgeDocument",
                        str(source_id),
                        id_field="source_id",
                        properties={
                            "source_type": source.get("source_type", ""),
                            "status": source.get("status", ""),
                        },
                    )
        except Exception as e:
            errors.append(f"图谱更新失败: {e}")

        duration = time.time() - start_time
        return {
            "status": "success" if not errors else "partial",
            "source_id": source_id,
            "chunk_count": rechunk_result.get("chunk_count", 0),
            "embedded_count": embed_result.get("embedded_count", 0),
            "errors": errors,
            "duration": round(duration, 2),
        }

    # ------------------------------------------------------------------
    # 搜索测试
    # ------------------------------------------------------------------

    async def fulltext_search(
        self,
        keyword: str,
        source_type: str = "",
        limit: int = 20,
    ) -> Dict[str, Any]:
        """全文检索（MySQL LIKE 搜索）"""
        start_time = time.time()
        db = SessionLocal()
        try:
            q = db.query(KnowledgeChunk).join(
                KnowledgeSource,
                KnowledgeChunk.knowledge_source_id == KnowledgeSource.id,
            )
            if keyword:
                q = q.filter(KnowledgeChunk.text.contains(keyword))
            if source_type:
                q = q.filter(KnowledgeSource.source_type == source_type)
            q = q.limit(limit)
            results = []
            for chunk in q.all():
                source = db.query(KnowledgeSource).filter_by(id=chunk.knowledge_source_id).first()
                results.append({
                    "chunk_id": chunk.id,
                    "source_id": chunk.knowledge_source_id,
                    "source_type": source.source_type if source else "",
                    "chunk_type": chunk.chunk_type,
                    "text": (chunk.text or "")[:500],
                    "milvus_id": chunk.milvus_id,
                    "score": 1.0,  # 全文检索无分数
                })

            duration = time.time() - start_time
            return {
                "status": "success",
                "search_type": "fulltext",
                "keyword": keyword,
                "results": results,
                "total": len(results),
                "duration": round(duration, 3),
            }
        finally:
            db.close()

    async def semantic_search(
        self,
        query: str,
        entity_types: List[str] = None,
        top_k: int = 10,
    ) -> Dict[str, Any]:
        """语义检索（向量搜索）"""
        start_time = time.time()

        # 生成查询向量
        embedding_model = get_embedding_factory().get_embedding()
        try:
            query_vector = await embedding_model.embed(query)
        except Exception as e:
            return {"status": "error", "message": f"Embedding失败: {e}"}

        # 向量搜索
        if entity_types is None:
            entity_types = ["chunk"]

        try:
            results = await self._vector_store.search(
                query_vector=query_vector,
                entity_types=entity_types,
                top_k=top_k,
            )
        except Exception as e:
            return {"status": "error", "message": f"向量搜索失败: {e}"}

        # 补充 MySQL 元数据
        formatted = []
        for r in results:
            formatted.append({
                "source_id": r.source_id,
                "entity_type": r.entity_type,
                "text": r.text[:500],
                "score": round(r.score, 4),
                "metadata": r.metadata,
            })

        duration = time.time() - start_time
        return {
            "status": "success",
            "search_type": "semantic",
            "query": query,
            "results": formatted,
            "total": len(formatted),
            "duration": round(duration, 3),
        }

    async def hybrid_search(
        self,
        keyword: str,
        query: str = "",
        entity_types: List[str] = None,
        top_k: int = 10,
    ) -> Dict[str, Any]:
        """混合检索（全文 + 语义融合）"""
        start_time = time.time()
        if entity_types is None:
            entity_types = ["chunk"]

        # 1. 全文检索
        fulltext_results = []
        try:
            ft = await self.fulltext_search(keyword, limit=top_k * 2)
            fulltext_results = ft.get("results", [])
        except Exception as e:
            logger.warning(f"[KnowledgeCenter] 全文检索失败: {e}")

        # 2. 语义检索
        semantic_results = []
        if query:
            try:
                sem = await self.semantic_search(query, entity_types, top_k=top_k * 2)
                semantic_results = sem.get("results", [])
            except Exception as e:
                logger.warning(f"[KnowledgeCenter] 语义检索失败: {e}")

        # 3. 融合排序（RRF算法 - Reciprocal Rank Fusion）
        rrf_scores: Dict[str, float] = {}
        rrf_data: Dict[str, Dict] = {}

        for rank, r in enumerate(fulltext_results):
            key = f"ft_{r.get('chunk_id', '')}"
            rrf_scores[key] = rrf_scores.get(key, 0) + 1.0 / (rank + 1)
            rrf_data[key] = {**r, "search_type": "fulltext"}

        for rank, r in enumerate(semantic_results):
            key = f"sem_{r.get('source_id', '')}"
            rrf_scores[key] = rrf_scores.get(key, 0) + 1.0 / (rank + 1)
            rrf_data[key] = {**r, "search_type": "semantic"}

        # 排序
        sorted_keys = sorted(rrf_scores.keys(), key=lambda k: rrf_scores[k], reverse=True)
        merged = []
        for key in sorted_keys[:top_k]:
            item = rrf_data[key]
            item["hybrid_score"] = round(rrf_scores[key], 4)
            merged.append(item)

        duration = time.time() - start_time
        return {
            "status": "success",
            "search_type": "hybrid",
            "keyword": keyword,
            "query": query,
            "results": merged,
            "total": len(merged),
            "fulltext_count": len(fulltext_results),
            "semantic_count": len(semantic_results),
            "duration": round(duration, 3),
        }

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    async def get_center_stats(self) -> Dict[str, Any]:
        """知识中心总览统计"""
        mysql_stats = self._mysql.get_stats()

        # Milvus 统计
        milvus_stats = {"available": False}
        try:
            raw_stats = await self._vector_store.get_stats()
            # 将分类型字典 {chunk:{available,...}, page:{...}} 转换为前端期望的 {available, collections} 格式
            collections = []
            any_available = False
            if isinstance(raw_stats, dict):
                for entity_type, stat in raw_stats.items():
                    if isinstance(stat, dict) and stat.get("available"):
                        any_available = True
                        collections.append({
                            "entity_type": entity_type,
                            "collection": stat.get("collection", ""),
                            "row_count": stat.get("row_count", 0),
                        })
                    elif isinstance(stat, dict):
                        collections.append({
                            "entity_type": entity_type,
                            "row_count": stat.get("row_count", 0),
                            "available": False,
                        })
            milvus_stats = {
                "available": any_available,
                "collections": collections,
            }
        except Exception as e:
            milvus_stats = {"available": False, "error": str(e)}

        # Neo4j 统计
        neo4j_stats = {"available": False}
        try:
            if neo4j_is_available():
                neo4j_stats = await self._graph.get_full_stats()
        except Exception as e:
            neo4j_stats = {"available": False, "error": str(e)}

        return {
            "status": "success",
            "mysql": mysql_stats,
            "milvus": milvus_stats,
            "neo4j": neo4j_stats,
        }


# ===== 单例 =====
_service: Optional[KnowledgeCenterService] = None


def get_knowledge_center_service() -> KnowledgeCenterService:
    global _service
    if _service is None:
        _service = KnowledgeCenterService()
    return _service
