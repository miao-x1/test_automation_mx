"""
接口测试 - 测试套件管理
"""
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel as PydanticModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.response import Response
from app.models.api_case import ApiCase
from app.models.test_suite import TestSuite, SuiteExecution
from app.core.auth import require_auth
from app.models.user import User
from app.api.api_test.execution_controller import _submit_execution

router = APIRouter()


# ========== Request Models ==========

class SaveSuiteRequest(PydanticModel):
    id: Optional[int] = None
    name: str
    description: Optional[str] = None
    suite_type: str = "custom"
    case_ids: List[int] = []
    env: str = "test"
    base_url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    variables: Optional[Dict[str, Any]] = None
    concurrency: int = 1
    fail_strategy: str = "continue"
    retry_count: int = 0


@router.post("/suite/save", summary="保存/创建套件")
async def save_suite(req: SaveSuiteRequest, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    if req.id:
        suite = db.query(TestSuite).filter(TestSuite.id == req.id, TestSuite.user_id == user.id, TestSuite.is_deleted == False).first()
        if not suite:
            raise HTTPException(status_code=404, detail="套件不存在")
        suite.name = req.name
        if req.description is not None: suite.description = req.description
        suite.suite_type = req.suite_type
        suite.case_ids = json.dumps(req.case_ids, ensure_ascii=False)
        suite.env = req.env
        if req.base_url is not None: suite.base_url = req.base_url
        if req.headers is not None: suite.headers = json.dumps(req.headers, ensure_ascii=False)
        if req.variables is not None: suite.variables = json.dumps(req.variables, ensure_ascii=False)
        suite.concurrency = req.concurrency
        suite.fail_strategy = req.fail_strategy
        suite.retry_count = req.retry_count
        db.commit(); db.refresh(suite)
    else:
        suite = TestSuite(
            name=req.name, description=req.description, suite_type=req.suite_type,
            case_ids=json.dumps(req.case_ids, ensure_ascii=False), env=req.env, base_url=req.base_url,
            headers=json.dumps(req.headers, ensure_ascii=False) if req.headers else None,
            variables=json.dumps(req.variables, ensure_ascii=False) if req.variables else None,
            concurrency=req.concurrency, fail_strategy=req.fail_strategy, retry_count=req.retry_count,
            user_id=user.id, created_by=user.id,
        )
        db.add(suite); db.commit(); db.refresh(suite)
    return Response(code=200, message="保存成功", data={"id": suite.id, "name": suite.name, "suite_type": suite.suite_type, "case_count": len(req.case_ids)})


@router.get("/suite/list", summary="套件列表")
async def list_suites(suite_type: Optional[str] = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user: User = Depends(require_auth), db: Session = Depends(get_db)):
    query = db.query(TestSuite).filter(TestSuite.user_id == user.id, TestSuite.is_deleted == False)
    if suite_type: query = query.filter(TestSuite.suite_type == suite_type)
    query = query.order_by(TestSuite.updated_at.desc())
    total = query.count()
    suites = query.offset((page - 1) * page_size).limit(page_size).all()
    items = [{"id": s.id, "name": s.name, "description": s.description, "suite_type": s.suite_type,
              "status": s.status, "case_count": len(json.loads(s.case_ids) if s.case_ids else []),
              "env": s.env, "concurrency": s.concurrency, "last_run_at": s.last_run_at,
              "run_count": s.run_count, "created_at": str(s.created_at) if s.created_at else None} for s in suites]
    return Response(code=200, message="success", data={"total": total, "page": page, "page_size": page_size, "items": items})


@router.get("/suite/{suite_id}", summary="套件详情")
async def get_suite(suite_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    suite = db.query(TestSuite).filter(TestSuite.id == suite_id, TestSuite.user_id == user.id, TestSuite.is_deleted == False).first()
    if not suite:
        raise HTTPException(status_code=404, detail="套件不存在")
    case_ids = json.loads(suite.case_ids) if suite.case_ids else []
    case_summaries = []
    if case_ids:
        cases = db.query(ApiCase).filter(ApiCase.id.in_(case_ids), ApiCase.is_deleted == False).all()
        case_map = {c.id: c for c in cases}
        for cid in case_ids:
            c = case_map.get(cid)
            if c:
                case_summaries.append({"id": c.id, "case_id": c.case_id, "title": c.title, "priority": c.priority, "status": c.status, "last_run_status": c.last_run_status})
    return Response(code=200, message="success", data={
        "id": suite.id, "name": suite.name, "description": suite.description, "suite_type": suite.suite_type,
        "status": suite.status, "case_ids": case_ids, "cases": case_summaries, "env": suite.env,
        "base_url": suite.base_url, "headers": json.loads(suite.headers) if suite.headers else None,
        "variables": json.loads(suite.variables) if suite.variables else None,
        "concurrency": suite.concurrency, "fail_strategy": suite.fail_strategy, "retry_count": suite.retry_count,
    })


@router.delete("/suite/{suite_id}", summary="删除套件")
async def delete_suite(suite_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    suite = db.query(TestSuite).filter(TestSuite.id == suite_id, TestSuite.user_id == user.id).first()
    if not suite:
        raise HTTPException(status_code=404, detail="套件不存在")
    suite.is_deleted = True
    db.commit()
    return Response(code=200, message="删除成功")


@router.post("/suite/{suite_id}/run", summary="执行套件（异步）")
async def run_suite(suite_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    suite = db.query(TestSuite).filter(TestSuite.id == suite_id, TestSuite.user_id == user.id, TestSuite.is_deleted == False).first()
    if not suite:
        raise HTTPException(status_code=404, detail="套件不存在")
    case_ids = json.loads(suite.case_ids) if suite.case_ids else []
    if not case_ids:
        raise HTTPException(status_code=400, detail="套件中没有用例")

    cases = db.query(ApiCase).filter(ApiCase.id.in_(case_ids), ApiCase.is_deleted == False).all()
    if not cases:
        raise HTTPException(status_code=400, detail="用例不存在或已删除")

    case_map = {c.id: c for c in cases}

    # L3延迟编译：在execution时才触发
    from app.services.case.pipeline import CasePipeline
    case_jsons = []
    base_url = suite.base_url or "http://localhost:8080"
    for cid in case_ids:
        if cid in case_map:
            compiled = await CasePipeline.compile_for_execution(
                case_id=cid,
                base_url=base_url,
                env=suite.env or "test",
            )
            if "error" not in compiled:
                case_jsons.append(compiled)
            else:
                case_jsons.append(case_map[cid].to_case_json())

    execution_id = await _submit_execution(
        user=user, db=db, cases_json=case_jsons, env=suite.env,
        base_url=suite.base_url or "http://localhost:8080",
        headers=json.loads(suite.headers) if suite.headers else {"Content-Type": "application/json"},
        variables=json.loads(suite.variables) if suite.variables else {},
        trigger_source=f"suite_{suite.suite_type}",
    )

    suite.status = "running"
    suite.run_count = (suite.run_count or 0) + 1
    db.commit()

    suite_exec = SuiteExecution(suite_id=suite_id, execution_id=execution_id, status="waiting", total=len(case_jsons), user_id=user.id, created_by=user.id)
    db.add(suite_exec); db.commit()

    return Response(code=200, message="套件执行已提交", data={"execution_id": execution_id, "suite_id": suite_id, "case_count": len(case_jsons), "status": "queued"})


@router.get("/suite/{suite_id}/executions", summary="套件执行历史")
async def list_suite_executions(
    suite_id: int,
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(require_auth), db: Session = Depends(get_db),
):
    suite = db.query(TestSuite).filter(TestSuite.id == suite_id, TestSuite.user_id == user.id, TestSuite.is_deleted == False).first()
    if not suite:
        raise HTTPException(status_code=404, detail="套件不存在")

    query = db.query(SuiteExecution).filter(SuiteExecution.suite_id == suite_id)
    query = query.order_by(SuiteExecution.created_at.desc())
    total = query.count()
    records = query.offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for r in records:
        items.append({
            "id": r.id,
            "suite_id": r.suite_id,
            "execution_id": r.execution_id,
            "status": r.status,
            "total": r.total,
            "passed": r.passed,
            "failed": r.failed,
            "duration": r.duration,
            "created_at": str(r.created_at) if r.created_at else None,
        })

    return Response(code=200, message="success", data={"total": total, "page": page, "page_size": page_size, "items": items})
