"""
测试资产中心 — 资产索引路由

挂载路径: /api/asset-center/assets

接口分组:
  1. CRUD         - POST /  GET /list  GET /{id}  PUT /{id}  DELETE /{id}
  2. 状态管理      - POST /{id}/publish  PUT /{id}/status  POST /{id}/mark-used
  3. 版本管理      - GET /{id}/versions  GET /{id}/versions/{ver}  POST /{id}/rollback/{ver}
  4. 统计         - GET /stats

设计要点:
  1. 使用 Depends(require_auth) 获取当前用户
  2. 所有响应用 Response[T] 包装
  3. /list /stats /batch-import 必须在 /{id} 之前注册
  4. 业务异常由统一处理器转 HTTP
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.core.auth import require_auth
from app.models.user import User
from app.schemas.asset_registry import (
    AssetCreate,
    AssetListItem,
    AssetListResponse,
    AssetResponse,
    AssetStatsResponse,
    AssetUpdate,
    AssetVersionDetail,
    AssetVersionItem,
    AssetVersionListResponse,
    OperationResult,
    PublishRequest,
    StateTransitionRequest,
)
from app.schemas.response import Response
from app.services.asset_registry_service import AssetRegistryService

router = APIRouter()

# 服务实例(无状态,可全局复用)
_service = AssetRegistryService()


# ============================================================
# 1. CRUD 接口
# ============================================================

@router.post("", response_model=Response[AssetResponse], summary="创建资产")
async def create_asset(
    payload: AssetCreate,
    user: User = Depends(require_auth),
):
    """创建一个新的测试资产索引

    - 首次创建固定为 draft 状态
    - asset_code 不传则系统生成
    - ref_type + ref_id 不能与既有资产重复 (ref_id > 0 时)
    """
    result = _service.create_asset(payload, user_id=user.id, created_by=user.id)
    return Response(data=AssetResponse(**result))


@router.get("/list", response_model=Response[AssetListResponse], summary="资产列表(分页)")
async def list_assets(
    keyword: Optional[str] = Query(default=None, description="关键词"),
    asset_type: Optional[str] = Query(default=None, description="资产类型"),
    status_filter: Optional[str] = Query(default=None, alias="status", description="状态"),
    module: Optional[str] = Query(default=None, description="模块"),
    source: Optional[str] = Query(default=None, description="来源"),
    tags: Optional[str] = Query(default=None, description="标签(逗号分隔)"),
    ref_type: Optional[str] = Query(default=None, description="关联表名"),
    min_quality: Optional[float] = Query(default=None, ge=0, le=100, description="最低质量评分"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    user: User = Depends(require_auth),
):
    """分页查询资产列表

    注意: GET /list 必须在 GET /{asset_id} 之前注册
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    result = _service.list_assets(
        user_id=user.id,
        keyword=keyword,
        asset_type=asset_type,
        status=status_filter,
        module=module,
        source=source,
        tags=tag_list,
        ref_type=ref_type,
        min_quality=min_quality,
        page=page,
        page_size=page_size,
    )
    return Response(data=AssetListResponse(**result))


@router.get("/stats", response_model=Response[AssetStatsResponse], summary="资产统计")
async def get_stats(
    user: User = Depends(require_auth),
):
    """按类型/状态/模块/来源统计资产数"""
    # 同时获取资产统计和关系统计
    asset_stats = _service.get_stats(user_id=user.id)

    # 补充关系统计 (从 AssetRelationService)
    from app.services.asset_relation_service import AssetRelationService
    rel_service = AssetRelationService()
    rel_stats = rel_service.get_stats(user_id=user.id)

    # 合并统计
    merged = {**asset_stats, **rel_stats}
    return Response(data=AssetStatsResponse(**merged))


@router.get("/{asset_id}", response_model=Response[AssetResponse], summary="资产详情")
async def get_asset(
    asset_id: int,
    user: User = Depends(require_auth),
):
    """按 ID 获取资产详情"""
    result = _service.get_asset(asset_id, user_id=user.id)
    return Response(data=AssetResponse(**result))


