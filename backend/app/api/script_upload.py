"""
脚本上传 API

上传 → 解析 → 校验 → 预览 → 执行
"""
import json
import uuid
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from pydantic import BaseModel
from app.db.database import SessionLocal
from app.runtime.agent_factory import AgentFactory
from app.core.config import settings
from app.core.logger import log
from app.schemas.response import Response
from app.core.auth import require_auth
from app.models.user import User

router = APIRouter()


class ExecuteScriptRequest(BaseModel):
    content: str
    script_type: str = "playwright"
    language: str = "python"
    task_id: Optional[int] = None
    timeout: int = 300


@router.post("/upload", summary="上传脚本文件")
async def upload_script(
    file: UploadFile = File(..., description="测试脚本文件"),
    user: User = Depends(require_auth),
):
    """上传脚本文件，自动解析和校验"""
    allowed_ext = {".py", ".js", ".ts", ".mjs", ".yaml", ".yml", ".json"}
    ext = Path(file.filename or "").suffix.lower()
    if ext not in allowed_ext:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}，支持: {', '.join(allowed_ext)}")

    content_bytes = await file.read()
    if len(content_bytes) > 1024 * 1024:  # 1MB限制
        raise HTTPException(status_code=400, detail="文件大小不能超过1MB")

    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = content_bytes.decode("gbk", errors="replace")

    # 解析
    parser = AgentFactory.create("script_parser")
    parsed = parser.parse(content, file.filename or "")

    # 校验
    validator = AgentFactory.create("script_validator")
    validation = validator.validate(parsed)

    # 保存文件
    upload_dir = Path(settings.UPLOAD_DIR) / "uploaded_scripts"
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    file_path = upload_dir / filename
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    relative_path = f"uploaded_scripts/{filename}"

    return Response(code=200, message="上传成功", data={
        "filename": file.filename,
        "saved_path": relative_path,
        "content": content,
        "parsed": parsed.to_dict(),
        "validation": validation.to_dict(),
    })


@router.post("/parse", summary="解析脚本内容")
async def parse_script(
    content: str = Form(...),
    filename: str = Form(""),
    user: User = Depends(require_auth),
):
    """解析脚本内容（不上传文件，直接粘贴内容）"""
    parser = AgentFactory.create("script_parser")
    parsed = parser.parse(content, filename)

    validator = AgentFactory.create("script_validator")
    validation = validator.validate(parsed)

    return Response(code=200, message="解析成功", data={
        "parsed": parsed.to_dict(),
        "validation": validation.to_dict(),
    })


@router.post("/validate", summary="校验脚本")
async def validate_script(
    content: str = Form(...),
    filename: str = Form(""),
    user: User = Depends(require_auth),
):
    """校验脚本语法和结构"""
    parser = AgentFactory.create("script_parser")
    parsed = parser.parse(content, filename)

    validator = AgentFactory.create("script_validator")
    validation = validator.validate(parsed)

    return Response(code=200, message="校验完成", data=validation.to_dict())


@router.post("/execute", summary="执行脚本（异步）")
async def execute_script(request: ExecuteScriptRequest, user: User = Depends(require_auth)):
    """
    执行上传的脚本（异步化改造）

    1. 校验脚本
    2. 创建 Task + ExecutionRecord（WAITING）
    3. 提交到 TaskQueue
    4. 立即返回 execution_id
    """
    if not request.content.strip():
        raise HTTPException(status_code=400, detail="脚本内容不能为空")

    # 先校验
    parser = AgentFactory.create("script_parser")
    parsed = parser.parse(request.content, "")
    validator = AgentFactory.create("script_validator")
    validation = validator.validate(parsed)

    if not validation.valid:
        raise HTTPException(status_code=400, detail=f"脚本校验失败: {'; '.join(validation.errors)}")

    # 创建Task记录
    db = SessionLocal()
    task_id = request.task_id
    try:
        if not task_id:
            from app.models.task import Task, TaskStatus, TaskType
            task = Task(
                task_name=f"脚本执行 - {parsed.name or 'unnamed'}",
                task_type=TaskType.WEB,
                status=TaskStatus.PROCESSING,
                user_id=user.id,
                created_by=user.id,
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id

        # 创建 ExecutionRecord（WAITING 状态）
        from app.models.execution_record import ExecutionRecord, ExecutionStatus
        exec_record = ExecutionRecord(
            task_id=task_id,
            status=ExecutionStatus.WAITING,
            trigger_source="script_upload",
            user_id=user.id,
            created_by=user.id,
        )
        db.add(exec_record)

        # 保存脚本到 Script 表
        from app.models.script import Script
        existing_script = db.query(Script).filter(Script.task_id == task_id).first()
        if existing_script:
            existing_script.script_content = request.content
        else:
            db.add(Script(
                task_id=task_id,
                script_content=request.content,
                script_source="uploaded",
                user_id=user.id,
                created_by=user.id,
            ))

        db.commit()
        db.refresh(exec_record)
        execution_id = exec_record.id
    except Exception as e:
        db.rollback()
        log.error(f"创建执行记录失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建执行记录失败: {e}")
    finally:
        db.close()

    # 提交到 TaskQueue 异步执行
    from app.core.task_queue import TaskQueue
    queue = TaskQueue()
    if queue.started:
        await queue.submit(
            execution_id=execution_id,
            task_id=task_id,
            script_content=request.content,
            trigger_source="script_upload",
        )
    else:
        log.warning("TaskQueue 未启动，脚本执行将无法异步执行")

    return Response(code=200, message="执行任务已创建", data={
        "task_id": task_id,
        "execution_id": execution_id,
        "status": "waiting",
        "script_type": parsed.script_type,
        "validation": validation.to_dict(),
    })
