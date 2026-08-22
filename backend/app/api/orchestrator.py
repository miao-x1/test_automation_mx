"""
TaskOrchestrator API

统一任务编排入口。所有业务流程必须经过 TaskOrchestrator。
禁止 API 层直接调用 Agent。

端点：
  GET  /orchestrator/flows              - 列出所有可用流程
  GET  /orchestrator/flows/{name}       - 获取流程详情
  POST /orchestrator/execute/{flow}     - 执行流程（SSE流式返回）
  POST /orchestrator/execute/{flow}/sync - 执行流程（同步返回）
  GET  /orchestrator/task/{task_id}     - 查询任务状态

  统一测试生成入口：
  POST /orchestrator/unified/generate   - 统一生成（SSE流式，支持文本/图片/文件/URL组合输入）
  POST /orchestrator/unified/precheck   - 图片URL预检测（检查图片中是否有URL）
  GET  /orchestrator/unified/options     - 获取可选项配置

  Agent 执行监控（时间线）：
  GET  /orchestrator/timeline/{task_id}       - 获取执行时间线（Dify风格）
  GET  /orchestrator/timeline/{task_id}/failed - 获取失败节点列表
  GET  /orchestrator/node/{log_id}            - 获取单个节点详情
  GET  /orchestrator/stats                    - 获取执行统计
"""
import asyncio
import json
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Body
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.orchestrator import get_task_orchestrator
from app.core.logger import log
from app.schemas.response import Response

router = APIRouter(prefix="/orchestrator", tags=["任务编排"])


# ==================== 请求模型 ====================

class ExecuteRequest(BaseModel):
    """流程执行请求"""
    payload: dict = {}
    task_id: Optional[int] = None
    session_id: Optional[int] = None


# ==================== 端点 ====================

@router.get("/flows")
async def list_flows():
    """列出所有可用流程"""
    orchestrator = get_task_orchestrator()
    flows = orchestrator.list_flows()
    return Response.success(data=flows, message=f"共 {len(flows)} 个流程")


@router.get("/flows/{flow_name}")
async def get_flow_detail(flow_name: str):
    """获取流程详情"""
    orchestrator = get_task_orchestrator()
    flow = orchestrator.get_flow(flow_name)
    if flow is None:
        return Response.error(message=f"流程 '{flow_name}' 不存在")
    return Response.success(data={
        "flow_name": flow.flow_name,
        "description": flow.description,
        "steps": [
            {
                "step_name": s.step_name,
                "agent_name": s.agent_name,
                "action": s.action,
                "description": s.description,
                "required": s.required,
                "on_failure": s.on_failure,
                "input_from": s.input_from,
            }
            for s in flow.steps
        ],
    })


