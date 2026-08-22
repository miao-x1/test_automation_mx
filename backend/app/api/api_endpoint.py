"""
API 接口管理路由

挂载路径: /api/endpoints

接口分组:
  1. CRUD        - POST /  GET /list  GET /{id}  PUT /{id}  DELETE /{id}
  2. 状态管理     - POST /{id}/publish  PUT /{id}/status
  3. 版本管理     - GET /{id}/versions  GET /{id}/versions/{ver}  POST /{id}/rollback/{ver}
  4. 统计        - GET /stats
  5. 批量导入     - POST /batch-import

设计要点:
  1. 使用 Depends(require_auth) 获取当前用户
  2. 所有响应用 Response[T] 包装,保持与既有接口一致
  3. 业务异常由统一处理器转 HTTP(本文件不手动 try/except)
  4. /list 与 /{id} 注册顺序:列表在前,避免参数解析冲突(项目硬约束)
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status

from app.core.auth import require_auth
from app.core.exceptions import BusinessError
from app.models.user import User
from app.schemas.api_endpoint import (
    BatchImportResult,
    EndpointCreate,
    EndpointListItem,
    EndpointListResponse,
    EndpointResponse,
    EndpointStatsResponse,
    EndpointVersionDetail,
    EndpointVersionItem,
    PublishRequest,
    EndpointUpdate,
)
from app.schemas.response import Response
from app.services.api_endpoint_service import ApiEndpointService

router = APIRouter()

# 服务实例(无状态,可全局复用)
_service = ApiEndpointService()


# ============================================================
# 1. CRUD 接口
# ============================================================

@router.post("", response_model=Response[EndpointResponse], summary="创建接口")
async def create_endpoint(
    payload: EndpointCreate,
    user: User = Depends(require_auth),
):
    """创建一个新的 API 接口

    - 首次创建固定为 draft 状态
    - method+path 不能重复
    """
    result = _service.create_endpoint(payload, user_id=user.id, created_by=user.id)
    return Response(data=EndpointResponse(**result))


@router.get("/list", response_model=Response[EndpointListResponse], summary="接口列表(分页)")
async def list_endpoints(
    keyword: Optional[str] = Query(default=None, description="关键词"),
    method: Optional[str] = Query(default=None, description="HTTP 方法"),
    module: Optional[str] = Query(default=None, description="模块"),
    status_filter: Optional[str] = Query(default=None, alias="status", description="状态"),
    tags: Optional[str] = Query(default=None, description="标签(逗号分隔)"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    user: User = Depends(require_auth),
):
    """分页查询接口列表

    注意:GET /list 必须在 GET /{endpoint_id} 之前注册,避免参数解析冲突
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    result = _service.list_endpoints(
        user_id=user.id,
        keyword=keyword,
        method=method,
        module=module,
        status=status_filter,
        tags=tag_list,
        page=page,
        page_size=page_size,
    )
    return Response(data=EndpointListResponse(**result))


@router.get("/stats", response_model=Response[EndpointStatsResponse], summary="接口统计")
async def get_stats(
    user: User = Depends(require_auth),
):
    """按状态/方法/模块统计接口数"""
    result = _service.get_stats(user_id=user.id)
    return Response(data=EndpointStatsResponse(**result))


@router.get("/{endpoint_id}", response_model=Response[EndpointResponse], summary="接口详情")
async def get_endpoint(
    endpoint_id: int,
    user: User = Depends(require_auth),
):
    """按 ID 获取接口详情"""
    result = _service.get_endpoint(endpoint_id, user_id=user.id)
    return Response(data=EndpointResponse(**result))


@router.put("/{endpoint_id}", response_model=Response[EndpointResponse], summary="更新接口")
async def update_endpoint(
    endpoint_id: int,
    payload: EndpointUpdate,
    user: User = Depends(require_auth),
):
    """更新接口(部分更新,只更新非空字段)"""
    result = _service.update_endpoint(endpoint_id, payload, user_id=user.id)
    return Response(data=EndpointResponse(**result))


