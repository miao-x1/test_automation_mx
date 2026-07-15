"""
图数据库 API路由

数据隔离：所有查询自动过滤 user_id
"""
from typing import Optional
from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel
from app.services.graph_service import GraphService
from app.runtime.agent_factory import AgentFactory
from app.db.neo4j_client import is_available, get_statistics
from app.schemas.response import Response
from app.core.auth import require_auth
from app.models.user import User

router = APIRouter()


class BuildRequest(BaseModel):
    full: bool = True
    clean_first: bool = True


class InferFlowRequest(BaseModel):
    requirement: str
    keywords: list[str] = None
    steps: list[str] = None


@router.post("/build", summary="全量构建图谱")
async def build_graph(request: BuildRequest = None, user: User = Depends(require_auth)):
    """从MySQL全量同步当前用户数据到Neo4j"""
    if not is_available():
        return Response(code=503, message="Neo4j不可用", data={"available": False})

    agent = AgentFactory.create("graph_agent")
    clean = request.clean_first if request else True
    stats = agent.build_full_graph(clean_first=clean, user_id=user.id)
    return Response(code=200, message="图谱构建完成", data=stats)


@router.post("/build/{task_id}", summary="构建任务图谱")
async def build_task_graph(task_id: int, user: User = Depends(require_auth)):
    """构建指定任务的图谱数据"""
    if not is_available():
        return Response(code=503, message="Neo4j不可用", data={"available": False})

    agent = AgentFactory.create("graph_agent")
    result = agent.sync_single_task(task_id, user_id=user.id)
    return Response(code=200, message="任务图谱构建完成", data=result)


@router.post("/sync/{task_id}", summary="增量同步任务")
async def sync_task(task_id: int, user: User = Depends(require_auth)):
    """增量同步指定任务到图谱"""
    if not is_available():
        return Response(code=503, message="Neo4j不可用", data={"available": False})

    agent = AgentFactory.create("graph_agent")
    result = agent.sync_single_task(task_id, user_id=user.id)
    return Response(code=200, message="同步完成", data=result)


@router.get("/data", summary="获取图谱可视化数据")
async def get_graph_data(
    types: Optional[str] = Query(default=None, description="节点类型: Page,Element,TestCase,Script"),
    limit: int = Query(default=500, ge=1, le=2000),
    user: User = Depends(require_auth),
):
    """获取当前用户的图谱可视化数据"""
    node_types = types.split(",") if types else None
    data = GraphService.get_graph_data(node_types=node_types, limit=limit, user_id=user.id)
    return Response(code=200, message="获取成功", data=data)


@router.get("/stat", summary="图谱统计")
async def get_stat(user: User = Depends(require_auth)):
    """获取当前用户的图谱统计"""
    stats = get_statistics(user_id=user.id)
    return Response(code=200, message="获取成功", data=stats)


@router.get("/query", summary="搜索图谱节点")
async def query_nodes(
    keyword: str = Query(..., description="搜索关键词"),
    limit: int = Query(default=30, ge=1, le=100),
    user: User = Depends(require_auth),
):
    """在当前用户的图谱中搜索节点"""
    results = GraphService.search_nodes(keyword, limit=limit, user_id=user.id)
    return Response(code=200, message="获取成功", data={
        "keyword": keyword,
        "results": results,
        "count": len(results),
    })


@router.get("/path", summary="查询最短路径")
async def get_shortest_path(
    from_id: str = Query(..., description="起始节点ID"),
    to_id: str = Query(..., description="目标节点ID"),
    user: User = Depends(require_auth),
):
    """查询两个节点之间的最短路径"""
    path_data = GraphService.get_shortest_path(from_id, to_id, user_id=user.id)
    if not path_data:
        return Response(code=404, message="未找到路径", data=None)
    return Response(code=200, message="获取成功", data=path_data)


@router.get("/pages", summary="获取所有页面节点")
async def get_pages(
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(require_auth),
):
    pages = GraphService.get_all_pages(limit=limit, user_id=user.id)
    return Response(code=200, message="获取成功", data=pages)


@router.get("/pages/{page_id}", summary="获取页面详情")
async def get_page_detail(page_id: str, user: User = Depends(require_auth)):
    """获取页面详情"""
    page = GraphService.get_page_detail(page_id, user_id=user.id)
    if not page:
        raise HTTPException(status_code=404, detail=f"页面 {page_id} 不存在")
    return Response(code=200, message="获取成功", data=page)


@router.get("/cases", summary="获取所有用例节点")
async def get_cases(
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(require_auth),
):
    cases = GraphService.get_all_cases(limit=limit, user_id=user.id)
    return Response(code=200, message="获取成功", data=cases)


@router.get("/cases/{case_id}", summary="获取用例详情")
async def get_case_detail(case_id: str, user: User = Depends(require_auth)):
    """获取用例详情"""
    case = GraphService.get_case_detail(case_id, user_id=user.id)
    if not case:
        raise HTTPException(status_code=404, detail=f"用例 {case_id} 不存在")
    return Response(code=200, message="获取成功", data=case)


@router.get("/scripts", summary="获取所有脚本节点")
async def get_scripts(
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(require_auth),
):
    scripts = GraphService.get_all_scripts(limit=limit, user_id=user.id)
    return Response(code=200, message="获取成功", data=scripts)


@router.get("/statistics", summary="获取图谱统计信息")
async def get_statistics_endpoint(user: User = Depends(require_auth)):
    """获取当前用户的图谱统计"""
    stats = get_statistics(user_id=user.id)
    return Response(code=200, message="获取成功", data=stats)


@router.get("/neighbors/{node_id}", summary="获取节点一阶邻居")
async def get_neighbors(
    node_id: str,
    rel_types: Optional[str] = Query(default=None, description="关系类型过滤，逗号分隔"),
    user: User = Depends(require_auth),
):
    """获取指定节点的一阶邻居"""
    types = rel_types.split(",") if rel_types else None
    data = GraphService.get_neighbors(node_id, rel_types=types, user_id=user.id)
    if not data.get("center"):
        raise HTTPException(status_code=404, detail=f"节点 {node_id} 不存在")
    return Response(code=200, message="获取成功", data=data)


@router.get("/business-flows", summary="获取业务流列表")
async def get_business_flows(user: User = Depends(require_auth)):
    """获取当前用户的所有业务流"""
    flows = GraphService.get_business_flows(user_id=user.id)
    return Response(code=200, message="获取成功", data={"flows": flows, "count": len(flows)})


@router.post("/infer", summary="Graph推理页面路径")
async def infer_flow(request: InferFlowRequest, user: User = Depends(require_auth)):
    """根据需求推理页面路径和业务流"""
    if not is_available():
        return Response(code=503, message="Neo4j不可用", data={"available": False})

    agent = AgentFactory.create("graph_agent")
    result = agent.infer_flow(
        requirement=request.requirement,
        keywords=request.keywords,
        steps=request.steps,
        user_id=user.id,
    )
    return Response(code=200, message="推理完成", data=result)


@router.get("/status", summary="检查Neo4j连接状态")
async def check_status():
    available = is_available()
    config_info = {"uri": "", "user": "", "available": available}
    if available:
        from app.core.config import settings
        config_info["uri"] = settings.NEO4J_URI
        config_info["user"] = settings.NEO4J_USER

    status_code = 200 if available else 503
    msg = "Neo4j连接正常" if available else "Neo4j不可用"
    return Response(code=status_code, message=msg, data=config_info)
