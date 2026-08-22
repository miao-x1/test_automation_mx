"""
API 测试数据生成 — Pydantic Schema

定义:
  - GenerateRequest:       生成请求
  - GenerateResponse:      生成响应
  - TemplateCreate:        创建模板
  - TemplateUpdate:        更新模板
  - TemplateResponse:      模板详情
  - GeneratedDataResponse: 已生成数据
"""
from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field


# ============================================================
# 生成请求/响应
# ============================================================

class GenerateRequest(BaseModel):
    """数据生成请求"""
    endpoint_id: int = Field(..., description="接口 ID")
    data_types: List[str] = Field(
        default=["normal", "abnormal", "boundary"],
        description="要生成的类型列表"
    )
    count: int = Field(default=3, ge=1, le=20, description="每类生成条数")
    fields_schema: Optional[List[Dict[str, Any]]] = Field(
        None, description="字段定义 (缺省时从 DB 加载)"
    )
    dependencies: Optional[List[Dict[str, Any]]] = Field(
        None, description="依赖关系 (dependent 类型用)"
    )
    use_template: bool = Field(default=True, description="优先使用模板")
    use_llm: bool = Field(default=True, description="允许 LLM 调用")


class GenerateResponse(BaseModel):
    """数据生成响应"""
    status: str
    endpoint_id: int
    data: Dict[str, List[Dict[str, Any]]] = Field(
        default_factory=dict,
        description="按类型分组的数据: {normal: [...], abnormal: [...]}"
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ============================================================
# 模板 CRUD
# ============================================================

class TemplateCreate(BaseModel):
    """创建模板"""
    endpoint_id: int
    name: str = Field(..., max_length=200)
    description: Optional[str] = None
    data_type: str = Field(default="normal")
    fields_schema: Optional[List[Dict[str, Any]]] = None
    generation_rules: Optional[List[Dict[str, Any]]] = None
    dependencies_json: Optional[List[Dict[str, Any]]] = None
    tags: Optional[str] = None


class TemplateUpdate(BaseModel):
    """更新模板"""
    name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    fields_schema: Optional[List[Dict[str, Any]]] = None
    generation_rules: Optional[List[Dict[str, Any]]] = None
    dependencies_json: Optional[List[Dict[str, Any]]] = None
    status: Optional[str] = None
    tags: Optional[str] = None


class TemplateResponse(BaseModel):
    """模板详情"""
    id: int
    endpoint_id: int
    name: str
    description: Optional[str]
    data_type: str
    fields_schema: Optional[Any] = None
    generation_rules: Optional[Any] = None
    dependencies_json: Optional[Any] = None
    status: str
    tags: Optional[str]
    usage_count: int
    last_used_at: Optional[str]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


# ============================================================
# 已生成数据
# ============================================================

class GeneratedDataResponse(BaseModel):
    """已生成数据响应"""
    id: int
    endpoint_id: int
    template_id: Optional[int]
    case_id: Optional[int]
    data_type: str
    generated_data: Any
    source: str
    elapsed_ms: int
    is_valid: bool
    validation_errors: Optional[str]
    created_at: Optional[str] = None


class GeneratedDataListResponse(BaseModel):
    """数据列表响应"""
    total: int
    items: List[GeneratedDataResponse]


# ============================================================
# 健康检查
# ============================================================

class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    agent: str
    faker_available: bool
    llm_available: bool
    supported_types: List[str]
    supported_sources: List[str]
