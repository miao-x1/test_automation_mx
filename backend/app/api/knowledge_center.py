"""
Knowledge Center API - 知识中心接口

端点：
  GET  /stats                    知识中心总览统计
  GET  /collections              集合列表
  GET  /collections/{type}       集合详情
  DELETE /collections/{type}     清空集合
  GET  /documents                文档列表
  GET  /documents/{id}           文档详情（含chunk）
  DELETE /documents/{id}         删除文档（三库联动）
  GET  /chunks/{source_id}       查看文档分片
  GET  /chunks/detail/{chunk_id} Chunk详情
  GET  /embedding-status/{id}    Embedding状态
  GET  /graph/overview           Graph总览
  GET  /graph/nodes              Graph节点列表
  GET  /graph/relations          Graph关系图
  POST /rebuild-embedding/{id}   重建Embedding
  POST /rechunk/{id}             重新分块
  POST /reindex/{id}             重新索引
  POST /search/fulltext          全文检索
  POST /search/semantic          语义检索
  POST /search/hybrid            混合检索
"""
import logging
from typing import Optional, List

from fastapi import APIRouter, Query, HTTPException, Form
from pydantic import BaseModel

from app.services.knowledge_center_service import get_knowledge_center_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ===== 请求模型 =====

class HybridSearchRequest(BaseModel):
    keyword: str = ""
    query: str = ""
    entity_types: List[str] = ["chunk"]
    top_k: int = 10


# ===== 总览统计 =====

@router.get("/stats")
async def get_stats():
    """知识中心总览统计"""
    service = get_knowledge_center_service()
    result = await service.get_center_stats()
    return {"code": 0, "message": "success", "data": result}


# ===== 集合管理 =====

@router.get("/collections")
async def list_collections():
    """集合列表"""
    service = get_knowledge_center_service()
    result = await service.list_collections()
    return {"code": 0, "message": "success", "data": result}


@router.get("/collections/{entity_type}")
async def get_collection_detail(entity_type: str):
    """集合详情"""
    service = get_knowledge_center_service()
    result = await service.get_collection_detail(entity_type)
    return {"code": 0, "message": "success", "data": result}


@router.delete("/collections/{entity_type}")
async def clear_collection(entity_type: str):
    """清空集合"""
    service = get_knowledge_center_service()
    result = await service.clear_collection(entity_type)
    return {"code": 0, "message": result.get("message", ""), "data": result}


# ===== 文档管理 =====

