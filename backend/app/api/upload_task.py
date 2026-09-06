"""
上传任务系统 API

任务驱动型上传架构：
  1. POST /create  → 创建任务（返回task_id）
  2. POST /{task_id}/upload → 上传文件到任务
  3. POST /{task_id}/start  → 启动处理（触发Pipeline）
  4. GET  /{task_id}/stream → SSE实时进度
  5. GET  /{task_id}        → 查询任务状态
  6. GET  /list             → 任务列表
  7. POST /{task_id}/retry  → 失败重试

核心原则：
  - 上传 = Task，不是UI行为
  - 所有状态后端托管
  - 跨页面可查询
"""
import json
import os
import asyncio
from typing import Optional, List
from fastapi import APIRouter, File, Form, UploadFile, HTTPException, Query, Depends
from pydantic import BaseModel as PydanticModel
from app.core.config import settings
from app.core.logger import log
from app.db.database import SessionLocal
from app.models.case_task import CaseTask, CaseTaskStatus
from app.core.auth import require_auth
from app.models.user import User

router = APIRouter()


class CreateTaskRequest(PydanticModel):
    """创建上传任务请求"""
    title: str = ""
    source_type: str = "text"
    compile_level: str = "l2"
    use_rag: bool = True
    case_types: List[str] = ["functional", "boundary", "error"]
    max_cases: int = 20
    framework: str = "pytest"
    base_url: str = "http://localhost:8080"
    project_id: str = ""


class StartTaskRequest(PydanticModel):
    """启动任务处理请求"""
    raw_text: str = ""
    url: str = ""


@router.post("/create")
async def create_task(
    request: CreateTaskRequest,
    user: User = Depends(require_auth),
):
    """
    创建上传任务（第一步）

    返回 task_id，后续上传文件和启动处理都基于此 task_id
    """
    db = SessionLocal()
    try:
        task = CaseTask(
            title=request.title or f"上传任务-{request.source_type}",
            source_type=request.source_type,
            status=CaseTaskStatus.WAITING,
            user_id=user.id,
            created_by=user.id,
        )
        # 将配置存入 raw_input（JSON格式）
        config = {
            "compile_level": request.compile_level,
            "use_rag": request.use_rag,
            "case_types": request.case_types,
            "max_cases": request.max_cases,
            "framework": request.framework,
            "base_url": request.base_url,
            "project_id": request.project_id,
        }
        task.raw_input = json.dumps(config, ensure_ascii=False)
        db.add(task)
        db.commit()
        db.refresh(task)

        return {
            "task_id": task.id,
            "status": task.status,
            "title": task.title,
            "created_at": str(task.created_at) if task.created_at else None,
        }
    finally:
        db.close()


@router.post("/{task_id}/upload")
async def upload_file(
    task_id: int,
    file: UploadFile = File(...),
    user: User = Depends(require_auth),
):
    """
    上传文件到任务（第二步）

    文件保存到磁盘，task记录更新 source_file
    """
    db = SessionLocal()
    try:
        task = db.query(CaseTask).filter(
            CaseTask.id == task_id,
            CaseTask.user_id == user.id,
        ).first()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        if task.status not in (CaseTaskStatus.WAITING, CaseTaskStatus.FAILED):
            raise HTTPException(status_code=400, detail=f"任务状态不允许上传: {task.status}")

        from app.core.upload_security import validate_upload_file
        validated = await validate_upload_file(file, declared_category="auto")

        upload_dir = os.path.join(settings.UPLOAD_DIR, "upload_tasks")
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, f"task_{task_id}_{validated.safe_name}")
        with open(file_path, "wb") as f:
            f.write(validated.content)

        task.source_file = file_path
        if task.source_type == "text":
            task.source_type = validated.category

        db.commit()

        return {
            "task_id": task_id,
            "file_path": file_path,
            "source_type": task.source_type,
            "status": task.status,
            "file_size": validated.size,
            "original_name": validated.original_name,
        }
    finally:
        db.close()


@router.post("/{task_id}/start")
async def start_task(
    task_id: int,
    request: StartTaskRequest = None,
    user: User = Depends(require_auth),
):
    """
    启动任务处理（第三步）

    触发Pipeline异步执行，立即返回task_id
    前端通过 /{task_id}/stream 监听进度
    """
    db = SessionLocal()
    try:
        task = db.query(CaseTask).filter(
            CaseTask.id == task_id,
            CaseTask.user_id == user.id,
        ).first()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        if task.status not in (CaseTaskStatus.WAITING, CaseTaskStatus.FAILED):
            raise HTTPException(status_code=400, detail=f"任务状态不允许启动: {task.status}")

        # 解析配置
        config = {}
        if task.raw_input:
            try:
                config = json.loads(task.raw_input)
            except Exception:
                pass

        # 更新URL和文本
        raw_text = request.raw_text if request else ""
        url = request.url if request else ""
        if raw_text:
            task.raw_input = raw_text  # 覆盖配置，存入实际文本
            # 保留配置在case_set中
            task.case_set = json.dumps({"config": config}, ensure_ascii=False)
        if url:
            task.source_url = url

        task.status = CaseTaskStatus.PARSING
        db.commit()

        # 创建并注册进度队列（供SSE端点复用）
        from app.services.case.compiler_utils import _progress_queues
        progress_queue = asyncio.Queue()
        _progress_queues[task_id] = progress_queue

        # 异步启动Pipeline（传入progress_queue）
        from app.services.case.pipeline import CasePipeline
        asyncio.create_task(
            CasePipeline.run_pipeline(
                project_id=config.get("project_id", ""),
                title=task.title,
                source_type=task.source_type,
                raw_text=raw_text,
                url=url or task.source_url or "",
                file_path=task.source_file or "",
                use_rag=config.get("use_rag", True),
                case_types=config.get("case_types", ["functional", "boundary", "error"]),
                max_cases=config.get("max_cases", 20),
                compile_level=config.get("compile_level", "l2"),
                framework=config.get("framework", "pytest"),
                base_url=config.get("base_url", "http://localhost:8080"),
                user_id=user.id,
                progress_queue=progress_queue,
            )
        )

        return {
            "task_id": task_id,
            "status": "running",
            "message": "任务已启动，通过 /stream 监听进度",
        }
    finally:
        db.close()


