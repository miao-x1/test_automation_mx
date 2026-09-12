"""项目理解 / 代码索引 / Project Memory / 全局项目 Agent。"""
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.core.auth import require_auth
from app.db.database import SessionLocal
from app.models.user import User
from app.schemas.response import Response
from app.services.project_agent import ProjectAgentService
from app.services.project_indexer import ProjectIndexer
from app.services.project_memory import ProjectMemoryService
from app.services.project_understanding import ProjectUnderstandingService
from app.services.workspace_service import VIEW, require_owned_project

router = APIRouter()
_indexer = ProjectIndexer()
_memory = ProjectMemoryService()
_agent = ProjectAgentService()
_understanding = ProjectUnderstandingService()


class ImportGithub(BaseModel):
    project_id: int
    repo_url: str = Field(..., min_length=8, max_length=500)


class ImportLocal(BaseModel):
    project_id: int
    local_path: str = Field(..., min_length=2, max_length=500)


class AgentAsk(BaseModel):
    project_id: int
    question: str = Field(..., min_length=1, max_length=2000)
    workspace: str = "understand"
    confirm: bool = False
    test_task_id: Optional[int] = None


class MemoryWrite(BaseModel):
    project_id: int
    kind: str
    title: str
    content: str
    workspace: Optional[str] = None


def _guard(user: User, project_id: int):
    db = SessionLocal()
    try:
        return require_owned_project(db, user, project_id, VIEW)
    finally:
        db.close()


def _import_git(payload: ImportGithub, user: User):
    _guard(user, payload.project_id)
    if not (payload.repo_url or "").strip():
        raise HTTPException(status_code=400, detail="请输入 Git 仓库地址")
    try:
        return Response(data=_indexer.import_git(user.id, payload.project_id, payload.repo_url))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/import/github", summary="导入 Git 项目并建立代码索引")
def import_github(payload: ImportGithub, user: User = Depends(require_auth)):
    return _import_git(payload, user)


@router.post("/import/git", summary="导入 GitHub / GitLab / Gitee 仓库")
def import_git(payload: ImportGithub, user: User = Depends(require_auth)):
    return _import_git(payload, user)


@router.post("/import/archive", summary="上传本地项目 ZIP 并建立索引")
async def import_archive(
    project_id: int = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(require_auth),
):
    _guard(user, project_id)
    payload = await file.read()
    try:
        return Response(data=_indexer.import_archive(user.id, project_id, file.filename or "project.zip", payload))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/import/local", summary="导入本地代码目录（仅夹具或已下载快照）")
def import_local(payload: ImportLocal, user: User = Depends(require_auth)):
    _guard(user, payload.project_id)
    try:
        return Response(data=_indexer.import_local(user.id, payload.project_id, payload.local_path))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class ImportSample(BaseModel):
    project_id: int


@router.post("/import/sample", summary="导入内置示例代码项目")
def import_sample(payload: ImportSample, user: User = Depends(require_auth)):
    _guard(user, payload.project_id)
    try:
        return Response(data=_indexer.import_sample(user.id, payload.project_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/overview", summary="项目理解结果")
def overview(project_id: int = Query(...), user: User = Depends(require_auth)):
    _guard(user, project_id)
    return Response(data=_indexer.overview(user.id, project_id))


@router.get("/understanding", summary="编译后的项目理解知识")
def understanding(
    project_id: int = Query(...),
    refresh: bool = Query(default=False),
    user: User = Depends(require_auth),
):
    _guard(user, project_id)
    return Response(data=_understanding.snapshot(user.id, project_id, refresh=refresh))


class AnalyzeBody(BaseModel):
    project_id: int
    mode: str = "incremental"


@router.post("/analyze", summary="重新分析已导入项目")
def analyze(payload: AnalyzeBody, user: User = Depends(require_auth)):
    _guard(user, payload.project_id)
    mode = payload.mode if payload.mode in {"incremental", "full"} else "incremental"
    try:
        return Response(data=_indexer.analyze(user.id, payload.project_id, mode=mode))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class CasePreview(BaseModel):
    project_id: int
    query: str = Field(..., min_length=1, max_length=500)


@router.post("/cases/preview", summary="预览将生成的测试用例，不写入资产")
def preview_cases(payload: CasePreview, user: User = Depends(require_auth)):
    _guard(user, payload.project_id)
    from app.services.testing_brain import build_professional_cases, infer_module
    module = infer_module(payload.query)
    return Response(data={"module": module, "cases": build_professional_cases(module, payload.query)})


@router.get("/file", summary="读取已导入源码文件")
def read_source_file(
    project_id: int = Query(...),
    path: str = Query(..., min_length=1, max_length=512),
    user: User = Depends(require_auth),
):
    _guard(user, project_id)
    try:
        return Response(data=_indexer.read_file(user.id, project_id, path))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/index", summary="查询代码索引")
def list_index(
    project_id: int = Query(...),
    keyword: Optional[str] = Query(default=None),
    kind: Optional[str] = Query(default=None),
    path: Optional[str] = Query(default=None),
    user: User = Depends(require_auth),
):
    _guard(user, project_id)
    return Response(data=_indexer.query_index(user.id, project_id, keyword=keyword, kind=kind, path=path))


@router.get("/memory", summary="读取共享 Project Memory")
def get_memory(project_id: int = Query(...), user: User = Depends(require_auth)):
    _guard(user, project_id)
    return Response(data=_memory.snapshot(user.id, project_id))


@router.post("/memory", summary="写入项目记忆")
def write_memory(payload: MemoryWrite, user: User = Depends(require_auth)):
    _guard(user, payload.project_id)
    try:
        return Response(data=_memory.remember(
            user.id, payload.project_id, kind=payload.kind, title=payload.title,
            content=payload.content, workspace=payload.workspace,
        ))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/agent/ask", summary="项目级 Agent 问答")
def agent_ask(payload: AgentAsk, user: User = Depends(require_auth)):
    _guard(user, payload.project_id)
    workspace = payload.workspace if payload.workspace in {"understand", "design", "execute"} else "understand"
    try:
        return Response(data=_agent.ask(
            user.id, payload.project_id, payload.question, workspace=workspace,
            confirm=payload.confirm, test_task_id=payload.test_task_id,
        ))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
