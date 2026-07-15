"""
GraphFlow API - 动态工作流图管理端点

提供：
- POST /graphflow/run         执行工作流
- POST /graphflow/stream      SSE 流式执行
- GET  /graphflow/graph       获取图结构
- POST /graphflow/nodes        添加节点
- DELETE /graphflow/nodes/{name}  删除节点
- POST /graphflow/edges        添加边
- DELETE /graphflow/edges     删除边
- POST /graphflow/feedback     提交人工反馈
- GET  /graphflow/nodes/list   列出所有节点

使用 DiGraphBuilder + GraphFlow 实现动态工作流编排。
"""
import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.runtime.graph_flow_manager import (
    GraphFlowManager,
    NodeSpec,
    get_graph_flow_manager,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/graphflow", tags=["GraphFlow 工作流"])


# ------------------------------------------------------------------ #
#  请求/响应模型                                                       #
# ------------------------------------------------------------------ #

class RunRequest(BaseModel):
    """执行工作流请求"""
    task: str = Field(..., description="任务描述")
    task_id: str = Field("", description="任务ID")
    session_key: str = Field("default", description="会话标识")
    context: Optional[Dict[str, Any]] = Field(None, description="上下文数据")


class AddNodeRequest(BaseModel):
    """添加节点请求"""
    name: str = Field(..., description="节点名称")
    step: str = Field("", description="步骤名称")
    description: str = Field("", description="节点描述")
    is_human: bool = Field(False, description="是否人工节点")
    model_alias: str = Field("", description="模型别名")
    capabilities: List[str] = Field(default_factory=list, description="能力标签")
    insert_after: str = Field("", description="在指定节点之后插入")


class AddEdgeRequest(BaseModel):
    """添加边请求"""
    source: str = Field(..., description="源节点")
    target: str = Field(..., description="目标节点")


class RemoveEdgeRequest(BaseModel):
    """删除边请求"""
    source: str = Field(...)
    target: str = Field(...)


class FeedbackRequest(BaseModel):
    """人工反馈请求"""
    feedback_id: str = Field(..., description="反馈ID")
    feedback: Dict[str, Any] = Field(..., description="反馈内容")


# ------------------------------------------------------------------ #
#  端点                                                                #
# ------------------------------------------------------------------ #

@router.post("/run")
async def run_graphflow(request: RunRequest) -> Dict[str, Any]:
    """
    执行 GraphFlow 工作流

    完整执行所有节点，返回最终结果。
    """
    manager = get_graph_flow_manager()
    result = await manager.run(
        task=request.task,
        task_id=request.task_id,
        session_key=request.session_key,
        context=request.context,
    )
    return result


@router.post("/stream")
async def stream_graphflow(request: RunRequest):
    """
    SSE 流式执行 GraphFlow 工作流

    返回 Server-Sent Events 流，每个节点输出一个事件。
    """
    from fastapi.responses import StreamingResponse

    manager = get_graph_flow_manager()

    async def event_generator():
        async for event in manager.run_stream(
            task=request.task,
            task_id=request.task_id,
            session_key=request.session_key,
            context=request.context,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )


@router.get("/graph")
async def get_graph() -> Dict[str, Any]:
    """获取当前图结构"""
    manager = get_graph_flow_manager()
    return manager.get_graph_info()


@router.get("/nodes/list")
async def list_nodes() -> List[Dict[str, Any]]:
    """列出所有节点"""
    manager = get_graph_flow_manager()
    return manager.list_nodes()


@router.get("/edges/list")
async def list_edges() -> List[Dict[str, str]]:
    """列出所有边"""
    manager = get_graph_flow_manager()
    return manager.list_edges()


@router.post("/nodes")
async def add_node(request: AddNodeRequest) -> Dict[str, Any]:
    """
    添加节点

    如果指定了 insert_after，则在该节点之后插入（自动处理边）。
    否则只是添加节点，需要单独调用 add_edge 连接。
    """
    manager = get_graph_flow_manager()
    spec = NodeSpec(
        name=request.name,
        step=request.step or request.name.lower(),
        description=request.description,
        is_human=request.is_human,
        model_alias=request.model_alias,
        capabilities=request.capabilities,
    )

    if request.insert_after:
        manager.add_node_after(request.insert_after, spec)
    else:
        manager.add_node(spec)

    return {"status": "ok", "node": request.name, "graph": manager.get_graph_info()}


@router.delete("/nodes/{name}")
async def remove_node(name: str) -> Dict[str, Any]:
    """删除节点"""
    manager = get_graph_flow_manager()
    manager.remove_node(name)
    return {"status": "ok", "removed": name, "graph": manager.get_graph_info()}


@router.post("/edges")
async def add_edge(request: AddEdgeRequest) -> Dict[str, Any]:
    """添加边"""
    manager = get_graph_flow_manager()
    manager.add_edge(request.source, request.target)
    return {"status": "ok", "edge": f"{request.source} → {request.target}"}


@router.delete("/edges")
async def remove_edge(source: str, target: str) -> Dict[str, Any]:
    """删除边"""
    manager = get_graph_flow_manager()
    manager.remove_edge(source, target)
    return {"status": "ok", "removed": f"{source} → {target}"}


@router.post("/feedback")
async def submit_feedback(request: FeedbackRequest) -> Dict[str, Any]:
    """提交人工反馈"""
    manager = get_graph_flow_manager()
    success = manager.submit_human_feedback(request.feedback_id, request.feedback)
    if not success:
        raise HTTPException(status_code=404, detail="No pending feedback request found")
    return {"status": "ok", "feedback_id": request.feedback_id}


@router.get("/presets")
async def get_presets() -> Dict[str, Any]:
    """获取预置可扩展节点模板"""
    return {
        "security_review": {
            "name": "SecurityReview",
            "step": "security_review",
            "description": "安全审查节点",
            "model_alias": "claude",
            "capabilities": ["security", "review"],
            "insert_after": "CaseReview",
        },
        "performance_review": {
            "name": "PerformanceReview",
            "step": "performance_review",
            "description": "性能审查节点",
            "model_alias": "deepseek",
            "capabilities": ["performance", "review"],
            "insert_after": "CaseReview",
        },
        "accessibility_review": {
            "name": "AccessibilityReview",
            "step": "accessibility_review",
            "description": "无障碍审查节点",
            "model_alias": "qwen",
            "capabilities": ["accessibility", "review"],
            "insert_after": "CaseReview",
        },
    }
