"""
接口测试 - 执行引擎
"""
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel as PydanticModel
from sqlalchemy.orm import Session

from app.db.database import get_db, SessionLocal
from app.schemas.response import Response
from app.models.api_case import ApiCase
from app.models.case_content import CaseContent
from app.models.execution_record import ExecutionRecord, ExecutionStatus
from app.models.task import Task
from app.core.auth import require_auth
from app.models.user import User

router = APIRouter()


# ========== Request Models ==========

class RunExecutionRequest(PydanticModel):
    case_ids: List[int] = []
    task_id: Optional[int] = None
    env: str = "test"
    base_url: str = "http://localhost:8080"
    headers: Dict[str, str] = {}
    variables: Dict[str, Any] = {}


class RunCaseJsonRequest(PydanticModel):
    cases: List[Dict[str, Any]]
    env: str = "test"
    base_url: str = "http://localhost:8080"
    headers: Dict[str, str] = {}
    variables: Dict[str, Any] = {}


# ========== Helper ==========

def _get_or_create_virtual_task(db: Session, user: User) -> Task:
    virtual_task = db.query(Task).filter(Task.task_name == "__execution_engine__").first()
    if not virtual_task:
        virtual_task = Task(
            task_name="__execution_engine__",
            page_url="",
            status="completed",
            user_id=user.id,
            created_by=user.id,
        )
        db.add(virtual_task)
        db.commit()
        db.refresh(virtual_task)
    return virtual_task


async def _submit_execution(
    user: User, db: Session, cases_json: List[Dict], env: str,
    base_url: str, headers: Dict, variables: Dict, trigger_source: str,
):
    """统一的执行提交逻辑"""
    virtual_task = _get_or_create_virtual_task(db, user)

    from app.services.execution.result_writer import ResultWriter
    execution_id = ResultWriter.create_execution(
        task_id=virtual_task.id,
        trigger_source=trigger_source,
        env=env,
    )

    record = db.query(ExecutionRecord).filter(ExecutionRecord.id == execution_id).first()
    if record:
        record.user_id = user.id
        record.created_by = user.id
        db.commit()

    context_config = {
        "base_url": base_url,
        "headers": headers or {"Content-Type": "application/json"},
        "variables": variables,
        "env": env,
    }

    from app.services.execution.redis_queue import get_execution_queue
    queue = get_execution_queue()
    await queue.submit(
        execution_id=execution_id,
        cases=cases_json,
        context_config=context_config,
    )

    return execution_id


# ========== 执行引擎端点 ==========

