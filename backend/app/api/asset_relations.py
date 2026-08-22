"""
测试资产中心 — 资产关系路由

挂载路径: /api/asset-center/relations

接口分组:
  1. CRUD         - POST /  GET /list  GET /{id}  PUT /{id}  DELETE /{id}
  2. 影响面分析   - GET /impact/{asset_id}
  3. 统计        - GET /stats

设计要点:
  1. 使用 Depends(require_auth) 获取当前用户
  2. /list /stats /impact 必须在 /{id} 之前注册
  3. Neo4j 同步为异步钩子, 不阻塞主流程
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.core.auth import require_auth
from app.models.user import User
from app.schemas.asset_registry import (
    AssetRelationItem,
    AssetRelationListResponse,
    AssetStatsResponse,
    RelationCreate,
    RelationOperationResult,
    RelationUpdate,
)
from app.schemas.response import Response
from app.services.asset_relation_service import AssetRelationService

router = APIRouter()

# 服务实例(无状态,可全局复用)
_service = AssetRelationService()


# ============================================================
# 1. CRUD 接口
# ============================================================

@router.post("", response_model=Response[AssetRelationItem], summary="创建资产关系")
async def create_relation(
    payload: RelationCreate,
    user: User = Depends(require_auth),
):
    """创建资产关系

    - source / target 资产必须存在 (未软删除)
    - source / target 不能是已归档状态
    - (source, type, target) 不重复
    - 不允许自环 (source_id == target_id)
    - 创建后触发 Neo4j 同步钩子
    """
    result = _service.create_relation(payload, user_id=user.id)
    return Response(data=AssetRelationItem(**result))


@router.get("/list", response_model=Response[AssetRelationListResponse], summary="关系列表(分页)")
async def list_relations(
    asset_id: Optional[int] = Query(default=None, description="查询该资产的出入关系"),
    direction: Optional[str] = Query(
        default=None, description="方向: outgoing / incoming (空则两者都查)",
    ),
    relation_type: Optional[str] = Query(default=None, description="关系类型"),
    target_type: Optional[str] = Query(default=None, description="对端资产类型"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=50, ge=1, le=200, description="每页条数"),
    user: User = Depends(require_auth),
):
    """分页查询关系列表

    注意: GET /list 必须在 GET /{relation_id} 之前注册
    """
    result = _service.list_relations(
        asset_id=asset_id,
        direction=direction,
        relation_type=relation_type,
        target_type=target_type,
        user_id=user.id,
        page=page,
        page_size=page_size,
    )
    return Response(data=AssetRelationListResponse(**result))


@router.get("/stats", response_model=Response[AssetStatsResponse], summary="关系统计")
async def get_stats(
    user: User = Depends(require_auth),
):
    """关系统计 (总数 + 待同步 Neo4j 数)"""
    result = _service.get_stats(user_id=user.id)
    return Response(data=AssetStatsResponse(
        total=0,  # 资产总数不在此接口返回, 仅返回关系统计
        by_type={}, by_status={}, by_module={}, by_source={},
        avg_quality_score=0.0,
        total_relations=result.get("total_relations", 0),
        pending_neo4j_sync=result.get("pending_neo4j_sync", 0),
    ))


@router.get("/impact/{asset_id}", summary="影响面分析")
async def impact_analysis(
    asset_id: int,
    depth: int = Query(default=2, ge=1, le=3, description="搜索深度 (1=直接, 2=二度, 3=三度)"),
    user: User = Depends(require_auth),
):
    """影响面分析: 给定资产, 找出所有受影响的相关资产 (BFS)

    - depth: 搜索深度, 默认 2 度
    - 返回 root_asset + impacted 列表 (含路径)
    """
    result = _service.impact_analysis(asset_id, depth=depth, user_id=user.id)
    return Response(data=result)


@router.get("/{relation_id}", response_model=Response[AssetRelationItem], summary="关系详情")
async def get_relation(
    relation_id: int,
    user: User = Depends(require_auth),
):
    """按 ID 获取关系详情 (含对端资产概要)"""
    result = _service.get_relation(relation_id, user_id=user.id)
    return Response(data=AssetRelationItem(**result))


@router.put("/{relation_id}", response_model=Response[AssetRelationItem], summary="更新关系")
async def update_relation(
    relation_id: int,
    payload: RelationUpdate,
    user: User = Depends(require_auth),
):
    """更新关系权重或元数据

    - 更新后 neo4j_synced 重置为 False (需要重新同步)
    """
    result = _service.update_relation(relation_id, payload, user_id=user.id)
    return Response(data=AssetRelationItem(**result))


@router.delete(
    "/{relation_id}",
    response_model=Response[RelationOperationResult],
    summary="删除关系(软删除)",
)
async def delete_relation(
    relation_id: int,
    user: User = Depends(require_auth),
):
    """软删除关系

    - 标记 is_deleted=True
    - Neo4j 中的对应边由补偿任务删除
    """
    result = _service.delete_relation(relation_id, user_id=user.id)
    return Response(
        data=RelationOperationResult(
            success=True,
            relation_id=result["id"],
            message="关系已软删除",
        )
    )


# ============================================================
# 2. Neo4j 同步 (管理接口)
# ============================================================

@router.post(
    "/neo4j/sync-pending",
    response_model=Response[dict],
    summary="同步待同步关系到 Neo4j (Phase 2 stub)",
)
async def sync_pending_to_neo4j(
    batch_size: int = Query(default=100, ge=1, le=1000, description="批量大小"),
    user: User = Depends(require_auth),
):
    """补偿任务: 批量同步未同步的关系到 Neo4j

    Phase 2: stub, 仅返回待同步数量
    Phase 3: 接入真实 Neo4j client
    """
    result = _service.sync_pending_to_neo4j(batch_size=batch_size)
    return Response(data=result)
