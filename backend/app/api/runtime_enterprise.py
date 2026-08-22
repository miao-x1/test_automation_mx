"""
企业级 Agent Runtime API

提供:
    1. 任务提交 / 查询 / 取消 / 重试
    2. SSE 实时事件流
    3. WebSocket 双向通信
    4. Dispatcher / WorkerPool / Scheduler 统计

架构:
    API Layer → TaskDispatcher → WorkerPool → AgentWorker → Agent → ResponseCollector
"""
import asyncio
import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Query, Depends
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.core.logger import log
from app.api.auth import require_auth
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)


# ============================================================
# 请求 / 响应模型
# ============================================================

class SubmitTaskRequest(BaseModel):
    """提交任务请求"""
    agent_name: str = Field(..., description="目标 Agent 名称")
    action: str = Field("execute", description="调用的 action")
    payload: Dict[str, Any] = Field(default_factory=dict, description="任务参数")
    priority: str = Field("normal", description="优先级: low/normal/high/urgent")
    timeout_seconds: int = Field(300, description="超时时间(秒)")
    max_retries: int = Field(3, description="最大重试次数")
    task_type: str = Field("agent", description="任务类型: agent/flow")
    wait: bool = Field(False, description="是否同步等待结果")


class ScheduleTaskRequest(BaseModel):
    """调度任务请求"""
    agent_name: str = Field(..., description="目标 Agent 名称")
    action: str = Field("execute", description="调用的 action")
    payload: Dict[str, Any] = Field(default_factory=dict, description="任务参数")
    delay_seconds: float = Field(0, description="延迟秒数(0=立即)")
    cron_expression: str = Field("", description="cron 表达式(定时)")
    max_runs: Optional[int] = Field(None, description="最大执行次数(None=无限)")


class TaskResponse(BaseModel):
    """任务响应"""
    code: int = 0
    message: str = "success"
    data: Optional[Any] = None


# ============================================================
# 任务管理接口
# ============================================================

@router.post("/tasks", summary="提交任务", response_model=TaskResponse)
async def submit_task(
    req: SubmitTaskRequest,
    user: User = Depends(require_auth),
):
    """提交任务到 TaskDispatcher

    - `wait=false` (默认): 立即返回 task_id,异步执行
    - `wait=true`: 同步等待结果后返回
    """
    from app.runtime.enterprise import (
        get_task_dispatcher, TaskRequest, TaskPriority,
    )

    try:
        dispatcher = get_task_dispatcher()
        priority = TaskPriority(req.priority)
        request = TaskRequest(
            agent_name=req.agent_name,
            action=req.action,
            payload=req.payload,
            priority=priority,
            user_id=user.id,
            timeout_seconds=req.timeout_seconds,
            max_retries=req.max_retries,
            task_type=req.task_type,
        )

        if req.wait:
            # 同步等待
            result = await dispatcher.submit_and_wait(request)
            return TaskResponse(data=result.to_dict())
        else:
            # 异步提交
            task_id = await dispatcher.submit(request)
            return TaskResponse(data={"task_id": task_id})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"提交任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"提交失败: {e}")


