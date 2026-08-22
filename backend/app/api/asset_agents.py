"""
测试资产中心 — Agent 业务流路由

挂载路径: /api/asset-center/agents

接口分组:
  1. 完整流程     - POST /analyze (搜索 → 复用 → 优化)
  2. 单步调用     - POST /search  POST /evaluate  POST /optimize
  3. 健康检查     - GET /health

设计要点:
  1. 使用 Depends(require_auth) 获取当前用户
  2. 完整流程返回搜索结果 + 复用决策 + 优化方案
  3. 单步调用支持单独使用某个 Agent
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.auth import require_auth
from app.models.user import User
from app.schemas.response import Response
from app.services.asset_center_orchestrator import get_asset_center_orchestrator

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================
# 请求模型
# ============================================================

class AnalyzeRequest(BaseModel):
    """完整资产分析请求"""
    requirement: str = Field(
        ..., min_length=1, max_length=500,
        description="需求描述 (如 '测试登录功能')",
    )
    asset_types: Optional[List[str]] = Field(
        default=None, description="限定资产类型",
    )
    module: Optional[str] = Field(default=None, description="模块过滤")
    tags: Optional[List[str]] = Field(default=None, description="标签过滤")
    limit: int = Field(default=10, ge=1, le=50, description="搜索结果上限")
    use_vector: bool = Field(default=True, description="启用 Milvus 向量召回")
    use_relation: bool = Field(default=True, description="启用 Neo4j 关系扩展")


class SearchStepRequest(BaseModel):
    """资产搜索单步请求"""
    query: str = Field(..., min_length=1, max_length=500)
    asset_types: Optional[List[str]] = None
    module: Optional[str] = None
    tags: Optional[List[str]] = None
    limit: int = Field(default=10, ge=1, le=50)
    use_vector: bool = True
    use_relation: bool = True


class EvaluateStepRequest(BaseModel):
    """复用评估单步请求"""
    requirement: str = Field(..., min_length=1, max_length=500)
    search_results: List[Dict[str, Any]] = Field(
        ..., description="搜索结果 (来自 AssetSearchAgent)",
    )


class OptimizeStepRequest(BaseModel):
    """方案优化单步请求"""
    requirement: str = Field(..., min_length=1, max_length=500)
    reuse_decision: Dict[str, Any] = Field(
        ..., description="复用决策 (来自 AssetReuseAgent)",
    )
    search_results: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="搜索结果 (可选, 用于上下文)",
    )


# ============================================================
# 1. 完整流程
# ============================================================

@router.post("/analyze", summary="完整资产分析流程")
async def analyze_requirement(
    req: AnalyzeRequest,
    user: User = Depends(require_auth),
):
    """完整资产分析流程: 搜索 → 复用评估 → 方案优化

    输入: 需求描述 (如 "测试登录功能")
    输出: 搜索结果 + 复用决策 + 优化方案

    业务流:
      1. AssetSearchAgent: 根据 requirement 搜索已有资产
      2. AssetReuseAgent: 评估搜索结果的可复用性
      3. AssetOptimizationAgent: 基于复用决策生成优化测试方案
    """
    orchestrator = get_asset_center_orchestrator()
    result = await orchestrator.analyze_requirement(
        requirement=req.requirement,
        asset_types=req.asset_types,
        module=req.module,
        tags=req.tags,
        limit=req.limit,
        use_vector=req.use_vector,
        use_relation=req.use_relation,
        user_id=user.id,
    )
    return Response(data=result)


# ============================================================
# 2. 单步调用
# ============================================================

@router.post("/search", summary="资产搜索 (单步)")
async def search_assets(
    req: SearchStepRequest,
    user: User = Depends(require_auth),
):
    """仅执行资产搜索步骤 (AssetSearchAgent)

    返回三源融合搜索结果, 含命中原因
    """
    orchestrator = get_asset_center_orchestrator()
    result = await orchestrator.search_assets(
        query=req.query,
        asset_types=req.asset_types,
        module=req.module,
        tags=req.tags,
        limit=req.limit,
        use_vector=req.use_vector,
        use_relation=req.use_relation,
        user_id=user.id,
    )
    return Response(data=result)


@router.post("/evaluate", summary="复用评估 (单步)")
async def evaluate_reuse(
    req: EvaluateStepRequest,
    user: User = Depends(require_auth),
):
    """仅执行复用评估步骤 (AssetReuseAgent)

    输入需求与搜索结果, 输出复用决策
    """
    orchestrator = get_asset_center_orchestrator()
    result = await orchestrator.evaluate_reuse(
        requirement=req.requirement,
        search_results=req.search_results,
    )
    return Response(data=result)


@router.post("/optimize", summary="方案优化 (单步)")
async def optimize_plan(
    req: OptimizeStepRequest,
    user: User = Depends(require_auth),
):
    """仅执行方案优化步骤 (AssetOptimizationAgent)

    输入需求与复用决策, 输出优化测试方案
    """
    orchestrator = get_asset_center_orchestrator()
    result = await orchestrator.optimize_plan(
        requirement=req.requirement,
        reuse_decision=req.reuse_decision,
        search_results=req.search_results,
    )
    return Response(data=result)


# ============================================================
# 3. 健康检查
# ============================================================

@router.get("/health", summary="Agent 服务健康检查")
async def health_check(
    user: User = Depends(require_auth),
):
    """检查 Agent 服务可用性"""
    return Response(data={
        "status": "healthy",
        "agents": [
            {"name": "asset_search_agent", "type": "tool", "enabled": True},
            {"name": "asset_reuse_agent", "type": "llm", "enabled": True},
            {"name": "asset_optimization_agent", "type": "llm", "enabled": True},
        ],
        "orchestrator": "AssetCenterOrchestrator",
        "flow": "search → reuse → optimize",
    })
