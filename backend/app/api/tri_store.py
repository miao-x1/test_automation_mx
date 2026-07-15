"""
三库协同 API

提供 MySQL / Milvus / Neo4j 三库统一的写入、查询、删除接口。

端点：
  POST   /sync-write           统一写入三库
  POST   /sync-write-relation  统一写入关系（Neo4j）
  POST   /sync-query           统一查询三库
  GET    /sync-relations/{type}/{id}  搜索实体关系网络
  DELETE /sync-delete/{type}/{id}     统一删除三库
  GET    /sync-stats           三库统一统计
  POST   /sync-ingest          文档入库 + 三库同步
  GET    /tags/{entity_type}/{entity_id}  获取实体标签
  POST   /tags                 添加标签
  GET    /graph/trace/{type}/{id}         获取追溯链路
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Form, Query, HTTPException
from pydantic import BaseModel, Field

from app.rag.service.tri_store_coordinator import get_tri_store_coordinator

logger = logging.getLogger(__name__)

router = APIRouter()


# ===== 请求模型 =====


class SyncWriteRequest(BaseModel):
    """统一写入请求"""
    entity_type: str = Field(..., description="实体类型: document/requirement/page/api/case/script")
    entity_id: str = Field(..., description="实体ID")
    text: str = Field("", description="文本内容（用于生成向量）")
    metadata: dict = Field(default_factory=dict, description="元数据")
    embedding: Optional[List[float]] = Field(None, description="向量（为空则自动生成）")
    tags: Optional[List[str]] = Field(None, description="标签列表")
    neo4j_label: Optional[str] = Field(None, description="Neo4j节点标签")
    neo4j_properties: Optional[dict] = Field(None, description="Neo4j节点属性")


class SyncWriteRelationRequest(BaseModel):
    """统一写入关系请求"""
    from_type: str = Field(..., description="源实体类型")
    from_id: str = Field(..., description="源实体ID")
    rel_type: str = Field(..., description="关系类型: HAS_ELEMENT/CALLS_API/USES_TABLE/FLOW_STEP/DERIVES_TEST/TESTS_API/TESTS_PAGE/GENERATES_SCRIPT/EXECUTES_PAGE/REQUIRES/NAVIGATE_TO")
    to_type: str = Field(..., description="目标实体类型")
    to_id: str = Field(..., description="目标实体ID")
    properties: Optional[dict] = Field(None, description="关系属性")


class SyncQueryRequest(BaseModel):
    """统一查询请求"""
    query: str = Field(..., description="查询文本")
    entity_types: Optional[List[str]] = Field(None, description="实体类型过滤")
    top_k: int = Field(10, description="返回数量")
    score_threshold: float = Field(0.0, description="分数阈值")
    expand_graph: bool = Field(True, description="是否扩展图检索")


class AddTagRequest(BaseModel):
    """添加标签请求"""
    tag_name: str = Field(..., description="标签名称")
    tag_type: str = Field("custom", description="标签类型")
    entity_type: str = Field(..., description="实体类型")
    entity_id: int = Field(..., description="实体ID")


# ===== API 端点 =====


@router.post("/sync-write")
async def sync_write(req: SyncWriteRequest):
    """统一写入三库

    一个接口完成 MySQL（元数据+Tag）+ Milvus（向量）+ Neo4j（关系节点）写入。
    """
    coordinator = get_tri_store_coordinator()
    result = await coordinator.sync_write(
        entity_type=req.entity_type,
        entity_id=req.entity_id,
        text=req.text,
        metadata=req.metadata,
        embedding=req.embedding,
        tags=req.tags,
        neo4j_label=req.neo4j_label,
        neo4j_properties=req.neo4j_properties,
    )
    return {"code": 0, "message": "三库写入完成", "data": result}


@router.post("/sync-write-relation")
async def sync_write_relation(req: SyncWriteRelationRequest):
    """统一写入关系（Neo4j）

    在 Neo4j 中建立两个实体之间的关系。
    """
    coordinator = get_tri_store_coordinator()
    result = await coordinator.sync_write_relation(
        from_type=req.from_type,
        from_id=req.from_id,
        rel_type=req.rel_type,
        to_type=req.to_type,
        to_id=req.to_id,
        properties=req.properties,
    )
    return {"code": 0, "message": "关系写入完成", "data": result}


@router.post("/sync-query")
async def sync_query(req: SyncQueryRequest):
    """统一查询三库

    流程：Milvus（向量召回） → MySQL（元数据补全） → Neo4j（关系扩展）
    """
    coordinator = get_tri_store_coordinator()
    result = await coordinator.sync_query(
        query_text=req.query,
        entity_types=req.entity_types,
        top_k=req.top_k,
        score_threshold=req.score_threshold,
        expand_graph=req.expand_graph,
    )
    return {"code": 0, "message": "三库查询完成", "data": result}


@router.get("/sync-relations/{entity_type}/{entity_id}")
async def sync_search_relations(
    entity_type: str,
    entity_id: str,
    depth: int = Query(2, ge=1, le=5),
):
    """搜索实体的关系网络

    在 Neo4j 中查找指定实体的关联节点和关系，并补充 MySQL 元数据。
    """
    coordinator = get_tri_store_coordinator()
    result = await coordinator.sync_search_relations(
        entity_type=entity_type,
        entity_id=entity_id,
        depth=depth,
    )
    return {"code": 0, "message": "关系网络查询完成", "data": result}


@router.delete("/sync-delete/{entity_type}/{entity_id}")
async def sync_delete(entity_type: str, entity_id: str):
    """统一删除三库数据

    删除顺序：Neo4j（关系） → Milvus（向量） → MySQL（结构化数据）
    """
    coordinator = get_tri_store_coordinator()
    result = await coordinator.sync_delete(
        entity_type=entity_type,
        entity_id=entity_id,
    )
    return {"code": 0, "message": "三库删除完成", "data": result}


@router.get("/sync-stats")
async def sync_stats():
    """三库统一统计"""
    coordinator = get_tri_store_coordinator()
    stats = await coordinator.sync_stats()
    return {"code": 0, "message": "success", "data": stats}


@router.post("/sync-ingest")
async def sync_ingest(
    file_path: str = Form(...),
    source_type: str = Form(""),
    project_id: str = Form("default"),
    user_id: Optional[int] = Form(None),
    tags: str = Form(""),  # 逗号分隔
):
    """文档入库 + 三库同步

    在 RAG 管道入库基础上，额外完成 Tag 写入和 Neo4j 实体节点创建。
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    coordinator = get_tri_store_coordinator()
    result = await coordinator.ingest_with_sync(
        file_path=file_path,
        source_type=source_type,
        project_id=project_id,
        user_id=user_id,
        tags=tag_list,
    )
    return {"code": 0, "message": "三库同步入库完成", "data": result}


