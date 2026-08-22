"""测试质量分析 — API

挂载路径: /api/quality-analysis

路由:
  POST   /                          创建质量分析任务
  GET    /list                      报告列表(分页)
  GET    /dashboard                 质量仪表盘
  GET    /stats                     统计信息
  GET    /{report_id}               报告详情
  PUT    /{report_id}               更新报告
  DELETE /{report_id}               删除报告
  POST   /{report_id}/regenerate    重新生成分析
  POST   /{report_id}/run           同步执行分析
"""
import asyncio
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.auth import require_auth
from app.models.user import User
from app.schemas.response import Response
from app.services.quality_analysis_service import (
    QualityAnalysisService,
    get_quality_analysis_service,
)

router = APIRouter()
_service: QualityAnalysisService = get_quality_analysis_service()


# ============================================================
# 请求 Schema
# ============================================================

class AnalysisScopeRequest(BaseModel):
    """分析范围"""
    asset_ids: Optional[List[int]] = Field(default=None, description="资产ID列表")
    execution_ids: Optional[List[int]] = Field(default=None, description="执行记录ID列表")
    time_range: Optional[Dict[str, str]] = Field(default=None, description="时间范围 {start, end}")
    modules: Optional[List[str]] = Field(default=None, description="模块列表")
    asset_types: Optional[List[str]] = Field(default=None, description="资产类型列表")


class QualityAnalysisCreateRequest(BaseModel):
    """创建质量分析请求"""
    title: str = Field(..., min_length=1, max_length=200, description="报告标题")
    description: Optional[str] = Field(default=None, description="报告描述")
    analysis_scope: Optional[AnalysisScopeRequest] = Field(default=None, description="分析范围")
    background: bool = Field(default=True, description="是否后台执行")


class QualityReportUpdateRequest(BaseModel):
    """更新报告请求"""
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None


# ============================================================
# 路由
# ============================================================

@router.post("", response_model=Response[Dict[str, Any]], summary="创建质量分析任务")
async def create_analysis(
    payload: QualityAnalysisCreateRequest,
    user: User = Depends(require_auth),
):
    """创建质量分析任务

    - background=True(默认): 立即返回报告ID,异步执行分析
    - background=False: 同步等待分析完成
    """
    try:
        data = payload.model_dump()
        # analysis_scope 转换为 dict
        if data.get("analysis_scope"):
            data["analysis_scope"] = data["analysis_scope"]
        result = _service.create_analysis(data, user_id=user.id, background=payload.background)
        return Response(data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list", response_model=Response[Dict[str, Any]], summary="报告列表(分页)")
async def list_reports(
    keyword: Optional[str] = Query(default=None, description="关键词搜索"),
    status: Optional[str] = Query(default=None, description="状态筛选"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    user: User = Depends(require_auth),
):
    """获取质量分析报告列表"""
    result = _service.list_reports(
        keyword=keyword,
        status=status,
        user_id=user.id,
        page=page,
        page_size=page_size,
    )
    return Response(data=result)


@router.get("/dashboard", response_model=Response[Dict[str, Any]], summary="质量仪表盘")
async def get_dashboard(
    user: User = Depends(require_auth),
):
    """获取质量仪表盘数据

    返回:
    - total: 报告总数
    - by_status: 按状态分组
    - avg_scores: 平均分数(质量/覆盖/风险/重复/缺陷)
    - recent_reports: 最近 5 条报告
    """
    result = _service.get_dashboard(user_id=user.id)
    return Response(data=result)


@router.get("/stats", response_model=Response[Dict[str, Any]], summary="统计信息")
async def get_stats(
    user: User = Depends(require_auth),
):
    """获取统计信息"""
    result = _service.get_stats(user_id=user.id)
    return Response(data=result)


@router.get("/{report_id}", response_model=Response[Dict[str, Any]], summary="报告详情")
async def get_report(
    report_id: int,
    include_analysis: bool = Query(default=True, description="是否包含分析结果"),
    user: User = Depends(require_auth),
):
    """获取质量分析报告详情"""
    result = _service.get_report(
        report_id,
        user_id=user.id,
        include_analysis=include_analysis,
    )
    if result is None:
        raise HTTPException(status_code=404, detail=f"QualityReport not found: {report_id}")
    return Response(data=result)


@router.put("/{report_id}", response_model=Response[Dict[str, Any]], summary="更新报告")
async def update_report(
    report_id: int,
    payload: QualityReportUpdateRequest,
    user: User = Depends(require_auth),
):
    """更新报告(仅允许更新 title/description)"""
    try:
        data = payload.model_dump(exclude_unset=True)
        result = _service.update_report(report_id, data, user_id=user.id)
        return Response(data=result)
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{report_id}", response_model=Response[Dict[str, Any]], summary="删除报告")
async def delete_report(
    report_id: int,
    hard: bool = Query(default=False, description="True=物理删除,False=软删除"),
    user: User = Depends(require_auth),
):
    """删除质量分析报告"""
    ok = _service.delete_report(report_id, hard=hard, user_id=user.id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"QualityReport not found: {report_id}")
    return Response(data={"deleted": True, "hard": hard, "report_id": report_id})


@router.post("/{report_id}/regenerate", response_model=Response[Dict[str, Any]], summary="重新生成分析")
async def regenerate_report(
    report_id: int,
    background: bool = Query(default=True, description="是否后台执行"),
    user: User = Depends(require_auth),
):
    """重新生成质量分析"""
    try:
        result = _service.regenerate(report_id, user_id=user.id, background=background)
        return Response(data=result)
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{report_id}/run", response_model=Response[Dict[str, Any]], summary="同步执行分析")
async def run_analysis(
    report_id: int,
    user: User = Depends(require_auth),
):
    """同步执行质量分析(等待完成)

    注意: 此接口会阻塞直到分析完成,可能耗时较长(30-60秒)
    """
    try:
        # 先获取报告
        report = _service.get_report(report_id, user_id=user.id)
        if report is None:
            raise HTTPException(status_code=404, detail=f"QualityReport not found: {report_id}")

        analysis_scope = report.get("analysis_scope") or {}
        result = await _service.run_analysis(report_id, analysis_scope, user_id=user.id)
        return Response(data=result)
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
