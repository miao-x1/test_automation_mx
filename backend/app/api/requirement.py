"""
需求驱动测试 API路由

数据隔离：所有查询自动过滤 user_id
"""
import json
import os
import uuid
from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form, Depends
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from app.services.requirement_flow_service import RequirementFlowService
from app.runtime.orchestrator import get_orchestrator
from app.db.database import SessionLocal, get_db
from app.models.requirement_task import RequirementTask, RequirementStatus
from app.core.config import settings
from app.core.logger import log
from app.schemas.response import Response
from app.core.auth import require_auth
from app.models.user import User
from fastapi.responses import FileResponse

router = APIRouter()


async def sse_wrapper(orchestrator_events):
    """将 Orchestrator 的 dict 事件转换为 SSE 格式

    Orchestrator.execute() 产出 plain dict，EventSourceResponse 需要
    {event, data} 形式，这里做一次包装。
    """
    async for event in orchestrator_events:
        yield {
            "event": event.get("event", "message"),
            "data": json.dumps(event, ensure_ascii=False, default=str),
        }


class CreateRequest(BaseModel):
    """需求创建请求"""
    requirement: str
    additional_info: Optional[str] = None
    image_paths: Optional[list[str]] = None
    script_format: Optional[str] = "playwright"
    task_type: Optional[str] = None
    test_scope: Optional[dict] = None


class GenerateRequest(BaseModel):
    """需求生成请求"""
    requirement: str
    feedback_context: Optional[str] = None
    additional_info: Optional[str] = None
    image_paths: Optional[list[str]] = None
    script_format: Optional[str] = "playwright"


class MultiModalGenerateRequest(BaseModel):
    """多模态需求生成请求"""
    text: Optional[str] = None
    images: Optional[list[str]] = None
    urls: Optional[list[str]] = None
    script_content: Optional[str] = None
    script_language: Optional[str] = "python"
    page_ids: Optional[list[int]] = None
    script_format: Optional[str] = "playwright"


class AnalyzeWithFeedbackRequest(BaseModel):
    """带反馈的分析请求"""
    feedback_context: Optional[str] = None


class ClassifyRequest(BaseModel):
    """测试类型分类请求"""
    requirement: str = ""
    urls: Optional[List[str]] = None
    images: Optional[List[str]] = None
    script_content: Optional[str] = None
    script_language: Optional[str] = None
    swagger_content: Optional[str] = None


@router.post("/classify", summary="AI自动判断测试类型")
async def classify_test_type(
    request: ClassifyRequest,
    user: User = Depends(require_auth),
):
    """AI自动判断测试类型

    用户输入需求文本，AI自动判断：
    - WEB（Web UI 测试）
    - API（接口测试）
    - ANDROID（移动端测试）
    - PERFORMANCE（性能测试）

    返回 test_type, platform, framework, confidence, reason

    用户可以在前端调整 AI 推荐的类型。
    """
    if not request.requirement.strip() and not request.urls and not request.images:
        raise HTTPException(status_code=400, detail="需求内容不能为空")

    from app.runtime.enterprise import get_task_dispatcher, TaskRequest

    try:
        # 通过 TaskDispatcher 提交 (企业级 Runtime)
        dispatcher = get_task_dispatcher()
        task_id = await dispatcher.submit(TaskRequest(
            agent_name="test_type_classifier",
            action="execute",
            payload={
                "requirement": request.requirement,
                "urls": request.urls,
                "images": request.images,
                "script_content": request.script_content,
                "script_language": request.script_language,
                "swagger_content": request.swagger_content,
            },
            timeout_seconds=60,
            max_retries=1,
        ))
        # 同步等待结果
        result = await dispatcher.wait_for_result(task_id, timeout=60)
        if result.status == "success":
            return {"code": 0, "message": "分类成功", "data": result.result}
        else:
            raise Exception(result.error or "分类失败")
    except Exception as e:
        log.error(f"测试类型分类失败: {e}", exc_info=True)
        # 降级返回默认类型
        return {
            "code": 0,
            "message": "分类降级",
            "data": {
                "test_type": "web",
                "platform": "browser",
                "framework": "playwright",
                "confidence": 0.0,
                "reason": "AI分类不可用，默认为Web测试",
                "scores": {},
                "detected_signals": {},
            },
        }


