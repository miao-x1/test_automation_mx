"""项目效能测评 API。"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import require_auth
from app.db.database import get_db
from app.models.user import User
from app.schemas.response import Response
from app.services.assessment_service import (
    assessment_out,
    create_assessment,
    delete_assessment,
    env_count,
    execute_assessment,
    get_assessment,
    list_assessments,
)
from app.services.workspace_service import ADMIN, RUN, VIEW, require_project

router = APIRouter()


class AssessmentCreate(BaseModel):
    name: str
    target_url: Optional[str] = None
    environment_id: Optional[int] = None
    rounds: int = 1
    scenario: str = "page"


@router.get("/projects/{project_id}/assessments", summary="效能测评历史")
def list_project_assessments(project_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    require_project(db, user, project_id, VIEW)
    rows = list_assessments(db, project_id)
    return Response(code=200, message="ok", data={
        "items": [assessment_out(row) for row in rows],
        "environment_count": env_count(db, project_id),
    })


@router.post("/projects/{project_id}/assessments", summary="创建效能测评")
def create_project_assessment(project_id: int, body: AssessmentCreate, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    require_project(db, user, project_id, RUN)
    if env_count(db, project_id) <= 0 and not (body.target_url or "").strip():
        raise HTTPException(status_code=400, detail="请先配置测试环境，或直接填写目标页面地址")
    row = create_assessment(db, project_id, user, body.name, body.target_url or "", body.environment_id, body.rounds, body.scenario)
    return Response(code=200, message="测评已创建", data=assessment_out(row))


@router.get("/projects/{project_id}/assessments/{assessment_id}", summary="效能测评详情")
def get_project_assessment(project_id: int, assessment_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    require_project(db, user, project_id, VIEW)
    return Response(code=200, message="ok", data=assessment_out(get_assessment(db, project_id, assessment_id)))


@router.post("/projects/{project_id}/assessments/{assessment_id}/run", summary="执行效能测评")
def run_project_assessment(project_id: int, assessment_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    require_project(db, user, project_id, RUN)
    row = get_assessment(db, project_id, assessment_id)
    row = execute_assessment(db, row)
    if row.status == "FAILED":
        return Response(code=200, message="测评未完成", data=assessment_out(row))
    return Response(code=200, message="测评完成", data=assessment_out(row))


@router.post("/projects/{project_id}/assessments/{assessment_id}/run/stream", summary="执行效能测评（进度）")
def run_project_assessment_stream(project_id: int, assessment_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    require_project(db, user, project_id, RUN)
    row = get_assessment(db, project_id, assessment_id)

    def events():
        yield f"data: {json.dumps({'step': '正在准备测试环境', 'index': 0}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'step': '正在打开页面', 'index': 1}, ensure_ascii=False)}\n\n"
        result = execute_assessment(db, row)
        after = [
            "正在采集页面性能",
            "正在分析资源加载",
            "正在统计测试执行情况",
            "正在生成测评报告",
        ]
        for index, message in enumerate(after, start=2):
            yield f"data: {json.dumps({'step': message, 'index': index}, ensure_ascii=False)}\n\n"
        payload = {
            "step": "测评完成" if result.status == "SUCCESS" else "测评未完成",
            "done": True,
            "data": assessment_out(result),
        }
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@router.delete("/projects/{project_id}/assessments/{assessment_id}", summary="删除效能测评")
def delete_project_assessment(project_id: int, assessment_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    require_project(db, user, project_id, ADMIN)
    delete_assessment(db, project_id, assessment_id)
    return Response(code=200, message="已删除")
