"""
三层上下文 API

提供上下文路由和检索的API端点。

端点：
    - POST /api/v1/context/route: 预览路由计划（不执行检索）
    - POST /api/v1/context/retrieve: 执行检索并返回融合上下文
    - GET /api/v1/context/preview/{task_id}: 查看任务使用的AI上下文
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.context.router import get_context_router
from app.context.models import TaskContext
from app.rag.retrieval_engine.manager import get_retrieval_manager

logger = logging.getLogger(__name__)
router = APIRouter()


# ================================================================== #
#  请求/响应模型                                                       #
# ================================================================== #

class RouteRequest(BaseModel):
    """路由请求"""
    task_id: str = Field(default="", description="任务ID")
    task_type: str = Field(default="general", description="任务类型")
    requirement: str = Field(default="", description="需求文本")
    business_module: str = Field(default="", description="业务模块")
    keywords: List[str] = Field(default_factory=list, description="关键词")
    page_names: List[str] = Field(default_factory=list, description="页面名称")
    api_names: List[str] = Field(default_factory=list, description="API名称")


class RetrieveRequest(RouteRequest):
    """检索请求（继承路由请求）"""
    execute: bool = Field(default=True, description="是否执行检索")


class ContextPreviewResponse(BaseModel):
    """上下文预览响应"""
    task_id: str = ""
    plan: Dict[str, Any] = {}
    mysql_data: Dict[str, Any] = {}
    vector_results: Dict[str, Any] = {}
    graph_results: Dict[str, Any] = {}
    fused_context: Dict[str, Any] = {}
    sources: List[str] = []
    summary: str = ""
    duration: float = 0.0


# ================================================================== #
#  API 端点                                                           #
# ================================================================== #

@router.post("/context/route")
async def preview_route(request: RouteRequest):
    """
    预览路由计划（不执行检索）

    根据任务上下文生成检索计划，展示AI将查询哪些数据库。
    """
    router_agent = get_context_router()

    context = TaskContext(
        task_id=request.task_id,
        task_type=request.task_type,
        requirement=request.requirement,
        business_module=request.business_module,
        keywords=request.keywords,
        page_names=request.page_names,
        api_names=request.api_names,
    )

    plan = router_agent.route(context)

    return {
        "task_id": request.task_id,
        "plan": plan.to_dict(),
        "reason": plan.reason,
    }


@router.post("/context/retrieve", response_model=ContextPreviewResponse)
async def execute_retrieve(request: RetrieveRequest):
    """
    执行检索并返回融合上下文

    流程：
        1. ContextRouter生成检索计划
        2. RetrievalManager执行三库检索
        3. ContextFusion融合结果
    """
    router_agent = get_context_router()
    manager = get_retrieval_manager()

    context = TaskContext(
        task_id=request.task_id,
        task_type=request.task_type,
        requirement=request.requirement,
        business_module=request.business_module,
        keywords=request.keywords,
        page_names=request.page_names,
        api_names=request.api_names,
    )

    # 1. 路由
    plan = router_agent.route(context)

    # 2. 执行检索（带追踪信息）
    trace = manager.retrieve_with_trace(plan)

    # 3. 构建响应
    fused = trace.get("fused_context", {})

    return ContextPreviewResponse(
        task_id=request.task_id,
        plan=trace.get("plan", {}),
        mysql_data=trace.get("mysql_result", {}).get("data", {}),
        vector_results=trace.get("milvus_result", {}).get("data", {}),
        graph_results=trace.get("neo4j_result", {}).get("data", {}),
        fused_context=fused,
        sources=fused.get("sources", []),
        summary=fused.get("summary", ""),
        duration=trace.get("duration", 0.0),
    )


@router.get("/context/preview/{task_id}", response_model=ContextPreviewResponse)
async def get_context_preview(task_id: str):
    """
    查看AI生成脚本之前使用了哪些上下文

    根据task_id查询关联的任务信息，
    自动构建上下文并展示三库数据来源。
    """
    # 从MySQL查询任务信息
    from app.db.database import SessionLocal
    db = SessionLocal()

    try:
        from app.models.task import Task
        task = db.query(Task).filter(Task.id == task_id).first()

        if not task:
            # 尝试作为字符串ID查询
            from app.models.test_requirement import TestRequirement
            req = db.query(TestRequirement).filter(TestRequirement.task_id == task_id).first()

            if not req:
                raise HTTPException(status_code=404, detail=f"未找到task_id={task_id}的记录")

            requirement_text = req.content or ""
            business_module = ""
            if req.parsed_result:
                import json
                try:
                    parsed = json.loads(req.parsed_result)
                    business_module = parsed.get("business_module", "")
                except json.JSONDecodeError:
                    pass
        else:
            requirement_text = task.requirement or ""
            business_module = ""

    finally:
        db.close()

    # 构建上下文并执行检索
    router_agent = get_context_router()
    manager = get_retrieval_manager()

    context = TaskContext(
        task_id=task_id,
        requirement=requirement_text,
        business_module=business_module,
    )

    plan = router_agent.route(context)
    trace = manager.retrieve_with_trace(plan)

    fused = trace.get("fused_context", {})

    return ContextPreviewResponse(
        task_id=task_id,
        plan=trace.get("plan", {}),
        mysql_data=trace.get("mysql_result", {}).get("data", {}),
        vector_results=trace.get("milvus_result", {}).get("data", {}),
        graph_results=trace.get("neo4j_result", {}).get("data", {}),
        fused_context=fused,
        sources=fused.get("sources", []),
        summary=fused.get("summary", ""),
        duration=trace.get("duration", 0.0),
    )


@router.get("/context/stats")
async def get_context_stats():
    """获取三层上下文系统统计信息"""
    from app.db.database import SessionLocal
    db = SessionLocal()

    try:
        stats = {
            "mysql": {"tables": 0, "total_rows": 0},
            "milvus": {"collections": 0, "total_vectors": 0},
            "neo4j": {"nodes": 0, "relationships": 0},
        }

        # MySQL统计
        from sqlalchemy import text
        result = db.execute(text("SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table'"))
        stats["mysql"]["tables"] = result.fetchone()[0] if result else 0

        # Milvus统计
        try:
            from app.db.milvus_client import get_milvus_client
            client = get_milvus_client()
            if client:
                from pymilvus import list_collections
                collections = list_collections()
                stats["milvus"]["collections"] = len(collections)
        except Exception:
            pass

        # Neo4j统计
        try:
            from app.db.neo4j_client import get_statistics
            neo4j_stats = get_statistics()
            if neo4j_stats:
                stats["neo4j"]["nodes"] = neo4j_stats.get("total_nodes", 0)
                stats["neo4j"]["relationships"] = neo4j_stats.get("total_relationships", 0)
        except Exception:
            pass

        return stats

    finally:
        db.close()
