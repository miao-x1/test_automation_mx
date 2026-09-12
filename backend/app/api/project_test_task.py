"""专业测试任务工作台 API。局部操作与全局 Agent 共用 Testing Brain。"""
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.auth import require_auth
from app.db.database import SessionLocal
from app.models.user import User
from app.schemas.response import Response
from app.services.project_agent import ProjectAgentService
from app.services.project_test_task import OPERATIONS, ProjectTestTaskService
from app.services.workspace_service import VIEW, require_owned_project

router = APIRouter()
_tasks = ProjectTestTaskService()
_agent = ProjectAgentService()


class TaskCreate(BaseModel):
    project_id: int
    name: str = Field(..., min_length=1, max_length=200)
    requirement_text: str = ""
    focus: str = ""


class TaskUpdate(BaseModel):
    name: Optional[str] = None
    focus: Optional[str] = None
    requirement_text: Optional[str] = None
    status: Optional[str] = None


class CasePayload(BaseModel):
    case_code: Optional[str] = None
    module: Optional[str] = None
    scenario: Optional[str] = None
    case_name: Optional[str] = None
    precondition: Optional[str] = None
    steps: Optional[Any] = None
    test_data: Optional[str] = None
    expected_result: Optional[str] = None
    priority: Optional[str] = "P1"
    type: Optional[str] = "functional"
    tags: Optional[Any] = None
    status: Optional[str] = "draft"


class OperatePayload(BaseModel):
    op: str
    query: Optional[str] = None
    title: Optional[str] = None
    steps: Optional[Any] = None
    expected: Optional[str] = None
    actual: Optional[str] = None


class TaskAsk(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    confirm: bool = False


def _guard(user: User, project_id: int):
    db = SessionLocal()
    try:
        return require_owned_project(db, user, project_id, VIEW)
    finally:
        db.close()


@router.get("", summary="当前项目的专业测试任务")
def list_tasks(project_id: int = Query(...), user: User = Depends(require_auth)):
    _guard(user, project_id)
    return Response(data=_tasks.list_tasks(user.id, project_id))


@router.post("", summary="创建专业测试任务")
def create_task(payload: TaskCreate, user: User = Depends(require_auth)):
    _guard(user, payload.project_id)
    try:
        return Response(data=_tasks.create_task(
            user.id, payload.project_id, payload.name,
            requirement_text=payload.requirement_text, focus=payload.focus,
        ))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{task_id}", summary="测试任务工作台")
def get_workspace(task_id: int, project_id: int = Query(...), user: User = Depends(require_auth)):
    _guard(user, project_id)
    try:
        return Response(data=_tasks.get_workspace(user.id, project_id, task_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{task_id}", summary="更新测试任务")
def update_task(task_id: int, payload: TaskUpdate, project_id: int = Query(...), user: User = Depends(require_auth)):
    _guard(user, project_id)
    try:
        return Response(data=_tasks.update_task(user.id, project_id, task_id, **payload.model_dump(exclude_none=True)))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{task_id}/cases", summary="专业测试用例表")
def list_cases(task_id: int, project_id: int = Query(...), user: User = Depends(require_auth)):
    _guard(user, project_id)
    try:
        return Response(data=_tasks.list_cases(user.id, project_id, task_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{task_id}/cases", summary="新增测试用例")
def create_case(task_id: int, payload: CasePayload, project_id: int = Query(...), user: User = Depends(require_auth)):
    _guard(user, project_id)
    try:
        return Response(data=_tasks.upsert_case(user.id, project_id, task_id, payload.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{task_id}/cases/{case_id}", summary="编辑测试用例")
def update_case(task_id: int, case_id: int, payload: CasePayload, project_id: int = Query(...), user: User = Depends(require_auth)):
    _guard(user, project_id)
    try:
        return Response(data=_tasks.upsert_case(user.id, project_id, task_id, payload.model_dump(), case_id=case_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{task_id}/cases/{case_id}", summary="删除测试用例")
def delete_case(task_id: int, case_id: int, project_id: int = Query(...), user: User = Depends(require_auth)):
    _guard(user, project_id)
    try:
        return Response(data=_tasks.delete_case(user.id, project_id, task_id, case_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{task_id}/cases/export", summary="导出测试用例")
def export_cases(task_id: int, project_id: int = Query(...), user: User = Depends(require_auth)):
    _guard(user, project_id)
    try:
        return Response(data=_tasks.export_cases(user.id, project_id, task_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{task_id}/operations", summary="可独立完成的局部操作")
def list_operations():
    return Response(data=OPERATIONS)


@router.post("/{task_id}/operations", summary="在当前任务上执行局部 AI 操作")
def operate(task_id: int, payload: OperatePayload, project_id: int = Query(...), user: User = Depends(require_auth)):
    _guard(user, project_id)
    try:
        return Response(data=_tasks.operate(user.id, project_id, task_id, payload.op, payload.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{task_id}/agent/ask", summary="任务内 Agent，共享全局 Testing Brain")
def task_ask(task_id: int, payload: TaskAsk, project_id: int = Query(...), user: User = Depends(require_auth)):
    _guard(user, project_id)
    try:
        return Response(data=_agent.ask(
            user.id, project_id, payload.question,
            workspace="design", confirm=payload.confirm, test_task_id=task_id,
        ))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
