"""
KnowledgePipeline - 知识入库管道

职责：
  统一编排知识入库流程，协调 R2R（预处理）+ RAGPipeline（三库写入）。

流程：
  用户上传文档
       ↓
  KnowledgePipeline.ingest()
       ↓
  ┌──────────────────────────────────────────┐
  │  Step 1: R2R 预处理（解析 + 切片）        │
  │    - upload_file() → R2R 内部解析+切片    │
  │    - get_chunks()  → 获取切片结果         │
  └──────────────────────────────────────────┘
       ↓
  ┌──────────────────────────────────────────┐
  │  Step 2: RAGPipeline 三库写入             │
  │    - ingest_chunks() → Embedding          │
  │    - MySQL 元数据保存                     │
  │    - Milvus 向量入库                      │
  │    - Neo4j 图谱节点                       │
  └──────────────────────────────────────────┘
       ↓
  返回入库结果（source_id, chunk_count, status）

设计原则：
  - R2R 负责入库前的所有工作（解析 + 切片）
  - RAGPipeline 负责入库后的所有工作（Embedding + 三库写入）
  - R2R 不可用时降级为本地解析+切片（RAGPipeline.ingest_document）
  - 不重复实现解析/切片逻辑，由 R2R 统一处理
"""
import os
import time
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logger import log


