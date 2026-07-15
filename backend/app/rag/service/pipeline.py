"""
RAG 管道编排器

一次完成：解析 → Chunk → Embedding → MySQL → Milvus → Neo4j

不发送所有文档给 LLM，而是过滤真正相关的信息。

核心方法：
  - ingest_document: 文件上传入库（完整管道）
  - ingest_text: 文本直接入库
  - query: RAG 查询（查询处理 → 向量检索 → 重排序 → 上下文构建）
  - delete_document: 三库联动删除
  - get_stats: 汇总统计
  - list_documents: 文档列表
"""
import asyncio
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.rag.models import (
    Chunk,
    DocumentStatus,
    DocumentType,
    LoadedDocument,
    RAGQuery,
    RAGResponse,
)
from app.rag.chunker.factory import get_chunker_factory
from app.rag.document_loader.loader_factory import get_loader_factory
from app.rag.embedding.factory import get_embedding_factory
from app.rag.graph_store.factory import get_graph_store
from app.rag.mysql_store.factory import get_mysql_store
from app.rag.query.factory import get_context_builder, get_query_processor
from app.rag.reranker.factory import get_reranker
from app.rag.retriever.factory import get_retriever
from app.rag.vector_store.factory import get_vector_store

logger = logging.getLogger(__name__)


