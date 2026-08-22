"""
API 测试数据生成路由

挂载路径: /api/api-test-data

接口分组:
  1. 数据生成   - POST /generate     POST /generate-one
  2. 健康检查   - GET  /health
  3. 模板 CRUD - GET  /templates/list   POST /templates   GET /templates/{id}
                  PUT  /templates/{id}   DELETE /templates/{id}
  4. 生成数据   - GET  /data/list    GET /data/{id}    DELETE /data/{id}

设计要点:
  1. 使用 Depends(require_auth) 获取当前用户
  2. 所有响应用 Response[T] 包装,保持与既有接口一致
  3. /list 必须在 /{id} 之前注册,避免参数解析冲突(项目硬约束)
  4. 异步路由用于 Agent 调用 (generate / health)
  5. 业务异常由统一处理器转 HTTP
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, status

from app.core.auth import require_auth
from app.models.user import User
from app.schemas.api_test_data import (
    GenerateRequest,
    GenerateResponse,
    GeneratedDataListResponse,
    GeneratedDataResponse,
    HealthResponse,
    TemplateCreate,
    TemplateResponse,
    TemplateUpdate,
)
from app.schemas.response import Response
from app.services.api_test_data_service import ApiTestDataService

router = APIRouter()

# 服务实例(无状态,可全局复用)
_service = ApiTestDataService()


# ============================================================
# 1. 数据生成 (Agent 调用)
# ============================================================

@router.post("/generate", response_model=Response[GenerateResponse], summary="生成测试数据(批量)")
async def generate_data(
    payload: GenerateRequest,
    user: User = Depends(require_auth),
):
    """调用 ApiDataGeneratorAgent 批量生成测试数据

    支持同时生成多种类型(normal/abnormal/boundary/dependent)
    缺省 fields_schema 时,从 DB 中 endpoint_id 对应的接口 Schema 加载
    """
    request_payload: Dict[str, Any] = {
        "action": "generate",
        "endpoint_id": payload.endpoint_id,
        "data_types": payload.data_types,
        "count": payload.count,
        "fields_schema": payload.fields_schema,
        "dependencies": payload.dependencies,
        "use_template": payload.use_template,
        "use_llm": payload.use_llm,
        "user_id": user.id,
    }
    result = await _service.generate_data(request_payload)
    return Response(data=GenerateResponse(**result))


@router.post("/generate-one", response_model=Response[GenerateResponse], summary="生成单条测试数据")
async def generate_one(
    payload: Dict[str, Any],
    user: User = Depends(require_auth),
):
    """生成单条数据

    body:
      endpoint_id: int
      data_type:   str (normal/abnormal/boundary/dependent)
      fields_schema: list (可选)
      dependencies:  list (可选, dependent 时必填)
    """
    request_payload = {
        "action": "generate_one",
        **payload,
        "user_id": user.id,
    }
    result = await _service.generate_data(request_payload)
    return Response(data=GenerateResponse(**result))


@router.post("/integrate/{endpoint_id}", response_model=Response, summary="一键流程: 接口→数据→用例建议")
async def integrate_with_case(
    endpoint_id: int,
    count: int = Query(default=3, ge=1, le=10, description="每类生成条数"),
    use_llm: bool = Query(default=True, description="允许 LLM 调用"),
    user: User = Depends(require_auth),
):
    """接入流程编排: 接口解析 → 依赖分析 → 数据生成 → 用例建议

    返回 endpoint + generated_data + suggested_cases
    suggested_cases 中每条可直接作为 ApiCase 的 steps/assertions 输入
    """
    result = await _service.generate_for_case(
        endpoint_id,
        count=count,
        use_llm=use_llm,
        user_id=user.id,
    )
    return Response(data=result)


# ============================================================
# 2. 健康检查
# ============================================================

@router.get("/health", response_model=Response[HealthResponse], summary="Agent 健康检查")
async def health_check(
    user: User = Depends(require_auth),
):
    """检查 ApiDataGeneratorAgent 的可用状态"""
    result = await _service.health_check()
    return Response(data=HealthResponse(**result))


# ============================================================
# 3. 模板 CRUD
# ============================================================

@router.get("/templates/list", response_model=Response, summary="模板列表(分页)")
async def list_templates(
    endpoint_id: Optional[int] = Query(default=None, description="按接口过滤"),
    data_type: Optional[str] = Query(default=None, description="按数据类型过滤"),
    status_filter: Optional[str] = Query(default=None, alias="status", description="按状态过滤"),
    keyword: Optional[str] = Query(default=None, description="关键词搜索"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    user: User = Depends(require_auth),
):
    """分页查询模板列表

    注意:GET /templates/list 必须在 GET /templates/{id} 之前注册
    """
    result = _service.list_templates(
        endpoint_id=endpoint_id,
        data_type=data_type,
        status=status_filter,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return Response(data=result)


@router.post("/templates", response_model=Response[TemplateResponse], summary="创建模板")
async def create_template(
    payload: TemplateCreate,
    user: User = Depends(require_auth),
):
    """创建测试数据模板"""
    result = _service.create_template(payload.dict(), user_id=user.id)
    return Response(data=TemplateResponse(**result))


@router.get("/templates/{template_id}", response_model=Response[TemplateResponse], summary="模板详情")
async def get_template(
    template_id: int,
    user: User = Depends(require_auth),
):
    """查模板详情"""
    result = _service.get_template(template_id)
    return Response(data=TemplateResponse(**result))


@router.put("/templates/{template_id}", response_model=Response[TemplateResponse], summary="更新模板")
async def update_template(
    template_id: int,
    payload: TemplateUpdate,
    user: User = Depends(require_auth),
):
    """更新模板字段

    可更新字段:name/description/fields_schema/generation_rules/dependencies_json/status/tags
    """
    update_data = payload.dict(exclude_unset=True)
    result = _service.update_template(template_id, update_data)
    return Response(data=TemplateResponse(**result))


@router.delete("/templates/{template_id}", response_model=Response, summary="删除模板(软删)")
async def delete_template(
    template_id: int,
    user: User = Depends(require_auth),
):
    """软删除模板"""
    result = _service.delete_template(template_id)
    return Response(data=result)


# ============================================================
# 4. 已生成数据查询
# ============================================================

@router.get("/data/list", response_model=Response, summary="已生成数据列表(分页)")
async def list_generated_data(
    endpoint_id: Optional[int] = Query(default=None, description="按接口过滤"),
    data_type: Optional[str] = Query(default=None, description="按数据类型过滤"),
    case_id: Optional[int] = Query(default=None, description="按用例过滤"),
    template_id: Optional[int] = Query(default=None, description="按模板过滤"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    user: User = Depends(require_auth),
):
    """分页查询已生成数据

    注意:GET /data/list 必须在 GET /data/{id} 之前注册
    """
    result = _service.list_generated_data(
        endpoint_id=endpoint_id,
        data_type=data_type,
        case_id=case_id,
        template_id=template_id,
        page=page,
        page_size=page_size,
    )
    return Response(data=result)


@router.get("/data/{data_id}", response_model=Response[GeneratedDataResponse], summary="生成数据详情")
async def get_generated_data(
    data_id: int,
    user: User = Depends(require_auth),
):
    """查单条生成数据"""
    result = _service.get_generated_data(data_id)
    return Response(data=GeneratedDataResponse(**result))


@router.delete("/data/{data_id}", response_model=Response, summary="删除生成数据(软删)")
async def delete_generated_data(
    data_id: int,
    user: User = Depends(require_auth),
):
    """软删除生成数据"""
    result = _service.delete_generated_data(data_id)
    return Response(data=result)
