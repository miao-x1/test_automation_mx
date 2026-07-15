"""
RequirementService - 需求知识服务

流程：上传 → knowledge.upload() → 返回 knowledge_id

职责：
1. 接收需求资料（文件/文本/URL）
2. 解析为 RequirementContext
3. 上传到知识库（R2R 或本地）
4. 返回 knowledge_id（异步索引，不阻塞）
"""
import os
from typing import Any, Dict, Optional
from app.core.config import settings
from app.core.logger import log
from app.db.database import SessionLocal
from app.models.knowledge_source import KnowledgeSource, KnowledgeSourceStatus


class RequirementService:
    """需求知识服务"""

    @staticmethod
    async def upload_file(
        file_path: str,
        project_id: str = "",
        source_type: str = "",
        title: str = "",
    ) -> Dict[str, Any]:
        """
        上传文件到知识库

        流程：
        1. 解析文件为 RequirementContext
        2. 存入 knowledge_source 表
        3. 上传到 R2R 知识库
        4. 返回 knowledge_id（不等待索引完成）

        Args:
            file_path: 文件路径
            project_id: 项目ID
            source_type: 输入类型（自动检测）
            title: 标题

        Returns:
            { knowledge_id, status, document_id }
        """
        if not os.path.exists(file_path):
            return {"error": f"文件不存在: {file_path}"}

        # 自动检测类型
        if not source_type:
            ext = os.path.splitext(file_path)[1].lower()
            type_map = {
                ".pdf": "pdf", ".doc": "doc", ".docx": "docx",
                ".png": "image", ".jpg": "image", ".jpeg": "image",
                ".mp4": "video", ".json": "swagger", ".yaml": "swagger", ".yml": "swagger",
            }
            source_type = type_map.get(ext, "text")

        # Step 1: 解析文件
        from app.agent.case.agent_selector import AgentSelector
        selector = AgentSelector()
        parse_result = selector.parse(
            source_type=source_type,
            task_id=0,
            file_path=file_path,
        )

        requirement_context = parse_result.get("requirement_context", "")
        structured_data = parse_result.get("structured_data", {})

        # Step 2: 存入数据库
        db = SessionLocal()
        try:
            ks = KnowledgeSource(
                project_id=project_id,
                source_type=source_type,
                file_path=file_path,
                raw_text=requirement_context,
                requirement_context={
                    "project_id": project_id,
                    "source_type": source_type,
                    "raw_text": requirement_context,
                    "structured_data": structured_data,
                    "business_goal": "",
                    "summary": requirement_context[:200] if requirement_context else "",
                },
                status=KnowledgeSourceStatus.PENDING,
            )
            db.add(ks)
            db.commit()
            db.refresh(ks)
            knowledge_id = ks.id
        finally:
            db.close()

        # Step 3: 通过 KnowledgePipeline 入库（统一入口，R2R 不可用时自动降级）
        document_id = None
        try:
            from app.services.knowledge.pipeline import get_knowledge_pipeline
            pipeline = get_knowledge_pipeline()
            ingest_result = await pipeline.ingest(
                file_path=file_path,
                source_type=source_type,
                project_id=project_id,
                user_id=None,
                metadata={"knowledge_id": knowledge_id},
            )
            document_id = ingest_result.get("r2r_document_id") or ""
            upload_result = ingest_result

            # 更新状态
            db2 = SessionLocal()
            try:
                ks2 = db2.query(KnowledgeSource).filter(KnowledgeSource.id == knowledge_id).first()
                if ks2:
                    ks2.status = KnowledgeSourceStatus.INDEXED
                    ks2.chunk_count = ingest_result.get("chunk_count", 0)
                    db2.commit()
            finally:
                db2.close()

        except Exception as e:
            log.warning(f"RequirementService | 知识库上传失败（降级为本地存储）: {e}")
            # 降级：标记为本地存储
            db3 = SessionLocal()
            try:
                ks3 = db3.query(KnowledgeSource).filter(KnowledgeSource.id == knowledge_id).first()
                if ks3:
                    ks3.status = KnowledgeSourceStatus.INDEXED
                    ks3.error_message = f"R2R上传失败，已降级为本地存储: {str(e)[:200]}"
                    db3.commit()
            finally:
                db3.close()

        log.info(f"RequirementService | upload | knowledge_id={knowledge_id}, source_type={source_type}")

        return {
            "knowledge_id": knowledge_id,
            "status": "indexed",
            "document_id": document_id,
            "source_type": source_type,
        }

    @staticmethod
    async def upload_text(
        text: str,
        project_id: str = "",
        source_type: str = "text",
        title: str = "",
    ) -> Dict[str, Any]:
        """
        上传文本到知识库

        Args:
            text: 文本内容
            project_id: 项目ID
            source_type: 输入类型
            title: 标题

        Returns:
            { knowledge_id, status }
        """
        # 存入数据库
        db = SessionLocal()
        try:
            ks = KnowledgeSource(
                project_id=project_id,
                source_type=source_type,
                raw_text=text,
                requirement_context={
                    "project_id": project_id,
                    "source_type": source_type,
                    "raw_text": text,
                    "business_goal": "",
                    "summary": text[:200],
                },
                status=KnowledgeSourceStatus.PENDING,
            )
            db.add(ks)
            db.commit()
            db.refresh(ks)
            knowledge_id = ks.id
        finally:
            db.close()

        # 通过 KnowledgePipeline 入库（统一入口）
        document_id = None
        try:
            from app.services.knowledge.pipeline import get_knowledge_pipeline
            pipeline = get_knowledge_pipeline()
            ingest_result = await pipeline.ingest_text(
                content=text,
                source_type=source_type,
                file_name=title or f"knowledge_{knowledge_id}",
                project_id=project_id,
            )
            document_id = ingest_result.get("r2r_document_id") or ""

            # 更新状态
            db2 = SessionLocal()
            try:
                ks2 = db2.query(KnowledgeSource).filter(KnowledgeSource.id == knowledge_id).first()
                if ks2:
                    ks2.status = KnowledgeSourceStatus.INDEXED
                    ks2.chunk_count = ingest_result.get("chunk_count", 0)
                    db2.commit()
            finally:
                db2.close()

        except Exception as e:
            log.warning(f"RequirementService | 文本上传失败: {e}")

        return {
            "knowledge_id": knowledge_id,
            "status": "indexed",
            "document_id": document_id,
            "source_type": source_type,
        }

    @staticmethod
    def get_knowledge_status(knowledge_id: int) -> Dict[str, Any]:
        """查询知识索引状态"""
        db = SessionLocal()
        try:
            ks = db.query(KnowledgeSource).filter(KnowledgeSource.id == knowledge_id).first()
            if not ks:
                return {"error": "不存在", "status": "not_found"}
            return {
                "knowledge_id": ks.id,
                "status": ks.status,
                "source_type": ks.source_type,
                "chunk_count": ks.chunk_count,
                "error_message": ks.error_message,
                "indexed_at": str(ks.indexed_at) if ks.indexed_at else None,
            }
        finally:
            db.close()

    @staticmethod
    def list_knowledge(
        project_id: str = "",
        skip: int = 0,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """列出知识文档"""
        db = SessionLocal()
        try:
            query = db.query(KnowledgeSource)
            if project_id:
                query = query.filter(KnowledgeSource.project_id == project_id)
            query = query.order_by(KnowledgeSource.id.desc())
            total = query.count()
            items = query.offset(skip).limit(limit).all()
            return {
                "items": [
                    {
                        "id": ks.id,
                        "project_id": ks.project_id,
                        "source_type": ks.source_type,
                        "status": ks.status,
                        "chunk_count": ks.chunk_count,
                        "error_message": ks.error_message,
                        "created_at": str(ks.created_at) if ks.created_at else None,
                        "indexed_at": str(ks.indexed_at) if ks.indexed_at else None,
                    }
                    for ks in items
                ],
                "total": total,
            }
        finally:
            db.close()

    @staticmethod
    def delete_knowledge(knowledge_id: int) -> Dict[str, Any]:
        """删除知识文档（MySQL 元数据 + R2R 文档）

        R2R 删除通过 KnowledgePipeline 统一处理。
        """
        db = SessionLocal()
        try:
            ks = db.query(KnowledgeSource).filter(KnowledgeSource.id == knowledge_id).first()
            if not ks:
                return {"error": "不存在"}

            # 获取 R2R document_id（如果有）
            r2r_doc_id = ""
            if ks.requirement_context and isinstance(ks.requirement_context, dict):
                r2r_doc_id = ks.requirement_context.get("document_id") or ""

            # 从 R2R 删除（通过 KnowledgePipeline 统一处理）
            if r2r_doc_id:
                try:
                    from app.services.knowledge.client import get_knowledge_client
                    client = get_knowledge_client()
                    client.delete_document(str(r2r_doc_id))
                    log.info(f"RequirementService | R2R删除成功 | doc={r2r_doc_id}")
                except Exception as e:
                    log.warning(f"RequirementService | R2R删除失败: {e}")

            # 从 MySQL 删除知识源记录
            db.delete(ks)
            db.commit()
            return {"status": "deleted", "knowledge_id": knowledge_id}
        finally:
            db.close()
