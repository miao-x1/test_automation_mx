"""
MySQL 元数据存储

使用现有 KnowledgeSource / KnowledgeChunk 模型，
管理 RAG 文档与分片的元数据（向量本身存于 Milvus）。

职责：
  - 创建 / 更新 / 删除知识源记录
  - 批量创建 chunk 元数据记录
  - 按条件查询文档与分片
  - 提供统计信息

注意：get_db() 是生成器，方法内手动管理 session 生命周期。
"""
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_source import KnowledgeSource, KnowledgeSourceStatus
from app.rag.models import Chunk, DocumentType

logger = logging.getLogger(__name__)


class MySQLStore:
    """RAG 元数据存储（MySQL）"""

    # ------------------------------------------------------------------
    # Session 管理
    # ------------------------------------------------------------------

    def _get_session(self) -> Session:
        """创建新的数据库 session（调用方负责关闭）"""
        return SessionLocal()

    @staticmethod
    def _safe_commit(db: Session):
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            raise e

    # ------------------------------------------------------------------
    # 知识源 CRUD
    # ------------------------------------------------------------------

    def create_source(
        self,
        source_type: str,
        file_path: str = "",
        file_name: str = "",
        raw_text: str = "",
        project_id: str = "default",
        user_id: Optional[int] = None,
        source_url: str = "",
        requirement_context: Optional[dict] = None,
    ) -> KnowledgeSource:
        """创建知识源记录

        Returns:
            KnowledgeSource ORM 对象（含 id）
        """
        db = self._get_session()
        try:
            source = KnowledgeSource(
                project_id=project_id,
                source_type=source_type,
                file_path=file_path,
                source_url=source_url,
                raw_text=raw_text[:65535] if raw_text else None,
                requirement_context=requirement_context,
                status=KnowledgeSourceStatus.PENDING,
                chunk_count=0,
                version=1,
                created_by=str(user_id) if user_id else None,
            )
            db.add(source)
            db.flush()  # 获取 id
            source_id = source.id
            db.commit()
            db.refresh(source)
            logger.info(
                f"[MySQLStore] 创建知识源 id={source_id} type={source_type} "
                f"file={file_name}"
            )
            # detach 避免后续访问报错
            db.expunge(source)
            return source
        except Exception as e:
            db.rollback()
            logger.error(f"[MySQLStore] 创建知识源失败: {e}")
            raise
        finally:
            db.close()

    def update_source_status(
        self,
        source_id: int,
        status: str,
        chunk_count: Optional[int] = None,
        error_message: str = "",
    ):
        """更新知识源状态"""
        db = self._get_session()
        try:
            source = db.query(KnowledgeSource).filter_by(id=source_id).first()
            if source is None:
                logger.warning(f"[MySQLStore] 知识源不存在 id={source_id}")
                return
            source.status = status
            if chunk_count is not None:
                source.chunk_count = chunk_count
            if error_message:
                source.error_message = error_message
            if status == KnowledgeSourceStatus.INDEXED:
                source.indexed_at = datetime.now()
            db.commit()
            logger.info(
                f"[MySQLStore] 更新知识源状态 id={source_id} status={status}"
            )
        except Exception as e:
            db.rollback()
            logger.error(f"[MySQLStore] 更新知识源状态失败: {e}")
            raise
        finally:
            db.close()

    def get_source(self, source_id: int) -> Optional[Dict[str, Any]]:
        """获取知识源（返回字典，避免 DetachedInstanceError）"""
        db = self._get_session()
        try:
            source = db.query(KnowledgeSource).filter_by(id=source_id).first()
            if source is None:
                return None
            return self._source_to_dict(source)
        finally:
            db.close()

    def get_sources(
        self,
        project_id: Optional[str] = None,
        source_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """查询知识源列表"""
        db = self._get_session()
        try:
            q = db.query(KnowledgeSource)
            if project_id:
                q = q.filter(KnowledgeSource.project_id == project_id)
            if source_type:
                q = q.filter(KnowledgeSource.source_type == source_type)
            if status:
                q = q.filter(KnowledgeSource.status == status)
            q = q.order_by(KnowledgeSource.created_at.desc())
            q = q.offset(offset).limit(limit)
            return [self._source_to_dict(s) for s in q.all()]
        finally:
            db.close()

    def delete_source(self, source_id: int) -> bool:
        """删除知识源（级联删除 chunks）"""
        db = self._get_session()
        try:
            # 先删 chunks
            db.query(KnowledgeChunk).filter(
                KnowledgeChunk.knowledge_source_id == source_id
            ).delete(synchronize_session=False)
            # 再删 source
            deleted = db.query(KnowledgeSource).filter_by(id=source_id).delete(
                synchronize_session=False
            )
            db.commit()
            logger.info(
                f"[MySQLStore] 删除知识源 id={source_id} deleted={deleted > 0}"
            )
            return deleted > 0
        except Exception as e:
            db.rollback()
            logger.error(f"[MySQLStore] 删除知识源失败: {e}")
            return False
        finally:
            db.close()

    # ------------------------------------------------------------------
    # Chunk CRUD
    # ------------------------------------------------------------------

    def create_chunks(
        self,
        source_id: int,
        chunks: List[Chunk],
        milvus_ids: Optional[Dict[str, int]] = None,
    ) -> List[int]:
        """批量创建 chunk 元数据记录

        Args:
            source_id: 知识源 ID
            chunks: Chunk 列表
            milvus_ids: chunk_id -> milvus_id 的映射（插入向量后回填）

        Returns:
            创建的 chunk 记录 ID 列表
        """
        if not chunks:
            return []
        milvus_ids = milvus_ids or {}
        db = self._get_session()
        created_ids: List[int] = []
        try:
            for chunk in chunks:
                meta = dict(chunk.metadata) if chunk.metadata else {}
                meta["token_count"] = chunk.token_count
                meta["start_char"] = chunk.start_char
                meta["end_char"] = chunk.end_char
                meta["chunk_index"] = chunk.chunk_index

                kc = KnowledgeChunk(
                    knowledge_source_id=source_id,
                    milvus_id=milvus_ids.get(chunk.chunk_id, 0),
                    chunk_type=chunk.chunk_type or "content",
                    text=chunk.text[:65535] if chunk.text else None,
                    chunk_metadata=meta,
                )
                db.add(kc)
                db.flush()
                created_ids.append(kc.id)
            db.commit()
            logger.info(
                f"[MySQLStore] 批量创建 chunks source_id={source_id} "
                f"count={len(created_ids)}"
            )
        except Exception as e:
            db.rollback()
            logger.error(f"[MySQLStore] 批量创建 chunks 失败: {e}")
            raise
        finally:
            db.close()
        return created_ids

    def get_chunks(self, source_id: int) -> List[Dict[str, Any]]:
        """获取指定知识源的所有 chunk"""
        db = self._get_session()
        try:
            rows = (
                db.query(KnowledgeChunk)
                .filter(KnowledgeChunk.knowledge_source_id == source_id)
                .order_by(KnowledgeChunk.id)
                .all()
            )
            return [self._chunk_to_dict(r) for r in rows]
        finally:
            db.close()

    def search_chunks_by_metadata(
        self,
        source_type: Optional[str] = None,
        chunk_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """按元数据搜索 chunk（join knowledge_source）"""
        db = self._get_session()
        try:
            q = db.query(KnowledgeChunk).join(
                KnowledgeSource,
                KnowledgeChunk.knowledge_source_id == KnowledgeSource.id,
            )
            if source_type:
                q = q.filter(KnowledgeSource.source_type == source_type)
            if chunk_type:
                q = q.filter(KnowledgeChunk.chunk_type == chunk_type)
            q = q.limit(limit)
            return [self._chunk_to_dict(r) for r in q.all()]
        finally:
            db.close()

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """获取存储统计"""
        db = self._get_session()
        try:
            total_sources = db.query(KnowledgeSource).count()
            total_chunks = db.query(KnowledgeChunk).count()

            # 按类型统计
            type_stats: Dict[str, int] = {}
            rows = (
                db.query(
                    KnowledgeSource.source_type,
                )
                .all()
            )
            from sqlalchemy import func as sql_func

            type_counts = (
                db.query(
                    KnowledgeSource.source_type,
                    sql_func.count(KnowledgeSource.id),
                )
                .group_by(KnowledgeSource.source_type)
                .all()
            )
            for st, cnt in type_counts:
                type_stats[st or "unknown"] = cnt

            # 按状态统计
            status_stats: Dict[str, int] = {}
            status_counts = (
                db.query(
                    KnowledgeSource.status,
                    sql_func.count(KnowledgeSource.id),
                )
                .group_by(KnowledgeSource.status)
                .all()
            )
            for st, cnt in status_counts:
                status_stats[st or "unknown"] = cnt

            return {
                "total_sources": total_sources,
                "total_chunks": total_chunks,
                "by_type": type_stats,
                "by_status": status_stats,
            }
        except Exception as e:
            logger.error(f"[MySQLStore] 获取统计失败: {e}")
            return {
                "total_sources": 0,
                "total_chunks": 0,
                "by_type": {},
                "by_status": {},
                "error": str(e),
            }
        finally:
            db.close()

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _source_to_dict(s: KnowledgeSource) -> Dict[str, Any]:
        """将 ORM 对象转为字典（避免 DetachedInstanceError）"""
        return {
            "id": s.id,
            "project_id": s.project_id,
            "source_type": s.source_type,
            "file_path": s.file_path,
            "source_url": s.source_url,
            "raw_text": (s.raw_text[:200] + "...") if s.raw_text and len(s.raw_text) > 200 else s.raw_text,
            "status": s.status,
            "error_message": s.error_message,
            "chunk_count": s.chunk_count,
            "version": s.version,
            "created_by": s.created_by,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "indexed_at": s.indexed_at.isoformat() if s.indexed_at else None,
        }

    @staticmethod
    def _chunk_to_dict(c: KnowledgeChunk) -> Dict[str, Any]:
        """将 chunk ORM 对象转为字典"""
        return {
            "id": c.id,
            "knowledge_source_id": c.knowledge_source_id,
            "milvus_id": c.milvus_id,
            "chunk_type": c.chunk_type,
            "text": c.text,
            "metadata": c.chunk_metadata if isinstance(c.chunk_metadata, dict) else {},
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
