"""
性能测试 API 路由

端点:
  任务管理:
    POST   /                          创建任务
    GET    /list                       任务列表
    GET    /{task_id}                  任务详情
    DELETE /{task_id}                  删除任务

  Agent 编排:
    POST   /{task_id}/plan             生成测试方案 (PerformancePlanAgent)
    POST   /{task_id}/script           生成脚本 (PerformanceScriptAgent)
    POST   /{task_id}/analyze          分析结果 (PerformanceAnalysisAgent)

  测试执行:
    POST   /{task_id}/execute          启动执行 (Locust 引擎)
    POST   /{task_id}/execute/stop     停止执行
    GET    /{task_id}/execute/status   执行状态
    GET    /{task_id}/execute/stream   实时指标 SSE 流

  结果和指标:
    GET    /{task_id}/results          执行结果列表
    GET    /{result_id}/metrics         实时指标
    POST   /{task_id}/results           手动保存结果
    POST   /{result_id}/metrics         手动保存指标
"""
import asyncio
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.auth import require_auth
from app.models.user import User
from app.schemas.response import Response
from app.services.performance_service import PerformanceService

router = APIRouter()
_service = PerformanceService()


# ================================================================
# Pydantic Schemas
# ================================================================

class TaskCreate(BaseModel):
    name: str = Field(..., description="任务名称")
    target_url: str = Field(..., description="目标接口 URL")
    method: str = Field(default="GET", description="HTTP 方法")
    test_type: str = Field(default="api", description="测试类型: api/web")
    headers: Optional[Dict[str, Any]] = Field(default=None, description="请求头")
    body: Optional[Dict[str, Any]] = Field(default=None, description="请求体")
    business_volume: int = Field(default=10000, description="预期日业务量")


class ScriptGenerate(BaseModel):
    script_type: str = Field(default="locust", description="脚本类型: locust/jmeter")


class ResultSave(BaseModel):
    total_requests: int = 0
    total_errors: int = 0
    error_rate: float = 0.0
    avg_tps: float = 0.0
    peak_tps: float = 0.0
    avg_rt: float = 0.0
    p50_rt: Optional[float] = None
    p90_rt: Optional[float] = None
    p95_rt: Optional[float] = None
    p99_rt: Optional[float] = None
    concurrency: int = 0
    duration_seconds: int = 0
    status: str = "completed"


class MetricSave(BaseModel):
    timestamp: float = 0.0
    elapsed: float = 0.0
    tps: float = 0.0
    avg_rt: float = 0.0
    concurrent_users: int = 0
    error_count: int = 0
    cpu_percent: Optional[float] = None
    memory_mb: Optional[float] = None


class AnalyzeRequest(BaseModel):
    logs: Optional[List[Any]] = Field(default=None, description="应用日志列表, 每条为 dict 或 str")


# ================================================================
# 任务管理
# ================================================================

@router.post("", summary="创建性能测试任务")
async def create_task(
    payload: TaskCreate,
    user: User = Depends(require_auth),
):
    result = _service.create_task(
        name=payload.name,
        target_url=payload.target_url,
        method=payload.method,
        test_type=payload.test_type,
        headers=payload.headers,
        body=payload.body,
        business_volume=payload.business_volume,
        user_id=user.id,
        created_by=user.id,
    )
    return Response(data=result)


@router.get("/list", summary="任务列表")
async def list_tasks(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    test_type: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    user: User = Depends(require_auth),
):
    result = _service.list_tasks(
        page=page, page_size=page_size,
        test_type=test_type, status=status,
        user_id=user.id,
    )
    return Response(data=result)


@router.get("/{task_id}", summary="任务详情")
async def get_task(task_id: int, user: User = Depends(require_auth)):
    result = _service.get_task(task_id)
    if not result:
        return Response(code=404, message="任务不存在")
    return Response(data=result)


@router.delete("/{task_id}", summary="删除任务")
async def delete_task(task_id: int, user: User = Depends(require_auth)):
    ok = _service.delete_task(task_id)
    if not ok:
        return Response(code=404, message="任务不存在")
    return Response(message="删除成功")


# ================================================================
# Agent 编排
# ================================================================

@router.post("/{task_id}/plan", summary="生成性能测试方案")
async def run_plan(task_id: int, user: User = Depends(require_auth)):
    result = await _service.run_plan(task_id)
    return Response(data=result)


