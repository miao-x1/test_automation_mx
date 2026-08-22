"""
测试环境管理 — API

挂载路径: /api/environments

接口分组:
  1. Environment CRUD
     - POST   /                      创建环境
     - GET    /list                  环境列表(分页)
     - GET    /{env_id}              环境详情(脱敏)
     - PUT    /{env_id}              更新环境
     - DELETE /{env_id}              删除环境
     - POST   /{env_id}/set-default  设为默认环境

  2. Secret 管理
     - GET    /{env_id}/secrets      列出密钥
     - POST   /{env_id}/secrets      添加密钥
     - DELETE /{env_id}/secrets/{key_name}  删除密钥

  3. 环境选择与配置
     - GET    /select                自动选择环境
     - GET    /{env_id}/runtime-config  获取运行时配置(解密)

  4. 测试连接
     - POST   /{env_id}/test          测试连通性

  5. 统计
     - GET    /stats                  环境统计
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.auth import require_auth
from app.models.user import User
from app.schemas.response import Response
from app.services.environment_manager import (
    EnvironmentManager,
    get_environment_manager,
)

router = APIRouter()

_service: EnvironmentManager = get_environment_manager()


# ============================================================
# 请求 Schema
# ============================================================

class EnvironmentCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, description="环境名称")
    display_name: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = None
    env_type: str = Field(default="test", description="环境类型: dev/test/staging/prod")
    base_url: Optional[str] = Field(default=None, max_length=500)
    api_url: Optional[str] = Field(default=None, max_length=500)
    web_url: Optional[str] = Field(default=None, max_length=500)
    db_host: Optional[str] = Field(default=None, max_length=200)
    db_port: Optional[int] = Field(default=None, ge=1, le=65535)
    db_name: Optional[str] = Field(default=None, max_length=100)
    db_user: Optional[str] = Field(default=None, max_length=100)
    db_password: Optional[str] = Field(default=None, description="数据库密码(自动加密)")
    api_key: Optional[str] = Field(default=None, description="API Key(自动加密)")
    api_secret: Optional[str] = Field(default=None, description="API Secret(自动加密)")
    headers_json: Optional[str] = None
    variables_json: Optional[str] = None
    tags: Optional[str] = None
    is_active: bool = Field(default=True)
    is_default: bool = Field(default=False)


class EnvironmentUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    env_type: Optional[str] = None
    base_url: Optional[str] = None
    api_url: Optional[str] = None
    web_url: Optional[str] = None
    db_host: Optional[str] = None
    db_port: Optional[int] = Field(default=None, ge=1, le=65535)
    db_name: Optional[str] = None
    db_user: Optional[str] = None
    db_password: Optional[str] = Field(default=None, description="新密码(自动加密)")
    api_key: Optional[str] = Field(default=None, description="新 API Key(自动加密)")
    api_secret: Optional[str] = Field(default=None, description="新 API Secret(自动加密)")
    headers_json: Optional[str] = None
    variables_json: Optional[str] = None
    tags: Optional[str] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None


class SecretAddRequest(BaseModel):
    key_name: str = Field(..., min_length=1, max_length=100)
    value: str = Field(..., description="密钥值(自动加密)")
    value_type: str = Field(default="string", description="值类型: string/json/base64")
    description: Optional[str] = None
    is_sensitive: bool = Field(default=True)


class TestConnectionRequest(BaseModel):
    test_type: str = Field(default="http", description="测试类型: http/db")


# ============================================================
# 1. Environment CRUD
# ============================================================

@router.post(
    "",
    response_model=Response[Dict[str, Any]],
    summary="创建测试环境",
)
async def create_environment(
    payload: EnvironmentCreateRequest,
    user: User = Depends(require_auth),
):
    """创建测试环境,敏感字段自动加密"""
    try:
        result = _service.create_environment(
            payload.model_dump(),
            user_id=user.id,
        )
        return Response(data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/list",
    response_model=Response[Dict[str, Any]],
    summary="环境列表(分页)",
)
async def list_environments(
    env_type: Optional[str] = Query(default=None, description="环境类型"),
    is_active: Optional[bool] = Query(default=None, description="是否启用"),
    keyword: Optional[str] = Query(default=None, description="关键词"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(require_auth),
):
    """分页查询环境列表(敏感字段脱敏)"""
    result = _service.list_environments(
        env_type=env_type,
        is_active=is_active,
        keyword=keyword,
        user_id=user.id,
        page=page,
        page_size=page_size,
    )
    return Response(data=result)


@router.get(
    "/stats",
    response_model=Response[Dict[str, Any]],
    summary="环境统计",
)
async def get_stats(
    user: User = Depends(require_auth),
):
    """获取环境统计"""
    result = _service.get_stats(user_id=user.id)
    return Response(data=result)


@router.get(
    "/select",
    response_model=Response[Dict[str, Any]],
    summary="自动选择环境",
)
async def select_environment(
    env_name: Optional[str] = Query(default=None, description="环境名称"),
    env_id: Optional[int] = Query(default=None, description="环境 ID"),
    user: User = Depends(require_auth),
):
    """自动选择环境

    优先级: env_id > env_name > 默认环境 > test 环境 > 第一个
    """
    result = _service.select_environment(
        env_name=env_name,
        env_id=env_id,
        user_id=user.id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="no available environment")
    return Response(data=result)


@router.get(
    "/{env_id}",
    response_model=Response[Dict[str, Any]],
    summary="环境详情",
)
async def get_environment(
    env_id: int,
    reveal: bool = Query(default=False, description="是否显示敏感字段明文(需要管理员权限)"),
    user: User = Depends(require_auth),
):
    """获取环境详情(默认脱敏)"""
    result = _service.get_environment(
        env_id,
        include_secrets=reveal,
        user_id=user.id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail=f"TestEnvironment not found: {env_id}")
    return Response(data=result)


@router.put(
    "/{env_id}",
    response_model=Response[Dict[str, Any]],
    summary="更新环境",
)
async def update_environment(
    env_id: int,
    payload: EnvironmentUpdateRequest,
    user: User = Depends(require_auth),
):
    """更新环境(敏感字段自动加密)"""
    try:
        data = payload.model_dump(exclude_unset=True)
        result = _service.update_environment(env_id, data, user_id=user.id)
        return Response(data=result)
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.delete(
    "/{env_id}",
    response_model=Response[Dict[str, Any]],
    summary="删除环境",
)
async def delete_environment(
    env_id: int,
    hard: bool = Query(default=False, description="True=物理删除,False=软删除"),
    user: User = Depends(require_auth),
):
    """删除环境(默认软删除)"""
    ok = _service.delete_environment(env_id, hard=hard, user_id=user.id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"TestEnvironment not found: {env_id}")
    return Response(data={"deleted": True, "hard": hard, "env_id": env_id})


@router.post(
    "/{env_id}/set-default",
    response_model=Response[Dict[str, Any]],
    summary="设为默认环境",
)
async def set_default_environment(
    env_id: int,
    user: User = Depends(require_auth),
):
    """设为默认环境(清除其他默认)"""
    try:
        result = _service.set_default(env_id, user_id=user.id)
        return Response(data=result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/{env_id}/runtime-config",
    response_model=Response[Dict[str, Any]],
    summary="获取运行时配置(解密)",
)
async def get_runtime_config(
    env_id: int,
    user: User = Depends(require_auth),
):
    """获取环境的运行时配置(包含解密后的敏感字段)

    供 ExecutionFlow / Agent 使用。
    """
    result = _service.get_runtime_config(env_id=env_id, user_id=user.id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"TestEnvironment not found: {env_id}")
    return Response(data=result)


# ============================================================
# 2. Secret 管理
# ============================================================

@router.get(
    "/{env_id}/secrets",
    response_model=Response[List[Dict[str, Any]]],
    summary="列出环境密钥",
)
async def list_secrets(
    env_id: int,
    reveal: bool = Query(default=False, description="是否显示密钥明文"),
    user: User = Depends(require_auth),
):
    """列出环境密钥(默认脱敏)"""
    result = _service.list_secrets(env_id, reveal=reveal)
    return Response(data=result)


@router.post(
    "/{env_id}/secrets",
    response_model=Response[Dict[str, Any]],
    summary="添加环境密钥",
)
async def add_secret(
    env_id: int,
    payload: SecretAddRequest,
    user: User = Depends(require_auth),
):
    """添加环境密钥(自动加密)"""
    try:
        result = _service.add_secret(
            env_id,
            payload.key_name,
            payload.value,
            value_type=payload.value_type,
            description=payload.description,
            is_sensitive=payload.is_sensitive,
            user_id=user.id,
        )
        return Response(data=result)
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.delete(
    "/{env_id}/secrets/{key_name}",
    response_model=Response[Dict[str, Any]],
    summary="删除环境密钥",
)
async def remove_secret(
    env_id: int,
    key_name: str,
    user: User = Depends(require_auth),
):
    """删除环境密钥"""
    ok = _service.remove_secret(env_id, key_name)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Secret '{key_name}' not found in environment {env_id}",
        )
    return Response(data={"removed": True, "env_id": env_id, "key_name": key_name})


# ============================================================
# 3. 测试连接
# ============================================================

@router.post(
    "/{env_id}/test",
    response_model=Response[Dict[str, Any]],
    summary="测试环境连通性",
)
async def test_connection(
    env_id: int,
    payload: TestConnectionRequest,
    user: User = Depends(require_auth),
):
    """测试环境连通性(HTTP / 数据库)"""
    result = await _service.test_connection(
        env_id,
        test_type=payload.test_type,
        user_id=user.id,
    )
    return Response(data=result)