@router.post("/create", summary="创建需求任务")
async def create_requirement(request: CreateRequest, user: User = Depends(require_auth)):
    """
    创建需求任务（不自动开始分析）

    支持附加信息、图片路径、脚本格式
    """
    if not request.requirement.strip():
        raise HTTPException(status_code=400, detail="需求内容不能为空")

    db = SessionLocal()
    try:
        task = RequirementFlowService._create_requirement_task(db, request.requirement.strip())
        # 保存附加信息
        if request.additional_info:
            task.additional_info = request.additional_info
        if request.image_paths:
            task.image_paths = json.dumps(request.image_paths, ensure_ascii=False)
        if request.script_format:
            task.script_format = request.script_format
        # 保存AI推断的测试类型
        if request.task_type:
            task.task_type = request.task_type
        if request.test_scope:
            task.type_config = json.dumps(request.test_scope, ensure_ascii=False)
        # 数据隔离
        task.user_id = user.id
        task.created_by = user.id
        db.commit()
        db.refresh(task)
        return Response(code=200, message="创建成功", data={
            "id": task.id,
            "requirement": task.requirement,
            "status": task.status,
            "additional_info": task.additional_info,
            "image_paths": request.image_paths,
            "script_format": task.script_format,
        })
    finally:
        db.close()


@router.post("/upload_images", summary="上传多张图片")
async def upload_images(files: List[UploadFile] = File(..., description="UI截图或原型图")):
    """
    上传多张图片，返回图片路径列表

    用于富文本编辑器中的图片上传
    """
    allowed_types = ["image/png", "image/jpeg", "image/jpg", "image/webp"]
    upload_dir = Path(settings.UPLOAD_DIR) / "requirement_images"
    upload_dir.mkdir(parents=True, exist_ok=True)

    saved_paths = []
    for file in files:
        if file.content_type not in allowed_types:
            raise HTTPException(status_code=400, detail=f"不支持的文件类型: {file.content_type}")

        content = await file.read()
        if len(content) > settings.MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=400, detail=f"文件 {file.filename} 大小超出限制")

        ext = Path(file.filename).suffix or ".png"
        filename = f"{uuid.uuid4().hex}{ext}"
        file_path = upload_dir / filename

        with open(file_path, "wb") as f:
            f.write(content)

        # 存储相对路径
        relative_path = f"requirement_images/{filename}"
        saved_paths.append(relative_path)
        log.info(f"需求图片上传成功 | 文件: {filename}")

    return Response(code=200, message="上传成功", data={"image_paths": saved_paths})


@router.get("/images/{image_path:path}", summary="获取上传的图片")
async def get_requirement_image(image_path: str):
    """获取上传的图片文件"""
    full_path = Path(settings.UPLOAD_DIR) / image_path
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(str(full_path))


@router.post("/analyze/{task_id}", summary="开始分析需求任务")
async def analyze_requirement(task_id: int, request: AnalyzeWithFeedbackRequest = None):
    """
    开始分析需求任务（生成脚本）

    用户点击"开始分析"时调用，返回SSE流式进度
    支持传入feedback_context用于基于反馈的重新生成
    """
    db = SessionLocal()
    try:
        task = db.query(RequirementTask).filter(RequirementTask.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="需求任务不存在")
        if task.status not in (RequirementStatus.PENDING, RequirementStatus.FAILED):
            raise HTTPException(status_code=400, detail=f"任务状态为 {task.status}，无法开始分析")
        # 在 session 关闭前提取所需字段，避免 detached instance 访问
        requirement = task.requirement
        image_paths = json.loads(task.image_paths) if task.image_paths else None
        additional_info = task.additional_info
        script_format = task.script_format or "playwright"
    finally:
        db.close()

    feedback_ctx = request.feedback_context if request else None

    # 构建 Orchestrator payload
    payload = {
        "requirement": requirement,
        "image_paths": image_paths,
        "additional_info": additional_info,
        "script_format": script_format,
        "feedback_context": feedback_ctx,
    }

    return EventSourceResponse(
        sse_wrapper(
            get_orchestrator().execute(
                "unified_test_flow",
                payload,
                task_id=task_id,
            )
        )
    )


