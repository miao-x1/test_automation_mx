"""
测试编排系统 — 管理 API

挂载路径: /api/test-orchestration

接口分组:
  1. Plan CRUD
     - POST   /plans                       创建测试计划
     - GET    /plans/list                   计划列表(分页)
     - GET    /plans/{plan_id}              计划详情
     - PUT    /plans/{plan_id}              更新计划
     - DELETE /plans/{plan_id}              删除计划
     - GET    /plans/{plan_id}/overview     计划概览(Suite + 最近执行 + 统计)

  2. PlanSuite 关联管理
     - GET    /plans/{plan_id}/suites       列出 Plan 中的 Suite
     - POST   /plans/{plan_id}/suites       添加 Suite 到 Plan
     - DELETE /plans/{plan_id}/suites/{suite_id}  从 Plan 移除 Suite
     - PUT    /plans/{plan_id}/suites/{suite_id}/toggle  启用/禁用 Suite
     - PUT    /plans/{plan_id}/suites/reorder  批量重排序

  3. 执行管理
     - POST   /plans/{plan_id}/execute       执行计划(支持同步/后台)
     - GET    /executions/list               执行历史列表
     - GET    /executions/{execution_id}     执行详情
     - POST   /executions/{execution_id}/cancel  取消执行
     - GET    /executions/stats              执行统计

  4. 报告
     - GET    /reports/{execution_id}        获取执行报告
     - GET    /reports/list                   报告列表

  5. 仪表盘
     - GET    /dashboard                     编排总览

设计要点:
  1. /list /stats /dashboard 必须在 /{id} 之前注册(避免参数解析冲突)
  2. 业务异常统一转为 HTTP 400/404
  3. execute_plan 为 async,其他方法同步
  4. 响应统一使用 Response[T] 包装
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.core.auth import require_auth
from app.models.user import User
from app.schemas.response import Response
from app.services.test_orchestration.orchestrator import (
    TestOrchestrator,
    get_test_orchestrator,
)

router = APIRouter()

# 全局服务实例(无状态,可复用)
_service: TestOrchestrator = get_test_orchestrator()


# ============================================================
# 请求 Schema
# ============================================================

class PlanCreateRequest(BaseModel):
    """创建测试计划"""
    name: str = Field(..., min_length=1, max_length=200, description="计划名称")
    description: Optional[str] = Field(default=None, description="计划描述")
    strategy: str = Field(default="serial", description="执行策略: serial/parallel")
    fail_policy: str = Field(default="continue", description="失败策略: stop/continue")
    env: str = Field(default="test", description="执行环境")
    base_url: Optional[str] = Field(default=None, description="基础 URL")
    headers_json: Optional[str] = Field(default=None, description="全局请求头(JSON)")
    variables_json: Optional[str] = Field(default=None, description="全局变量(JSON)")
    max_concurrency: int = Field(default=4, ge=1, le=20, description="最大并发数(parallel 模式)")
    retry_count: int = Field(default=0, ge=0, le=5, description="失败重试次数")
    retry_delay: int = Field(default=5, ge=0, le=300, description="重试间隔(秒)")
    timeout_seconds: int = Field(default=3600, ge=10, le=86400, description="计划超时(秒)")
    schedule_cron: Optional[str] = Field(default=None, description="定时调度表达式")
    schedule_enabled: bool = Field(default=False, description="是否启用定时调度")
    tags: Optional[str] = Field(default=None, description="标签(逗号分隔)")


class PlanUpdateRequest(BaseModel):
    """更新测试计划(部分更新)"""
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    strategy: Optional[str] = None
    fail_policy: Optional[str] = None
    env: Optional[str] = None
    base_url: Optional[str] = None
    headers_json: Optional[str] = None
    variables_json: Optional[str] = None
    max_concurrency: Optional[int] = Field(default=None, ge=1, le=20)
    retry_count: Optional[int] = Field(default=None, ge=0, le=5)
    retry_delay: Optional[int] = Field(default=None, ge=0, le=300)
    timeout_seconds: Optional[int] = Field(default=None, ge=10, le=86400)
    schedule_cron: Optional[str] = None
    schedule_enabled: Optional[bool] = None
    status: Optional[str] = None
    tags: Optional[str] = None


class SuiteAddRequest(BaseModel):
    """添加 Suite 到 Plan"""
    suite_id: int = Field(..., description="TestSuite ID")
    execution_order: Optional[int] = Field(default=None, description="执行顺序(为空追加)")
    role: str = Field(default="main", description="角色: main/setup/teardown")
    env_override: Optional[str] = None
    base_url_override: Optional[str] = None
    variables_override: Optional[str] = None
    enabled: bool = Field(default=True, description="是否启用")


class SuiteToggleRequest(BaseModel):
    """启用/禁用 Suite"""
    enabled: bool


class SuiteReorderRequest(BaseModel):
    """批量重排序"""
    suite_orders: List[Dict[str, int]] = Field(
        ..., description="[{'suite_id': 5, 'execution_order': 0}, ...]"
    )


class ExecutePlanRequest(BaseModel):
    """执行计划"""
    execution_id: Optional[str] = Field(default=None, description="自定义执行 ID")
    trigger_source: str = Field(default="manual", description="触发来源")
    background: bool = Field(default=False, description="True=后台执行,False=同步等待")


# ============================================================
# 1. Plan CRUD
# ============================================================

@router.post(
    "/plans",
    response_model=Response[Dict[str, Any]],
    summary="创建测试计划",
)
async def create_plan(
    payload: PlanCreateRequest,
    user: User = Depends(require_auth),
):
    """创建一个新的测试计划"""
    try:
        result = _service.create_plan(
            payload.model_dump(),
            user_id=user.id,
        )
        return Response(data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/plans/list",
    response_model=Response[Dict[str, Any]],
    summary="测试计划列表(分页)",
)
async def list_plans(
    keyword: Optional[str] = Query(default=None, description="关键词"),
    status_filter: Optional[str] = Query(default=None, alias="status", description="状态"),
    strategy: Optional[str] = Query(default=None, description="执行策略"),
    tags: Optional[str] = Query(default=None, description="标签(逗号分隔)"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    user: User = Depends(require_auth),
):
    """分页查询测试计划列表

    注意: GET /plans/list 必须在 GET /plans/{plan_id} 之前注册
    """
    result = _service.list_plans(
        keyword=keyword,
        status=status_filter,
        strategy=strategy,
        tags=tags,
        user_id=user.id,
        page=page,
        page_size=page_size,
    )
    return Response(data=result)


@router.get(
    "/plans/{plan_id}",
    response_model=Response[Dict[str, Any]],
    summary="测试计划详情",
)
async def get_plan(
    plan_id: int,
    include_suites: bool = Query(default=True, description="是否包含 Suite 列表"),
    user: User = Depends(require_auth),
):
    """获取测试计划详情"""
    result = _service.get_plan(plan_id, include_suites=include_suites, user_id=user.id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"TestPlan not found: {plan_id}")
    return Response(data=result)


@router.put(
    "/plans/{plan_id}",
    response_model=Response[Dict[str, Any]],
    summary="更新测试计划",
)
async def update_plan(
    plan_id: int,
    payload: PlanUpdateRequest,
    user: User = Depends(require_auth),
):
    """更新测试计划(部分更新)"""
    try:
        data = payload.model_dump(exclude_unset=True)
        result = _service.update_plan(plan_id, data, user_id=user.id)
        return Response(data=result)
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.delete(
    "/plans/{plan_id}",
    response_model=Response[Dict[str, Any]],
    summary="删除测试计划",
)
async def delete_plan(
    plan_id: int,
    hard: bool = Query(default=False, description="True=物理删除,False=软删除"),
    user: User = Depends(require_auth),
):
    """删除测试计划(默认软删除)"""
    ok = _service.delete_plan(plan_id, hard=hard, user_id=user.id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"TestPlan not found: {plan_id}")
    return Response(data={"deleted": True, "hard": hard, "plan_id": plan_id})


@router.get(
    "/plans/{plan_id}/overview",
    response_model=Response[Dict[str, Any]],
    summary="测试计划概览",
)
async def get_plan_overview(
    plan_id: int,
    user: User = Depends(require_auth),
):
    """获取计划概览:基本信息 + Suite 列表 + 最近执行 + 统计"""
    try:
        result = _service.get_plan_overview(plan_id, user_id=user.id)
        return Response(data=result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ============================================================
# 2. PlanSuite 关联管理
# ============================================================

@router.get(
    "/plans/{plan_id}/suites",
    response_model=Response[List[Dict[str, Any]]],
    summary="列出 Plan 中的 Suite",
)
async def list_plan_suites(
    plan_id: int,
    only_enabled: bool = Query(default=False, description="只返回启用的 Suite"),
    user: User = Depends(require_auth),
):
    """列出 Plan 中的所有 Suite(带 Suite 详情)"""
    result = _service.list_suites(plan_id, only_enabled=only_enabled, user_id=user.id)
    return Response(data=result)


@router.post(
    "/plans/{plan_id}/suites",
    response_model=Response[Dict[str, Any]],
    summary="添加 Suite 到 Plan",
)
async def add_suite_to_plan(
    plan_id: int,
    payload: SuiteAddRequest,
    user: User = Depends(require_auth),
):
    """将 TestSuite 添加到 TestPlan"""
    try:
        result = _service.add_suite(
            plan_id=plan_id,
            suite_id=payload.suite_id,
            execution_order=payload.execution_order,
            role=payload.role,
            env_override=payload.env_override,
            base_url_override=payload.base_url_override,
            variables_override=payload.variables_override,
            enabled=payload.enabled,
            user_id=user.id,
        )
        return Response(data=result)
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.delete(
    "/plans/{plan_id}/suites/{suite_id}",
    response_model=Response[Dict[str, Any]],
    summary="从 Plan 移除 Suite",
)
async def remove_suite_from_plan(
    plan_id: int,
    suite_id: int,
    user: User = Depends(require_auth),
):
    """从 TestPlan 移除 TestSuite"""
    ok = _service.remove_suite(plan_id, suite_id, user_id=user.id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Suite {suite_id} not in plan {plan_id}",
        )
    return Response(data={"removed": True, "plan_id": plan_id, "suite_id": suite_id})


@router.put(
    "/plans/{plan_id}/suites/{suite_id}/toggle",
    response_model=Response[Dict[str, Any]],
    summary="启用/禁用 Suite",
)
async def toggle_plan_suite(
    plan_id: int,
    suite_id: int,
    payload: SuiteToggleRequest,
    user: User = Depends(require_auth),
):
    """启用或禁用 Plan 中的 Suite"""
    result = _service.toggle_suite(plan_id, suite_id, payload.enabled, user_id=user.id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Suite {suite_id} not in plan {plan_id}",
        )
    return Response(data=result)


@router.put(
    "/plans/{plan_id}/suites/reorder",
    response_model=Response[List[Dict[str, Any]]],
    summary="批量重排序 Suite",
)
async def reorder_plan_suites(
    plan_id: int,
    payload: SuiteReorderRequest,
    user: User = Depends(require_auth),
):
    """批量重排序 Plan 中的 Suite"""
    try:
        result = _service.reorder_suites(
            plan_id, payload.suite_orders, user_id=user.id,
        )
        return Response(data=result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ============================================================
# 3. 执行管理
# ============================================================

@router.post(
    "/plans/{plan_id}/execute",
    response_model=Response[Dict[str, Any]],
    summary="执行测试计划",
)
async def execute_plan(
    plan_id: int,
    payload: ExecutePlanRequest,
    user: User = Depends(require_auth),
):
    """执行测试计划

    - background=True: 后台执行,立即返回 execution_id
    - background=False: 同步等待执行完成,返回完整结果
    """
    try:
        result = await _service.execute_plan(
            plan_id=plan_id,
            user_id=user.id,
            execution_id=payload.execution_id,
            trigger_source=payload.trigger_source,
            background=payload.background,
        )
        return Response(data=result)
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/executions/list",
    response_model=Response[Dict[str, Any]],
    summary="执行历史列表(分页)",
)
async def list_executions(
    plan_id: Optional[int] = Query(default=None, description="计划 ID"),
    status_filter: Optional[str] = Query(default=None, alias="status", description="状态"),
    trigger_source: Optional[str] = Query(default=None, description="触发来源"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    user: User = Depends(require_auth),
):
    """分页查询执行历史

    注意: GET /executions/list 必须在 GET /executions/{execution_id} 之前注册
    """
    result = _service.list_executions(
        plan_id=plan_id,
        status=status_filter,
        trigger_source=trigger_source,
        user_id=user.id,
        page=page,
        page_size=page_size,
    )
    return Response(data=result)


@router.get(
    "/executions/stats",
    response_model=Response[Dict[str, Any]],
    summary="执行统计",
)
async def get_execution_stats(
    plan_id: Optional[int] = Query(default=None, description="计划 ID"),
    user: User = Depends(require_auth),
):
    """获取执行统计"""
    result = _service.get_execution_stats(plan_id=plan_id, user_id=user.id)
    return Response(data=result)


@router.get(
    "/executions/{execution_id}",
    response_model=Response[Dict[str, Any]],
    summary="执行详情",
)
async def get_execution(
    execution_id: str,
    include_details: bool = Query(default=True, description="是否包含 Suite 明细"),
    user: User = Depends(require_auth),
):
    """获取执行记录详情"""
    result = _service.get_execution(
        execution_id, include_details=include_details,
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"PlanExecution not found: {execution_id}",
        )
    return Response(data=result)


@router.post(
    "/executions/{execution_id}/cancel",
    response_model=Response[Dict[str, Any]],
    summary="取消执行",
)
async def cancel_execution(
    execution_id: str,
    user: User = Depends(require_auth),
):
    """取消正在执行的 Plan"""
    try:
        result = await _service.cancel_execution(execution_id, user_id=user.id)
        return Response(data=result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ============================================================
# 4. 报告
# ============================================================

@router.get(
    "/reports/list",
    response_model=Response[Dict[str, Any]],
    summary="报告列表(分页)",
)
async def list_reports(
    plan_id: Optional[int] = Query(default=None, description="计划 ID"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    user: User = Depends(require_auth),
):
    """列出执行报告(只返回有 report_path 的记录)"""
    result = _service.list_reports(
        plan_id=plan_id,
        user_id=user.id,
        page=page,
        page_size=page_size,
    )
    return Response(data=result)


@router.get(
    "/reports/{execution_id}",
    response_model=Response[Dict[str, Any]],
    summary="获取执行报告",
)
async def get_report(
    execution_id: str,
    format: str = Query(default="json", description="报告格式"),
    user: User = Depends(require_auth),
):
    """获取计划执行报告

    优先读取已生成的报告文件,文件不存在则基于 DB 数据构建。
    """
    result = _service.get_report(execution_id, format=format)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return Response(data=result)


# ============================================================
# 5. 仪表盘
# ============================================================

@router.get(
    "/dashboard",
    response_model=Response[Dict[str, Any]],
    summary="测试编排总览",
)
async def get_dashboard(
    user: User = Depends(require_auth),
):
    """获取测试编排总览数据(计划统计 + 执行统计)"""
    result = _service.get_dashboard(user_id=user.id)
    return Response(data=result)
