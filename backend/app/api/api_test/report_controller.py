"""
接口测试 - 报告
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.response import Response
from app.models.execution_record import ExecutionRecord, ExecutionStatus
from app.core.auth import require_auth
from app.models.user import User

router = APIRouter()


@router.get("/execution/{execution_id}/report", summary="获取测试报告")
async def get_execution_report(execution_id: int, format: str = Query("json"), user: User = Depends(require_auth), db: Session = Depends(get_db)):
    record = db.query(ExecutionRecord).filter(ExecutionRecord.id == execution_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if record.status in (ExecutionStatus.WAITING, ExecutionStatus.PENDING, ExecutionStatus.RUNNING):
        return Response(code=200, message="执行尚未完成", data={"execution_id": execution_id, "status": record.status, "report": None})

    from app.services.execution.report_generator import ReportGenerator
    report = ReportGenerator.generate(execution_id, format=format)
    return Response(code=200, message="success", data=report)


@router.get("/execution/{execution_id}/report/export", summary="导出报告")
async def export_execution_report(
    execution_id: int,
    format: str = Query("html", description="导出格式: html|markdown"),
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    record = db.query(ExecutionRecord).filter(ExecutionRecord.id == execution_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if record.status in (ExecutionStatus.WAITING, ExecutionStatus.PENDING, ExecutionStatus.RUNNING):
        raise HTTPException(status_code=400, detail="执行尚未完成，无法导出报告")

    if format not in ("html", "markdown"):
        raise HTTPException(status_code=400, detail="不支持的导出格式，仅支持 html 或 markdown")

    from app.services.execution.report_generator import ReportGenerator
    report = ReportGenerator.generate(execution_id, format=format)

    if format == "html":
        content = report.get("html", "")
        return PlainTextResponse(content=content, media_type="text/html")
    else:
        content = report.get("markdown", "")
        return PlainTextResponse(content=content, media_type="text/markdown")