@router.get("/tasks/{task_id}", summary="查询任务状态")
async def get_task_status(
    task_id: str,
    user: User = Depends(require_auth),
):
    """查询任务状态"""
    from app.runtime.enterprise import get_task_dispatcher

    dispatcher = get_task_dispatcher()
    state = await dispatcher.get_status(task_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    return {"code": 0, "data": state.to_dict()}


@router.get("/tasks", summary="列出任务")
async def list_tasks(
    status: Optional[str] = Query(None, description="过滤状态"),
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(require_auth),
):
    """列出任务"""
    from app.runtime.enterprise import get_task_dispatcher, TaskStatus

    dispatcher = get_task_dispatcher()
    task_status = TaskStatus(status) if status else None
    tasks = await dispatcher.list_tasks(status=task_status, limit=limit)
    return {"code": 0, "data": [t.to_dict() for t in tasks]}


@router.get("/tasks/{task_id}/result", summary="获取任务结果")
async def get_task_result(
    task_id: str,
    user: User = Depends(require_auth),
):
    """获取已完成任务的结果"""
    from app.runtime.enterprise import get_task_dispatcher

    dispatcher = get_task_dispatcher()
    result = await dispatcher.get_result(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"结果不存在: {task_id}")
    return {"code": 0, "data": result.to_dict()}


@router.post("/tasks/{task_id}/cancel", summary="取消任务")
async def cancel_task(
    task_id: str,
    user: User = Depends(require_auth),
):
    """取消任务"""
    from app.runtime.enterprise import get_task_dispatcher

    dispatcher = get_task_dispatcher()
    success = await dispatcher.cancel(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="任务不存在或已终态")
    return {"code": 0, "message": "已取消"}


@router.post("/tasks/{task_id}/retry", summary="重试任务")
async def retry_task(
    task_id: str,
    user: User = Depends(require_auth),
):
    """重试失败的任务"""
    from app.runtime.enterprise import get_task_dispatcher

    dispatcher = get_task_dispatcher()
    success = await dispatcher.retry(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="任务不可重试")
    return {"code": 0, "message": "重试已启动"}


# ============================================================
# SSE 实时事件流
# ============================================================

@router.get("/stream/{task_id}", summary="SSE 事件流")
async def sse_stream(
    task_id: str,
    # user: User = Depends(require_auth),  # SSE 不方便带 token,暂不鉴权
):
    """SSE 实时事件流

    前端使用 EventSource 订阅:
        const es = new EventSource('/api/runtime/stream/task_xxx');
        es.onmessage = (e) => console.log(JSON.parse(e.data));
        es.addEventListener('done', () => es.close());

    事件类型:
        - start:    任务开始
        - progress:  进度更新
        - end:       任务完成
        - error:     错误
        - done:      流结束 (信号)
        - ping:      心跳保活
    """
    from app.runtime.enterprise import get_stream_publisher

    publisher = get_stream_publisher()

    async def event_generator():
        try:
            async for event in publisher.sse_stream(task_id):
                # SSE 格式: event + data
                event_type = event.get("event", "message")
                yield {
                    "event": event_type,
                    "data": json.dumps(event, ensure_ascii=False, default=str),
                }
                if event_type == "done":
                    break
        except asyncio.CancelledError:
            logger.info(f"SSE 流被取消: {task_id}")
        except Exception as e:
            logger.error(f"SSE 流异常: {task_id} | {e}", exc_info=True)
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e), "task_id": task_id}),
            }

    return EventSourceResponse(event_generator())


# ============================================================
# WebSocket 双向通信
# ============================================================

