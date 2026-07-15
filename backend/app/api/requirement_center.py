"""
RequirementCenter API - 需求中心接口

第二阶段新增接口：
- POST /requirement-center/upload      上传文件
- POST /requirement-center/analyze      开始AI分析（SSE）
- POST /requirement-center/review       提交评审回答
- POST /requirement-center/finalize     最终化需求并创建Task
- GET  /requirement-center/{id}         获取需求详情
- GET  /requirement-center/session/{session_id}  获取完整会话信息
- POST /requirement-center/session      创建会话
- GET  /requirement-center/sessions     列出会话
- DELETE /requirement-center/session/{session_id}  删除会话
- DELETE /requirement-center/file/{file_id}       删除文件
"""
import json
from typing import List, Optional
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.orm import Session

from app.core.auth import require_auth
from app.core.logger import log
from app.db.database import get_db, SessionLocal
from app.models.user import User
from app.services.requirement_center_service import get_requirement_center_service

router = APIRouter(prefix="/requirement-center", tags=["需求中心"])


# ================================================================
# Request Schemas
# ================================================================

class CreateSessionRequest(BaseModel):
    title: str = ""
    input_text: str = ""
    input_urls: str = ""
    additional_context: str = ""
    system_name: str = ""
    business_background: str = ""
    test_scope: str = ""
    credentials: str = ""
    notes: str = ""
    special_requirements: str = ""


class SaveContextRequest(BaseModel):
    system_name: str = ""
    business_background: str = ""
    test_scope: str = ""
    credentials: str = ""
    notes: str = ""
    special_requirements: str = ""


class AnalyzeRequest(BaseModel):
    session_id: int


class ReviewAnswerItem(BaseModel):
    question_id: int
    answer: str


class SubmitReviewRequest(BaseModel):
    session_id: int
    answers: List[ReviewAnswerItem]


class FinalizeRequest(BaseModel):
    session_id: int
    final_requirement: str = ""
    edited_requirement: str = ""  # 用户可能编辑的最终需求


# ================================================================
# Session 管理
# ================================================================

