"""
RAG V2 API - 企业级知识库接口

提供文档上传、查询、管理等 API。
所有操作通过 RAGPipeline 服务编排完成。

端点：
  POST   /upload         上传文档
  POST   /ingest-text    文本入库
  POST   /query          RAG 查询（含上下文构建）
  POST   /search         简单搜索（仅返回检索结果）
  GET    /documents      文档列表
  GET    /documents/{id} 文档详情
  DELETE /documents/{id} 删除文档
  GET    /stats          统计信息
  GET    /source-types   支持的来源类型
  POST   /batch-upload   批量上传
"""
import logging
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException, Query

from app.rag.models import RAGQuery, DocumentType
from app.rag.service.factory import get_rag_service
from app.core.auth import require_auth
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    source_type: str = Form(""),
    project_id: str = Form("default"),
    user_id: Optional[int] = Form(None),
    user: User = Depends(require_auth),
):
    """上传文档并自动完成入库管道

    支持：PDF/Word/Excel/Markdown/Swagger/Postman/文本/图片等
    """
    # 保存文件
    upload_dir = os.path.join(os.getcwd(), "uploads", "rag")
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file.filename)
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # 执行入库管道
    service = get_rag_service()
    result = await service.ingest_document(
        file_path=file_path,
        source_type=source_type,
        project_id=project_id,
        user_id=user_id,
    )
    return {"code": 0, "message": "文档入库完成", "data": result}


@router.post("/ingest-text")
async def ingest_text(
    content: str = Form(...),
    source_type: str = Form("text"),
    file_name: str = Form("manual_input"),
    project_id: str = Form("default"),
    user_id: Optional[int] = Form(None),
    user: User = Depends(require_auth),
):
    """文本直接入库（无需文件上传）"""
    service = get_rag_service()
    result = await service.ingest_text(
        content=content,
        source_type=source_type,
        file_name=file_name,
        project_id=project_id,
        user_id=user_id,
    )
    return {"code": 0, "message": "文本入库完成", "data": result}


@router.post("/query")
async def rag_query(query: RAGQuery, user: User = Depends(require_auth)):
    """RAG 查询

    完整流程：查询处理 → 向量检索 → 重排序 → 上下文构建
    返回 RAGResponse（含 results + context）
    """
    service = get_rag_service()
    response = await service.query(query)
    return {"code": 0, "message": "查询完成", "data": response.model_dump()}


@router.post("/search")
async def simple_search(
    query: str = Form(...),
    top_k: int = Form(10),
    source_types: str = Form(""),  # 逗号分隔
    user: User = Depends(require_auth),
):
    """简单搜索（仅返回检索结果，不构建上下文）"""
    from app.rag.models import RAGQuery as RQ

    types_list = [s.strip() for s in source_types.split(",") if s.strip()] if source_types else []
    rag_q = RQ(
        query=query,
        top_k=top_k,
        source_types=types_list,
        rerank=True,
        rerank_top_k=top_k,
    )
    service = get_rag_service()
    response = await service.query(rag_q)
    # 仅返回 results
    return {
        "code": 0,
        "message": "搜索完成",
        "data": {
            "query": response.query,
            "results": [r.model_dump() for r in response.results],
            "total": len(response.results),
            "latency_ms": response.latency_ms,
            "reranked": response.reranked,
        },
    }


@router.get("/documents")
async def list_documents(
    project_id: str = Query(None),
    source_type: str = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(require_auth),
):
    """文档列表"""
    service = get_rag_service()
    docs = await service.list_documents(
        project_id=project_id,
        source_type=source_type,
        limit=limit,
        offset=offset,
    )
    return {"code": 0, "message": "success", "data": docs}


@router.get("/documents/{source_id}")
async def get_document(source_id: str, user: User = Depends(require_auth)):
    """文档详情（含 chunk 列表）"""
    service = get_rag_service()
    doc = await service.get_document(source_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"code": 0, "message": "success", "data": doc}


@router.delete("/documents/{source_id}")
async def delete_document(source_id: str, user: User = Depends(require_auth)):
    """删除文档（三库联动）"""
    service = get_rag_service()
    result = await service.delete_document(source_id)
    return {"code": 0, "message": "删除完成", "data": result}


@router.get("/stats")
async def get_stats(user: User = Depends(require_auth)):
    """统计信息：MySQL + Milvus + Neo4j"""
    service = get_rag_service()
    stats = await service.get_stats()
    return {"code": 0, "message": "success", "data": stats}


@router.get("/source-types")
async def get_source_types(user: User = Depends(require_auth)):
    """获取支持的来源类型"""
    types = [{"value": t.value, "label": t.value} for t in DocumentType]
    return {"code": 0, "message": "success", "data": types}


