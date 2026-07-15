"""
接口测试 - 用例管理 + 目录管理
"""
import copy
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel as PydanticModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.response import Response
from app.models.api_case import ApiCase, ApiCaseFolder
from app.core.auth import require_auth
from app.models.user import User

router = APIRouter()


# ========== Request Models ==========

class SaveCaseRequest(PydanticModel):
    id: Optional[int] = None
    title: str
    case_id: Optional[str] = None
    description: Optional[str] = None
    folder_id: Optional[int] = None
    priority: str = "medium"
    status: str = "draft"
    tags: Optional[str] = None
    precondition: Optional[str] = None
    steps: List[Dict[str, Any]] = []
    assertions: List[Dict[str, Any]] = []
    extracts: List[Dict[str, Any]] = []
    env_override: Optional[Dict[str, Any]] = None


class SaveFolderRequest(PydanticModel):
    id: Optional[int] = None
    name: str
    parent_id: Optional[int] = None
    description: Optional[str] = None
    sort_order: int = 0


# ========== 用例管理 ==========

@router.post("/cases/save", summary="保存/创建用例")
async def save_case(req: SaveCaseRequest, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    if req.id:
        case = db.query(ApiCase).filter(ApiCase.id == req.id, ApiCase.user_id == user.id, ApiCase.is_deleted == False).first()
        if not case:
            raise HTTPException(status_code=404, detail="用例不存在")
        case.title = req.title
        if req.case_id is not None: case.case_id = req.case_id
        if req.description is not None: case.description = req.description
        if req.folder_id is not None: case.folder_id = req.folder_id
        case.priority = req.priority
        case.status = req.status
        if req.tags is not None: case.tags = req.tags
        if req.precondition is not None: case.precondition = req.precondition
        case.steps = json.dumps(req.steps, ensure_ascii=False)
        case.assertions = json.dumps(req.assertions, ensure_ascii=False) if req.assertions else None
        case.extracts = json.dumps(req.extracts, ensure_ascii=False) if req.extracts else None
        if req.env_override is not None: case.env_override = json.dumps(req.env_override, ensure_ascii=False)
        case.version = (case.version or 1) + 1
        db.commit(); db.refresh(case)
    else:
        case = ApiCase(
            title=req.title, case_id=req.case_id, description=req.description,
            folder_id=req.folder_id, priority=req.priority, status=req.status,
            tags=req.tags, precondition=req.precondition,
            steps=json.dumps(req.steps, ensure_ascii=False),
            assertions=json.dumps(req.assertions, ensure_ascii=False) if req.assertions else None,
            extracts=json.dumps(req.extracts, ensure_ascii=False) if req.extracts else None,
            env_override=json.dumps(req.env_override, ensure_ascii=False) if req.env_override else None,
            user_id=user.id, created_by=user.id,
        )
        db.add(case); db.commit(); db.refresh(case)

    return Response(code=200, message="保存成功", data={"id": case.id, "case_id": case.case_id, "title": case.title, "status": case.status, "version": case.version})


@router.get("/cases/list", summary="用例列表")
async def list_cases(
    folder_id: Optional[int] = None, priority: Optional[str] = None,
    status: Optional[str] = None, keyword: Optional[str] = None,
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(require_auth), db: Session = Depends(get_db),
):
    query = db.query(ApiCase).filter(ApiCase.user_id == user.id, ApiCase.is_deleted == False)
    if folder_id is not None: query = query.filter(ApiCase.folder_id == folder_id)
    if priority: query = query.filter(ApiCase.priority == priority)
    if status: query = query.filter(ApiCase.status == status)
    if keyword: query = query.filter(ApiCase.title.contains(keyword))
    query = query.order_by(ApiCase.updated_at.desc())
    total = query.count()
    cases = query.offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for c in cases:
        items.append({
            "id": c.id, "case_id": c.case_id, "title": c.title, "description": c.description,
            "folder_id": c.folder_id, "priority": c.priority, "status": c.status, "tags": c.tags,
            "steps": json.loads(c.steps) if c.steps else [],
            "assertions": json.loads(c.assertions) if c.assertions else [],
            "extracts": json.loads(c.extracts) if c.extracts else [],
            "version": c.version, "last_run_status": c.last_run_status, "run_count": c.run_count,
            "created_at": str(c.created_at) if c.created_at else None,
            "updated_at": str(c.updated_at) if c.updated_at else None,
        })
    return Response(code=200, message="success", data={"total": total, "page": page, "page_size": page_size, "items": items})


@router.get("/cases/{case_id}", summary="用例详情")
async def get_case(case_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    case = db.query(ApiCase).filter(ApiCase.id == case_id, ApiCase.user_id == user.id, ApiCase.is_deleted == False).first()
    if not case:
        raise HTTPException(status_code=404, detail="用例不存在")
    return Response(code=200, message="success", data={
        "id": case.id, "case_id": case.case_id, "title": case.title, "description": case.description,
        "folder_id": case.folder_id, "priority": case.priority, "status": case.status, "tags": case.tags,
        "precondition": case.precondition,
        "steps": json.loads(case.steps) if case.steps else [],
        "assertions": json.loads(case.assertions) if case.assertions else [],
        "extracts": json.loads(case.extracts) if case.extracts else [],
        "env_override": json.loads(case.env_override) if case.env_override else None,
        "version": case.version, "last_run_status": case.last_run_status, "last_run_at": case.last_run_at,
        "run_count": case.run_count,
    })


@router.delete("/cases/{case_id}", summary="删除用例")
async def delete_case(case_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    case = db.query(ApiCase).filter(ApiCase.id == case_id, ApiCase.user_id == user.id).first()
    if not case:
        raise HTTPException(status_code=404, detail="用例不存在")
    case.is_deleted = True
    db.commit()
    return Response(code=200, message="删除成功")


@router.post("/cases/copy/{case_id}", summary="复制用例")
async def copy_case(case_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    case = db.query(ApiCase).filter(ApiCase.id == case_id, ApiCase.user_id == user.id, ApiCase.is_deleted == False).first()
    if not case:
        raise HTTPException(status_code=404, detail="用例不存在")

    steps_data = json.loads(case.steps) if case.steps else []
    assertions_data = json.loads(case.assertions) if case.assertions else []
    extracts_data = json.loads(case.extracts) if case.extracts else []
    env_override_data = json.loads(case.env_override) if case.env_override else None

    new_case = ApiCase(
        title=case.title + "（副本）",
        case_id=case.case_id,
        description=case.description,
        folder_id=case.folder_id,
        priority=case.priority,
        status="draft",
        tags=case.tags,
        precondition=case.precondition,
        steps=json.dumps(copy.deepcopy(steps_data), ensure_ascii=False),
        assertions=json.dumps(copy.deepcopy(assertions_data), ensure_ascii=False) if assertions_data else None,
        extracts=json.dumps(copy.deepcopy(extracts_data), ensure_ascii=False) if extracts_data else None,
        env_override=json.dumps(copy.deepcopy(env_override_data), ensure_ascii=False) if env_override_data else None,
        user_id=user.id,
        created_by=user.id,
    )
    db.add(new_case); db.commit(); db.refresh(new_case)

    return Response(code=200, message="复制成功", data={"id": new_case.id, "title": new_case.title, "status": new_case.status})


# ========== 目录管理 ==========

@router.post("/folders/save", summary="保存/创建目录")
async def save_folder(req: SaveFolderRequest, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    if req.id:
        folder = db.query(ApiCaseFolder).filter(ApiCaseFolder.id == req.id, ApiCaseFolder.user_id == user.id, ApiCaseFolder.is_deleted == False).first()
        if not folder:
            raise HTTPException(status_code=404, detail="目录不存在")
        folder.name = req.name
        if req.parent_id is not None: folder.parent_id = req.parent_id
        if req.description is not None: folder.description = req.description
        folder.sort_order = req.sort_order
        db.commit(); db.refresh(folder)
    else:
        folder = ApiCaseFolder(name=req.name, parent_id=req.parent_id, description=req.description, sort_order=req.sort_order, user_id=user.id, created_by=user.id)
        db.add(folder); db.commit(); db.refresh(folder)
    return Response(code=200, message="保存成功", data={"id": folder.id, "name": folder.name, "parent_id": folder.parent_id})


@router.get("/folders/tree", summary="目录树")
async def get_folder_tree(user: User = Depends(require_auth), db: Session = Depends(get_db)):
    folders = db.query(ApiCaseFolder).filter(ApiCaseFolder.user_id == user.id, ApiCaseFolder.is_deleted == False).order_by(ApiCaseFolder.sort_order.asc()).all()
    folder_case_counts = {}
    for f in folders:
        count = db.query(ApiCase).filter(ApiCase.folder_id == f.id, ApiCase.is_deleted == False).count()
        folder_case_counts[f.id] = count

    def build_tree(parent_id=None):
        return [{"id": f.id, "name": f.name, "description": f.description, "sort_order": f.sort_order,
                 "case_count": folder_case_counts.get(f.id, 0), "children": build_tree(f.id)}
                for f in folders if f.parent_id == parent_id]

    return Response(code=200, message="success", data=build_tree())


@router.delete("/folders/{folder_id}", summary="删除目录")
async def delete_folder(folder_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    folder = db.query(ApiCaseFolder).filter(ApiCaseFolder.id == folder_id, ApiCaseFolder.user_id == user.id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="目录不存在")
    db.query(ApiCase).filter(ApiCase.folder_id == folder_id).update({"folder_id": None})
    folder.is_deleted = True
    db.commit()
    return Response(code=200, message="删除成功")