@router.post("/execute/{flow_name}")
async def execute_flow(flow_name: str, req: ExecuteRequest):
    """执行流程（SSE流式返回）

    返回 Server-Sent Events 流，每个事件包含步骤进度。
    """
    orchestrator = get_task_orchestrator()

    if not orchestrator.is_flow_exists(flow_name):
        raise HTTPException(
            status_code=404,
            detail=f"流程 '{flow_name}' 不存在。可用: {[f for f in orchestrator.list_flows()]}",
        )

    async def event_stream():
        """SSE 事件流"""
        try:
            async for event in orchestrator.execute(
                flow_name=flow_name,
                payload=req.payload,
                task_id=req.task_id,
                session_id=req.session_id,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
        except Exception as e:
            log.error(f"Orchestrator API | 执行异常: {e}", exc_info=True)
            error_event = {
                "event": "flow_failed",
                "flow_name": flow_name,
                "error": str(e),
            }
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'event': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/execute/{flow_name}/sync")
async def execute_flow_sync(flow_name: str, req: ExecuteRequest):
    """执行流程（同步返回结果）"""
    orchestrator = get_task_orchestrator()

    if not orchestrator.is_flow_exists(flow_name):
        raise HTTPException(
            status_code=404,
            detail=f"流程 '{flow_name}' 不存在",
        )

    result = orchestrator.execute_sync(
        flow_name=flow_name,
        payload=req.payload,
        task_id=req.task_id,
        session_id=req.session_id,
    )

    return Response.success(data=result, message=f"流程 '{flow_name}' 执行完成")


@router.get("/task/{task_id}")
async def get_task_status(task_id: int):
    """查询任务状态"""
    from app.db.database import SessionLocal
    from app.models.task_state import TaskState

    db = SessionLocal()
    try:
        state = (
            db.query(TaskState)
            .filter(TaskState.task_id == task_id)
            .order_by(TaskState.created_at.desc())
            .first()
        )
        if state is None:
            return Response.error(message=f"任务 {task_id} 不存在")
        return Response.success(data=state.to_dict())
    finally:
        db.close()


@router.post("/reload")
async def reload_flows():
    """重新加载流程定义（运行时刷新）"""
    orchestrator = get_task_orchestrator()
    orchestrator.reload()
    flows = orchestrator.list_flows()
    return Response.success(
        data={"flow_count": len(flows)},
        message=f"重新加载完成，共 {len(flows)} 个流程",
    )


# ==================== 统一测试生成入口 ====================


class UnifiedGenerateRequest(BaseModel):
    """统一生成请求

    用户可自由组合输入方式：
    - requirement: 需求文本
    - image_paths: 截图路径列表
    - target_url: 目标URL（用户手动输入）
    - 文件上传通过 /unified/upload 端点处理

    可选项：
    - enable_knowledge_graph: 启用知识图谱推理（默认 True）
    - enable_human_review: 启用人工审查（默认 False）
    - enable_reuse_check: 启用复用检查（默认 True）
    - test_type: 测试类型（空则自动识别）
    """
    requirement: str = ""
    image_paths: list[str] = []
    target_url: str = ""
    enable_knowledge_graph: bool = True
    enable_human_review: bool = False
    enable_reuse_check: bool = True
    test_type: str = ""
    task_id: Optional[int] = None
    session_id: Optional[int] = None


@router.get("/unified/options")
async def get_unified_options():
    """获取统一生成的可选项配置

    前端用此渲染选项面板。
    """
    return Response.success(data={
        "input_modes": [
            {"key": "requirement", "label": "需求文本", "type": "textarea"},
            {"key": "image_paths", "label": "上传截图", "type": "image_upload"},
            {"key": "target_url", "label": "目标URL", "type": "text"},
        ],
        "options": [
            {
                "key": "enable_knowledge_graph",
                "label": "知识图谱推理",
                "description": "启用页面关联+图谱路径+流程检测，适合复杂Web系统",
                "default": True,
            },
            {
                "key": "enable_human_review",
                "label": "人工审查用例",
                "description": "生成用例后暂停，等待人工确认再生成脚本",
                "default": False,
            },
            {
                "key": "enable_reuse_check",
                "label": "复用检查",
                "description": "检查是否有相似的历史脚本可直接复用",
                "default": True,
            },
        ],
        "test_types": [
            {"value": "", "label": "自动识别"},
            {"value": "web", "label": "Web 测试"},
            {"value": "api", "label": "API 测试"},
            {"value": "android", "label": "Android 测试"},
            {"value": "performance", "label": "性能测试"},
        ],
    })


class PrecheckRequest(BaseModel):
    """图片URL预检测请求"""
    image_paths: list[str] = []
    requirement: str = ""
    target_url: str = ""


@router.post("/unified/precheck")
async def precheck_images(req: PrecheckRequest):
    """图片URL预检测

    检查图片中是否检测到URL：
    - 有URL → 自动使用图片中的URL
    - 无URL但有用户输入URL → 使用用户URL
    - 无URL且无用户输入 → 返回 warning，前端弹窗提示用户

    返回：
    {
        "has_url": bool,
        "url_source": "image" | "user" | "none",
        "target_url": str,
        "warning": str | None,
        "elements_detected": list,
    }
    """
    detected_url = ""
    elements = []

    if req.image_paths:
        from app.runtime.agent_factory import AgentFactory

        try:
            agent = AgentFactory.create("element_agent")
            result = agent.analyze({"image_paths": req.image_paths})
            detected_url = result.get("page_url", "")
            elements = result.get("elements", [])
        except Exception as e:
            log.warning(f"precheck | 元素识别失败: {e}")

    # URL 优先级：用户输入 > 图片检测
    if req.target_url:
        final_url = req.target_url
        url_source = "user"
    elif detected_url:
        final_url = detected_url
        url_source = "image"
    else:
        final_url = ""
        url_source = "none"

    warning = None
    if not final_url and req.image_paths:
        warning = (
            "未检测到页面URL。当前仅有DOM元素信息，"
            "RAG检索将被跳过（无URL可能导致检索不准确）。"
            "您可以：1. 手动输入URL后继续；2. 仅基于元素生成脚本；3. 取消"
        )

    return Response.success(data={
        "has_url": bool(final_url),
        "url_source": url_source,
        "target_url": final_url,
        "elements_detected": elements,
        "element_count": len(elements),
        "warning": warning,
    })


@router.post("/unified/generate")
async def unified_generate(req: UnifiedGenerateRequest):
    """统一测试生成入口（SSE流式返回）

    支持的输入组合：
    - 纯文本需求
    - 纯图片
    - 文本 + 图片
    - 文本 + URL
    - 文本 + 图片 + URL

    SSE 事件类型：
    - step_start / step_success / step_skipped / step_failed
    - degradation: 降级提示（前端弹窗）
    - reuse_hit: 复用命中（前端弹窗确认）
    - human_feedback_required: 需要人工审查（前端弹窗）
    - flow_success / flow_failed / done
    """
    orchestrator = get_task_orchestrator()

    # 构建 payload
    payload = {
        "requirement": req.requirement,
        "image_paths": req.image_paths,
        "target_url": req.target_url,
        "enable_knowledge_graph": req.enable_knowledge_graph,
        "enable_human_review": req.enable_human_review,
        "enable_reuse_check": req.enable_reuse_check,
        "test_type": req.test_type,
    }

    # 如果有图片但没有URL，先检测图片中的URL
    if req.image_paths and not req.target_url:
        try:
            agent_result = None
            from app.runtime.agent_factory import AgentFactory
            agent = AgentFactory.create("element_agent")
            agent_result = agent.analyze({"image_paths": req.image_paths})
            detected_url = agent_result.get("page_url", "")
            if detected_url:
                payload["target_url"] = detected_url
                log.info(f"unified_generate | 图片中检测到URL: {detected_url}")
        except Exception as e:
            log.warning(f"unified_generate | 图片URL检测失败: {e}")

    # 如果既没有需求文本也没有图片，报错
    if not req.requirement and not req.image_paths:
        return Response.error(
            message="请至少输入需求文本或上传图片"
        )

    async def event_stream():
        """SSE 事件流"""
        try:
            async for event in orchestrator.execute(
                flow_name="unified_test_flow",
                payload=payload,
                task_id=req.task_id,
                session_id=req.session_id,
            ):
                event_type = event.get("event", "")

                # 检测降级信息并推送弹窗事件
                if event_type == "step_success":
                    output = event.get("output", {})
                    if isinstance(output, dict):
                        degr = output.get("degradation_info")
                        if degr and degr.get("level", 1) > 1:
                            yield f"data: {json.dumps({'event': 'degradation', 'level': degr.get('level'), 'source': degr.get('source'), 'message': degr.get('message'), 'action_required': degr.get('action_required', False)}, ensure_ascii=False)}\n\n"

                        # 检测复用命中
                        reuse = output.get("reuse_info")
                        if reuse and reuse.get("reuse"):
                            sim = reuse.get("similarity", 0)
                            sname = reuse.get("script_name", "")
                            reuse_event = {
                                "event": "reuse_hit",
                                "similarity": sim,
                                "script_name": sname,
                                "message": f"检测到相似度 {sim:.2%} 的历史脚本，是否复用？",
                            }
                            yield f"data: {json.dumps(reuse_event, ensure_ascii=False)}\n\n"

                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

            yield f"data: {json.dumps({'event': 'done'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            log.error(f"unified_generate | 执行异常: {e}", exc_info=True)
            yield f"data: {json.dumps({'event': 'flow_failed', 'error': str(e)}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'event': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/unified/upload")
