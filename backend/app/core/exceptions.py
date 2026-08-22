"""
业务异常定义

本文件定义通用业务异常基类与接口管理模块专用异常。
与 app/agent/core/exceptions.py 的 Agent 异常体系独立,互不影响。

设计原则:
  1. 所有业务异常继承 BusinessError,便于上层统一捕获
  2. 每个异常带 code + details,可序列化为 API 响应
  3. 异常分级:NotFoundError(404) / ConflictError(409) / ValidationError(422) / StateError(409)
"""
from typing import Any, Dict, Optional


class BusinessError(Exception):
    """业务异常基类"""

    #: HTTP 状态码(子类覆盖)
    status_code: int = 400

    #: 错误码(子类覆盖)
    code: str = "BUSINESS_ERROR"

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code or self.code
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


# ============================================================
# 通用异常
# ============================================================

class NotFoundError(BusinessError):
    """资源不存在(404)"""
    status_code = 404
    code = "NOT_FOUND"


class ConflictError(BusinessError):
    """资源冲突(409)"""
    status_code = 409
    code = "CONFLICT"


class ValidationError(BusinessError):
    """业务校验失败(422)"""
    status_code = 422
    code = "VALIDATION_ERROR"


class StateError(BusinessError):
    """状态机错误(409) - 资源当前状态不允许此操作"""
    status_code = 409
    code = "STATE_ERROR"


# ============================================================
# 接口管理模块专用异常
# ============================================================

class EndpointNotFoundError(NotFoundError):
    """接口不存在"""
    code = "ENDPOINT_NOT_FOUND"

    def __init__(self, message: str, *, endpoint_id: Optional[int] = None):
        details = {"endpoint_id": endpoint_id} if endpoint_id else {}
        super().__init__(message, details=details)


class EndpointConflictError(ConflictError):
    """接口冲突(method+path 重复)"""
    code = "ENDPOINT_CONFLICT"

    def __init__(self, message: str, *, endpoint_id: Optional[int] = None):
        details = {"existing_id": endpoint_id} if endpoint_id else {}
        super().__init__(message, details=details)


class EndpointVersionNotFoundError(NotFoundError):
    """接口版本不存在"""
    code = "ENDPOINT_VERSION_NOT_FOUND"

    def __init__(
        self,
        message: str,
        *,
        endpoint_id: Optional[int] = None,
        version: Optional[int] = None,
    ):
        details = {}
        if endpoint_id is not None:
            details["endpoint_id"] = endpoint_id
        if version is not None:
            details["version"] = version
        super().__init__(message, details=details)


class EndpointStateError(StateError):
    """接口状态机错误(如 draft 状态无法回滚)"""
    code = "ENDPOINT_STATE_ERROR"

    def __init__(
        self,
        message: str,
        *,
        endpoint_id: Optional[int] = None,
        current_status: Optional[str] = None,
        expected_status: Optional[str] = None,
    ):
        details = {}
        if endpoint_id is not None:
            details["endpoint_id"] = endpoint_id
        if current_status is not None:
            details["current_status"] = current_status
        if expected_status is not None:
            details["expected_status"] = expected_status
        super().__init__(message, details=details)


# ============================================================
# 测试资产中心专用异常
# ============================================================

class AssetNotFoundError(NotFoundError):
    """资产不存在"""
    code = "ASSET_NOT_FOUND"

    def __init__(self, message: str, *, asset_id: Optional[int] = None):
        details = {"asset_id": asset_id} if asset_id else {}
        super().__init__(message, details=details)


class AssetConflictError(ConflictError):
    """资产冲突(asset_code 重复 / ref_type+ref_id 已索引)"""
    code = "ASSET_CONFLICT"

    def __init__(
        self,
        message: str,
        *,
        asset_id: Optional[int] = None,
        asset_code: Optional[str] = None,
    ):
        details = {}
        if asset_id is not None:
            details["existing_id"] = asset_id
        if asset_code is not None:
            details["asset_code"] = asset_code
        super().__init__(message, details=details)


class AssetStateError(StateError):
    """资产状态机错误(如 draft 直接跳到 archived / archived 不允许删除等)

    状态机流转规则:
      draft      → active (publish)
      draft      → archived
      active     → deprecated
      active     → archived
      deprecated → active (re-publish)
      deprecated → archived
      archived   → draft (recover)
    """
    code = "ASSET_STATE_ERROR"

    def __init__(
        self,
        message: str,
        *,
        asset_id: Optional[int] = None,
        current_status: Optional[str] = None,
        target_status: Optional[str] = None,
    ):
        details = {}
        if asset_id is not None:
            details["asset_id"] = asset_id
        if current_status is not None:
            details["current_status"] = current_status
        if target_status is not None:
            details["target_status"] = target_status
        super().__init__(message, details=details)


class AssetValidationError(ValidationError):
    """资产业务校验失败(ref_type 与 asset_type 不匹配 / ref_id 不存在等)"""
    code = "ASSET_VALIDATION_ERROR"

    def __init__(
        self,
        message: str,
        *,
        asset_id: Optional[int] = None,
        field: Optional[str] = None,
    ):
        details = {}
        if asset_id is not None:
            details["asset_id"] = asset_id
        if field is not None:
            details["field"] = field
        super().__init__(message, details=details)


class AssetVersionNotFoundError(NotFoundError):
    """资产版本不存在"""
    code = "ASSET_VERSION_NOT_FOUND"

    def __init__(
        self,
        message: str,
        *,
        asset_id: Optional[int] = None,
        version: Optional[int] = None,
    ):
        details = {}
        if asset_id is not None:
            details["asset_id"] = asset_id
        if version is not None:
            details["version"] = version
        super().__init__(message, details=details)


class AssetRelationNotFoundError(NotFoundError):
    """资产关系不存在"""
    code = "ASSET_RELATION_NOT_FOUND"

    def __init__(self, message: str, *, relation_id: Optional[int] = None):
        details = {"relation_id": relation_id} if relation_id else {}
        super().__init__(message, details=details)


class AssetRelationConflictError(ConflictError):
    """资产关系冲突(source+type+target 重复 / 自环关系)"""
    code = "ASSET_RELATION_CONFLICT"

    def __init__(
        self,
        message: str,
        *,
        relation_id: Optional[int] = None,
        source_id: Optional[int] = None,
        target_id: Optional[int] = None,
        relation_type: Optional[str] = None,
    ):
        details = {}
        if relation_id is not None:
            details["existing_id"] = relation_id
        if source_id is not None:
            details["source_id"] = source_id
        if target_id is not None:
            details["target_id"] = target_id
        if relation_type is not None:
            details["relation_type"] = relation_type
        super().__init__(message, details=details)