@router.post("/{task_id}/script", summary="生成测试脚本")
async def run_script(
    task_id: int,
    payload: ScriptGenerate,
    user: User = Depends(require_auth),
):
    result = await _service.run_script(task_id, script_type=payload.script_type)
    return Response(data=result)


@router.post("/{task_id}/analyze", summary="分析性能结果")
async def run_analysis(
    task_id: int,
    payload: AnalyzeRequest = None,
    user: User = Depends(require_auth),
):
    logs = payload.logs if payload else None
    result = await _service.run_analysis(task_id, logs=logs)
    return Response(data=result)


# ================================================================
# 性能诊断 (PerformanceDiagnosticAgent)
# ================================================================

class DiagnoseRequest(BaseModel):
    jstack_dump: str = Field(default="", description="jstack 命令输出文本")
    logs: Optional[List[Any]] = Field(default=None, description="应用日志列表")


@router.post("/{task_id}/diagnose", summary="性能诊断 (jstack/日志/监控分析)")
async def run_diagnostic(
    task_id: int,
    payload: DiagnoseRequest = None,
    user: User = Depends(require_auth),
):
    """执行性能诊断

    输入 jstack dump + 应用日志, 结合监控数据进行深度问题定位:
      - 线程阻塞 / 死锁 / CPU 热点 (jstack 分析)
      - 错误聚类 / 慢操作 / 错误突增 (日志分析)
      - 多源关联分析 (jstack + 日志 + 监控)
      - LLM 根因定位和修复建议
    """
    jstack_dump = payload.jstack_dump if payload else ""
    logs = payload.logs if payload else None
    result = await _service.run_diagnostic(task_id, jstack_dump=jstack_dump, logs=logs)
    if result.get("status") == "error":
        return Response(code=400, message=result.get("error", "诊断失败"))
    return Response(data=result)


# ================================================================
# 测试执行 (PerformanceExecutor)
# ================================================================

@router.post("/{task_id}/execute", summary="启动性能测试执行")
async def run_execute(task_id: int, user: User = Depends(require_auth)):
    """启动 Locust 性能测试执行, 实时采集 TPS/RT/CPU/Memory 指标"""
    result = await _service.run_execute(task_id)
    if result.get("status") == "error":
        return Response(code=400, message=result.get("error", "启动失败"))
    return Response(data=result)


@router.post("/{task_id}/execute/stop", summary="停止性能测试执行")
async def stop_execute(task_id: int, user: User = Depends(require_auth)):
    """停止正在运行的性能测试"""
    result = await _service.stop_execute(task_id)
    return Response(data=result)


@router.get("/{task_id}/execute/status", summary="获取执行状态")
async def get_execute_status(task_id: int, user: User = Depends(require_auth)):
    """获取性能测试执行状态"""
    result = _service.get_execution_status(task_id)
    return Response(data=result)


@router.get("/{task_id}/execute/stream", summary="实时指标 SSE 流")
async def stream_execute_metrics(task_id: int, user: User = Depends(require_auth)):
    """SSE 流式推送实时性能指标

    事件格式 (data: JSON):
      - {"type": "metric", "tps": ..., "avg_rt": ..., "cpu_percent": ..., ...}
      - {"type": "final", "data": {...最终统计...}}
      - {"type": "end", "status": "completed/failed/stopped"}
    """
    async def event_generator():
        async for event in _service.stream_metrics(task_id):
            yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ================================================================
# 结果和指标
# ================================================================

@router.get("/{task_id}/results", summary="执行结果列表")
async def get_results(task_id: int, user: User = Depends(require_auth)):
    results = _service.get_results(task_id)
    return Response(data=results)


@router.get("/{result_id}/metrics", summary="实时指标")
async def get_metrics(result_id: int, user: User = Depends(require_auth)):
    metrics = _service.get_metrics(result_id)
    return Response(data=metrics)


@router.post("/{task_id}/results", summary="保存执行结果")
async def save_result(
    task_id: int,
    payload: ResultSave,
    user: User = Depends(require_auth),
):
    result = _service.save_result(task_id, payload.model_dump())
    return Response(data=result)


@router.post("/{result_id}/metrics", summary="保存实时指标")
async def save_metric(
    result_id: int,
    payload: MetricSave,
    user: User = Depends(require_auth),
):
    result = _service.save_metric(result_id, payload.model_dump())
    return Response(data=result)