@router.get("/{task_id}/stream")
async def task_stream(
    task_id: int,
    user: User = Depends(require_auth),
):
    """
    SSE实时进度流

    前端通过此端点监听任务处理进度
    """
    from fastapi.responses import StreamingResponse

    db = SessionLocal()
    try:
        task = db.query(CaseTask).filter(
            CaseTask.id == task_id,
            CaseTask.user_id == user.id,
        ).first()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
    finally:
        db.close()

    # 复用已注册的进度队列（start_task时创建），或创建新的
    from app.services.case.compiler_utils import _progress_queues
    progress_queue = _progress_queues.get(task_id, asyncio.Queue())
    _progress_queues[task_id] = progress_queue

    async def event_generator():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(progress_queue.get(), timeout=120.0)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    if event.get("type") in ("completed", "error"):
                        break
                except asyncio.TimeoutError:
                    # 检查任务是否已完成
                    db = SessionLocal()
                    try:
                        t = db.query(CaseTask).filter(CaseTask.id == task_id).first()
                        if t and t.status in (CaseTaskStatus.COMPLETED, CaseTaskStatus.FAILED):
                            yield f"data: {json.dumps({'type': 'completed' if t.status == CaseTaskStatus.COMPLETED else 'error', 'payload': {'task_id': task_id, 'status': t.status}}, ensure_ascii=False)}\n\n"
                            break
                    finally:
                        db.close()
                    yield f"data: {json.dumps({'type': 'heartbeat'}, ensure_ascii=False)}\n\n"
        finally:
            # 清理
            _progress_queues.pop(task_id, None)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/{task_id}")
async def get_task_status(
    task_id: int,
    user: User = Depends(require_auth),
):
    """查询任务状态"""
    db = SessionLocal()
    try:
        task = db.query(CaseTask).filter(
            CaseTask.id == task_id,
            CaseTask.user_id == user.id,
        ).first()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        case_set = json.loads(task.case_set) if task.case_set else {}
        config = case_set.get("config", {})

        return {
            "task_id": task.id,
            "title": task.title,
            "source_type": task.source_type,
            "source_file": task.source_file,
            "status": task.status,
            "error_message": task.error_message,
            "compile_level": config.get("compile_level", "l2"),
            "case_count": case_set.get("content_count", case_set.get("case_count", 0)),
            "created_at": str(task.created_at) if task.created_at else None,
            "updated_at": str(task.updated_at) if task.updated_at else None,
        }
    finally:
        db.close()


@router.get("/list")
async def list_tasks(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    user: User = Depends(require_auth),
):
    """任务列表（当前用户）"""
    db = SessionLocal()
    try:
        query = db.query(CaseTask).filter(CaseTask.user_id == user.id)
        if status:
            query = query.filter(CaseTask.status == status)
        query = query.order_by(CaseTask.id.desc())
        total = query.count()
        tasks = query.offset(skip).limit(limit).all()

        return {
            "items": [
                {
                    "task_id": t.id,
                    "title": t.title,
                    "source_type": t.source_type,
                    "status": t.status,
                    "error_message": t.error_message,
                    "created_at": str(t.created_at) if t.created_at else None,
                    "updated_at": str(t.updated_at) if t.updated_at else None,
                }
                for t in tasks
            ],
            "total": total,
        }
    finally:
        db.close()


@router.post("/{task_id}/retry")
async def retry_task(
    task_id: int,
    user: User = Depends(require_auth),
):
    """失败重试"""
    db = SessionLocal()
    try:
        task = db.query(CaseTask).filter(
            CaseTask.id == task_id,
            CaseTask.user_id == user.id,
        ).first()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        if task.status != CaseTaskStatus.FAILED:
            raise HTTPException(status_code=400, detail="只能重试失败的任务")

        task.status = CaseTaskStatus.WAITING
        task.error_message = None
        db.commit()

        return {"task_id": task_id, "status": "waiting", "message": "任务已重置，可重新启动"}
    finally:
        db.close()