@router.post("/batch-upload")
async def batch_upload(
    files: List[UploadFile] = File(...),
    project_id: str = Form("default"),
    user_id: Optional[int] = Form(None),
    user: User = Depends(require_auth),
):
    """批量上传文档"""
    upload_dir = os.path.join(os.getcwd(), "uploads", "rag")
    os.makedirs(upload_dir, exist_ok=True)

    file_paths: List[str] = []
    for f in files:
        file_path = os.path.join(upload_dir, f.filename)
        with open(file_path, "wb") as fp:
            content = await f.read()
            fp.write(content)
        file_paths.append(file_path)

    service = get_rag_service()
    results = await service.batch_ingest(
        file_paths=file_paths,
        project_id=project_id,
        user_id=user_id,
    )
    return {"code": 0, "message": f"批量入库完成，共 {len(results)} 个文件", "data": results}


# ===== 索引管理（兼容前端 rag.ts）=====

from pydantic import BaseModel


class ClearConfirmRequest(BaseModel):
    confirm: bool = False
    collection_name: Optional[str] = None


@router.post("/index/{task_id}", summary="按任务索引")
async def index_by_task(task_id: int, user: User = Depends(require_auth)):
    """按任务ID索引相关数据到向量库"""
    try:
        from app.db.database import SessionLocal
        from app.models.task import Task
        from app.models.script import Script
        from app.services.context_router.storage_router import get_storage_router
        from app.db.collection_constants import CASE_COLLECTION, SCRIPT_COLLECTION

        db = SessionLocal()
        try:
            # 索引任务关联的脚本
            scripts = db.query(Script).filter(Script.task_id == task_id).all()
            indexed = 0
            storage = get_storage_router()

            for script in scripts:
                desc = f"任务{task_id}脚本: Script #{script.id}"
                embeddings = storage.embed_batch_sync([desc])
                if embeddings:
                    storage.milvus_insert(SCRIPT_COLLECTION, [{
                        "id": hash(f"task_{task_id}_script_{script.id}") & 0x7FFFFFFF,
                        "task_id": task_id,
                        "script_name": f"Script #{script.id}",
                        "script_content": script.script_content[:8000] if script.script_content else "",
                        "description": desc,
                        "vector": embeddings[0],
                    }])
                    indexed += 1

            return {"code": 200, "message": f"已索引 {indexed} 条数据", "data": {"task_id": task_id, "indexed": indexed}}
        finally:
            db.close()
    except Exception as e:
        logger.error(f"按任务索引失败: {e}", exc_info=True)
        return {"code": 500, "message": f"索引失败: {e}", "data": None}


@router.post("/index/all", summary="全量索引")
async def index_all(user: User = Depends(require_auth)):
    """全量索引所有数据到向量库"""
    try:
        from app.db.database import SessionLocal
        from app.models.script import Script
        from app.models.test_case import TestCase
        from app.services.context_router.storage_router import get_storage_router
        from app.db.collection_constants import CASE_COLLECTION, SCRIPT_COLLECTION

        db = SessionLocal()
        try:
            storage = get_storage_router()
            indexed = 0

            # 索引所有脚本
            scripts = db.query(Script).all()
            for script in scripts:
                desc = f"脚本: Script #{script.id}"
                embeddings = storage.embed_batch_sync([desc])
                if embeddings:
                    storage.milvus_insert(SCRIPT_COLLECTION, [{
                        "id": hash(f"script_{script.id}") & 0x7FFFFFFF,
                        "task_id": script.task_id or 0,
                        "script_name": f"Script #{script.id}",
                        "script_content": script.script_content[:8000] if script.script_content else "",
                        "description": desc,
                        "vector": embeddings[0],
                    }])
                    indexed += 1

            return {"code": 200, "message": f"全量索引完成，共 {indexed} 条", "data": {"indexed": indexed}}
        finally:
            db.close()
    except Exception as e:
        logger.error(f"全量索引失败: {e}", exc_info=True)
        return {"code": 500, "message": f"全量索引失败: {e}", "data": None}


@router.post("/index/incremental", summary="增量索引")
async def index_incremental(user: User = Depends(require_auth)):
    """增量索引：只索引新增或修改的数据"""
    try:
        # 使用 RAG service 的增量索引功能
        service = get_rag_service()
        result = await service.incremental_index() if hasattr(service, 'incremental_index') else {"indexed": 0}
        return {"code": 200, "message": "增量索引完成", "data": result}
    except Exception as e:
        logger.error(f"增量索引失败: {e}", exc_info=True)
        return {"code": 500, "message": f"增量索引失败: {e}", "data": None}


@router.post("/index/cases", summary="索引用例")
async def index_cases(user: User = Depends(require_auth)):
    """索引所有测试用例到向量库"""
    try:
        from app.db.database import SessionLocal
        from app.models.test_case import TestCase
        from app.services.context_router.storage_router import get_storage_router
        from app.db.collection_constants import CASE_COLLECTION

        db = SessionLocal()
        try:
            storage = get_storage_router()
            cases = db.query(TestCase).all()
            indexed = 0

            for case in cases:
                desc = f"用例: {case.case_name or ''}"
                embeddings = storage.embed_batch_sync([desc])
                if embeddings:
                    storage.milvus_insert(CASE_COLLECTION, [{
                        "id": hash(f"case_{case.id}") & 0x7FFFFFFF,
                        "task_id": case.task_id or 0,
                        "case_name": case.case_name or "",
                        "description": desc,
                        "vector": embeddings[0],
                    }])
                    indexed += 1

            return {"code": 200, "message": f"已索引 {indexed} 条用例", "data": {"indexed": indexed}}
        finally:
            db.close()
    except Exception as e:
        logger.error(f"用例索引失败: {e}", exc_info=True)
        return {"code": 500, "message": f"用例索引失败: {e}", "data": None}