class RAGPipeline:
    """RAG 管道编排器"""

    def __init__(self):
        self._loader_factory = get_loader_factory()
        self._chunker_factory = get_chunker_factory()
        self._embedding_factory = get_embedding_factory()
        self._vector_store = get_vector_store()
        self._mysql_store = get_mysql_store()
        self._graph_store = get_graph_store()
        self._retriever = get_retriever()
        self._reranker = get_reranker()
        self._query_processor = get_query_processor()
        self._context_builder = get_context_builder()

    # ------------------------------------------------------------------
    # 文档入库
    # ------------------------------------------------------------------

    async def ingest_document(
        self,
        file_path: str,
        source_type: str = "",
        project_id: str = "default",
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """文件上传入库（完整管道）

        流程：解析 → Chunk → Embedding → MySQL → Milvus → Neo4j

        Returns:
            包含 source_id, chunk_count, status, errors 等信息的字典
        """
        start_time = time.time()
        file_name = os.path.basename(file_path)
        errors: List[str] = []

        logger.info(f"[RAGPipeline] 开始入库 file={file_name}")

        # 1. 解析文档
        try:
            document = await self._loader_factory.load(file_path)
            if not source_type:
                source_type = document.source_type.value if document.source_type else "unknown"
            document.source_id = str(uuid.uuid4())
            logger.info(
                f"[RAGPipeline] 解析完成 type={source_type} "
                f"content_len={len(document.content)}"
            )
        except Exception as e:
            logger.error(f"[RAGPipeline] 解析失败: {e}")
            return {
                "status": "failed",
                "error": f"文档解析失败: {e}",
                "file_name": file_name,
            }

        # 2. 创建 MySQL 知识源记录
        try:
            source = self._mysql_store.create_source(
                source_type=source_type,
                file_path=file_path,
                file_name=file_name,
                raw_text=document.content,
                project_id=project_id,
                user_id=user_id,
            )
            source_id = source.id
            self._mysql_store.update_source_status(
                source_id, DocumentStatus.LOADING
            )
        except Exception as e:
            logger.error(f"[RAGPipeline] 创建知识源失败: {e}")
            return {
                "status": "failed",
                "error": f"MySQL 记录创建失败: {e}",
                "file_name": file_name,
            }

        # 3. Chunk 分块
        try:
            self._mysql_store.update_source_status(
                source_id, DocumentStatus.CHUNKING
            )
            chunks = self._chunker_factory.chunk_document(document)
            for i, chunk in enumerate(chunks):
                chunk.source_id = str(source_id)
                chunk.metadata["source_type"] = source_type
                chunk.metadata["source_name"] = file_name
                chunk.metadata["project_id"] = project_id
            logger.info(f"[RAGPipeline] 分块完成 count={len(chunks)}")
            self._mysql_store.update_source_status(
                source_id, DocumentStatus.CHUNKED, chunk_count=len(chunks)
            )
        except Exception as e:
            logger.error(f"[RAGPipeline] 分块失败: {e}")
            errors.append(f"分块失败: {e}")
            self._mysql_store.update_source_status(
                source_id, DocumentStatus.FAILED, error_message=str(e)
            )
            return {
                "source_id": source_id,
                "status": "failed",
                "error": str(e),
                "file_name": file_name,
            }

        # 4. Embedding
        try:
            self._mysql_store.update_source_status(
                source_id, DocumentStatus.EMBEDDING
            )
            embedding_provider = self._embedding_factory.get_embedding()
            texts = [c.text for c in chunks]
            # 批量 embedding
            batch_size = 25
            all_embeddings: List[List[float]] = []
            for i in range(0, len(texts), batch_size):
                batch = texts[i : i + batch_size]
                batch_embeddings = await embedding_provider.embed_batch(batch)
                all_embeddings.extend(batch_embeddings)
            for i, emb in enumerate(all_embeddings):
                if i < len(chunks):
                    chunks[i].embedding = emb
            logger.info(
                f"[RAGPipeline] Embedding 完成 count={len(all_embeddings)} "
                f"dim={len(all_embeddings[0]) if all_embeddings else 0}"
            )
            self._mysql_store.update_source_status(
                source_id, DocumentStatus.EMBEDDED
            )
        except Exception as e:
            logger.error(f"[RAGPipeline] Embedding 失败: {e}")
            errors.append(f"Embedding 失败: {e}")

        # 5. MySQL chunk 元数据
        try:
            self._mysql_store.create_chunks(source_id, chunks)
            logger.info(f"[RAGPipeline] MySQL chunk 记录已创建")
        except Exception as e:
            logger.error(f"[RAGPipeline] MySQL chunk 创建失败: {e}")
            errors.append(f"MySQL chunk 失败: {e}")

        # 6. Milvus 向量入库
        milvus_inserted = 0
        try:
            self._mysql_store.update_source_status(
                source_id, DocumentStatus.STORING
            )
            milvus_inserted = await self._vector_store.insert(chunks)
            logger.info(f"[RAGPipeline] Milvus 向量入库 inserted={milvus_inserted}")
        except Exception as e:
            logger.error(f"[RAGPipeline] Milvus 入库失败: {e}")
            errors.append(f"Milvus 失败: {e}")

        # 7. Neo4j 图谱
        try:
            await self._graph_store.create_document_node(
                source_id=str(source_id),
                source_type=source_type,
                file_name=file_name,
                metadata={"project_id": project_id},
            )
            # 创建 chunk 节点 + 实体提取
            for chunk in chunks:
                await self._graph_store.create_chunk_node(
                    chunk_id=chunk.chunk_id,
                    source_id=str(source_id),
                    text=chunk.text,
                    chunk_type=chunk.chunk_type,
                    metadata=chunk.metadata,
                )
                await self._graph_store.extract_and_create_entities(
                    source_id=str(source_id),
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                )
            logger.info(f"[RAGPipeline] Neo4j 图谱节点已创建")
        except Exception as e:
            logger.error(f"[RAGPipeline] Neo4j 入库失败: {e}")
            errors.append(f"Neo4j 失败: {e}")

        # 8. 更新最终状态
        final_status = DocumentStatus.STORED if not errors else DocumentStatus.FAILED
        try:
            self._mysql_store.update_source_status(
                source_id, final_status, chunk_count=len(chunks)
            )
        except Exception:
            pass

        duration = time.time() - start_time
        result = {
            "source_id": source_id,
            "source_type": source_type,
            "file_name": file_name,
            "chunk_count": len(chunks),
            "milvus_inserted": milvus_inserted,
            "status": final_status.value if hasattr(final_status, "value") else str(final_status),
            "duration": round(duration, 2),
            "errors": errors,
        }
        logger.info(f"[RAGPipeline] 入库完成 {result}")
        return result

    async def ingest_chunks(
        self,
        chunks: List[Dict[str, Any]],
        source_type: str = "",
        file_name: str = "",
        project_id: str = "default",
        user_id: Optional[int] = None,
        r2r_document_id: str = "",
    ) -> Dict[str, Any]:
        """已切片数据入库（跳过解析和切片，直接 Embedding + 三库写入）

        R2R 完成文档解析和切片后，此方法接收 R2R 的切片结果，
        完成 Embedding 向量化和 MySQL + Milvus + Neo4j 三库写入。

        流程：
          R2R 切片结果 → Chunk 模型转换 → Embedding → MySQL → Milvus → Neo4j

        Args:
            chunks: R2R 返回的切片列表，每项包含 text, id, metadata 等
            source_type: 来源类型
            file_name: 文件名
            project_id: 项目ID
            user_id: 用户ID
            r2r_document_id: R2R 文档ID（用于追溯）

        Returns:
            包含 source_id, chunk_count, status, errors 等信息的字典
        """
        start_time = time.time()
        errors: List[str] = []
        if not file_name:
            file_name = f"r2r_{r2r_document_id or uuid.uuid4().hex[:8]}"

        logger.info(
            f"[RAGPipeline] 开始切片入库 chunks={len(chunks)} "
            f"file={file_name} r2r_doc={r2r_document_id}"
        )

        # 1. 转换 R2R 切片为项目 Chunk 模型
        try:
            project_chunks: List[Chunk] = []
            for i, r2r_chunk in enumerate(chunks):
                chunk = Chunk(
                    chunk_id=r2r_chunk.get("id", str(uuid.uuid4())),
                    text=r2r_chunk.get("text", ""),
                    chunk_type=r2r_chunk.get("metadata", {}).get("chunk_type", "content"),
                    chunk_index=i,
                    token_count=len(r2r_chunk.get("text", "")) // 2,  # 粗略估算
                    metadata={
                        "source_type": source_type,
                        "source_name": file_name,
                        "project_id": project_id,
                        "r2r_document_id": r2r_document_id,
                        "r2r_chunk_id": r2r_chunk.get("id", ""),
                        **(r2r_chunk.get("metadata") or {}),
                    },
                )
                project_chunks.append(chunk)
            logger.info(f"[RAGPipeline] 切片转换完成 count={len(project_chunks)}")
        except Exception as e:
            logger.error(f"[RAGPipeline] 切片转换失败: {e}")
            return {
                "status": "failed",
                "error": f"切片转换失败: {e}",
                "file_name": file_name,
            }

        # 2. 拼接 raw_text 并创建 MySQL 知识源记录
        raw_text = "\n\n".join(c.text for c in project_chunks)
        try:
            source = self._mysql_store.create_source(
                source_type=source_type,
                file_path="",
                file_name=file_name,
                raw_text=raw_text,
                project_id=project_id,
                user_id=user_id,
            )
            source_id = source.id
            self._mysql_store.update_source_status(source_id, DocumentStatus.LOADING)
        except Exception as e:
            logger.error(f"[RAGPipeline] 创建知识源失败: {e}")
            return {
                "status": "failed",
                "error": f"MySQL 记录创建失败: {e}",
                "file_name": file_name,
            }

        # 设置 source_id
        for chunk in project_chunks:
            chunk.source_id = str(source_id)

        # 3. Embedding（批量）
        try:
            self._mysql_store.update_source_status(source_id, DocumentStatus.EMBEDDING)
            embedding_provider = self._embedding_factory.get_embedding()
            texts = [c.text for c in project_chunks]
            batch_size = 25
            all_embeddings: List[List[float]] = []
            for i in range(0, len(texts), batch_size):
                batch = texts[i: i + batch_size]
                batch_embeddings = await embedding_provider.embed_batch(batch)
                all_embeddings.extend(batch_embeddings)
            for i, emb in enumerate(all_embeddings):
                if i < len(project_chunks):
                    project_chunks[i].embedding = emb
            logger.info(
                f"[RAGPipeline] Embedding 完成 count={len(all_embeddings)} "
                f"dim={len(all_embeddings[0]) if all_embeddings else 0}"
            )
            self._mysql_store.update_source_status(source_id, DocumentStatus.EMBEDDED)
        except Exception as e:
            logger.error(f"[RAGPipeline] Embedding 失败: {e}")
            errors.append(f"Embedding 失败: {e}")

        # 4. MySQL chunk 元数据
        try:
            self._mysql_store.create_chunks(source_id, project_chunks)
            self._mysql_store.update_source_status(
                source_id, DocumentStatus.CHUNKED, chunk_count=len(project_chunks)
            )
            logger.info(f"[RAGPipeline] MySQL chunk 记录已创建")
        except Exception as e:
            logger.error(f"[RAGPipeline] MySQL chunk 创建失败: {e}")
            errors.append(f"MySQL chunk 失败: {e}")

        # 5. Milvus 向量入库
        milvus_inserted = 0
        try:
            self._mysql_store.update_source_status(source_id, DocumentStatus.STORING)
            milvus_inserted = await self._vector_store.insert(project_chunks)
            logger.info(f"[RAGPipeline] Milvus 向量入库 inserted={milvus_inserted}")
        except Exception as e:
            logger.error(f"[RAGPipeline] Milvus 入库失败: {e}")
            errors.append(f"Milvus 失败: {e}")

        # 6. Neo4j 图谱
        try:
            await self._graph_store.create_document_node(
                source_id=str(source_id),
                source_type=source_type,
                file_name=file_name,
                metadata={"project_id": project_id, "r2r_document_id": r2r_document_id},
            )
            for chunk in project_chunks:
                await self._graph_store.create_chunk_node(
                    chunk_id=chunk.chunk_id,
                    source_id=str(source_id),
                    text=chunk.text,
                    chunk_type=chunk.chunk_type,
                    metadata=chunk.metadata,
                )
                await self._graph_store.extract_and_create_entities(
                    source_id=str(source_id),
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                )
            logger.info(f"[RAGPipeline] Neo4j 图谱节点已创建")
        except Exception as e:
            logger.error(f"[RAGPipeline] Neo4j 入库失败: {e}")
            errors.append(f"Neo4j 失败: {e}")

        # 7. 更新最终状态
        final_status = DocumentStatus.STORED if not errors else DocumentStatus.FAILED
        try:
            self._mysql_store.update_source_status(
                source_id, final_status, chunk_count=len(project_chunks)
            )
        except Exception:
            pass

        duration = time.time() - start_time
        result = {
            "source_id": source_id,
            "source_type": source_type,
            "file_name": file_name,
            "chunk_count": len(project_chunks),
            "milvus_inserted": milvus_inserted,
            "r2r_document_id": r2r_document_id,
            "status": final_status.value if hasattr(final_status, "value") else str(final_status),
            "duration": round(duration, 2),
            "errors": errors,
        }
        logger.info(f"[RAGPipeline] 切片入库完成 {result}")
        return result

    async def ingest_text(
        self,
        content: str,
        source_type: str = "text",
        file_name: str = "manual_input",
        project_id: str = "default",
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """文本直接入库"""
        # 将文本写入临时文件，复用 ingest_document
        import tempfile

        suffix = ".txt"
        if source_type == "markdown":
            suffix = ".md"
        elif source_type == "json":
            suffix = ".json"

        tmp_path = os.path.join(tempfile.gettempdir(), f"rag_{uuid.uuid4().hex}{suffix}")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(content)
            return await self.ingest_document(
                file_path=tmp_path,
                source_type=source_type,
                project_id=project_id,
                user_id=user_id,
            )
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # RAG 查询
    # ------------------------------------------------------------------

    async def query(self, rag_query: RAGQuery) -> RAGResponse:
        """RAG 查询

        流程：查询处理 → 向量检索 → 重排序 → 上下文构建

        RAG 的职责：过滤真正相关的信息，不要把所有文档发送给 LLM。
        """
        start_time = time.time()
        logger.info(f"[RAGPipeline] 查询开始 query='{rag_query.query[:50]}'")

        # 1. 查询处理（扩展、优化）
        try:
            processed_query = await self._query_processor.process(rag_query)
            expanded_query = processed_query.filters.get("_expanded_query", rag_query.query)
        except Exception as e:
            logger.warning(f"[RAGPipeline] 查询处理失败，使用原始查询: {e}")
            processed_query = rag_query
            expanded_query = rag_query.query

        # 2. 生成查询向量
        try:
            embedding_provider = self._embedding_factory.get_embedding()
            query_vector = await embedding_provider.embed(rag_query.query)
        except Exception as e:
            logger.error(f"[RAGPipeline] 查询向量生成失败: {e}")
            return RAGResponse(
                query=rag_query.query,
                results=[],
                total_found=0,
                returned=0,
                latency_ms=int((time.time() - start_time) * 1000),
                expanded_query=expanded_query,
                reranked=False,
                context="",
                token_count=0,
            )

        # 3. 检索（混合检索）
        try:
            results = await self._retriever.retrieve(query_vector, processed_query)
        except Exception as e:
            logger.error(f"[RAGPipeline] 检索失败: {e}")
            results = []

        # 4. 重排序
        reranked = False
        if rag_query.rerank and results:
            try:
                rerank_k = min(rag_query.rerank_top_k, len(results))
                results = await self._reranker.rerank(
                    rag_query.query, results, top_k=rerank_k
                )
                reranked = True
            except Exception as e:
                logger.warning(f"[RAGPipeline] 重排序失败: {e}")

        # 5. 构建上下文
        context = self._context_builder.build_context(results)
        token_count = self._context_builder.estimate_tokens(context)

        latency_ms = int((time.time() - start_time) * 1000)

        response = RAGResponse(
            query=rag_query.query,
            results=results,
            total_found=len(results),
            returned=len(results),
            latency_ms=latency_ms,
            expanded_query=expanded_query,
            reranked=reranked,
            context=context,
            token_count=token_count,
        )
        logger.info(
            f"[RAGPipeline] 查询完成 results={len(results)} "
            f"reranked={reranked} latency={latency_ms}ms tokens={token_count}"
        )
        return response

    # ------------------------------------------------------------------
    # 文档管理
    # ------------------------------------------------------------------

    async def delete_document(self, source_id: str) -> Dict[str, Any]:
        """三库联动删除文档

        删除顺序：Milvus → Neo4j → MySQL
        """
        errors: List[str] = []
        source_id_int = int(source_id) if source_id.isdigit() else source_id

        # Milvus
        try:
            milvus_deleted = await self._vector_store.delete_by_source(str(source_id))
        except Exception as e:
            milvus_deleted = 0
            errors.append(f"Milvus 删除失败: {e}")

        # Neo4j
        try:
            await self._graph_store.delete_document(str(source_id))
        except Exception as e:
            errors.append(f"Neo4j 删除失败: {e}")

        # MySQL
        try:
            if isinstance(source_id_int, int):
                self._mysql_store.delete_source(source_id_int)
        except Exception as e:
            errors.append(f"MySQL 删除失败: {e}")

        return {
            "source_id": source_id,
            "milvus_deleted": milvus_deleted,
            "status": "success" if not errors else "partial",
            "errors": errors,
        }

    async def get_stats(self) -> Dict[str, Any]:
        """汇总统计：MySQL + Milvus + Neo4j"""
        stats: Dict[str, Any] = {}
        try:
            stats["mysql"] = self._mysql_store.get_stats()
        except Exception as e:
            stats["mysql"] = {"error": str(e)}

        try:
            stats["milvus"] = await self._vector_store.get_stats()
        except Exception as e:
            stats["milvus"] = {"error": str(e)}

        try:
            stats["neo4j"] = await self._graph_store.get_stats()
        except Exception as e:
            stats["neo4j"] = {"error": str(e)}

        return stats

    async def list_documents(
        self,
        project_id: Optional[str] = None,
        source_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """列出文档"""
        return self._mysql_store.get_sources(
            project_id=project_id,
            source_type=source_type,
            limit=limit,
            offset=offset,
        )

    async def get_document(self, source_id: str) -> Optional[Dict[str, Any]]:
        """获取文档详情（含 chunk 列表）"""
        sid = int(source_id) if source_id.isdigit() else source_id
        source = self._mysql_store.get_source(sid if isinstance(sid, int) else 0)
        if source is None:
            return None
        chunks = self._mysql_store.get_chunks(sid if isinstance(sid, int) else 0)
        return {
            "source": source,
            "chunks": chunks,
        }

    # ------------------------------------------------------------------
    # 批量入库
    # ------------------------------------------------------------------

    async def batch_ingest(
        self,
        file_paths: List[str],
        project_id: str = "default",
        user_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """批量入库"""
        tasks = [
            self.ingest_document(fp, project_id=project_id, user_id=user_id)
            for fp in file_paths
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        formatted: List[Dict[str, Any]] = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                formatted.append({
                    "file_path": file_paths[i],
                    "status": "failed",
                    "error": str(r),
                })
            else:
                formatted.append(r)
        return formatted