@router.get("/documents")
async def list_documents(
    project_id: str = Query(""),
    source_type: str = Query(""),
    status: str = Query(""),
    keyword: str = Query(""),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    """文档列表"""
    service = get_knowledge_center_service()
    result = await service.list_documents(
        project_id=project_id,
        source_type=source_type,
        status=status,
        keyword=keyword,
        limit=limit,
        offset=offset,
    )
    return {"code": 0, "message": "success", "data": result}


@router.get("/documents/{source_id}")
async def get_document_detail(source_id: int):
    """文档详情（含chunk列表）"""
    service = get_knowledge_center_service()
    result = await service.get_document_detail(source_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=result.get("message"))
    return {"code": 0, "message": "success", "data": result}


@router.delete("/documents/{source_id}")
async def delete_document(source_id: int):
    """删除文档（三库联动删除）"""
    service = get_knowledge_center_service()
    result = await service.delete_document(source_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=result.get("message"))
    return {"code": 0, "message": result.get("message", ""), "data": result}


# ===== Chunk 查看 =====

@router.get("/chunks/{source_id}")
async def list_chunks(
    source_id: int,
    chunk_type: str = Query(""),
    limit: int = Query(100, le=500),
):
    """查看文档的分片列表"""
    service = get_knowledge_center_service()
    result = await service.list_chunks(source_id, chunk_type=chunk_type, limit=limit)
    return {"code": 0, "message": "success", "data": result}


@router.get("/chunks/detail/{chunk_id}")
async def get_chunk_detail(chunk_id: int):
    """单个 Chunk 详情"""
    service = get_knowledge_center_service()
    result = await service.get_chunk_detail(chunk_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=result.get("message"))
    return {"code": 0, "message": "success", "data": result}


# ===== Embedding 状态 =====

@router.get("/embedding-status/{source_id}")
async def get_embedding_status(source_id: int):
    """检查文档的 Embedding 状态"""
    service = get_knowledge_center_service()
    result = await service.get_embedding_status(source_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=result.get("message"))
    return {"code": 0, "message": "success", "data": result}


# ===== Graph 查看 =====

@router.get("/graph/overview")
async def get_graph_overview():
    """Neo4j 图谱总览"""
    service = get_knowledge_center_service()
    result = await service.get_graph_overview()
    return {"code": 0, "message": "success", "data": result}


@router.get("/graph/nodes")
async def get_graph_nodes(
    label: str = Query("", description="节点标签，空则返回各标签数量"),
    limit: int = Query(50, le=200),
):
    """查看图谱节点"""
    service = get_knowledge_center_service()
    result = await service.get_graph_nodes(label=label, limit=limit)
    return {"code": 0, "message": "success", "data": result}


@router.get("/graph/relations")
async def get_graph_relations(
    label: str = Query(..., description="节点标签"),
    entity_id: str = Query(..., description="实体ID"),
    depth: int = Query(2, ge=1, le=5),
):
    """查看实体的关系图"""
    service = get_knowledge_center_service()
    result = await service.get_graph_relations(label, entity_id, depth=depth)
    return {"code": 0, "message": "success", "data": result}


# ===== 重建操作 =====

@router.post("/rebuild-embedding/{source_id}")
async def rebuild_embedding(source_id: int):
    """重建文档的 Embedding"""
    service = get_knowledge_center_service()
    result = await service.rebuild_embedding(source_id)
    return {"code": 0, "message": "重建Embedding完成", "data": result}


@router.post("/rechunk/{source_id}")
async def rechunk_document(
    source_id: int,
    chunk_size: int = Query(500, ge=100, le=2000),
):
    """重新分块文档"""
    service = get_knowledge_center_service()
    result = await service.rechunk_document(source_id, chunk_size=chunk_size)
    return {"code": 0, "message": "重新分块完成", "data": result}


@router.post("/reindex/{source_id}")
async def reindex_document(
    source_id: int,
    chunk_size: int = Query(500, ge=100, le=2000),
):
    """完整重新索引（分块 + Embedding + 图谱）"""
    service = get_knowledge_center_service()
    result = await service.reindex_document(source_id, chunk_size=chunk_size)
    return {"code": 0, "message": "重新索引完成", "data": result}


# ===== 搜索测试 =====

@router.post("/search/fulltext")
async def fulltext_search(
    keyword: str = Form(...),
    source_type: str = Form(""),
    limit: int = Form(20),
):
    """全文检索（MySQL LIKE 搜索）"""
    service = get_knowledge_center_service()
    result = await service.fulltext_search(keyword, source_type=source_type, limit=limit)
    return {"code": 0, "message": "success", "data": result}


@router.post("/search/semantic")
async def semantic_search(
    query: str = Form(...),
    entity_types: str = Form("chunk"),
    top_k: int = Form(10),
):
    """语义检索（向量搜索）"""
    service = get_knowledge_center_service()
    etypes = [t.strip() for t in entity_types.split(",") if t.strip()]
    result = await service.semantic_search(query, entity_types=etypes, top_k=top_k)
    return {"code": 0, "message": "success", "data": result}


@router.post("/search/hybrid")
async def hybrid_search(req: HybridSearchRequest):
    """混合检索（全文 + 语义融合）"""
    service = get_knowledge_center_service()
    result = await service.hybrid_search(
        keyword=req.keyword,
        query=req.query,
        entity_types=req.entity_types,
        top_k=req.top_k,
    )
    return {"code": 0, "message": "success", "data": result}
