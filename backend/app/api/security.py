"""企业级安全模块 — API

挂载路径: /api/security

路由:
  ===== API Key 管理 =====
  POST   /api-keys                         创建API Key(明文仅返回一次)
  GET    /api-keys/list                     API Key列表(脱敏)
  GET    /api-keys/stats                    API Key统计
  GET    /api-keys/{key_id}                 API Key详情
  PUT    /api-keys/{key_id}                 更新API Key
  DELETE /api-keys/{key_id}                 删除API Key
  POST   /api-keys/{key_id}/revoke          撤销API Key
  POST   /api-keys/cleanup-expired          清理过期Key

  ===== 脱敏规则管理 =====
  POST   /masking/rules                     创建脱敏规则
  GET    /masking/rules/list                脱敏规则列表
  GET    /masking/rules/{rule_id}           脱敏规则详情
  PUT    /masking/rules/{rule_id}           更新脱敏规则
  DELETE /masking/rules/{rule_id}           删除脱敏规则
  POST   /masking/init-defaults             初始化默认规则
  POST   /masking/test                      测试脱敏(传入数据返回脱敏结果)

  ===== 操作日志 =====
  GET    /audit/logs/list                   操作日志列表
  GET    /audit/logs/{log_id}               操作日志详情

  ===== 审计事件 =====
  GET    /audit/events/list                 审计事件列表
  GET    /audit/events/{event_id}           审计事件详情

  ===== 安全仪表盘 =====
  GET    /dashboard                         安全仪表盘
  GET    /stats                             安全统计
  GET    /anomalies                         安全异常检测
"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.auth import require_auth, require_admin
from app.models.user import User
from app.schemas.response import Response
from app.services.api_key_service import (
    ApiKeyService,
    get_api_key_service,
)
from app.services.audit_service import (
    AuditService,
    get_audit_service,
)
from app.services.masking_service import (
    MaskingService,
    get_masking_service,
)

router = APIRouter()

# 服务单例(模块级)
_api_key_service: ApiKeyService = get_api_key_service()
_audit_service: AuditService = get_audit_service()
_masking_service: MaskingService = get_masking_service()


# ============================================================
# 请求 Schema
# ============================================================

class ApiKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Key名称")
    description: Optional[str] = Field(default=None, max_length=500, description="描述")
    scopes: Optional[List[str]] = Field(default=None, description="权限范围")
    expires_at: Optional[str] = Field(default=None, description="过期时间(ISO格式)")


class ApiKeyUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = Field(default=None)
    scopes: Optional[List[str]] = Field(default=None)
    expires_at: Optional[str] = Field(default=None)
    is_active: Optional[bool] = Field(default=None)


class MaskingRuleCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="规则名称")
    description: Optional[str] = Field(default=None)
    field_name: Optional[str] = Field(default=None, description="字段名(精确匹配)")
    field_pattern: Optional[str] = Field(default=None, description="字段名正则匹配")
    mask_type: str = Field(..., description="脱敏类型: phone/email/id_card/bank_card/api_key/password/token/custom")
    visible_chars: Optional[int] = Field(default=4, ge=0, le=20)
    custom_mask: Optional[str] = Field(default=None)
    is_active: Optional[bool] = Field(default=True)


class MaskingRuleUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    field_name: Optional[str] = Field(default=None)
    field_pattern: Optional[str] = Field(default=None)
    mask_type: Optional[str] = Field(default=None)
    visible_chars: Optional[int] = Field(default=None, ge=0, le=20)
    custom_mask: Optional[str] = Field(default=None)
    is_active: Optional[bool] = Field(default=None)


class MaskingTestRequest(BaseModel):
    data: Dict[str, Any] = Field(..., description="待脱敏数据")
    rules: Optional[List[Dict[str, Any]]] = Field(default=None, description="自定义规则")


# ============================================================
# API Key 管理路由
# ============================================================

@router.post("/api-keys", response_model=Response[Dict[str, Any]], summary="创建API Key")
async def create_api_key(
    payload: ApiKeyCreateRequest,
    user: User = Depends(require_auth),
):
    """创建API Key

    - 明文Key仅在创建时返回一次,请妥善保存
    - 支持 scope 权限范围
    - 支持 expires_at 过期时间
    """
    try:
        expires_at = None
        if payload.expires_at:
            try:
                expires_at = datetime.fromisoformat(payload.expires_at)
            except ValueError:
                raise HTTPException(status_code=400, detail="expires_at 格式错误,需ISO格式")

        result = _api_key_service.create_key(
            name=payload.name,
            description=payload.description or "",
            scopes=payload.scopes,
            expires_at=expires_at,
            user_id=user.id,
        )

        # 记录审计事件
        _audit_service.log_event(
            event_type="api_key_operation",
            severity="info",
            user_id=user.id,
            username=user.username,
            action=f"创建API Key: {payload.name}",
            target_type="api_key",
            target_id=str(result.get("id")),
            details={"key_prefix": result.get("key_prefix"), "scopes": payload.scopes},
        )

        return Response(data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api-keys/list", response_model=Response[Dict[str, Any]], summary="API Key列表")
async def list_api_keys(
    is_active: Optional[bool] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(require_auth),
):
    """获取API Key列表(脱敏显示,不含明文)"""
    result = _api_key_service.list_keys(
        is_active=is_active,
        user_id=user.id,
        page=page,
        page_size=page_size,
    )
    return Response(data=result)


@router.get("/api-keys/stats", response_model=Response[Dict[str, Any]], summary="API Key统计")
async def get_api_key_stats(
    user: User = Depends(require_auth),
):
    """获取API Key统计信息"""
    result = _api_key_service.get_stats(user_id=user.id)
    return Response(data=result)


@router.get("/api-keys/{key_id}", response_model=Response[Dict[str, Any]], summary="API Key详情")
async def get_api_key(
    key_id: int,
    user: User = Depends(require_auth),
):
    """获取API Key详情(不含明文)"""
    result = _api_key_service.get_key(key_id, user_id=user.id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"ApiKey not found: {key_id}")
    return Response(data=result)


@router.put("/api-keys/{key_id}", response_model=Response[Dict[str, Any]], summary="更新API Key")
async def update_api_key(
    key_id: int,
    payload: ApiKeyUpdateRequest,
    user: User = Depends(require_auth),
):
    """更新API Key信息(名称/描述/范围/过期)"""
    try:
        data = payload.model_dump(exclude_unset=True)
        if "expires_at" in data and data["expires_at"]:
            try:
                data["expires_at"] = datetime.fromisoformat(data["expires_at"])
            except ValueError:
                raise HTTPException(status_code=400, detail="expires_at 格式错误")
        result = _api_key_service.update_key(key_id, data, user_id=user.id)
        return Response(data=result)
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api-keys/{key_id}", response_model=Response[Dict[str, Any]], summary="删除API Key")
async def delete_api_key(
    key_id: int,
    hard: bool = Query(default=False),
    user: User = Depends(require_auth),
):
    """删除API Key(默认软删除)"""
    ok = _api_key_service.delete_key(key_id, hard=hard, user_id=user.id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"ApiKey not found: {key_id}")

    _audit_service.log_event(
        event_type="api_key_operation",
        severity="warning",
        user_id=user.id,
        username=user.username,
        action=f"删除API Key: {key_id}",
        target_type="api_key",
        target_id=str(key_id),
    )

    return Response(data={"deleted": True, "hard": hard, "key_id": key_id})


@router.post("/api-keys/{key_id}/revoke", response_model=Response[Dict[str, Any]], summary="撤销API Key")
async def revoke_api_key(
    key_id: int,
    user: User = Depends(require_auth),
):
    """撤销API Key(停用,不可恢复)"""
    try:
        result = _api_key_service.revoke_key(key_id, user_id=user.id)

        _audit_service.log_event(
            event_type="api_key_operation",
            severity="warning",
            user_id=user.id,
            username=user.username,
            action=f"撤销API Key: {key_id}",
            target_type="api_key",
            target_id=str(key_id),
        )

        return Response(data=result)
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api-keys/cleanup-expired", response_model=Response[Dict[str, Any]], summary="清理过期Key")
async def cleanup_expired_keys(
    user: User = Depends(require_admin),
):
    """清理已过期的API Key(需管理员权限)"""
    count = _api_key_service.cleanup_expired()

    _audit_service.log_event(
        event_type="api_key_operation",
        severity="info",
        user_id=user.id,
        username=user.username,
        action=f"清理过期API Key: {count}个",
    )

    return Response(data={"cleaned": count})


# ============================================================
# 脱敏规则路由
# ============================================================

@router.post("/masking/rules", response_model=Response[Dict[str, Any]], summary="创建脱敏规则")
async def create_masking_rule(
    payload: MaskingRuleCreateRequest,
    user: User = Depends(require_auth),
):
    """创建脱敏规则"""
    try:
        result = _masking_service.create_rule(payload.model_dump())
        return Response(data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/masking/rules/list", response_model=Response[Dict[str, Any]], summary="脱敏规则列表")
async def list_masking_rules(
    is_active: Optional[bool] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    user: User = Depends(require_auth),
):
    """获取脱敏规则列表"""
    result = _masking_service.list_rules(is_active=is_active, page=page, page_size=page_size)
    return Response(data=result)


@router.get("/masking/rules/{rule_id}", response_model=Response[Dict[str, Any]], summary="脱敏规则详情")
async def get_masking_rule(
    rule_id: int,
    user: User = Depends(require_auth),
):
    """获取脱敏规则详情"""
    result = _masking_service.get_rule(rule_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"MaskingRule not found: {rule_id}")
    return Response(data=result)


@router.put("/masking/rules/{rule_id}", response_model=Response[Dict[str, Any]], summary="更新脱敏规则")
async def update_masking_rule(
    rule_id: int,
    payload: MaskingRuleUpdateRequest,
    user: User = Depends(require_auth),
):
    """更新脱敏规则"""
    try:
        result = _masking_service.update_rule(rule_id, payload.model_dump(exclude_unset=True))
        return Response(data=result)
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/masking/rules/{rule_id}", response_model=Response[Dict[str, Any]], summary="删除脱敏规则")
async def delete_masking_rule(
    rule_id: int,
    hard: bool = Query(default=False),
    user: User = Depends(require_auth),
):
    """删除脱敏规则"""
    ok = _masking_service.delete_rule(rule_id, hard=hard)
    if not ok:
        raise HTTPException(status_code=404, detail=f"MaskingRule not found: {rule_id}")
    return Response(data={"deleted": True, "hard": hard, "rule_id": rule_id})


@router.post("/masking/init-defaults", response_model=Response[Dict[str, Any]], summary="初始化默认脱敏规则")
async def init_default_masking_rules(
    user: User = Depends(require_admin),
):
    """初始化默认脱敏规则(需管理员权限,仅在无规则时创建)"""
    count = _masking_service.init_default_rules()
    return Response(data={"initialized": count})


@router.post("/masking/test", response_model=Response[Dict[str, Any]], summary="测试脱敏")
async def test_masking(
    payload: MaskingTestRequest,
    user: User = Depends(require_auth),
):
    """测试脱敏效果(传入数据返回脱敏结果)"""
    masked = _masking_service.mask_dict(payload.data, payload.rules)
    return Response(data={"original": payload.data, "masked": masked})


# ============================================================
# 操作日志路由
# ============================================================

@router.get("/audit/logs/list", response_model=Response[Dict[str, Any]], summary="操作日志列表")
async def list_operation_logs(
    username: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None),
    resource_type: Optional[str] = Query(default=None),
    ip_address: Optional[str] = Query(default=None),
    start_time: Optional[str] = Query(default=None, description="开始时间(ISO)"),
    end_time: Optional[str] = Query(default=None, description="结束时间(ISO)"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    user: User = Depends(require_auth),
):
    """获取操作日志列表(支持多条件筛选)"""
    start_dt = None
    end_dt = None
    if start_time:
        try:
            start_dt = datetime.fromisoformat(start_time)
        except ValueError:
            raise HTTPException(status_code=400, detail="start_time 格式错误")
    if end_time:
        try:
            end_dt = datetime.fromisoformat(end_time)
        except ValueError:
            raise HTTPException(status_code=400, detail="end_time 格式错误")

    result = _audit_service.list_operation_logs(
        username=username,
        action=action,
        resource_type=resource_type,
        ip_address=ip_address,
        start_time=start_dt,
        end_time=end_dt,
        page=page,
        page_size=page_size,
    )
    return Response(data=result)


@router.get("/audit/logs/{log_id}", response_model=Response[Dict[str, Any]], summary="操作日志详情")
async def get_operation_log(
    log_id: int,
    user: User = Depends(require_auth),
):
    """获取操作日志详情"""
    result = _audit_service.get_operation_log(log_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"OperationLog not found: {log_id}")
    return Response(data=result)


# ============================================================
# 审计事件路由
# ============================================================

@router.get("/audit/events/list", response_model=Response[Dict[str, Any]], summary="审计事件列表")
async def list_audit_events(
    event_type: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default=None),
    username: Optional[str] = Query(default=None),
    target_type: Optional[str] = Query(default=None),
    start_time: Optional[str] = Query(default=None),
    end_time: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    user: User = Depends(require_auth),
):
    """获取审计事件列表"""
    start_dt = None
    end_dt = None
    if start_time:
        try:
            start_dt = datetime.fromisoformat(start_time)
        except ValueError:
            raise HTTPException(status_code=400, detail="start_time 格式错误")
    if end_time:
        try:
            end_dt = datetime.fromisoformat(end_time)
        except ValueError:
            raise HTTPException(status_code=400, detail="end_time 格式错误")

    result = _audit_service.list_audit_events(
        event_type=event_type,
        severity=severity,
        username=username,
        target_type=target_type,
        start_time=start_dt,
        end_time=end_dt,
        page=page,
        page_size=page_size,
    )
    return Response(data=result)


@router.get("/audit/events/{event_id}", response_model=Response[Dict[str, Any]], summary="审计事件详情")
async def get_audit_event(
    event_id: int,
    user: User = Depends(require_auth),
):
    """获取审计事件详情"""
    result = _audit_service.get_audit_event(event_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"AuditEvent not found: {event_id}")
    return Response(data=result)


# ============================================================
# 安全仪表盘
# ============================================================

@router.get("/dashboard", response_model=Response[Dict[str, Any]], summary="安全仪表盘")
async def get_security_dashboard(
    hours: int = Query(default=24, ge=1, le=168, description="统计时间范围(小时)"),
    user: User = Depends(require_auth),
):
    """获取安全仪表盘数据

    返回:
    - operation_logs: 操作日志统计(按动作/状态/用户/IP)
    - audit_events: 审计事件统计(按类型/严重级别)
    - alerts: 告警信息(异常IP/高错误率/严重事件)
    """
    result = _audit_service.get_dashboard(hours=hours)
    return Response(data=result)


@router.get("/stats", response_model=Response[Dict[str, Any]], summary="安全统计")
async def get_security_stats(
    hours: int = Query(default=24, ge=1, le=168),
    user: User = Depends(require_auth),
):
    """获取安全统计信息"""
    result = _audit_service.get_stats(hours=hours)
    return Response(data=result)


@router.get("/anomalies", response_model=Response[Dict[str, Any]], summary="安全异常检测")
async def detect_anomalies(
    hours: int = Query(default=1, ge=1, le=24, description="检测时间范围(小时)"),
    user: User = Depends(require_auth),
):
    """检测安全异常

    检测规则:
    1. 同IP高频访问(>50次/小时)
    2. 大量失败请求(>10次/小时)
    3. 敏感操作(删除/权限变更)
    """
    result = _audit_service.detect_security_anomalies(hours=hours)
    return Response(data={"anomalies": result, "count": len(result)})
