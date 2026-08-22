"""
Runtime v2 API — 统一 Agent 运行时入口

所有 API 请求必须通过此入口提交给 Runtime, 禁止直接调用 Agent。

路由:
    POST   /api/v2/runtime/tasks              提交任务
    GET    /api/v2/runtime/tasks/{task_id}     查询任务状态
    GET    /api/v2/runtime/tasks/{task_id}/result  等待任务结果
    DELETE /api/v2/runtime/tasks/{task_id}      取消任务
    GET    /api/v2/runtime/tasks               列出任务
    GET    /api/v2/runtime/stream/{task_id}     SSE 流式推送
    WS     /api/v2/runtime/ws/{task_id}         WebSocket 流式推送
    GET    /api/v2/runtime/stats                运行时统计
    GET    /api/v2/runtime/workers              Worker 状态
    GET    /api/v2/runtime/schedules            调度任务列表
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/runtime", tags=["Runtime v2"])


# ============================================================
# 请求模型
# ============================================================

class SubmitTaskRequest(BaseModel):
    """提交任务请求"""
    agent_name: str = Field(..., description="Agent 名称")
    action: str = Field("execute", description="Agent 动作")
    payload: Dict[str, Any] = Field(default_factory=dict, description="任务参数")
    priority: str = Field("normal", description="优先级: urgent/high/normal/low")
    timeout: int = Field(300, description="超时秒数")
    max_retries: int = Field(3, description="最大重试次数")
    session_id: Optional[str] = Field(None, description="会话 ID")
    user_id: Optional[int] = Field(None, description="用户 ID")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="扩展元数据")


class TaskResponse(BaseModel):
    """任务响应"""
    task_id: str
    status: str
    agent_name: str
    message: str = ""


# ============================================================
# API 端点
# ============================================================

@router.post("/tasks", response_model=TaskResponse)
async def submit_task(req: SubmitTaskRequest):
    """提交任务到 Runtime

    流程: API → Dispatcher → WorkerPool → AgentWorker → Agent.execute()
    """
    from app.runtime.v2 import get_dispatcher
    from app.runtime.v2.state import TaskRequest, TaskPriority

    # 优先级映射
    priority_map = {
        "urgent": TaskPriority.URGENT,
        "high": TaskPriority.HIGH,
        "normal": TaskPriority.NORMAL,
        "low": TaskPriority.LOW,
    }

    request = TaskRequest(
        agent_name=req.agent_name,
        action=req.action,
        payload=req.payload,
        priority=priority_map.get(req.priority, TaskPriority.NORMAL),
        timeout=req.timeout,
        max_retries=req.max_retries,
        session_id=req.session_id,
        user_id=req.user_id,
        metadata=req.metadata,
    )

    dispatcher = get_dispatcher()
    task_id = await dispatcher.submit(request)

    return TaskResponse(
        task_id=task_id,
        status="pending",
        agent_name=req.agent_name,
        message="任务已提交",
    )


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """查询任务状态"""
    from app.runtime.v2 import get_dispatcher

    dispatcher = get_dispatcher()
    state = await dispatcher.get_task(task_id)

    if state is None:
        return {"code": 404, "message": "任务不存在", "data": None}

    return {"code": 200, "message": "OK", "data": state.to_dict()}


@router.get("/tasks/{task_id}/result")
async def get_task_result(task_id: str, timeout: Optional[int] = None):
    """等待并获取任务结果"""
    from app.runtime.v2 import get_dispatcher

    dispatcher = get_dispatcher()
    result = await dispatcher.wait_for_result(
        task_id, timeout=float(timeout) if timeout else None
    )

    if result is None:
        return {"code": 408, "message": "任务结果超时或不存在", "data": None}

    return {"code": 200, "message": "OK", "data": result.to_dict()}


@router.delete("/tasks/{task_id}")
async def cancel_task(task_id: str):
    """取消任务"""
    from app.runtime.v2 import get_dispatcher

    dispatcher = get_dispatcher()
    success = await dispatcher.cancel(task_id)

    if success:
        return {"code": 200, "message": "任务已取消", "data": {"task_id": task_id}}
    return {"code": 400, "message": "取消失败 (任务不存在或已结束)", "data": None}


@router.get("/tasks")
async def list_tasks(
    status: Optional[str] = None,
    limit: int = 50,
):
    """列出任务"""
    from app.runtime.v2 import get_dispatcher
    from app.runtime.v2.state import TaskStatus

    dispatcher = get_dispatcher()
    task_status = TaskStatus(status) if status else None
    tasks = dispatcher.list_tasks(status=task_status, limit=limit)

    return {"code": 200, "message": "OK", "data": tasks}


# ============================================================
# SSE 流式推送
# ============================================================

@router.get("/stream/{task_id}")
async def stream_task(task_id: str):
    """SSE 流式推送任务事件

    事件格式:
        data: {"event": "start", "agent_name": "...", ...}
        data: {"event": "progress", "status": "running", ...}
        data: {"event": "end", "status": "success", ...}
        data: {"event": "done"}  ← 流结束信号
    """
    from app.runtime.v2 import get_publisher

    publisher = get_publisher()

    async def event_generator():
        async for event in publisher.sse_stream(task_id):
            yield {
                "event": event.get("event", "message"),
                "data": json.dumps(event, ensure_ascii=False, default=str),
            }

    return EventSourceResponse(event_generator())


# ============================================================
# WebSocket
# ============================================================

@router.websocket("/ws/{task_id}")
async def ws_task(websocket: WebSocket, task_id: str):
    """WebSocket 流式推送"""
    await websocket.accept()

    from app.runtime.v2 import get_publisher
    publisher = get_publisher()

    try:
        await publisher.serve_ws(task_id, websocket)
    except WebSocketDisconnect:
        logger.info(f"WebSocket 断开: {task_id}")
    except Exception as e:
        logger.error(f"WebSocket 异常: {task_id} | {e}")


# ============================================================
# 统计与监控
# ============================================================

@router.get("/stats")
async def get_stats():
    """运行时统计"""
    from app.runtime.v2 import (
        get_dispatcher, get_worker_pool,
        get_collector, get_publisher, get_scheduler,
    )

    return {
        "code": 200,
        "data": {
            "dispatcher": get_dispatcher().get_stats(),
            "worker_pool": get_worker_pool().get_stats(),
            "collector": get_collector().get_stats(),
            "publisher": get_publisher().get_stats(),
            "scheduler": get_scheduler().get_stats(),
        },
    }


@router.get("/workers")
async def get_workers():
    """Worker 状态"""
    from app.runtime.v2 import get_worker_pool
    return {
        "code": 200,
        "data": get_worker_pool().get_stats(),
    }


@router.get("/schedules")
async def get_schedules():
    """调度任务列表"""
    from app.runtime.v2 import get_scheduler
    return {
        "code": 200,
        "data": get_scheduler().list_schedules(),
    }