# ===== Tag 管理 =====


@router.get("/tags/{entity_type}/{entity_id}")
async def get_tags(entity_type: str, entity_id: int):
    """获取实体的标签列表"""
    coordinator = get_tri_store_coordinator()
    tags = coordinator._get_tags(entity_type, entity_id)
    return {"code": 0, "message": "success", "data": {"tags": tags}}


@router.post("/tags")
async def add_tag(req: AddTagRequest):
    """添加标签"""
    coordinator = get_tri_store_coordinator()
    coordinator._save_tags(req.entity_type, req.entity_id, [req.tag_name])
    return {"code": 0, "message": "标签添加成功"}


# ===== 追溯链路 =====


@router.get("/graph/trace/{entity_type}/{entity_id}")
async def get_traceability(
    entity_type: str,
    entity_id: str,
):
    """获取实体的追溯链路

    从指定实体出发，查找完整的关系追溯路径。
    例如：需求 → 页面 → 接口 → 表 → 流程 → 用例 → 脚本
    """
    coordinator = get_tri_store_coordinator()
    from app.rag.graph_store.extended_store import (
        NEO4J_LABEL_MAP,
        NEO4J_ID_FIELD_MAP,
        get_extended_graph_store,
    )

    label = NEO4J_LABEL_MAP.get(entity_type, "Entity")
    id_field = NEO4J_ID_FIELD_MAP.get(entity_type, "source_id")

    ext_graph = get_extended_graph_store()
    traces = await ext_graph.get_traceability(label, entity_id, id_field)
    return {"code": 0, "message": "success", "data": traces}