async def unified_upload(
    file: UploadFile = File(...),
):
    """上传文件到统一生成入口

    支持图片（png/jpg）和文档（pdf/docx/txt）。
    返回文件路径，前端将其加入 image_paths 或后续处理。
    """
    import os
    from pathlib import Path
    from app.core.config import settings

    upload_dir = Path(settings.UPLOAD_DIR) / "unified"
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_path = upload_dir / file.filename
    with open(file_path, "wb") as buffer:
        import shutil
        shutil.copyfileobj(file.file, buffer)

    file_size = os.path.getsize(file_path)
    mime_type = file.content_type or ""

    return Response.success(data={
        "file_path": str(file_path),
        "file_name": file.filename,
        "file_size": file_size,
        "mime_type": mime_type,
        "is_image": mime_type.startswith("image/"),
    })


# ==================== Agent 执行监控（时间线） ====================


@router.get("/timeline/{task_id}")
async def get_execution_timeline(task_id: str):
    """获取执行时间线（Dify 风格）

    返回完整的执行时间线，包含每个步骤的：
    - step_index / step_name / agent_name
    - status (running/success/error/skipped)
    - start_time / end_time / duration_ms
    - input / output / error
    - tokens_used / model_name

    前端用此数据渲染类似 Dify 工作流执行展示的时间线。
    """
    from app.services.monitor import get_execution_monitor

    monitor = get_execution_monitor()
    timeline = monitor.get_timeline(task_id)
    return Response.success(data=timeline)


