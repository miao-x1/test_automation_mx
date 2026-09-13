"""项目理解 / 代码索引 / Project Memory / 全局项目 Agent。"""
import json
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
from app.services.requirement_analysis_doc import RequirementAnalysisDocService, extract_file_text
from app.services.test_design_doc import TestDesignDocService
from app.services.test_pipeline import TestPipelineService
from app.services.workspace_service import VIEW, require_owned_project

_requirement_docs = RequirementAnalysisDocService()
_test_designs = TestDesignDocService()
_pipeline = TestPipelineService()

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
    question: str = Field(..., min_length=1, max_length=16000)
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
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"导入 ZIP 失败：{exc}") from exc


@router.post("/import/folder", summary="上传本地文件夹并建立索引")
async def import_folder(
    project_id: int = Form(...),
    paths_json: str = Form(...),
    files: list[UploadFile] = File(...),
    user: User = Depends(require_auth),
):
    _guard(user, project_id)
    try:
        paths = json.loads(paths_json or "[]")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="文件夹路径无效") from exc
    if not isinstance(paths, list) or len(paths) != len(files):
        raise HTTPException(status_code=400, detail="文件与路径数量不一致")
    items: list[tuple[str, bytes]] = []
    for path, uploaded in zip(paths, files):
        items.append((str(path or uploaded.filename or ""), await uploaded.read()))
    try:
        return Response(data=_indexer.import_files(user.id, project_id, items))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"导入文件夹失败：{exc}") from exc


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


class RequirementAnalyzeBody(BaseModel):
    project_id: int
    text: str = ""
    answers: Optional[list[dict]] = None


class RequirementPatchBody(BaseModel):
    project_id: int
    document: dict = Field(default_factory=dict)


class RequirementConfirmBody(BaseModel):
    project_id: int


@router.get("/requirement-analysis", summary="读取项目需求分析结果")
def get_requirement_analysis(project_id: int = Query(...), user: User = Depends(require_auth)):
    _guard(user, project_id)
    return Response(data=_requirement_docs.get(user.id, project_id))


@router.post("/requirement-analysis", summary="分析需求材料并写入结构化结果")
def analyze_requirement_text(payload: RequirementAnalyzeBody, user: User = Depends(require_auth)):
    _guard(user, payload.project_id)
    try:
        return Response(data=_requirement_docs.analyze(
            user.id, payload.project_id, payload.text or "",
            answers=payload.answers,
            project_name="",
        ))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/requirement-analysis/upload", summary="上传需求文档并分析")
async def analyze_requirement_upload(
    project_id: int = Form(...),
    text: str = Form(""),
    files: list[UploadFile] = File(default=[]),
    user: User = Depends(require_auth),
):
    _guard(user, project_id)
    parts = [text.strip()] if text and text.strip() else []
    source_files: list[dict] = []
    for uploaded in files or []:
        payload = await uploaded.read()
        name = uploaded.filename or "file"
        extracted = extract_file_text(name, payload)
        if extracted.strip():
            parts.append(f"【文件 {name}】\n{extracted.strip()}")
            source_files.append({"name": name, "chars": len(extracted)})
    try:
        return Response(data=_requirement_docs.analyze(
            user.id, project_id, "\n\n".join(parts),
            source_files=source_files,
        ))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/requirement-analysis", summary="修改需求分析结果")
def patch_requirement_analysis(payload: RequirementPatchBody, user: User = Depends(require_auth)):
    _guard(user, payload.project_id)
    try:
        return Response(data=_requirement_docs.save_edits(user.id, payload.project_id, payload.document or {}))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/requirement-analysis/confirm", summary="确认需求分析结果，供测试设计使用")