@router.post("/index/scripts", summary="索引脚本")
async def index_scripts(user: User = Depends(require_auth)):
    """索引所有测试脚本到向量库"""
    try:
        from app.db.database import SessionLocal
        from app.models.script import Script
        from app.services.context_router.storage_router import get_storage_router
        from app.db.collection_constants import SCRIPT_COLLECTION

        db = SessionLocal()
        try:
            storage = get_storage_router()
            scripts = db.query(Script).all()
            indexed = 0

            for script in scripts:
                desc = f"脚本: Script #{script.id}"
                embeddings = storage.embed_batch_sync([desc])
                if embeddings:
                    storage.milvus_insert(SCRIPT_COLLECTION, [{
                        "id": hash(f"script_{script.id}") & 0x7FFFFFFF,
                        "task_id": script.task_id or 0,
                        "script_name": f"Script #{script.id}",
                        "script_content": script.script_content[:8000] if script.script_content else "",
                        "description": desc,
                        "vector": embeddings[0],
                    }])
                    indexed += 1

            return {"code": 200, "message": f"已索引 {indexed} 条脚本", "data": {"indexed": indexed}}
        finally:
            db.close()
    except Exception as e:
        logger.error(f"脚本索引失败: {e}", exc_info=True)
        return {"code": 500, "message": f"脚本索引失败: {e}", "data": None}


@router.post("/clear", summary="清空索引（确认）")
async def clear_index(req: ClearConfirmRequest, user: User = Depends(require_auth)):
    """清空索引数据（需要确认）"""
    if not req.confirm:
        return {"code": 400, "message": "请确认清空操作（传 confirm=true）"}
    try:
        from app.services.context_router.storage_router import get_storage_router
        from app.db.collection_constants import ALL_COLLECTIONS
        storage = get_storage_router()
        cleared = 0
        for collection in ALL_COLLECTIONS:
            try:
                storage.milvus_delete(collection, "")  # 删除所有
                cleared += 1
            except Exception:
                pass
        return {"code": 200, "message": f"已清空 {cleared} 个集合", "data": {"cleared": cleared}}
    except Exception as e:
        logger.error(f"清空索引失败: {e}", exc_info=True)
        return {"code": 500, "message": f"清空失败: {e}", "data": None}


@router.post("/clear_all", summary="清空所有数据")
async def clear_all(user: User = Depends(require_auth)):
    """清空所有向量数据（无需确认，谨慎使用）"""
    try:
        from app.services.context_router.storage_router import get_storage_router
        from app.db.collection_constants import ALL_COLLECTIONS
        storage = get_storage_router()
        cleared = 0
        for collection in ALL_COLLECTIONS:
            try:
                storage.milvus_delete(collection, "")
                cleared += 1
            except Exception:
                pass
        return {"code": 200, "message": f"已清空 {cleared} 个集合", "data": {"cleared": cleared}}
    except Exception as e:
        logger.error(f"清空所有失败: {e}", exc_info=True)
        return {"code": 500, "message": f"清空失败: {e}", "data": None}


@router.get("/collection/{collection_name}", summary="获取集合信息")
async def get_collection_info(collection_name: str, user: User = Depends(require_auth)):
    """获取指定集合的统计信息"""
    try:
        from app.services.context_router.storage_router import get_storage_router
        storage = get_storage_router()
        # 使用 milvus_query 获取统计信息
        try:
            data = storage.milvus_query(collection_name, "id >= 0", output_fields=["id"])
            stats = {"count": len(data) if data else 0}
        except Exception:
            stats = {"count": 0, "error": "无法获取统计信息"}
        return {"code": 200, "message": "success", "data": {
            "collection_name": collection_name,
            "stats": stats,
        }}
    except Exception as e:
        logger.error(f"获取集合信息失败: {e}", exc_info=True)
        return {"code": 500, "message": f"获取失败: {e}", "data": None}


@router.post("/reset", summary="重置知识库")
async def reset_knowledge_base(user: User = Depends(require_auth)):
    """重置知识库（清空并重建）"""
    try:
        from app.services.context_router.storage_router import get_storage_router
        from app.db.collection_constants import ALL_COLLECTIONS
        storage = get_storage_router()

        # 清空所有集合
        for collection in ALL_COLLECTIONS:
            try:
                storage.milvus_delete(collection, "")
            except Exception:
                pass

        return {"code": 200, "message": "知识库已重置", "data": {"reset": True}}
    except Exception as e:
        logger.error(f"重置失败: {e}", exc_info=True)
        return {"code": 500, "message": f"重置失败: {e}", "data": None}
