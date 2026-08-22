"""AI 测试反馈学习 — API

挂载路径: /api/feedback-learning

路由:
  POST   /                                    创建反馈学习任务
  GET    /dashboard                           反馈学习仪表盘
  GET    /stats                               统计信息

  GET    /records/list                        学习记录列表(分页)
  GET    /records/{record_id}                 学习记录详情
  DELETE /records/{record_id}                 删除学习记录

  GET    /optimizations/list                  优化建议列表(分页)
  GET    /optimizations/{optimization_id}     优化建议详情
  DELETE /optimizations/{optimization_id}     删除优化建议
  POST   /optimizations/{optimization_id}/apply    应用优化建议
  POST   /optimizations/{optimization_id}/reject  拒绝优化建议

  POST   /{optimization_id}/run               同步执行学习
"""
import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.auth import require_auth
from app.models.user import User
from app.schemas.response import Response
from app.services.feedback_learning_service import (
    FeedbackLearningService,
    get_feedback_learning_service,
)

router = APIRouter()
_service: FeedbackLearningService = get_feedback_learning_service()


# ============================================================
# 请求 Schema
# ============================================================

class CollectScopeRequest(BaseModel):
    """收集范围"""
    time_range: Optional[Dict[str, str]] = Field(default=None, description="时间范围 {start, end}")
    agent_names: Optional[List[str]] = Field(default=None, description="Agent名称列表")
    limit: Optional[int] = Field(default=200, ge=1, le=1000, description="每种案例收集上限")


class FeedbackLearningCreateRequest(BaseModel):
    """创建反馈学习请求"""
    title: str = Field(..., min_length=1, max_length=200, description="学习任务标题")
    description: Optional[str] = Field(default=None, description="学习任务描述")
    collect_scope: Optional[CollectScopeRequest] = Field(default=None, description="收集范围")
    background: bool = Field(default=True, description="是否后台执行")


class RejectRequest(BaseModel):
    """拒绝优化建议请求"""
    reason: Optional[str] = Field(default=None, description="拒绝原因")


# ============================================================
# 学习任务路由
# ============================================================