@router.post("/analyze_and_execute/{task_id}", summary="分析需求任务（兼容旧接口，已改为仅分析）")
async def analyze_and_execute_requirement(task_id: int, request: AnalyzeWithFeedbackRequest = None):
    """
    [兼容旧接口] 原为"分析并执行"，现收敛为仅分析

    需求模块不再直接执行测试，执行由 Web 执行层负责
    内部转发到 /analyze/{task_id}
    """
    return await analyze_requirement(task_id, request)


@router.post("/execute/{task_id}", summary="执行已生成的脚本（兼容旧接口，已废弃）")
async def execute_requirement(task_id: int):
    """
    [已废弃] 需求模块不再直接执行测试

    执行请使用 POST /executions {task_id}
    此接口返回提示信息，引导用户到执行层
    """
    db = SessionLocal()
    try:
        req_task = db.query(RequirementTask).filter(RequirementTask.id == task_id).first()
        if not req_task:
            raise HTTPException(status_code=404, detail="需求任务不存在")
        if not req_task.task_id:
            raise HTTPException(status_code=400, detail="未关联测试任务，请先分析")
    finally:
        db.close()

    # 返回 task_id，引导前端到执行层
    return Response(code=200, message="请使用执行层接口", data={
        "task_id": req_task.task_id,
        "hint": "需求模块不再直接执行，请调用 POST /executions {task_id} 或在前端 Web/执行测试 页面操作",
    })


@router.post("/generate", summary="一键生成测试脚本")
async def generate_script(request: GenerateRequest):
    """
    一键生成：创建需求任务并立即开始分析

    流程：创建任务 → 需求解析 → 脚本复用检查 → RAG检索 → 用例生成 → 脚本生成
    返回SSE流式进度
    """
    if not request.requirement.strip():
        raise HTTPException(status_code=400, detail="需求内容不能为空")

    payload = {
        "requirement": request.requirement,
        "feedback_context": request.feedback_context,
        "additional_info": request.additional_info,
        "image_paths": request.image_paths,
        "script_format": request.script_format or "playwright",
    }

    return EventSourceResponse(
        sse_wrapper(
            get_orchestrator().execute("unified_test_flow", payload)
        )
    )


@router.post("/generate_and_execute", summary="一键生成并执行测试（兼容旧接口，已改为仅生成）")
async def generate_and_execute(request: GenerateRequest):
    """
    [兼容旧接口] 原为"生成并执行"，现收敛为仅生成

    需求模块不再直接执行测试，执行由 Web 执行层负责
    内部转发到 /generate
    """
    return await generate_script(request)


@router.post("/generate_multimodal", summary="多模态需求一键生成")
async def generate_multimodal(request: MultiModalGenerateRequest):
    """
    多模态需求一键生成：解析多模态输入 → 融合 → 生成测试脚本

    支持文本/图片/URL/脚本混合输入
    流程：多模态解析 → 融合 → 需求解析 → RAG检索 → 用例生成 → 脚本生成
    返回SSE流式进度
    """
    has_input = any([
        request.text and request.text.strip(),
        request.images and len(request.images) > 0,
        request.urls and len(request.urls) > 0,
        request.script_content and request.script_content.strip(),
    ])
    if not has_input:
        raise HTTPException(status_code=400, detail="至少提供一种输入（文本/图片/URL/脚本）")

    payload = {
        "text": request.text,
        "images": request.images,
        "urls": request.urls,
        "script_content": request.script_content,
        "script_language": request.script_language or "python",
        "page_ids": request.page_ids,
        "script_format": request.script_format or "playwright",
    }

    return EventSourceResponse(
        sse_wrapper(
            get_orchestrator().execute("unified_test_flow", payload)
        )
    )


@router.post("/generate_multimodal_and_execute", summary="多模态需求一键生成并执行（兼容旧接口，已改为仅生成）")
async def generate_multimodal_and_execute(request: MultiModalGenerateRequest):
    """
    [兼容旧接口] 原为"多模态生成并执行"，现收敛为仅生成

    需求模块不再直接执行测试，执行由 Web 执行层负责
    内部转发到 /generate_multimodal
    """
    return await generate_multimodal(request)


