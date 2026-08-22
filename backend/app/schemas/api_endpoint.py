"""
API 接口管理 Pydantic Schemas

定义接口管理的请求/响应数据结构,与 SQLAlchemy Model 解耦。
所有 JSON 字段(如 headers_json)在 schema 层用 dict/list 表达,序列化由 repository 处理。
"""
from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


# ============================================================
# 基础字段类型
# ============================================================

class HeaderItem(BaseModel):
    """请求头项"""
    key: str = Field(..., description="Header 名,如 Content-Type")
    value: str = Field(default="", description="Header 值")
    desc: str = Field(default="", description="说明")


class ParamItem(BaseModel):
    """参数项(Query/Path)"""
    name: str = Field(..., description="参数名")
    location: str = Field(default="query", description="参数位置: query/path/header/cookie")
    type: str = Field(default="string", description="参数类型: string/integer/boolean/number/array/object")
    required: bool = Field(default=False, description="是否必填")
    default: Optional[str] = Field(default=None, description="默认值")
    desc: str = Field(default="", description="说明")
    example: Optional[str] = Field(default=None, description="示例值")


class BodySpec(BaseModel):
    """请求体规范"""
    content_type: str = Field(default="application/json", description="Content-Type: application/json/form-data/x-www-form-urlencoded/raw")
    raw: Optional[str] = Field(default=None, description="原始文本(当 content_type=raw 时)")
    json_schema: Optional[Dict[str, Any]] = Field(default=None, description="JSON Schema 规范")
    form_fields: Optional[List[Dict[str, Any]]] = Field(default=None, description="表单字段列表")
    example: Optional[Any] = Field(default=None, description="示例")


class ResponseSpec(BaseModel):
    """响应规范"""
    status_code: int = Field(default=200, description="HTTP 状态码")
    headers: Optional[List[HeaderItem]] = Field(default=None, description="响应头")
    body_schema: Optional[Dict[str, Any]] = Field(default=None, description="响应体 JSON Schema")
    example: Optional[Any] = Field(default=None, description="响应示例")
    desc: str = Field(default="", description="说明")


class AuthSpec(BaseModel):
    """认证规范"""
    type: str = Field(default="none", description="认证类型: none/basic/bearer/api_key/oauth2/custom")
    details: Optional[Dict[str, Any]] = Field(default=None, description="认证详情(敏感字段用占位符)")


# ============================================================
# 创建/更新请求
# ============================================================

