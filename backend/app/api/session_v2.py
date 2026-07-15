"""
Session V2 API - 统一会话管理端点

提供：
- POST   /session/v2/create       创建会话
- GET    /session/v2/list         会话列表
- GET    /session/v2/{id}        会话详情
- GET    /session/v2/{id}/restore 恢复整个会话
- DELETE /session/v2/{id}        删除会话
- POST   /session/v2/{id}/run    执行 GraphFlow
- POST   /session/v2/{id}/artifacts  添加制品
- GET    /session/v2/{id}/artifacts  获取制品列表
- GET    /session/v2/{id}/stats   会话统计
- POST   /session/v2/{id}/upload  上传文件

每个用户请求自动生成 Session，整个 Session 可以恢复。
"""
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query
from pydantic import BaseModel, Field

from app.services.session_db_service import get_session_manager
from app.models.session_artifact import ArtifactType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/session/v2", tags=["会话管理"])


# ------------------------------------------------------------------ #
#  请求/响应模型                                                       #
# ------------------------------------------------------------------ #

class CreateSessionRequest(BaseModel):
    """创建会话请求"""
    requirement: str = Field("", description="需求文本")
    input_mode: str = Field("text", description="输入模式: text/image/file/url")
    session_name: str = Field("", description="会话名称（空则自动生成）")
    project_id: str = Field("", description="项目ID")
    config: Optional[Dict[str, Any]] = Field(None, description="会话配置")
    user_id: Optional[int] = Field(None, description="用户ID")
    task_id: Optional[int] = Field(None, description="关联的任务ID")


class AddArtifactRequest(BaseModel):
    """添加制品请求"""
    artifact_type: str = Field(..., description="制品类型")
    name: str = Field(..., description="制品名称")
    content: Optional[Dict[str, Any]] = Field(None, description="制品内容")
    file_path: str = Field("", description="文件路径")
    file_size: int = Field(0, description="文件大小")
    mime_type: str = Field("", description="MIME类型")
    step: str = Field("", description="流程步骤")
    source_agent: str = Field("", description="来源Agent")
    tags: str = Field("", description="标签")
    metadata: Optional[Dict[str, Any]] = Field(None, description="元数据")


class RunGraphflowRequest(BaseModel):
    """执行 GraphFlow 请求"""
    requirement: str = Field("", description="需求文本（空则使用会话中的需求）")
    context: Optional[Dict[str, Any]] = Field(None, description="上下文数据")


# ------------------------------------------------------------------ #
#  端点                                                                #
# ------------------------------------------------------------------ #

@router.post("/create")
async def create_session(request: CreateSessionRequest) -> Dict[str, Any]:
    """
    创建新会话

    每个用户请求自动生成一个 Session。
    """
    manager = get_session_manager()
    session = manager.create_session(
        user_id=request.user_id,
        requirement=request.requirement,
        input_mode=request.input_mode,
        session_name=request.session_name,
        project_id=request.project_id,
        config=request.config,
        task_id=request.task_id,
    )
    return {
        "id": session.id,
        "session_name": session.session_name,
        "session_key": session.session_key,
        "session_id": session.session_key,
        "user_id": session.user_id,
        "task_id": session.task_id,
        "status": session.status,
        "requirement_text": session.requirement_text,
        "created_at": session.created_at.isoformat() if session.created_at else None,
    }


@router.get("/list")
async def list_sessions(
    user_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> List[Dict[str, Any]]:
    """
    会话列表

    前端 Session 列表展示，支持按用户和状态过滤。
    """
    manager = get_session_manager()
    return manager.list_sessions(user_id=user_id, status=status, skip=skip, limit=limit)


@router.get("/{session_id}")
async def get_session(session_id: int) -> Dict[str, Any]:
    """获取会话基本信息"""
    manager = get_session_manager()
    session = manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "id": session.id,
        "session_name": session.session_name,
        "status": session.status,
        "current_step": session.current_step,
        "requirement_text": session.requirement_text,
        "requirement_summary": session.requirement_summary,
        "input_mode": session.input_mode,
        "session_key": session.session_key,
        "graphflow_task_id": session.graphflow_task_id,
        "total_tokens": session.total_tokens,
        "total_duration": session.total_duration,
        "artifact_count": session.artifact_count,
        "error_count": session.error_count,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
    }


@router.get("/{session_id}/restore")
async def restore_session(session_id: int) -> Dict[str, Any]:
    """
    恢复整个 Session

    返回完整的会话状态，包括所有制品、Agent 事件、Flow 结果。
    前端点击会话后调用此方法，恢复整个 AI 执行历史。
    """
    manager = get_session_manager()
    state = manager.restore_session(session_id)
    if "error" in state:
        raise HTTPException(status_code=404, detail=state["error"])
    return state