@router.delete("/{endpoint_id}", response_model=Response, summary="删除接口(软删除)")
async def delete_endpoint(
    endpoint_id: int,
    user: User = Depends(require_auth),
):
    """软删除接口(标记 is_deleted=True,不物理删除)"""
    _service.delete_endpoint(endpoint_id, user_id=user.id)
    return Response(message="删除成功")


# ============================================================
# 2. 状态管理
# ============================================================

@router.post("/{endpoint_id}/publish", response_model=Response[EndpointResponse], summary="发布接口")
async def publish_endpoint(
    endpoint_id: int,
    payload: PublishRequest,
    user: User = Depends(require_auth),
):
    """发布接口

    - 生成版本快照(自增版本号)
    - 状态置为 active
    - archived 状态需先恢复为 draft
    """
    result = _service.publish_endpoint(endpoint_id, payload, user_id=user.id)
    return Response(data=EndpointResponse(**result))


@router.put("/{endpoint_id}/status", response_model=Response[EndpointResponse], summary="修改状态")
async def change_status(
    endpoint_id: int,
    new_status: str = Query(..., description="目标状态: draft/active/deprecated/archived"),
    user: User = Depends(require_auth),
):
    """显式状态流转(不生成版本,用于 deprecated/archived 等切换)"""
    result = _service.change_status(endpoint_id, new_status, user_id=user.id)
    return Response(data=EndpointResponse(**result))


# ============================================================
# 3. 版本管理
# ============================================================

@router.get("/{endpoint_id}/versions", response_model=Response[List[EndpointVersionItem]], summary="版本列表")
async def list_versions(
    endpoint_id: int,
    user: User = Depends(require_auth),
):
    """列出接口的所有版本(按版本号倒序)"""
    result = _service.list_versions(endpoint_id, user_id=user.id)
    return Response(data=[EndpointVersionItem(**v) for v in result])


@router.get(
    "/{endpoint_id}/versions/{version}",
    response_model=Response[EndpointVersionDetail],
    summary="版本详情",
)
async def get_version(
    endpoint_id: int,
    version: int,
    user: User = Depends(require_auth),
):
    """获取指定版本详情(含完整快照)"""
    result = _service.get_version(endpoint_id, version, user_id=user.id)
    return Response(data=EndpointVersionDetail(**result))


@router.post(
    "/{endpoint_id}/rollback/{version}",
    response_model=Response[EndpointResponse],
    summary="回滚到指定版本",
)
async def rollback_to_version(
    endpoint_id: int,
    version: int,
    user: User = Depends(require_auth),
):
    """回滚到指定版本

    - 用目标版本快照覆盖当前接口字段
    - 创建新版本(标记"回滚自 vX")
    - archived 状态不允许回滚
    """
    result = _service.rollback_to_version(endpoint_id, version, user_id=user.id)
    return Response(data=EndpointResponse(**result))


# ============================================================
# 4. 批量导入
# ============================================================

@router.post("/batch-import", response_model=Response[BatchImportResult], summary="批量导入接口")
async def batch_import(
    endpoints: List[EndpointCreate],
    source: str = Query(default="import", description="来源: swagger/postman/har/import/ai"),
    user: User = Depends(require_auth),
):
    """批量导入接口(用于 Swagger/Postman 导入)

    - method+path 重复则跳过
    - 单条失败不影响其他,汇总返回
    """
    result = _service.batch_import(
        endpoints,
        source=source,
        user_id=user.id,
        created_by=user.id,
    )
    return Response(data=BatchImportResult(**result))


# ============================================================
# 业务异常 → HTTP 异常
# ============================================================
# 注意: APIRouter 不支持 exception_handler 装饰器,
# BusinessError 的统一处理由 app.main 中的全局异常处理器负责,
# 此处仅保留说明, 不在 router 级别注册 handler。