@router.put("/{asset_id}", response_model=Response[AssetResponse], summary="更新资产")
async def update_asset(
    asset_id: int,
    payload: AssetUpdate,
    user: User = Depends(require_auth),
):
    """更新资产(部分更新,只更新非空字段)

    - 不可变字段: asset_code / asset_type / ref_type / ref_id
    - archived 状态不允许更新, 需先恢复为 draft
    - 更新不生成新版本, 需调用 /publish 才生成版本
    """
    result = _service.update_asset(asset_id, payload, user_id=user.id)
    return Response(data=AssetResponse(**result))


@router.delete("/{asset_id}", response_model=Response[OperationResult], summary="删除资产(软删除)")
async def delete_asset(
    asset_id: int,
    user: User = Depends(require_auth),
):
    """软删除资产(标记 is_deleted=True,不物理删除)

    - 历史版本与关系保留 (供审计)
    - 可通过 include_deleted=True 查询
    """
    result = _service.delete_asset(asset_id, user_id=user.id)
    return Response(
        data=OperationResult(
            success=True,
            asset_id=result["id"],
            message="资产已软删除",
        )
    )


# ============================================================
# 2. 状态管理
# ============================================================

@router.post("/{asset_id}/publish", response_model=Response[AssetResponse], summary="发布资产")
async def publish_asset(
    asset_id: int,
    payload: PublishRequest,
    user: User = Depends(require_auth),
):
    """发布资产

    - 生成版本快照(自增版本号)
    - 状态置为 active
    - 生成与上一版本的 diff_summary
    - archived 状态需先恢复为 draft
    """
    result = _service.publish_asset(asset_id, payload, user_id=user.id)
    return Response(data=AssetResponse(**result))


@router.put("/{asset_id}/status", response_model=Response[AssetResponse], summary="状态流转")
async def change_status(
    asset_id: int,
    payload: StateTransitionRequest,
    user: User = Depends(require_auth),
):
    """显式状态流转 (生成 status_change 版本记录)

    允许的流转:
      draft      → active / archived
      active     → deprecated / archived
      deprecated → active / archived
      archived   → draft (仅恢复)
    """
    result = _service.change_status(asset_id, payload, user_id=user.id)
    return Response(data=AssetResponse(**result))


@router.post(
    "/{asset_id}/mark-used",
    response_model=Response[AssetResponse],
    summary="标记资产被使用",
)
async def mark_used(
    asset_id: int,
    user: User = Depends(require_auth),
):
    """标记资产被复用 (reuse_count +1, 更新 last_used_at)

    用于 Agent 复用资产后更新统计
    """
    result = _service.mark_used(asset_id, user_id=user.id)
    return Response(data=AssetResponse(**result))


# ============================================================
# 3. 版本管理
# ============================================================

@router.get(
    "/{asset_id}/versions",
    response_model=Response[AssetVersionListResponse],
    summary="版本列表",
)
async def list_versions(
    asset_id: int,
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=50, ge=1, le=200, description="每页条数"),
    user: User = Depends(require_auth),
):
    """列出资产的所有版本(按版本号倒序)"""
    result = _service.list_versions(
        asset_id, user_id=user.id, page=page, page_size=page_size
    )
    return Response(data=AssetVersionListResponse(**result))


@router.get(
    "/{asset_id}/versions/{version}",
    response_model=Response[AssetVersionDetail],
    summary="版本详情",
)
async def get_version(
    asset_id: int,
    version: int,
    user: User = Depends(require_auth),
):
    """获取指定版本详情(含完整快照)"""
    result = _service.get_version(asset_id, version, user_id=user.id)
    return Response(data=AssetVersionDetail(**result))


@router.post(
    "/{asset_id}/rollback/{version}",
    response_model=Response[AssetResponse],
    summary="回滚到指定版本",
)
async def rollback_to_version(
    asset_id: int,
    version: int,
    user: User = Depends(require_auth),
):
    """回滚到指定版本

    - 用目标版本快照恢复可变字段 (name/summary/description/module/tags/extra_metadata)
    - 不可变字段不恢复: asset_code / asset_type / ref_type / ref_id
    - 创建新版本 (change_type=rollback)
    - archived 状态不允许回滚
    """
    result = _service.rollback_to_version(asset_id, version, user_id=user.id)
    return Response(data=AssetResponse(**result))