@router.delete("/{session_id}")
async def delete_session(session_id: int) -> Dict[str, Any]:
    """删除会话（软删除）"""
    manager = get_session_manager()
    success = manager.delete_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "ok", "deleted": session_id}


@router.post("/{session_id}/run")
async def run_graphflow(session_id: int, request: RunGraphflowRequest) -> Dict[str, Any]:
    """
    为会话执行 GraphFlow 工作流

    执行完整流程：Requirement → CaseGenerate → CaseReview → HumanFeedback → ScriptGenerate → Export
    """
    manager = get_session_manager()
    result = await manager.run_graphflow(
        session_id=session_id,
        requirement=request.requirement,
        context=request.context,
    )
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/{session_id}/artifacts")
async def add_artifact(session_id: int, request: AddArtifactRequest) -> Dict[str, Any]:
    """
    添加会话制品

    制品类型：requirement/file/agent_message/test_point/case/script/log/mindmap/export/feedback/review
    """
    manager = get_session_manager()
    artifact = manager.add_artifact(
        session_id=session_id,
        artifact_type=request.artifact_type,
        name=request.name,
        content=request.content,
        file_path=request.file_path,
        file_size=request.file_size,
        mime_type=request.mime_type,
        step=request.step,
        source_agent=request.source_agent,
        tags=request.tags,
        metadata=request.metadata,
    )
    return {
        "id": artifact.id,
        "session_id": artifact.session_id,
        "artifact_type": artifact.artifact_type,
        "name": artifact.name,
        "step": artifact.step,
        "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
    }


@router.get("/{session_id}/artifacts")
async def get_artifacts(
    session_id: int,
    artifact_type: Optional[str] = Query(None, description="制品类型过滤"),
    step: Optional[str] = Query(None, description="步骤过滤"),
) -> List[Dict[str, Any]]:
    """获取会话制品列表"""
    manager = get_session_manager()
    return manager.get_artifacts(
        session_id=session_id,
        artifact_type=artifact_type,
        step=step,
    )


@router.get("/{session_id}/stats")
async def get_session_stats(session_id: int) -> Dict[str, Any]:
    """获取会话统计信息"""
    manager = get_session_manager()
    return manager.get_session_stats(session_id)


@router.post("/{session_id}/upload")
async def upload_file(
    session_id: int,
    file: UploadFile = File(...),
    description: str = Form(""),
) -> Dict[str, Any]:
    """
    上传文件到会话

    文件保存到 uploads 目录，并记录为制品。
    """
    import shutil
    from pathlib import Path

    # 确保上传目录存在
    upload_dir = Path(f"uploads/session_{session_id}")
    upload_dir.mkdir(parents=True, exist_ok=True)

    # 保存文件
    file_path = upload_dir / file.filename
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    file_size = os.path.getsize(file_path)

    # 添加为制品
    manager = get_session_manager()
    artifact = manager.add_artifact(
        session_id=session_id,
        artifact_type=ArtifactType.FILE,
        name=file.filename,
        content={"description": description, "original_name": file.filename},
        file_path=str(file_path),
        file_size=file_size,
        mime_type=file.content_type or "",
        step="upload",
        source_agent="User",
    )

    return {
        "id": artifact.id,
        "name": file.filename,
        "file_path": str(file_path),
        "file_size": file_size,
        "mime_type": file.content_type,
    }


# ------------------------------------------------------------------ #
#  企业级 Session 增强端点                                              #
# ------------------------------------------------------------------ #

@router.get("/{session_id}/detail")
async def get_session_detail(session_id: int) -> Dict[str, Any]:
    """
    获取会话完整详情（企业级）

    返回完整关联数据：
    - 会话基本信息（session_id / user_id / task_id）
    - 上传文件列表
    - Agent 消息记录
    - 执行日志
    - 生成结果（用例/脚本）
    - 测试报告
    - TaskState 状态
    - Agent 事件
    - Flow 结果
    """
    manager = get_session_manager()
    state = manager.restore_session(session_id)
    if "error" in state:
        raise HTTPException(status_code=404, detail=state["error"])
    return state


