"""
三层分析 API - 兼容前端 threeLayer.ts 调用

提供三层（需求理解→用例生成→脚本编译）统一入口。
内部转发到统一测试流程服务。

端点：
  POST /analyze       三层分析入口
  POST /compile       编译用例
  POST /generate      生成脚本
  POST /execute       执行测试
  GET  /tasks          三层任务列表
  GET  /tasks/{id}     三层任务详情
  GET  /tasks/{id}/result  三层任务结果
"""
import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db, SessionLocal
from app.core.logger import log
from app.core.auth import require_auth
from app.models.user import User
from app.schemas.response import Response

logger = logging.getLogger(__name__)

router = APIRouter()


class AnalyzeRequest(BaseModel):
    """分析请求"""
    requirement: str
    task_id: Optional[int] = None
    mode: str = "full"


class CompileRequest(BaseModel):
    """编译请求"""
    task_id: int
    cases: Optional[List[dict]] = None


class GenerateRequest(BaseModel):
    """生成请求"""
    task_id: int
    case_ids: Optional[List[int]] = None
    framework: str = "playwright"


class ExecuteRequest(BaseModel):
    """执行请求"""
    task_id: int
    env: str = "test"
    base_url: str = "http://localhost:8080"


@router.post("/analyze", summary="三层分析")
async def three_layer_analyze(
    req: AnalyzeRequest,
    user: User = Depends(require_auth),
):
    """
    三层分析入口：需求理解 → 用例生成 → 脚本编译

    内部调用 CasePipeline 统一测试流程。
    """
    try:
        from app.services.case.pipeline import CasePipeline
        pipeline = CasePipeline()
        result = await pipeline.run_pipeline(
            requirement=req.requirement,
            task_id=req.task_id,
        )
        return Response(code=200, message="分析完成", data=result)
    except Exception as e:
        logger.error(f"三层分析失败: {e}", exc_info=True)
        return Response(code=500, message=f"分析失败: {e}", data=None)


@router.post("/compile", summary="编译用例")
async def three_layer_compile(
    req: CompileRequest,
    user: User = Depends(require_auth),
):
    """编译测试用例为可执行格式"""
    try:
        from app.services.case.pipeline import CasePipeline
        pipeline = CasePipeline()
        result = await pipeline.compile_for_execution(
            task_id=req.task_id,
            cases=req.cases,
        )
        return Response(code=200, message="编译完成", data=result)
    except Exception as e:
        logger.error(f"编译失败: {e}", exc_info=True)
        return Response(code=500, message=f"编译失败: {e}", data=None)


@router.post("/generate", summary="生成脚本")
async def three_layer_generate(
    req: GenerateRequest,
    user: User = Depends(require_auth),
):
    """根据用例生成测试脚本"""
    try:
        from app.runtime.agent_factory import AgentFactory
        from app.db.database import SessionLocal
        from app.models.task import Task
        from app.models.script import Script

        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == req.task_id).first()
            if not task:
                raise HTTPException(status_code=404, detail="任务不存在")

            # 通过 TaskDispatcher 提交脚本生成任务 (企业级 Runtime)
            from app.runtime.enterprise import get_task_dispatcher, TaskRequest
            dispatcher = get_task_dispatcher()
            task_id = await dispatcher.submit(TaskRequest(
                agent_name="script_generation_agent",
                action="execute",
                payload={
                    "task_id": req.task_id,
                    "case_ids": req.case_ids,
                    "framework": req.framework,
                },
                timeout_seconds=300,
                max_retries=1,
            ))
            # 同步等待结果
            task_result = await dispatcher.wait_for_result(task_id, timeout=300)
            if task_result.status == "success":
                return Response(code=200, message="生成完成", data=task_result.result)
            else:
                raise Exception(task_result.error or "生成失败")
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"脚本生成失败: {e}", exc_info=True)
        return Response(code=500, message=f"生成失败: {e}", data=None)