@router.post("/execution/run", summary="⚠ 废弃：请使用 POST /execution/run/asset", deprecated=True)
async def run_execution(req: RunExecutionRequest, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    # 加载用例
    query = db.query(ApiCase).filter(ApiCase.is_deleted == False)
    if req.case_ids:
        query = query.filter(ApiCase.id.in_(req.case_ids))
    elif req.task_id:
        # 从CaseContent加载
        ccs = db.query(CaseContent).filter(CaseContent.case_task_id == req.task_id, CaseContent.is_deleted == False).all()
        cases_json = []
        for cc in ccs:
            steps = json.loads(cc.steps) if cc.steps else []
            assertions = json.loads(cc.expected) if cc.expected else []
            if isinstance(assertions, dict): assertions = [assertions]
            cases_json.append({"case_id": f"C{cc.id}", "title": cc.title, "type": cc.case_type, "steps": steps, "assertions": assertions})
        if not cases_json:
            raise HTTPException(status_code=400, detail="未找到可执行的用例")
        execution_id = await _submit_execution(user, db, cases_json, req.env, req.base_url, req.headers, req.variables, "api_test")
        return Response(code=200, message="执行任务已提交", data={"execution_id": execution_id, "status": "queued", "case_count": len(cases_json)})
    else:
        raise HTTPException(status_code=400, detail="请指定 case_ids 或 task_id")

    api_cases = query.all()
    if not api_cases:
        raise HTTPException(status_code=400, detail="未找到可执行的用例")

    # L3延迟编译：在execution时才触发L3编译（变量解析+URL补全+schema标准化）
    from app.services.case.pipeline import CasePipeline
    cases_json = []
    for c in api_cases:
        compiled = await CasePipeline.compile_for_execution(
            case_id=c.id,
            base_url=req.base_url or "http://localhost:8080",
            env=req.env or "test",
        )
        if "error" not in compiled:
            cases_json.append(compiled)
        else:
            # 降级：使用旧格式
            cases_json.append(c.to_case_json())

    execution_id = await _submit_execution(user, db, cases_json, req.env, req.base_url, req.headers, req.variables, "api_test")

    return Response(code=200, message="执行任务已提交", data={"execution_id": execution_id, "status": "queued", "case_count": len(cases_json)})


@router.post("/execution/run/json", summary="⚠ 废弃：请使用 POST /execution/run/asset", deprecated=True)
async def run_execution_json(req: RunCaseJsonRequest, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    if not req.cases:
        raise HTTPException(status_code=400, detail="用例列表不能为空")
    execution_id = await _submit_execution(user, db, req.cases, req.env, req.base_url, req.headers, req.variables, "api_test_json")
    return Response(code=200, message="执行任务已提交", data={"execution_id": execution_id, "status": "queued", "case_count": len(req.cases)})


@router.get("/execution/{execution_id}", summary="查询执行状态")
async def get_execution_status(execution_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    record = db.query(ExecutionRecord).filter(ExecutionRecord.id == execution_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    analysis = None
    if record.analysis_result:
        try: analysis = json.loads(record.analysis_result)
        except Exception: pass
    return Response(code=200, message="success", data={
        "execution_id": record.id, "task_id": record.task_id, "status": record.status,
        "trigger_source": record.trigger_source, "duration": record.duration,
        "success_count": record.success_count, "failed_count": record.failed_count,
        "error_message": record.error_message, "created_at": str(record.created_at) if record.created_at else None,
        "analysis": analysis,
    })


@router.get("/execution/list", summary="执行历史")
async def list_executions(status: Optional[str] = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user: User = Depends(require_auth), db: Session = Depends(get_db)):
    query = db.query(ExecutionRecord).filter(ExecutionRecord.user_id == user.id)
    if status: query = query.filter(ExecutionRecord.status == status)
    query = query.order_by(ExecutionRecord.created_at.desc())
    total = query.count()
    records = query.offset((page - 1) * page_size).limit(page_size).all()
    items = [{"execution_id": r.id, "task_id": r.task_id, "status": r.status, "trigger_source": r.trigger_source,
              "duration": r.duration, "success_count": r.success_count, "failed_count": r.failed_count,
              "created_at": str(r.created_at) if r.created_at else None} for r in records]
    return Response(code=200, message="success", data={"total": total, "page": page, "page_size": page_size, "items": items})


@router.post("/execution/retry/{execution_id}", summary="重跑执行")
async def retry_execution(execution_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    record = db.query(ExecutionRecord).filter(ExecutionRecord.id == execution_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="执行记录不存在")

    # 从原始执行记录获取 task_id 对应的用例
    from app.models.task import Task
    task = db.query(Task).filter(Task.id == record.task_id).first()

    # 根据 trigger_source 重新加载用例
    trigger_source = record.trigger_source or "api_test"

    # 从原始执行记录的 analysis_result 中提取用例信息
    cases_json = []
    if record.analysis_result:
        try:
            analysis = json.loads(record.analysis_result)
            original_cases = analysis.get("cases", [])
            for c in original_cases:
                cases_json.append({
                    "case_id": c.get("case_id", ""),
                    "title": c.get("title", ""),
                    "type": "api",
                    "steps": c.get("steps", []),
                    "assertions": c.get("assertions", []),
                    "extracts": c.get("extracts", []),
                })
        except Exception:
            pass

    if not cases_json:
        raise HTTPException(status_code=400, detail="无法从原执行记录中恢复用例数据，请手动重新执行")

    new_execution_id = await _submit_execution(
        user=user, db=db, cases_json=cases_json, env="test",
        base_url="http://localhost:8080",
        headers={"Content-Type": "application/json"},
        variables={},
        trigger_source="retry",
    )

    return Response(code=200, message="重跑任务已提交", data={"execution_id": new_execution_id, "original_execution_id": execution_id, "status": "queued", "case_count": len(cases_json)})