@router.websocket("/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    """WebSocket 双向通信

    前端使用:
        const ws = new WebSocket('ws://localhost:8000/api/runtime/ws/task_xxx');
        ws.onmessage = (e) => console.log(JSON.parse(e.data));
        ws.onclose = () => console.log('连接关闭');

    客户端可发送:
        - "ping": 心跳,服务端返回 "pong"
        - "cancel": 取消订阅
    """
    from app.runtime.enterprise import get_stream_publisher

    await websocket.accept()
    publisher = get_stream_publisher()

    await publisher.add_ws_client(task_id, websocket)
    logger.info(f"WebSocket 连接 | task_id={task_id}")

    try:
        # 启动服务循环 (接收客户端消息)
        await publisher.serve_ws(task_id, websocket)
    except WebSocketDisconnect:
        logger.info(f"WebSocket 断开 | task_id={task_id}")
    except Exception as e:
        logger.error(f"WebSocket 异常: {task_id} | {e}", exc_info=True)
    finally:
        await publisher.remove_ws_client(task_id, websocket)


# ============================================================
# 调度接口
# ============================================================

@router.post("/schedule", summary="调度任务")
async def schedule_task(
    req: ScheduleTaskRequest,
    user: User = Depends(require_auth),
):
    """调度任务 (延迟 / 定时)"""
    from app.runtime.enterprise import (
        get_task_scheduler, get_task_dispatcher, TaskRequest,
    )

    try:
        dispatcher = get_task_dispatcher()
        scheduler = get_task_scheduler(dispatcher=dispatcher)

        request = TaskRequest(
            agent_name=req.agent_name,
            action=req.action,
            payload=req.payload,
            user_id=user.id,
        )

        if req.cron_expression:
            sched_id = await scheduler.schedule_cron(
                request=request,
                cron_expression=req.cron_expression,
                max_runs=req.max_runs,
            )
            return {"code": 0, "data": {"schedule_id": sched_id, "type": "cron"}}
        else:
            sched_id = await scheduler.schedule(
                request=request,
                delay_seconds=req.delay_seconds,
            )
            return {"code": 0, "data": {"schedule_id": sched_id, "type": "delayed"}}
    except Exception as e:
        logger.error(f"调度失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/schedules", summary="列出调度任务")
async def list_schedules(
    enabled_only: bool = Query(False),
    user: User = Depends(require_auth),
):
    """列出所有调度任务"""
    from app.runtime.enterprise import get_task_scheduler

    scheduler = get_task_scheduler()
    schedules = await scheduler.list_schedules(enabled_only=enabled_only)
    return {"code": 0, "data": [s.to_dict() for s in schedules]}


@router.delete("/schedules/{schedule_id}", summary="取消调度")
async def cancel_schedule(
    schedule_id: str,
    user: User = Depends(require_auth),
):
    """取消调度任务"""
    from app.runtime.enterprise import get_task_scheduler

    scheduler = get_task_scheduler()
    success = await scheduler.cancel(schedule_id)
    if not success:
        raise HTTPException(status_code=404, detail="调度任务不存在")
    return {"code": 0, "message": "已取消"}


# ============================================================
# 统计接口
# ============================================================

@router.get("/stats", summary="Runtime 统计")
async def get_runtime_stats(
    user: User = Depends(require_auth),
):
    """获取 Runtime 全部统计信息"""
    from app.runtime.enterprise import (
        get_task_dispatcher, get_worker_pool,
        get_response_collector, get_stream_publisher,
        get_task_scheduler,
    )

    dispatcher = get_task_dispatcher()
    pool = get_worker_pool()
    collector = get_response_collector()
    publisher = get_stream_publisher()
    scheduler = get_task_scheduler()

    return {
        "code": 0,
        "data": {
            "dispatcher": await dispatcher.get_stats(),
            "worker_pool": await pool.get_stats(),
            "collector": await collector.get_stats(),
            "stream_publisher": await publisher.get_stats(),
            "scheduler": await scheduler.get_stats(),
        },
    }


@router.get("/workers", summary="Worker 统计")
async def get_worker_stats(
    user: User = Depends(require_auth),
):
    """获取 WorkerPool 统计"""
    from app.runtime.enterprise import get_worker_pool

    pool = get_worker_pool()
    return {"code": 0, "data": await pool.get_stats()}


@router.get("/health", summary="Runtime 健康检查")
async def runtime_health():
    """Runtime 健康检查 (无需鉴权)"""
    from app.runtime.enterprise import get_task_dispatcher

    try:
        dispatcher = get_task_dispatcher()
        stats = await dispatcher.get_stats()
        return {
            "status": "healthy",
            "mode": stats["mode"],
            "started": stats["started"],
            "queue_size": stats["queue_size"],
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


# ============================================================
# 历史任务查询
# ============================================================

@router.get("/history", summary="查询历史任务")
async def query_history(
    status: Optional[str] = Query(None, description="过滤状态"),
    agent_name: Optional[str] = Query(None, description="过滤 Agent"),
    hours: int = Query(24, ge=1, le=720, description="查询最近 N 小时"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(require_auth),
):
    """查询历史任务 (从数据库)

    支持按状态、Agent、时间范围过滤。
    """
    from app.services.runtime_persistence import get_runtime_persistence
    from datetime import datetime, timedelta

    persistence = get_runtime_persistence()
    if not persistence.enabled:
        raise HTTPException(status_code=503, detail="持久化服务未启用")

    start_time = datetime.now() - timedelta(hours=hours)
    tasks, total = persistence.query_history(
        status=status,
        agent_name=agent_name,
        user_id=user.id,
        start_time=start_time,
        limit=limit,
        offset=offset,
    )
    return {
        "code": 0,
        "data": {
            "tasks": tasks,
            "total": total,
            "limit": limit,
            "offset": offset,
        },
    }


@router.get("/history/{task_id}", summary="查询历史任务详情")
async def get_history_task(
    task_id: str,
    user: User = Depends(require_auth),
):
    """按 task_id 查询历史任务详情"""
    from app.services.runtime_persistence import get_runtime_persistence

    persistence = get_runtime_persistence()
    if not persistence.enabled:
        raise HTTPException(status_code=503, detail="持久化服务未启用")

    task = persistence.get_task_by_id(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    return {"code": 0, "data": task}


# ============================================================
# 指标统计
# ============================================================

@router.get("/metrics", summary="Runtime 指标统计")
async def get_runtime_metrics(
    hours: int = Query(24, ge=1, le=720, description="统计最近 N 小时"),
    agent_name: Optional[str] = Query(None, description="按 Agent 过滤"),
    user: User = Depends(require_auth),
):
    """获取 Runtime 指标统计

    返回:
        - total: 总任务数
        - by_status: 按状态分组
        - success_rate: 成功率
        - avg_duration_ms: 平均耗时
        - p50_duration_ms: 中位数耗时
        - p95_duration_ms: 95 分位耗时
        - throughput: 吞吐量 (任务/分钟)
        - by_agent: 按 Agent 分组
        - hourly: 按小时分组的趋势
    """
    from app.services.runtime_persistence import get_runtime_persistence

    persistence = get_runtime_persistence()
    if not persistence.enabled:
        raise HTTPException(status_code=503, detail="持久化服务未启用")

    metrics = persistence.get_metrics(hours=hours, agent_name=agent_name)
    return {"code": 0, "data": metrics}
