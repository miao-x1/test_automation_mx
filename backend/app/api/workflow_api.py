"""
Workflow API — 工作流 REST 接口

端点:
    POST /api/v1/workflow/run         — 同步执行工作流
    POST /api/v1/workflow/stream      — SSE 流式执行工作流
    GET  /api/v1/workflow/flows       — 列出所有可用工作流
    GET  /api/v1/workflow/{name}/graph — 获取工作流图结构
"""
import asyncio
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.workflow import get_workflow_runner, list_flows, get_flow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/workflow", tags=["Workflow"])


# ================================================================== #
#  Request/Response 模型                                               #
# ================================================================== #

class RunWorkflowRequest(BaseModel):
    """执行工作流请求"""
    flow_name: str = Field(..., description="工作流名称: ui_test / api_test / performance_test")
    requirement: str = Field(..., description="用户需求文本")
    metadata: Optional[Dict[str, Any]] = Field(None, description="额外元数据")


class RunWorkflowResponse(BaseModel):
    """执行工作流响应"""
    code: int = 200
    data: Dict[str, Any]


# ================================================================== #
#  API 端点                                                            #
# ================================================================== #

@router.post("/run", response_model=RunWorkflowResponse)
async def run_workflow(req: RunWorkflowRequest):
    """同步执行工作流

    等待所有节点执行完成后返回最终结果。
    """
    runner = get_workflow_runner()
    state = await runner.run(
        flow_name=req.flow_name,
        requirement=req.requirement,
        metadata=req.metadata,
    )
    return {
        "code": 200,
        "data": {
            "workflow_id": state.workflow_id,
            "status": state.status.value,
            "final_result": state.final_result,
            "node_results": [r.to_dict() for r in state.node_results],
            "error": state.error,
        },
    }


@router.post("/stream")
async def stream_workflow(req: RunWorkflowRequest):
    """SSE 流式执行工作流

    逐个节点推送事件, 支持实时进度展示。
    """
    from sse_starlette.sse import EventSourceResponse

    runner = get_workflow_runner()

    async def event_generator():
        async for event in runner.run_stream(
            flow_name=req.flow_name,
            requirement=req.requirement,
            metadata=req.metadata,
        ):
            yield event

    return EventSourceResponse(event_generator())


@router.get("/flows")
async def list_available_flows():
    """列出所有可用的工作流"""
    flows = list_flows()
    flow_details = []
    for name, cls_name in flows.items():
        flow = get_flow(name)
        if flow:
            graph = flow.get_graph_info()
            flow_details.append({
                "name": name,
                "class": cls_name,
                "description": flow.description,
                "node_count": len(graph["nodes"]),
                "edge_count": len(graph["edges"]),
                "nodes": [n["name"] for n in graph["nodes"]],
            })
    return {"code": 200, "data": {"flows": flow_details}}


@router.get("/{name}/graph")
async def get_workflow_graph(name: str):
    """获取工作流图结构"""
    flow = get_flow(name)
    if flow is None:
        return {"code": 404, "message": f"工作流不存在: {name}"}
    return {"code": 200, "data": flow.get_graph_info()}