class KnowledgePipeline:
    """知识入库管道

    协调 R2R（文档解析+切片）和 RAGPipeline（Embedding+三库写入）。

    R2R 负责入库前：
      文档解析 → 切片
    RAGPipeline 负责入库后：
      Embedding → MySQL → Milvus → Neo4j
    """

    def __init__(self) -> None:
        self._rag_pipeline = None
        self._r2r_client = None

    @property
    def rag_pipeline(self):
        """延迟加载 RAGPipeline"""
        if self._rag_pipeline is None:
            from app.rag.service.pipeline import RAGPipeline
            self._rag_pipeline = RAGPipeline()
        return self._rag_pipeline

    @property
    def r2r_client(self):
        """延迟加载 R2R 客户端"""
        if self._r2r_client is None:
            from app.services.knowledge.client import get_knowledge_client
            self._r2r_client = get_knowledge_client()
        return self._r2r_client

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    async def ingest(
        self,
        file_path: str,
        source_type: str = "",
        project_id: str = "default",
        user_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """知识入库（完整管道）

        R2R 负责解析+切片，RAGPipeline 负责三库写入。
        R2R 不可用时降级为本地解析。

        Args:
            file_path: 文件路径
            source_type: 来源类型 (pdf/word/markdown/swagger/text)
            project_id: 项目ID
            user_id: 用户ID
            metadata: 额外元数据

        Returns:
            {
                "source_id": int,
                "status": str,
                "chunk_count": int,
                "milvus_inserted": int,
                "r2r_document_id": str,
                "r2r_chunk_count": int,
                "duration": float,
                "errors": List[str],
            }
        """
        start = time.time()
        file_name = os.path.basename(file_path)
        errors: List[str] = []

        log.info(
            f"KnowledgePipeline | 开始入库 | file={file_name} | "
            f"type={source_type} | project={project_id}"
        )

        # Step 1: R2R 预处理（解析 + 切片）
        r2r_document_id = ""
        r2r_chunks: List[Dict[str, Any]] = []

        try:
            r2r_result = self.r2r_client.upload_file(
                file_path,
                metadata={
                    "project_id": project_id,
                    "source_type": source_type,
                    "file_name": file_name,
                    **(metadata or {}),
                },
            )
            r2r_document_id = r2r_result.get("document_id") or r2r_result.get("id") or ""

            if r2r_result.get("status") != "failed" and r2r_document_id:
                log.info(f"KnowledgePipeline | R2R上传成功 | doc_id={r2r_document_id}")

                # 获取 R2R 切片结果
                chunks_data = self.r2r_client.get_chunks(r2r_document_id)
                r2r_chunks = chunks_data.get("results", [])

                if r2r_chunks:
                    log.info(
                        f"KnowledgePipeline | R2R切片成功 | "
                        f"chunks={len(r2r_chunks)} | file={file_name}"
                    )
                else:
                    log.warning(
                        f"KnowledgePipeline | R2R未返回切片 | file={file_name} | "
                        f"降级为本地解析"
                    )
            else:
                error_msg = r2r_result.get("error", "unknown")
                log.warning(
                    f"KnowledgePipeline | R2R上传失败: {error_msg} | "
                    f"降级为本地解析"
                )
                errors.append(f"R2R上传失败: {error_msg}")
        except Exception as e:
            log.warning(f"KnowledgePipeline | R2R预处理异常: {e} | 降级为本地解析")
            errors.append(f"R2R预处理异常: {e}")

        # Step 2: 三库写入
        rag_result: Dict[str, Any] = {}
        try:
            if r2r_chunks:
                # 主路径：R2R 已完成解析+切片，直接 Embedding + 三库写入
                log.info(
                    f"KnowledgePipeline | 开始三库写入 | "
                    f"chunks={len(r2r_chunks)} | file={file_name}"
                )
                rag_result = await self.rag_pipeline.ingest_chunks(
                    chunks=r2r_chunks,
                    source_type=source_type,
                    file_name=file_name,
                    project_id=project_id,
                    user_id=user_id,
                    r2r_document_id=r2r_document_id,
                )
                log.info(
                    f"KnowledgePipeline | 三库写入完成 | "
                    f"source_id={rag_result.get('source_id')} | "
                    f"milvus_inserted={rag_result.get('milvus_inserted', 0)}"
                )
            else:
                # 降级路径：R2R 不可用或未返回切片，使用本地解析+切片
                log.info(f"KnowledgePipeline | 本地解析入库 | file={file_name}")
                rag_result = await self.rag_pipeline.ingest_document(
                    file_path=file_path,
                    source_type=source_type,
                    project_id=project_id,
                    user_id=user_id,
                )
                log.info(
                    f"KnowledgePipeline | 本地入库完成 | "
                    f"chunks={rag_result.get('chunk_count', 0)} | "
                    f"milvus_inserted={rag_result.get('milvus_inserted', 0)}"
                )

            if rag_result.get("status") != "stored" and rag_result.get("status") != "success":
                errors.extend(rag_result.get("errors", []))

        except Exception as e:
            log.error(f"KnowledgePipeline | 三库写入失败: {e}", exc_info=True)
            errors.append(f"三库写入失败: {e}")
            rag_result = {"status": "failed", "chunk_count": 0, "milvus_inserted": 0}

        duration = round(time.time() - start, 2)
        final_status = "success" if not errors else (
            "partial" if rag_result.get("source_id") else "failed"
        )

        result = {
            "source_id": rag_result.get("source_id"),
            "source_type": source_type,
            "file_name": file_name,
            "status": final_status,
            "chunk_count": rag_result.get("chunk_count", 0),
            "milvus_inserted": rag_result.get("milvus_inserted", 0),
            "r2r_document_id": r2r_document_id,
            "r2r_chunk_count": len(r2r_chunks),
            "duration": duration,
            "errors": errors,
        }

        log.info(
            f"KnowledgePipeline | 入库完成 | file={file_name} | "
            f"status={final_status} | chunks={result['chunk_count']} | "
            f"milvus={result['milvus_inserted']} | "
            f"r2r_doc={r2r_document_id or 'N/A'} | "
            f"耗时={duration}s"
        )

        return result

    async def ingest_text(
        self,
        content: str,
        source_type: str = "text",
        file_name: str = "manual_input",
        project_id: str = "default",
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """文本直接入库

        R2R 负责解析+切片，RAGPipeline 负责三库写入。
        R2R 不可用时降级为本地处理。
        """
        start = time.time()
        errors: List[str] = []

        # Step 1: R2R 预处理
        r2r_document_id = ""
        r2r_chunks: List[Dict[str, Any]] = []

        try:
            r2r_result = self.r2r_client.upload(
                content=content,
                doc_type=source_type,
                metadata={
                    "project_id": project_id,
                    "file_name": file_name,
                },
            )
            r2r_document_id = r2r_result.get("document_id") or r2r_result.get("id") or ""

            if r2r_result.get("status") != "failed" and r2r_document_id:
                chunks_data = self.r2r_client.get_chunks(r2r_document_id)
                r2r_chunks = chunks_data.get("results", [])
                log.info(
                    f"KnowledgePipeline | R2R文本切片成功 | "
                    f"chunks={len(r2r_chunks)} | doc_id={r2r_document_id}"
                )
        except Exception as e:
            log.warning(f"KnowledgePipeline | R2R文本预处理失败: {e}")
            errors.append(f"R2R文本预处理失败: {e}")

        # Step 2: 三库写入
        rag_result: Dict[str, Any] = {}
        try:
            if r2r_chunks:
                rag_result = await self.rag_pipeline.ingest_chunks(
                    chunks=r2r_chunks,
                    source_type=source_type,
                    file_name=file_name,
                    project_id=project_id,
                    user_id=user_id,
                    r2r_document_id=r2r_document_id,
                )
            else:
                # 降级：本地处理
                rag_result = await self.rag_pipeline.ingest_text(
                    content=content,
                    source_type=source_type,
                    file_name=file_name,
                    project_id=project_id,
                    user_id=user_id,
                )
        except Exception as e:
            log.error(f"KnowledgePipeline | 三库写入失败: {e}", exc_info=True)
            errors.append(f"三库写入失败: {e}")
            rag_result = {"status": "failed", "chunk_count": 0, "milvus_inserted": 0}

        duration = round(time.time() - start, 2)
        rag_result["r2r_document_id"] = r2r_document_id
        rag_result["r2r_chunk_count"] = len(r2r_chunks)
        rag_result["duration"] = duration
        if errors:
            rag_result["errors"] = errors

        return rag_result

    async def delete(self, source_id: str, r2r_document_id: str = "") -> Dict[str, Any]:
        """删除知识（三库联动 + R2R 删除）

        Args:
            source_id: 项目内的知识源ID
            r2r_document_id: R2R 文档ID（可选，若提供则同时从 R2R 删除）
        """
        log.info(
            f"KnowledgePipeline | 删除知识 | source_id={source_id} | "
            f"r2r_doc={r2r_document_id or 'N/A'}"
        )

        errors: List[str] = []

        # R2R 删除
        if r2r_document_id:
            try:
                r2r_result = self.r2r_client.delete_document(r2r_document_id)
                if r2r_result.get("status") == "failed":
                    errors.append(f"R2R删除失败: {r2r_result.get('error')}")
                else:
                    log.info(f"KnowledgePipeline | R2R删除成功 | doc={r2r_document_id}")
            except Exception as e:
                log.warning(f"KnowledgePipeline | R2R删除异常: {e}")
                errors.append(f"R2R删除异常: {e}")

        # RAGPipeline 三库联动删除
        try:
            rag_result = await self.rag_pipeline.delete_document(source_id)
            errors.extend(rag_result.get("errors", []))
        except Exception as e:
            errors.append(f"RAGPipeline删除失败: {e}")
            rag_result = {"milvus_deleted": 0}

        return {
            "source_id": source_id,
            "milvus_deleted": rag_result.get("milvus_deleted", 0),
            "r2r_deleted": r2r_document_id and not any("R2R" in e for e in errors),
            "status": "success" if not errors else "partial",
            "errors": errors,
        }

    async def get_stats(self) -> Dict[str, Any]:
        """获取知识库统计"""
        try:
            return await self.rag_pipeline.get_stats()
        except Exception as e:
            log.error(f"KnowledgePipeline | 获取统计失败: {e}")
            return {"error": str(e)}

    async def list_documents(
        self,
        project_id: Optional[str] = None,
        source_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """列出知识文档"""
        try:
            return await self.rag_pipeline.list_documents(
                project_id=project_id,
                source_type=source_type,
                limit=limit,
                offset=offset,
            )
        except Exception as e:
            log.error(f"KnowledgePipeline | 列出文档失败: {e}")
            return []


# ------------------------------------------------------------------
# 单例
# ------------------------------------------------------------------

_knowledge_pipeline: Optional[KnowledgePipeline] = None


def get_knowledge_pipeline() -> KnowledgePipeline:
    """获取 KnowledgePipeline 单例"""
    global _knowledge_pipeline
    if _knowledge_pipeline is None:
        _knowledge_pipeline = KnowledgePipeline()
    return _knowledge_pipeline