@router.get("/list", summary="获取需求任务列表")
async def list_requirements(
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(require_auth),
):
    """获取需求任务列表（自动过滤当前用户）"""
    db = SessionLocal()
    try:
        tasks = db.query(RequirementTask).filter(
            RequirementTask.user_id == user.id
        ).order_by(RequirementTask.created_at.desc()).limit(limit).all()
        data = []
        for t in tasks:
            data.append({
                "id": t.id,
                "requirement": t.requirement,
                "status": t.status,
                "intent": t.intent,
                "task_id": t.task_id,
                "execution_id": t.execution_id,
                "error_message": t.error_message,
                "script_format": t.script_format,
                "created_at": str(t.created_at) if t.created_at else None,
            })
        return Response(code=200, message="获取成功", data=data)
    finally:
        db.close()


@router.get("/{task_id}", summary="获取需求任务详情")
async def get_requirement(task_id: int, user: User = Depends(require_auth)):
    """获取需求任务详情"""
    db = SessionLocal()
    try:
        task = db.query(RequirementTask).filter(
            RequirementTask.id == task_id,
            RequirementTask.user_id == user.id
        ).first()
        if not task:
            raise HTTPException(status_code=404, detail="需求任务不存在")

        # 解析image_paths
        image_paths = []
        if task.image_paths:
            try:
                image_paths = json.loads(task.image_paths)
            except Exception:
                image_paths = []

        return Response(code=200, message="获取成功", data={
            "id": task.id,
            "requirement": task.requirement,
            "status": task.status,
            "intent": task.intent,
            "generated_case": task.generated_case,
            "generated_script": task.generated_script,
            "generated_yaml": task.generated_yaml,
            "task_id": task.task_id,
            "execution_id": task.execution_id,
            "error_message": task.error_message,
            "rag_result": task.rag_result,
            "script_source": task.script_source,
            "reuse_similarity": task.reuse_similarity,
            "script_format": task.script_format,
            "additional_info": task.additional_info,
            "image_paths": image_paths,
            "page_overview": task.page_overview,
            "page_elements": task.page_elements,
            "test_scenarios": task.test_scenarios,
            "expected_results": task.expected_results,
            "graph_result": task.graph_result,
            "created_at": str(task.created_at) if task.created_at else None,
            "updated_at": str(task.updated_at) if task.updated_at else None,
        })
    finally:
        db.close()


class DeleteRequirementRequest(BaseModel):
    """批量删除需求请求"""
    ids: list[int]


@router.get("/reuse_stats", summary="获取脚本复用统计")
async def get_reuse_stats():
    """获取脚本复用统计信息"""
    db = SessionLocal()
    try:
        stats = RequirementFlowService.get_reuse_stats(db)
        return Response(code=200, message="获取成功", data=stats)
    finally:
        db.close()


@router.delete("/{task_id}", summary="删除需求任务")
async def delete_requirement(task_id: int, user: User = Depends(require_auth)):
    """删除需求任务及关联数据"""
    db = SessionLocal()
    try:
        task = db.query(RequirementTask).filter(
            RequirementTask.id == task_id,
            RequirementTask.user_id == user.id
        ).first()
        if not task:
            raise HTTPException(status_code=404, detail="需求任务不存在")
        db.delete(task)
        db.commit()
        return Response(code=200, message="删除成功")
    finally:
        db.close()


@router.post("/batch_delete", summary="批量删除需求任务")
async def batch_delete_requirements(request: DeleteRequirementRequest, user: User = Depends(require_auth)):
    """批量删除需求任务"""
    if not request.ids:
        raise HTTPException(status_code=400, detail="请选择要删除的需求")
    db = SessionLocal()
    try:
        success_count = 0
        for req_id in request.ids:
            task = db.query(RequirementTask).filter(
                RequirementTask.id == req_id,
                RequirementTask.user_id == user.id
            ).first()
            if task:
                db.delete(task)
                success_count += 1
        db.commit()
        return Response(code=200, message=f"删除完成: 成功{success_count}个")
    finally:
        db.close()