@router.get("/timeline/{task_id}/failed")
async def get_failed_nodes(task_id: str):
    """获取失败节点列表

    仅返回 status='error' 的节点，包含错误详情。
    用于前端快速定位失败节点。
    """
    from app.services.monitor import get_execution_monitor

    monitor = get_execution_monitor()
    failed = monitor.get_failed_nodes(task_id)
    return Response.success(
        data={"task_id": task_id, "failed_count": len(failed), "nodes": failed},
        message=f"共 {len(failed)} 个失败节点" if failed else "无失败节点",
    )


@router.get("/node/{log_id}")
async def get_node_detail(log_id: int):
    """获取单个执行节点详情

    用于前端点击时间线节点时展开详情。
    包含完整的 input/output/error 信息。
    """
    from app.services.monitor import get_execution_monitor

    monitor = get_execution_monitor()
    detail = monitor.get_node_detail(log_id)
    if detail is None:
        return Response.error(message=f"节点 {log_id} 不存在")
    return Response.success(data=detail)


@router.get("/stats")
async def get_execution_stats(
    task_id: Optional[str] = Query(None, description="按任务ID过滤"),
    session_id: Optional[str] = Query(None, description="按会话ID过滤"),
):
    """获取执行统计

    返回聚合统计：
    - total / success / failed / running / skipped
    - success_rate
    - total_duration_s / total_tokens
    - by_agent（按 Agent 分组统计）
    """
    from app.services.monitor import get_execution_monitor

    monitor = get_execution_monitor()
    stats = monitor.get_stats(task_id=task_id or "", session_id=session_id or "")
    return Response.success(data=stats)