@router.post("/session")
async def create_session(
    req: CreateSessionRequest,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """创建需求分析会话"""
    svc = get_requirement_center_service()

    # 构建附加上下文
    additional_context = ""
    parts = []
    if req.system_name:
        parts.append(f"系统名称: {req.system_name}")
    if req.business_background:
        parts.append(f"业务背景: {req.business_background}")
    if req.test_scope:
        parts.append(f"测试范围: {req.test_scope}")
    if req.credentials:
        parts.append(f"账号密码: {req.credentials}")
    if req.notes:
        parts.append(f"注意事项: {req.notes}")
    if req.special_requirements:
        parts.append(f"特殊要求: {req.special_requirements}")
    if parts:
        additional_context = json.dumps(parts, ensure_ascii=False)

    session = svc.create_session(
        db=db,
        user_id=user.id,
        title=req.title,
        input_text=req.input_text,
        input_urls=req.input_urls,
        additional_context=additional_context,
    )

    # 保存上下文
    if req.system_name or req.business_background or req.test_scope or req.notes or req.special_requirements:
        svc.save_context(
            db=db,
            session_id=session.id,
            system_name=req.system_name,
            business_background=req.business_background,
            test_scope=req.test_scope,
            credentials=req.credentials,
            notes=req.notes,
            special_requirements=req.special_requirements,
        )

    return {
        "code": 0,
        "message": "Session created",
        "data": {
            "session_id": session.id,
            "title": session.title,
            "status": session.status,
        },
    }


@router.get("/sessions")
async def list_sessions(
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
):
    """列出用户的需求会话"""
    svc = get_requirement_center_service()
    sessions = svc.list_sessions(db, user.id, limit)

    return {
        "code": 0,
        "data": [
            {
                "id": s.id,
                "title": s.title,
                "status": s.status,
                "current_step": s.current_step,
                "finalized": s.finalized,
                "task_id": s.task_id,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in sessions
        ],
    }


@router.delete("/session/{session_id}")
async def delete_session(
    session_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """删除会话"""
    svc = get_requirement_center_service()
    success = svc.delete_session(db, session_id, user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"code": 0, "message": "Session deleted"}


# ================================================================
# 文件上传
# ================================================================

@router.post("/upload")
async def upload_files(
    session_id: int = Form(...),
    files: List[UploadFile] = File(...),
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """上传文件（支持多文件）"""
    svc = get_requirement_center_service()

    # 验证Session归属
    session = svc.get_session(db, session_id, user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 支持的文件类型
    allowed_extensions = {
        "image": {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"},
        "document": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt", ".md", ".json", ".yaml", ".yml"},
        "video": {".mp4", ".avi", ".mov", ".mkv"},
        "schema": {".sql", ".ddl"},
    }
    all_allowed = set()
    for exts in allowed_extensions.values():
        all_allowed.update(exts)

    results = []
    for file in files:
        # 检查文件类型
        ext = ""
        if "." in file.filename:
            ext = "." + file.filename.rsplit(".", 1)[-1].lower()

        if ext not in all_allowed:
            results.append({
                "file_name": file.filename,
                "success": False,
                "error": f"Unsupported file type: {ext}",
            })
            continue

        # 检查文件大小
        content = await file.read()
        if len(content) > 50 * 1024 * 1024:  # 50MB
            results.append({
                "file_name": file.filename,
                "success": False,
                "error": "File too large (max 50MB)",
            })
            continue

        # 确定文件类型
        file_type = "document"
        for category, exts in allowed_extensions.items():
            if ext in exts:
                file_type = category
                break

        try:
            req_file = svc.save_file(
                db=db,
                session_id=session_id,
                file_name=file.filename,
                file_content=content,
                file_type=file_type,
                mime_type=file.content_type or "application/octet-stream",
                user_id=user.id,
            )
            results.append({
                "file_id": req_file.id,
                "file_name": req_file.file_name,
                "file_path": req_file.file_path,
                "category": req_file.category,
                "file_size": req_file.file_size,
                "success": True,
            })
        except Exception as e:
            log.error(f"Upload file '{file.filename}' failed: {e}")
            results.append({
                "file_name": file.filename,
                "success": False,
                "error": str(e),
            })

    return {
        "code": 0,
        "message": f"Uploaded {sum(1 for r in results if r.get('success'))}/{len(results)} files",
        "data": results,
    }


@router.delete("/file/{file_id}")
async def delete_file(
    file_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """删除文件"""
    svc = get_requirement_center_service()
    success = svc.delete_file(db, file_id, user.id)
    if not success:
        raise HTTPException(status_code=404, detail="File not found")
    return {"code": 0, "message": "File deleted"}


@router.post("/context")
async def save_context(
    session_id: int = Form(...),
    system_name: str = Form(""),
    business_background: str = Form(""),
    test_scope: str = Form(""),
    credentials: str = Form(""),
    notes: str = Form(""),
    special_requirements: str = Form(""),
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """保存附加上下文"""
    svc = get_requirement_center_service()
    session = svc.get_session(db, session_id, user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    context = svc.save_context(
        db=db,
        session_id=session_id,
        system_name=system_name,
        business_background=business_background,
        test_scope=test_scope,
        credentials=credentials,
        notes=notes,
        special_requirements=special_requirements,
    )
    return {"code": 0, "message": "Context saved", "data": {"session_id": session_id}}


# ================================================================
# AI 分析（SSE）
# ================================================================

@router.post("/analyze")
async def analyze(
    req: AnalyzeRequest,
    user: User = Depends(require_auth),
):
    """开始AI分析（SSE流式返回）"""
    svc = get_requirement_center_service()

    async def event_generator():
        # 使用独立DB session
        db = SessionLocal()
        try:
            # 验证权限
            session = svc.get_session(db, req.session_id, user.id)
            if not session:
                yield json.dumps({"event": "error", "data": {"message": "Session not found"}}, ensure_ascii=False)
                return

            async for event in svc.analyze(db, req.session_id, user.id):
                yield event
        finally:
            db.close()

    return EventSourceResponse(event_generator())


# ================================================================
# 评审回答
# ================================================================

@router.post("/review")
async def submit_review(
    req: SubmitReviewRequest,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """提交评审回答"""
    svc = get_requirement_center_service()
    session = svc.get_session(db, req.session_id, user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    answers_data = [{"question_id": a.question_id, "answer": a.answer} for a in req.answers]
    review = svc.submit_review_answers(db, req.session_id, answers_data, user.id)

    return {
        "code": 0,
        "message": "Review submitted",
        "data": {
            "session_id": req.session_id,
            "review_id": review.id if review else None,
            "status": review.status if review else "unknown",
        },
    }


# ================================================================
# 最终化
# ================================================================

@router.post("/finalize")
async def finalize(
    req: FinalizeRequest,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """最终化需求并创建Task"""
    svc = get_requirement_center_service()
    session = svc.get_session(db, req.session_id, user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 优先使用用户编辑的需求，否则用已有最终需求
    final_req = req.edited_requirement or req.final_requirement or session.final_requirement
    if not final_req:
        raise HTTPException(status_code=400, detail="No final requirement provided")

    result = svc.finalize(db, req.session_id, final_req, user.id)

    return {
        "code": 0,
        "message": "Requirement finalized, task created",
        "data": result,
    }


# ================================================================
# 查询
# ================================================================

@router.get("/session/{session_id}")
async def get_session(
    session_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """获取完整会话信息"""
    svc = get_requirement_center_service()
    data = svc.get_full_session(db, session_id, user.id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")

    return {"code": 0, "data": data}


@router.get("/{id}")
async def get_requirement(
    id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """获取需求详情（通过session_id）"""
    svc = get_requirement_center_service()
    data = svc.get_full_session(db, id, user.id)
    if not data:
        raise HTTPException(status_code=404, detail="Requirement not found")

    return {"code": 0, "data": data}