@router.get("/{session_id}/messages")
async def get_session_messages(
    session_id: int,
    source_agent: Optional[str] = Query(None, description="按发送方过滤"),
    target_agent: Optional[str] = Query(None, description="按接收方过滤"),
    limit: int = Query(100, ge=1, le=500),
) -> List[Dict[str, Any]]:
    """获取会话的 Agent 消息记录"""
    from app.db.database import SessionLocal as DbSession
    from app.models.session import Session as SessionModel
    from app.models.agent_message_record import AgentMessageRecord

    db = DbSession()
    try:
        session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")

        session_key = session.session_key or str(session.id)
        q = db.query(AgentMessageRecord).filter(
            AgentMessageRecord.session_id == session_key
        )
        if source_agent:
            q = q.filter(AgentMessageRecord.source_agent == source_agent)
        if target_agent:
            q = q.filter(AgentMessageRecord.target_agent == target_agent)
        records = q.order_by(AgentMessageRecord.id).limit(limit).all()
        return [r.to_dict() for r in records]
    finally:
        db.close()


@router.get("/{session_id}/execution-logs")
async def get_session_execution_logs(
    session_id: int,
    limit: int = Query(20, ge=1, le=100),
) -> List[Dict[str, Any]]:
    """获取会话的执行日志"""
    from app.db.database import SessionLocal as DbSession
    from app.models.session import Session as SessionModel
    from app.models.execution_record import ExecutionRecord

    db = DbSession()
    try:
        session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")

        if not session.task_id:
            return []

        execs = db.query(ExecutionRecord).filter(
            ExecutionRecord.task_id == session.task_id
        ).order_by(ExecutionRecord.created_at.desc()).limit(limit).all()

        return [
            {
                "id": e.id,
                "status": e.status,
                "execution_type": e.execution_type,
                "duration": getattr(e, "duration", None),
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in execs
        ]
    finally:
        db.close()


@router.get("/{session_id}/task-states")
async def get_session_task_states(session_id: int) -> List[Dict[str, Any]]:
    """获取会话关联的 TaskState 记录"""
    from app.db.database import SessionLocal as DbSession
    from app.models.session import Session as SessionModel
    from app.models.task_state import TaskState

    db = DbSession()
    try:
        session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")

        if not session.task_id:
            return []

        states = db.query(TaskState).filter(
            TaskState.task_id == session.task_id
        ).order_by(TaskState.created_at.desc()).limit(10).all()

        return [s.to_dict() for s in states]
    finally:
        db.close()


@router.get("/{session_id}/results")
async def get_session_results(session_id: int) -> Dict[str, Any]:
    """
    获取会话生成的所有结果

    返回按类型分组的生成结果：
    - cases: 测试用例
    - scripts: 测试脚本
    - mindmaps: 思维导图
    - exports: 导出文件
    - feedback: 反馈
    - reviews: 审查结果
    """
    manager = get_session_manager()
    artifacts = manager.get_artifacts(session_id=session_id)

    results_by_type: Dict[str, List[Dict]] = {}
    for a in artifacts:
        art_type = a.get("artifact_type", "other")
        if art_type not in results_by_type:
            results_by_type[art_type] = []
        results_by_type[art_type].append(a)

    return {
        "session_id": session_id,
        "results": results_by_type,
        "total": len(artifacts),
        "types": list(results_by_type.keys()),
    }


@router.post("/{session_id}/resume")
async def resume_session(
    session_id: int,
    flow_name: str = Query("requirement_test_flow", description="恢复流程名称"),
) -> Dict[str, Any]:
    """
    恢复历史任务

    从上次中断的步骤继续执行。
    恢复流程：
    1. 加载会话历史状态
    2. 确定中断的步骤
    3. 通过 TaskOrchestrator 从中断点继续
    """
    manager = get_session_manager()
    state = manager.restore_session(session_id)
    if "error" in state:
        raise HTTPException(status_code=404, detail=state["error"])

    session_data = state.get("session", {})
    session_status = session_data.get("status", "")

    # 如果会话已完成，返回历史结果
    if session_status == "completed":
        return {
            "status": "already_completed",
            "session_id": session_id,
            "message": "会话已完成，无需恢复。使用 /detail 查看完整结果。",
            "stats": state.get("stats", {}),
        }

    # 返回恢复信息
    task_states = state.get("task_states", [])
    last_step = None
    if task_states:
        last_task_state = task_states[0]
        last_step = {
            "flow_name": last_task_state.get("flow_name"),
            "current_agent": last_task_state.get("current_agent"),
            "step_index": last_task_state.get("step_index"),
            "total_steps": last_task_state.get("total_steps"),
            "status": last_task_state.get("status"),
        }

    return {
        "status": "ready_to_resume",
        "session_id": session_id,
        "session_name": session_data.get("session_name"),
        "last_step": last_step,
        "requirement_text": session_data.get("requirement_text"),
        "resume_flow": flow_name,
        "stats": state.get("stats", {}),
        "message": f"会话可从步骤 {last_step['step_index'] + 1 if last_step else 0} 恢复执行。",
    }