class EndpointCreate(BaseModel):
    """创建接口请求"""
    name: str = Field(..., min_length=1, max_length=200, description="接口名称")
    method: str = Field(..., description="HTTP 方法: GET/POST/PUT/DELETE/PATCH/HEAD/OPTIONS")
    path: str = Field(..., min_length=1, max_length=500, description="接口路径")
    summary: Optional[str] = Field(default=None, max_length=500, description="摘要")
    description: Optional[str] = Field(default=None, description="详细说明")
    tags: Optional[List[str]] = Field(default=None, description="标签列表")
    module: Optional[str] = Field(default=None, max_length=100, description="所属模块")
    status: str = Field(default="draft", description="状态: draft/active/deprecated/archived")
    source: str = Field(default="manual", description="来源: manual/swagger/postman/har/import/ai")
    headers: Optional[List[HeaderItem]] = Field(default=None, description="请求头")
    params: Optional[List[ParamItem]] = Field(default=None, description="Query/Path 参数")
    body: Optional[BodySpec] = Field(default=None, description="请求体")
    response: Optional[ResponseSpec] = Field(default=None, description="响应")
    auth: Optional[AuthSpec] = Field(default=None, description="认证")

    @field_validator("method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        v = v.upper()
        allowed = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
        if v not in allowed:
            raise ValueError(f"method 必须是 {allowed} 之一")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        allowed = {"draft", "active", "deprecated", "archived"}
        if v not in allowed:
            raise ValueError(f"status 必须是 {allowed} 之一")
        return v


class EndpointUpdate(BaseModel):
    """更新接口请求(所有字段可选)"""
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    method: Optional[str] = Field(default=None)
    path: Optional[str] = Field(default=None, min_length=1, max_length=500)
    summary: Optional[str] = Field(default=None, max_length=500)
    description: Optional[str] = Field(default=None)
    tags: Optional[List[str]] = Field(default=None)
    module: Optional[str] = Field(default=None, max_length=100)
    status: Optional[str] = Field(default=None)
    headers: Optional[List[HeaderItem]] = Field(default=None)
    params: Optional[List[ParamItem]] = Field(default=None)
    body: Optional[BodySpec] = Field(default=None)
    response: Optional[ResponseSpec] = Field(default=None)
    auth: Optional[AuthSpec] = Field(default=None)

    @field_validator("method")
    @classmethod
    def validate_method(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.upper()
        allowed = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
        if v not in allowed:
            raise ValueError(f"method 必须是 {allowed} 之一")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        allowed = {"draft", "active", "deprecated", "archived"}
        if v not in allowed:
            raise ValueError(f"status 必须是 {allowed} 之一")
        return v


class EndpointQueryParams(BaseModel):
    """接口列表查询参数"""
    keyword: Optional[str] = Field(default=None, description="关键词,匹配 name/path/summary")
    method: Optional[str] = Field(default=None, description="HTTP 方法过滤")
    module: Optional[str] = Field(default=None, description="模块过滤")
    status: Optional[str] = Field(default=None, description="状态过滤")
    tags: Optional[List[str]] = Field(default=None, description="标签过滤(任一匹配)")
    page: int = Field(default=1, ge=1, description="页码,从 1 开始")
    page_size: int = Field(default=20, ge=1, le=100, description="每页条数")


class PublishRequest(BaseModel):
    """发布接口(生成版本快照)"""
    change_log: str = Field(default="", max_length=500, description="变更说明")


# ============================================================
# 响应
# ============================================================

class EndpointResponse(BaseModel):
    """接口详情响应"""
    id: int
    name: str
    method: str
    path: str
    summary: Optional[str] = None
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    module: Optional[str] = None
    status: str
    source: str
    headers: List[HeaderItem] = Field(default_factory=list)
    params: List[ParamItem] = Field(default_factory=list)
    body: Optional[BodySpec] = None
    response: Optional[ResponseSpec] = None
    auth: AuthSpec = Field(default_factory=lambda: AuthSpec(type="none"))
    version: int
    user_id: Optional[int] = None
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EndpointListItem(BaseModel):
    """接口列表项(精简字段)"""
    id: int
    name: str
    method: str
    path: str
    summary: Optional[str] = None
    module: Optional[str] = None
    status: str
    source: str
    version: int
    tags: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class EndpointListResponse(BaseModel):
    """接口列表响应"""
    total: int
    page: int
    page_size: int
    items: List[EndpointListItem]


class EndpointVersionItem(BaseModel):
    """接口版本项"""
    id: int
    endpoint_id: int
    version: int
    change_log: Optional[str] = None
    is_current: bool
    created_by: Optional[int] = None
    created_at: datetime


class EndpointVersionDetail(BaseModel):
    """接口版本详情(含快照)"""
    id: int
    endpoint_id: int
    version: int
    snapshot: Dict[str, Any]
    change_log: Optional[str] = None
    is_current: bool
    created_by: Optional[int] = None
    created_at: datetime


class EndpointStatsResponse(BaseModel):
    """接口统计响应"""
    total: int = Field(description="接口总数")
    by_status: Dict[str, int] = Field(default_factory=dict, description="按状态统计")
    by_method: Dict[str, int] = Field(default_factory=dict, description="按方法统计")
    by_module: Dict[str, int] = Field(default_factory=dict, description="按模块统计")


class BatchImportResult(BaseModel):
    """批量导入结果"""
    total: int = Field(description="解析到的接口数")
    imported: int = Field(default=0, description="成功导入数")
    skipped: int = Field(default=0, description="跳过数(method+path 重复)")
    failed: int = Field(default=0, description="失败数")
    errors: List[str] = Field(default_factory=list, description="错误详情")
    imported_ids: List[int] = Field(default_factory=list, description="导入的接口 ID 列表")