@router.post("/execute", summary="执行测试")
async def three_layer_execute(
    req: ExecuteRequest,
    user: User = Depends(require_auth),
):
    """执行测试脚本"""
    try:
        from app.services.execution.dispatcher import ExecutionDispatcher
        from app.models.task import Task
        from app.models.test_asset import TestAsset
        from app.db.database import SessionLocal

        db = SessionLocal()
        try:
            # 查找任务关联的 TestAsset
            task = db.query(Task).filter(Task.id == req.task_id).first()
            if not task:
                raise HTTPException(status_code=404, detail="任务不存在")

            # 查找关联的可执行资产
            assets = db.query(TestAsset).filter(
                TestAsset.task_id == req.task_id,
                TestAsset.is_deleted == False,
            ).all()

            if not assets:
                raise HTTPException(status_code=400, detail="任务没有可执行的测试资产")

            asset_ids = [a.id for a in assets]
            result = await ExecutionDispatcher.dispatch_batch(
                asset_ids=asset_ids,
                user_id=user.id,
                env=req.env,
                base_url=req.base_url or task.page_url or "http://localhost:8080",
            )
            return Response(code=200, message="执行完成", data=result)
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"执行失败: {e}", exc_info=True)
        return Response(code=500, message=f"执行失败: {e}", data=None)


@router.get("/tasks", summary="三层任务列表")
async def list_three_layer_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(require_auth),
):
    """获取任务列表"""
    db = SessionLocal()
    try:
        from app.models.task import Task
        query = db.query(Task).filter(Task.user_id == user.id)
        total = query.count()
        tasks = query.order_by(Task.id.desc()).offset(
            (page - 1) * page_size
        ).limit(page_size).all()
        return Response(code=200, message="success", data={
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [
                {
                    "id": t.id,
                    "title": t.task_name,
                    "status": t.status.value if hasattr(t.status, 'value') else str(t.status),
                    "task_type": t.task_type.value if hasattr(t.task_type, 'value') else str(t.task_type),
                    "created_at": str(t.created_at) if t.created_at else None,
                }
                for t in tasks
            ],
        })
    finally:
        db.close()


@router.get("/tasks/{task_id}", summary="任务详情")
async def get_three_layer_task(
    task_id: int,
    user: User = Depends(require_auth),
):
    """获取任务详情"""
    db = SessionLocal()
    try:
        from app.models.task import Task
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        return Response(code=200, message="success", data={
            "id": task.id,
            "title": task.task_name,
            "status": task.status.value if hasattr(task.status, 'value') else str(task.status),
            "task_type": task.task_type.value if hasattr(task.task_type, 'value') else str(task.task_type),
            "page_url": task.page_url,
            "framework": task.framework,
            "created_at": str(task.created_at) if task.created_at else None,
            "updated_at": str(task.updated_at) if task.updated_at else None,
        })
    finally:
        db.close()


@router.get("/tasks/{task_id}/result", summary="任务结果")
async def get_three_layer_result(
    task_id: int,
    user: User = Depends(require_auth),
):
    """获取任务执行结果"""
    db = SessionLocal()
    try:
        from app.models.task import Task
        from app.models.execution_record import ExecutionRecord
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        # 获取关联的执行记录
        executions = db.query(ExecutionRecord).filter(
            ExecutionRecord.task_id == task_id
        ).order_by(ExecutionRecord.created_at.desc()).all()

        return Response(code=200, message="success", data={
            "task": {
                "id": task.id,
                "title": task.task_name,
                "status": task.status.value if hasattr(task.status, 'value') else str(task.status),
            },
            "executions": [
                {
                    "id": e.id,
                    "status": e.status.value if hasattr(e.status, 'value') else str(e.status),
                    "success_count": e.success_count,
                    "failed_count": e.failed_count,
                    "duration": e.duration,
                }
                for e in executions
            ],
        })
    finally:
        db.close()
