"""测试生命周期资产中心 API。"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.auth import require_auth
from app.models.execution_record import ExecutionRecord
from app.models.requirement_task import RequirementTask
from app.models.user import User
from app.schemas.response import Response
from app.services.asset_lifecycle import PILLARS, STAGES, AssetLifecycleService

router = APIRouter()
_service = AssetLifecycleService()


class LifecycleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    stage: str
    category: Optional[str] = None
    content: Optional[str] = None
    source: str = "manual"
    tags: Optional[list[str]] = None
    project_id: Optional[int] = None
    reusable: bool = True
    related_ids: Optional[list[int]] = None


class LifecycleUpdate(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None
    tags: Optional[list[str]] = None
    reusable: Optional[bool] = None


class LifecycleLink(BaseModel):
    target_id: int
    relation_type: Optional[str] = None


@router.get("/stages", summary="测试流程阶段")
def list_stages(
    project_id: Optional[int] = Query(default=None),
    user: User = Depends(require_auth),
):
    return Response(data={
        "pillars": _service.pillars(user.id, project_id),
        "stages": _service.stages(user.id, project_id),
        "catalog": STAGES,
        "pillar_catalog": PILLARS,
    })


@router.get("/assets", summary="按阶段列出资产")
def list_lifecycle_assets(
    stage: Optional[str] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
    asset_type: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    source: Optional[str] = Query(default=None),
    project_id: Optional[int] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(require_auth),
):
    return Response(data=_service.list_assets(
        user.id,
        stage=stage,
        keyword=keyword,
        asset_type=asset_type,
        status=status,
        source=source,
        project_id=project_id,
        page=page,
        page_size=page_size,
    ))


@router.post("/assets", summary="新建生命周期资产")
def create_lifecycle_asset(payload: LifecycleCreate, user: User = Depends(require_auth)):
    try:
        return Response(data=_service.create_asset(user.id, **payload.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/assets/{asset_id}", summary="资产详情与关联")
def get_lifecycle_asset(asset_id: int, user: User = Depends(require_auth)):
    try:
        return Response(data=_service.get_asset(user.id, asset_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/assets/{asset_id}", summary="更新资产")
def update_lifecycle_asset(asset_id: int, payload: LifecycleUpdate, user: User = Depends(require_auth)):
    try:
        return Response(data=_service.update_asset(user.id, asset_id, payload.model_dump(exclude_none=True)))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/assets/{asset_id}/link", summary="关联资产")
def link_lifecycle_asset(asset_id: int, payload: LifecycleLink, user: User = Depends(require_auth)):
    try:
        return Response(data=_service.link(user.id, asset_id, payload.target_id, payload.relation_type))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/reuse", summary="复用推荐")
def reuse_lifecycle_assets(
    keyword: str = Query(..., min_length=1),
    stage: Optional[str] = Query(default=None),
    user: User = Depends(require_auth),
):
    return Response(data=_service.reuse_candidates(user.id, keyword, stage))


@router.post("/sync", summary="把已有测试产物沉淀进资产中心")
def sync_lifecycle_assets(
    project_id: Optional[int] = Query(default=None),
    user: User = Depends(require_auth),
):
    from app.db.database import SessionLocal
    db = SessionLocal()
    created = 0
    try:
        tasks = db.query(RequirementTask).filter(RequirementTask.user_id == user.id)
        if project_id:
            tasks = tasks.filter(RequirementTask.project_id == project_id)
        for task in tasks.order_by(RequirementTask.id.desc()).limit(50).all():
            created += len(_service.sink_requirement(task))
        runs = db.query(ExecutionRecord).filter(ExecutionRecord.user_id == user.id)
        if project_id:
            runs = runs.filter(ExecutionRecord.project_id == project_id)
        for record in runs.order_by(ExecutionRecord.id.desc()).limit(50).all():
            created += len(_service.sink_execution(record))
    finally:
        db.close()
    return Response(data={"sunk": created})
