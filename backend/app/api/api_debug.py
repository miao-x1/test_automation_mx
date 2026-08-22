"""
AI 接口调试路由

挂载路径: /api/api-debug

接口分组:
  1. 执行接口   - POST /execute
  2. AI 分析    - POST /analyze/{record_id}   POST /analyze/inline
  3. 健康检查   - GET  /health
  4. 记录查询   - GET  /records/list   GET /records/{id}   DELETE /records/{id}
  5. 错误模式   - GET  /patterns
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.core.auth import require_auth
from app.models.user import User
from app.schemas.api_debug import (
    AnalyzeRequest,
    AnalysisResult,
    ExecuteRequest,
    ExecuteResponse,
    HealthResponse,
)
from app.schemas.response import Response
from app.services.api_debug_service import ApiDebugService

router = APIRouter()

_service = ApiDebugService()


# ============================================================
# 1. 执行接口
# ============================================================

@router.post("/execute", response_model=Response, summary="执行 HTTP 请求 (Postman 风格)")
async def execute_request(
    payload: ExecuteRequest,
    user: User = Depends(require_auth),
):
    """执行一次 HTTP 请求

    - 自动保存到 api_execution_record
    - auto_analyze=True 时,失败自动调用 AI 分析
    """
    result = await _service.execute_request(
        method=payload.method,
        url=payload.url,
        headers=payload.headers,
        params=payload.params,
        body=payload.body,
        auth=payload.auth,
        timeout=payload.timeout,
        api_id=payload.api_id,
        case_id=payload.case_id,
        env=payload.env,
        auto_analyze=payload.auto_analyze,
        user_id=user.id,
    )
    return Response(data=result)


# ============================================================
# 2. AI 分析
# ============================================================

@router.post("/analyze/{record_id}", response_model=Response, summary="AI 分析执行记录")
async def analyze_record(
    record_id: int,
    force: bool = Query(default=False, description="强制分析(即使成功)"),
    user: User = Depends(require_auth),
):
    """对执行记录进行 AI 分析

    输出: 问题原因 / 解决方案 / 修复建议 / 置信度
    """
    result = await _service.analyze_record(record_id, force=force)
    return Response(data=result)


@router.post("/analyze/inline", response_model=Response, summary="直接分析(不落库)")
async def analyze_inline(
    payload: AnalyzeRequest,
    user: User = Depends(require_auth),
):
    """直接传入请求/响应做分析,不查库"""
    if not payload.request and not payload.record_id:
        from app.core.exceptions import ValidationError
        raise ValidationError("必须提供 record_id 或 request")
    if payload.request:
        result = await _service.analyze_inline(
            request=payload.request,
            response=payload.response or {},
            error=payload.error,
            status=payload.status or "failed",
        )
    else:
        result = await _service.analyze_record(payload.record_id, force=payload.force)
    return Response(data=result)


# ============================================================
# 3. 健康检查
# ============================================================

@router.get("/health", response_model=Response[HealthResponse], summary="Agent 健康检查")
async def health_check(
    user: User = Depends(require_auth),
):
    result = await _service.health_check()
    return Response(data=HealthResponse(**result))


# ============================================================
# 4. 记录查询
# ============================================================

@router.get("/records/list", response_model=Response, summary="执行记录列表(分页)")
async def list_records(
    api_id: Optional[int] = Query(default=None),
    case_id: Optional[int] = Query(default=None),
    status: Optional[str] = Query(default=None),
    status_code: Optional[int] = Query(default=None),
    method: Optional[str] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(require_auth),
):
    """分页查询执行记录"""
    result = _service.list_records(
        api_id=api_id,
        case_id=case_id,
        status=status,
        status_code=status_code,
        method=method,
        keyword=keyword,
        user_id=user.id,
        page=page,
        page_size=page_size,
    )
    return Response(data=result)


@router.get("/records/{record_id}", response_model=Response, summary="执行记录详情")
async def get_record(
    record_id: int,
    user: User = Depends(require_auth),
):
    result = _service.get_record(record_id)
    return Response(data=result)


@router.delete("/records/{record_id}", response_model=Response, summary="删除执行记录(软删)")
async def delete_record(
    record_id: int,
    user: User = Depends(require_auth),
):
    result = _service.delete_record(record_id)
    return Response(data=result)


# ============================================================
# 5. 错误模式
# ============================================================

@router.get("/patterns", response_model=Response, summary="列出所有错误模式")
async def list_patterns(
    user: User = Depends(require_auth),
):
    """列出规则引擎支持的所有错误模式"""
    from app.agents.flows.api_debug_agent import ApiDebugAgent
    agent = ApiDebugAgent()
    return Response(data=agent._do_list_patterns())