def confirm_requirement_analysis(payload: RequirementConfirmBody, user: User = Depends(require_auth)):
    _guard(user, payload.project_id)
    try:
        return Response(data=_requirement_docs.confirm(user.id, payload.project_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class TestDesignBody(BaseModel):
    project_id: int
    answers: Optional[list[dict]] = None


class TestDesignPatchBody(BaseModel):
    project_id: int
    document: dict = Field(default_factory=dict)


class TestDesignConfirmBody(BaseModel):
    project_id: int


@router.get("/test-design", summary="读取项目测试设计结果")
def get_test_design(project_id: int = Query(...), user: User = Depends(require_auth)):
    _guard(user, project_id)
    return Response(data=_test_designs.get(user.id, project_id))


@router.post("/test-design", summary="基于需求分析结果生成测试设计")
def create_test_design(payload: TestDesignBody, user: User = Depends(require_auth)):
    _guard(user, payload.project_id)
    try:
        return Response(data=_test_designs.design(user.id, payload.project_id, answers=payload.answers))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/test-design", summary="修改测试设计结果")
def patch_test_design(payload: TestDesignPatchBody, user: User = Depends(require_auth)):
    _guard(user, payload.project_id)
    try:
        return Response(data=_test_designs.save_edits(user.id, payload.project_id, payload.document or {}))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/test-design/confirm", summary="确认测试设计，供测试用例生成使用")
def confirm_test_design(payload: TestDesignConfirmBody, user: User = Depends(require_auth)):
    _guard(user, payload.project_id)
    try:
        return Response(data=_test_designs.confirm(user.id, payload.project_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class PipelineProject(BaseModel):
    project_id: int


class PrepDataBody(BaseModel):
    project_id: int
    count: int = Field(default=20, ge=1, le=500)


class PrepAccountBody(BaseModel):
    project_id: int
    count: int = Field(default=10, ge=1, le=200)
    roles: Optional[list[str]] = None


class PrepAccountBatchBody(BaseModel):
    project_id: int
    ids: list[str]
    action: str


class RunBatchBody(BaseModel):
    project_id: int
    case_ids: Optional[list[int]] = None
    env: str = ""


class RunResultBody(BaseModel):
    project_id: int
    batch_id: str
    updates: list[dict]
    executor: str = ""


class BugDraftBody(BaseModel):
    project_id: int
    batch_id: Optional[str] = None


class BugSubmitBody(BaseModel):
    project_id: int
    bug: dict = Field(default_factory=dict)


class BugVerifyBody(BaseModel):
    project_id: int
    bug_id: str
    result: str
    actual: str
    evidence: Optional[list] = None
    executor: str = ""


class RegressionBody(BaseModel):
    project_id: int
    bug_ids: list[str]
    version: str = ""


class RegressionResultBody(BaseModel):
    project_id: int
    batch_id: str
    updates: list[dict]


@router.get("/pipeline/snapshot", summary="测试链路汇总")
def pipeline_snapshot(project_id: int = Query(...), user: User = Depends(require_auth)):
    _guard(user, project_id)
    return Response(data=_pipeline.snapshot(user.id, project_id))


@router.get("/pipeline/cases", summary="当前项目测试用例")
def pipeline_cases(project_id: int = Query(...), user: User = Depends(require_auth)):
    _guard(user, project_id)
    return Response(data=_pipeline.list_cases(user.id, project_id))


@router.get("/pipeline/prep", summary="测试准备包")
def pipeline_prep(project_id: int = Query(...), user: User = Depends(require_auth)):
    _guard(user, project_id)
    return Response(data=_pipeline.get_prep(user.id, project_id))


@router.post("/pipeline/prep/data", summary="批量生成测试数据")
def pipeline_prep_data(payload: PrepDataBody, user: User = Depends(require_auth)):
    _guard(user, payload.project_id)
    try:
        return Response(data=_pipeline.generate_data(user.id, payload.project_id, payload.count))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/pipeline/prep/accounts", summary="批量生成测试账号清单")
def pipeline_prep_accounts(payload: PrepAccountBody, user: User = Depends(require_auth)):
    _guard(user, payload.project_id)
    try:
        return Response(data=_pipeline.generate_accounts(user.id, payload.project_id, payload.count, payload.roles))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/pipeline/prep/accounts/batch", summary="批量启用/禁用/回收账号清单")
def pipeline_prep_account_batch(payload: PrepAccountBatchBody, user: User = Depends(require_auth)):
    _guard(user, payload.project_id)
    try:
        return Response(data=_pipeline.account_batch(user.id, payload.project_id, payload.ids, payload.action))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/pipeline/prep/accounts/export", summary="导出账号清单 CSV")
def pipeline_prep_export(project_id: int = Query(...), user: User = Depends(require_auth)):
    _guard(user, project_id)
    return Response(data={"csv": _pipeline.export_accounts(user.id, project_id)})


@router.post("/pipeline/prep/env-check", summary="测试环境检查")
def pipeline_prep_env(payload: PipelineProject, user: User = Depends(require_auth)):
    _guard(user, payload.project_id)
    return Response(data=_pipeline.check_environment(user.id, payload.project_id))


@router.get("/pipeline/runs", summary="测试执行批次")
def pipeline_runs(project_id: int = Query(...), user: User = Depends(require_auth)):
    _guard(user, project_id)
    return Response(data=_pipeline.get_runs(user.id, project_id))


@router.post("/pipeline/runs", summary="创建执行批次")
def pipeline_create_run(payload: RunBatchBody, user: User = Depends(require_auth)):
    _guard(user, payload.project_id)
    try:
        return Response(data=_pipeline.create_run_batch(user.id, payload.project_id, payload.case_ids, payload.env))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/pipeline/runs/results", summary="批量记录执行结果")
def pipeline_run_results(payload: RunResultBody, user: User = Depends(require_auth)):
    _guard(user, payload.project_id)
    try:
        return Response(data=_pipeline.record_results(user.id, payload.project_id, payload.batch_id, payload.updates, payload.executor))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/pipeline/defects", summary="缺陷列表")
def pipeline_defects(project_id: int = Query(...), user: User = Depends(require_auth)):
    _guard(user, project_id)
    return Response(data=_pipeline.get_defects(user.id, project_id))


@router.post("/pipeline/defects/draft", summary="从失败执行生成缺陷草稿")
def pipeline_defect_draft(payload: BugDraftBody, user: User = Depends(require_auth)):
    _guard(user, payload.project_id)
    try:
        return Response(data=_pipeline.draft_bugs_from_fails(user.id, payload.project_id, payload.batch_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/pipeline/defects", summary="确认并提交缺陷")
def pipeline_defect_submit(payload: BugSubmitBody, user: User = Depends(require_auth)):
    _guard(user, payload.project_id)
    try:
        return Response(data=_pipeline.submit_bug(user.id, payload.project_id, payload.bug or {}))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/pipeline/defects/verify", summary="缺陷验证")
def pipeline_defect_verify(payload: BugVerifyBody, user: User = Depends(require_auth)):
    _guard(user, payload.project_id)
    try:
        return Response(data=_pipeline.verify_bug(
            user.id, payload.project_id, payload.bug_id, payload.result, payload.actual, payload.evidence, payload.executor,
        ))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/pipeline/regressions", summary="回归批次")
def pipeline_regs(project_id: int = Query(...), user: User = Depends(require_auth)):
    _guard(user, project_id)
    return Response(data=_pipeline.get_regressions(user.id, project_id))


@router.post("/pipeline/regressions/recommend", summary="按缺陷推荐回归用例")
def pipeline_reg_recommend(payload: RegressionBody, user: User = Depends(require_auth)):
    _guard(user, payload.project_id)
    try:
        return Response(data=_pipeline.recommend_regression(user.id, payload.project_id, payload.bug_ids))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/pipeline/regressions", summary="创建回归批次")
def pipeline_reg_create(payload: RegressionBody, user: User = Depends(require_auth)):
    _guard(user, payload.project_id)
    try:
        return Response(data=_pipeline.create_regression(user.id, payload.project_id, payload.bug_ids, payload.version))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/pipeline/regressions/results", summary="记录回归结果")
def pipeline_reg_results(payload: RegressionResultBody, user: User = Depends(require_auth)):
    _guard(user, payload.project_id)
    try:
        return Response(data=_pipeline.record_regression(user.id, payload.project_id, payload.batch_id, payload.updates))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/pipeline/reports", summary="测试报告列表")
def pipeline_reports(project_id: int = Query(...), user: User = Depends(require_auth)):
    _guard(user, project_id)
    return Response(data=_pipeline.get_reports(user.id, project_id))


@router.post("/pipeline/reports", summary="汇总生成测试报告")
def pipeline_report_create(payload: PipelineProject, user: User = Depends(require_auth)):
    _guard(user, payload.project_id)
    return Response(data=_pipeline.generate_report(user.id, payload.project_id))