@router.post("", response_model=Response[Dict[str, Any]], summary="创建反馈学习任务")
async def create_learning(
    payload: FeedbackLearningCreateRequest,
    user: User = Depends(require_auth),
):
    """创建反馈学习任务

    - background=True(默认): 立即返回任务ID,异步执行学习
    - background=False: 同步等待学习完成

    流程:
    1. 收集成功/失败/人工修改案例
    2. LLM 分析案例模式
    3. 生成 RAG/Prompt/策略 三类优化建议
    """
    try:
        data = payload.model_dump()
        result = _service.create_learning(data, user_id=user.id, background=payload.background)
        return Response(data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dashboard", response_model=Response[Dict[str, Any]], summary="反馈学习仪表盘")
async def get_dashboard(
    user: User = Depends(require_auth),
):
    """获取反馈学习仪表盘数据

    返回:
    - records: 学习记录统计(按类型/状态)
    - optimizations: 优化建议统计(按类型/状态/平均置信度)
    - recent_optimizations: 最近5条优化建议
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


@router.post("/{optimization_id}/run", response_model=Response[Dict[str, Any]], summary="同步执行学习")
async def run_learning(
    optimization_id: int,
    user: User = Depends(require_auth),
):
    """同步执行反馈学习(等待完成)

    注意: 此接口会阻塞直到学习完成,可能耗时较长(30-60秒)
    """
    try:
        opt = _service.get_optimization(optimization_id, user_id=user.id)
        if opt is None:
            raise HTTPException(status_code=404, detail=f"FeedbackOptimization not found: {optimization_id}")

        opt_json = opt.get("optimization_json") or {}
        collect_scope = opt_json.get("collect_scope", {}) if isinstance(opt_json, dict) else {}
        result = await _service.run_learning(optimization_id, collect_scope, user_id=user.id)
        return Response(data=result)
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 学习记录路由
# ============================================================

@router.get("/records/list", response_model=Response[Dict[str, Any]], summary="学习记录列表(分页)")
async def list_records(
    record_type: Optional[str] = Query(default=None, description="记录类型: success/failure/modification"),
    agent_name: Optional[str] = Query(default=None, description="Agent名称筛选"),
    status: Optional[str] = Query(default=None, description="状态筛选"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    user: User = Depends(require_auth),
):
    """获取学习记录列表"""
    result = _service.list_records(
        record_type=record_type,
        agent_name=agent_name,
        status=status,
        user_id=user.id,
        page=page,
        page_size=page_size,
    )
    return Response(data=result)


@router.get("/records/{record_id}", response_model=Response[Dict[str, Any]], summary="学习记录详情")
async def get_record(
    record_id: int,
    user: User = Depends(require_auth),
):
    """获取学习记录详情"""
    result = _service.get_record(record_id, user_id=user.id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"FeedbackLearningRecord not found: {record_id}")
    return Response(data=result)


@router.delete("/records/{record_id}", response_model=Response[Dict[str, Any]], summary="删除学习记录")
async def delete_record(
    record_id: int,
    hard: bool = Query(default=False, description="True=物理删除,False=软删除"),
    user: User = Depends(require_auth),
):
    """删除学习记录"""
    ok = _service.delete_record(record_id, hard=hard, user_id=user.id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"FeedbackLearningRecord not found: {record_id}")
    return Response(data={"deleted": True, "hard": hard, "record_id": record_id})


# ============================================================
# 优化建议路由
# ============================================================

@router.get("/optimizations/list", response_model=Response[Dict[str, Any]], summary="优化建议列表(分页)")
async def list_optimizations(
    optimization_type: Optional[str] = Query(default=None, description="优化类型: rag/prompt/strategy"),
    agent_name: Optional[str] = Query(default=None, description="Agent名称筛选"),
    status: Optional[str] = Query(default=None, description="状态筛选"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    user: User = Depends(require_auth),
):
    """获取优化建议列表"""
    result = _service.list_optimizations(
        optimization_type=optimization_type,
        agent_name=agent_name,
        status=status,
        user_id=user.id,
        page=page,
        page_size=page_size,
    )
    return Response(data=result)


@router.get("/optimizations/{optimization_id}", response_model=Response[Dict[str, Any]], summary="优化建议详情")
async def get_optimization(
    optimization_id: int,
    user: User = Depends(require_auth),
):
    """获取优化建议详情"""
    result = _service.get_optimization(optimization_id, user_id=user.id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"FeedbackOptimization not found: {optimization_id}")
    return Response(data=result)


@router.delete("/optimizations/{optimization_id}", response_model=Response[Dict[str, Any]], summary="删除优化建议")
async def delete_optimization(
    optimization_id: int,
    hard: bool = Query(default=False, description="True=物理删除,False=软删除"),
    user: User = Depends(require_auth),
):
    """删除优化建议"""
    ok = _service.delete_optimization(optimization_id, hard=hard, user_id=user.id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"FeedbackOptimization not found: {optimization_id}")
    return Response(data={"deleted": True, "hard": hard, "optimization_id": optimization_id})


@router.post("/optimizations/{optimization_id}/apply", response_model=Response[Dict[str, Any]], summary="应用优化建议")
async def apply_optimization(
    optimization_id: int,
    user: User = Depends(require_auth),
):
    """应用优化建议

    根据优化类型执行不同操作:
    - rag: 标记应用(检索参数需系统配置确认)
    - prompt: 通过 PromptManager 创建新版本并激活
    - strategy: 标记应用(Agent配置需系统管理确认)
    """
    try:
        result = _service.apply_optimization(optimization_id, user_id=user.id)
        return Response(data=result)
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/optimizations/{optimization_id}/reject", response_model=Response[Dict[str, Any]], summary="拒绝优化建议")
async def reject_optimization(
    optimization_id: int,
    payload: Optional[RejectRequest] = None,
    user: User = Depends(require_auth),
):
    """拒绝优化建议"""
    try:
        reason = payload.reason if payload else None
        result = _service.reject_optimization(optimization_id, reason=reason, user_id=user.id)
        return Response(data=result)
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
