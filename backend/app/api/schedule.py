"""
定时任务 API

CRUD + 运行历史 + 暂停/启用 + 手动触发
"""
import json
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from app.db.database import SessionLocal
from app.models.schedule_task import ScheduleTask, ScheduleType, ScheduleStatus, ScheduleRunLog
from app.core.logger import log
from app.schemas.response import Response
from app.core.auth import require_auth
from app.models.user import User
from app.runtime.agent_factory import AgentFactory

router = APIRouter()


# ==================== 请求模型 ====================

class CreateScheduleTaskRequest(BaseModel):
    name: str
    description: Optional[str] = None
    schedule_type: str = "daily"  # once/daily/cron
    cron_expression: Optional[str] = None
    execute_time: Optional[str] = None  # HH:MM
    execute_date: Optional[str] = None  # YYYY-MM-DD
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    timeout: int = 3600
    max_retries: int = 3
    retry_interval: int = 60
    notify_on_success: bool = False
    notify_on_failure: bool = True
    notify_channels: Optional[str] = None
    requirement_id: Optional[int] = None
    task_config: Optional[dict] = None  # {requirement, target_url, script_format}


class UpdateScheduleTaskRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    schedule_type: Optional[str] = None
    cron_expression: Optional[str] = None
    execute_time: Optional[str] = None
    execute_date: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    timeout: Optional[int] = None
    max_retries: Optional[int] = None
    retry_interval: Optional[int] = None
    notify_on_success: Optional[bool] = None
    notify_on_failure: Optional[bool] = None
    notify_channels: Optional[str] = None
    task_config: Optional[dict] = None


# ==================== API端点 ====================

@router.get("", summary="获取定时任务列表")
async def list_schedule_tasks(
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(require_auth),
):
    db = SessionLocal()
    try:
        query = db.query(ScheduleTask).filter(ScheduleTask.user_id == user.id)
        if status:
            query = query.filter(ScheduleTask.status == status)
        query = query.order_by(ScheduleTask.created_at.desc())

        total = query.count()
        tasks = query.offset((page - 1) * page_size).limit(page_size).all()

        return Response(code=200, message="获取成功", data={
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [t.to_dict() for t in tasks],
        })
    finally:
        db.close()


@router.post("", summary="创建定时任务")
async def create_schedule_task(request: CreateScheduleTaskRequest, user: User = Depends(require_auth)):
    db = SessionLocal()
    try:
        # 验证调度配置
        if request.schedule_type == "cron" and not request.cron_expression:
            raise HTTPException(status_code=400, detail="Cron类型必须提供cron_expression")
        if request.schedule_type == "once" and not request.execute_date:
            raise HTTPException(status_code=400, detail="一次性任务必须提供execute_date")
        if request.schedule_type == "daily" and not request.execute_time:
            raise HTTPException(status_code=400, detail="每日任务必须提供execute_time")

        # 解析时间字段
        start_time = None
        if request.start_time:
            try:
                start_time = datetime.fromisoformat(request.start_time)
            except ValueError:
                # 尝试纯日期格式 YYYY-MM-DD
                try:
                    start_time = datetime.strptime(request.start_time, "%Y-%m-%d")
                except ValueError:
                    raise HTTPException(status_code=400, detail=f"start_time格式错误: {request.start_time}")

        end_time = None
        if request.end_time:
            try:
                end_time = datetime.fromisoformat(request.end_time)
            except ValueError:
                try:
                    end_time = datetime.strptime(request.end_time, "%Y-%m-%d")
                except ValueError:
                    raise HTTPException(status_code=400, detail=f"end_time格式错误: {request.end_time}")

        task = ScheduleTask(
            name=request.name,
            description=request.description,
            schedule_type=request.schedule_type,
            cron_expression=request.cron_expression,
            execute_time=request.execute_time,
            execute_date=request.execute_date,
            start_time=start_time,
            end_time=end_time,
            timeout=request.timeout,
            max_retries=request.max_retries,
            retry_interval=request.retry_interval,
            notify_on_success=request.notify_on_success,
            notify_on_failure=request.notify_on_failure,
            notify_channels=request.notify_channels,
            requirement_id=request.requirement_id,
            task_config=json.dumps(request.task_config, ensure_ascii=False) if request.task_config else None,
            status=ScheduleStatus.ACTIVE,
            user_id=user.id,
            created_by=user.id,
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        # 添加到调度器
        try:
            agent = AgentFactory.create("scheduler_agent")
            agent.add_task(task)
        except Exception as e:
            log.warning(f"添加调度任务失败（任务已创建）: {e}")

        # 重新读取以获取next_run_at
        db.refresh(task)
        return Response(code=200, message="创建成功", data=task.to_dict())
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        log.error(f"创建定时任务异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


# ==================== 全局历史记录（必须在 /{task_id} 之前注册）====================

@router.get("/history/list", summary="获取所有定时任务执行历史")
async def list_schedule_history(
    status: Optional[str] = None,
    trigger_type: Optional[str] = None,
    schedule_id: Optional[int] = None,
    keyword: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(require_auth),
):
    """获取当前用户所有定时任务的执行历史（分页、筛选、搜索）"""
    db = SessionLocal()
    try:
        query = db.query(ScheduleRunLog).filter(ScheduleRunLog.user_id == user.id)

        if status:
            query = query.filter(ScheduleRunLog.status == status)
        if trigger_type:
            query = query.filter(ScheduleRunLog.trigger_type == trigger_type)
        if schedule_id:
            query = query.filter(ScheduleRunLog.schedule_task_id == schedule_id)

        if keyword:
            schedule_ids = [
                t.id for t in db.query(ScheduleTask)
                .filter(ScheduleTask.name.contains(keyword), ScheduleTask.user_id == user.id)
                .all()
            ]
            query = query.filter(ScheduleRunLog.schedule_task_id.in_(schedule_ids))

        query = query.order_by(ScheduleRunLog.created_at.desc())

        total = query.count()
        records = query.offset((page - 1) * page_size).limit(page_size).all()

        items = []
        for r in records:
            item = r.to_dict()
            st = db.query(ScheduleTask).filter(ScheduleTask.id == r.schedule_task_id).first()
            item["schedule_name"] = st.name if st else f"定时任务#{r.schedule_task_id}"
            items.append(item)

        return Response(code=200, message="获取成功", data={
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": items,
        })
    finally:
        db.close()


@router.get("/history/{record_id}", summary="获取执行历史详情")
async def get_schedule_history_detail(
    record_id: int,
    user: User = Depends(require_auth),
):
    """获取单条执行历史记录的详细信息"""
    db = SessionLocal()
    try:
        record = db.query(ScheduleRunLog).filter(
            ScheduleRunLog.id == record_id, ScheduleRunLog.user_id == user.id
        ).first()
        if not record:
            raise HTTPException(status_code=404, detail="执行记录不存在")

        item = record.to_dict()

        st = db.query(ScheduleTask).filter(ScheduleTask.id == record.schedule_task_id).first()
        item["schedule_name"] = st.name if st else f"定时任务#{record.schedule_task_id}"
        item["schedule_type"] = st.schedule_type if st else None
        item["task_config"] = st.task_config if st else None

        if record.execution_id:
            from app.models.execution_record import ExecutionRecord
            exec_record = db.query(ExecutionRecord).filter(ExecutionRecord.id == record.execution_id).first()
            if exec_record:
                item["execution_detail"] = exec_record.to_dict()

        return Response(code=200, message="获取成功", data=item)
    finally:
        db.close()


@router.post("/history/{record_id}/retry", summary="重试执行")
async def retry_schedule_history(
    record_id: int,
    user: User = Depends(require_auth),
):
    """基于历史记录重试执行"""
    db = SessionLocal()
    try:
        record = db.query(ScheduleRunLog).filter(
            ScheduleRunLog.id == record_id, ScheduleRunLog.user_id == user.id
        ).first()
        if not record:
            raise HTTPException(status_code=404, detail="执行记录不存在")

        schedule_task = db.query(ScheduleTask).filter(ScheduleTask.id == record.schedule_task_id).first()
        if not schedule_task:
            raise HTTPException(status_code=404, detail="关联的定时任务不存在")

        schedule_task.run_count += 1
        new_run = ScheduleRunLog(
            schedule_task_id=schedule_task.id,
            run_number=schedule_task.run_count,
            status="running",
            trigger_type="retry",
            operator=user.username or f"user#{user.id}",
            started_at=datetime.now(),
            user_id=user.id,
            created_by=user.id,
        )
        db.add(new_run)
        db.commit()
        db.refresh(new_run)

        import asyncio
        from app.agent.scheduling.scheduler_agent import _execute_schedule_task
        asyncio.create_task(_execute_schedule_task(schedule_task.id))

        return Response(code=200, message="已触发重试", data={"run_id": new_run.id})
    finally:
        db.close()


@router.get("/{task_id}", summary="获取定时任务详情")
async def get_schedule_task(task_id: int, user: User = Depends(require_auth)):
    db = SessionLocal()
    try:
        task = db.query(ScheduleTask).filter(
            ScheduleTask.id == task_id, ScheduleTask.user_id == user.id
        ).first()
        if not task:
            raise HTTPException(status_code=404, detail="定时任务不存在")
        return Response(code=200, message="获取成功", data=task.to_dict())
    finally:
        db.close()


@router.put("/{task_id}", summary="更新定时任务")
async def update_schedule_task(task_id: int, request: UpdateScheduleTaskRequest, user: User = Depends(require_auth)):
    db = SessionLocal()
    try:
        task = db.query(ScheduleTask).filter(
            ScheduleTask.id == task_id, ScheduleTask.user_id == user.id
        ).first()
        if not task:
            raise HTTPException(status_code=404, detail="定时任务不存在")

        # 更新字段
        update_fields = request.model_dump(exclude_unset=True)
        for k, v in update_fields.items():
            if k == "task_config":
                setattr(task, k, json.dumps(v, ensure_ascii=False) if v else None)
            elif k in ("start_time", "end_time") and v:
                try:
                    setattr(task, k, datetime.fromisoformat(v))
                except ValueError:
                    try:
                        setattr(task, k, datetime.strptime(v, "%Y-%m-%d"))
                    except ValueError:
                        pass
            else:
                setattr(task, k, v)

        db.commit()
        db.refresh(task)

        # 重新调度
        if task.status == ScheduleStatus.ACTIVE:
            agent = AgentFactory.create("scheduler_agent")
            agent.remove_task(task.id)
            agent.add_task(task)

        return Response(code=200, message="更新成功", data=task.to_dict())
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.delete("/{task_id}", summary="删除定时任务")
async def delete_schedule_task(task_id: int, user: User = Depends(require_auth)):
    db = SessionLocal()
    try:
        task = db.query(ScheduleTask).filter(
            ScheduleTask.id == task_id, ScheduleTask.user_id == user.id
        ).first()
        if not task:
            raise HTTPException(status_code=404, detail="定时任务不存在")

        # 从调度器移除
        agent = AgentFactory.create("scheduler_agent")
        agent.remove_task(task.id)

        # 删除执行日志
        db.query(ScheduleRunLog).filter(ScheduleRunLog.schedule_task_id == task_id).delete()
        db.delete(task)
        db.commit()

        return Response(code=200, message="删除成功")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.post("/{task_id}/pause", summary="暂停定时任务")
async def pause_schedule_task(task_id: int, user: User = Depends(require_auth)):
    db = SessionLocal()
    try:
        task = db.query(ScheduleTask).filter(
            ScheduleTask.id == task_id, ScheduleTask.user_id == user.id
        ).first()
        if not task:
            raise HTTPException(status_code=404, detail="定时任务不存在")

        task.status = ScheduleStatus.PAUSED
        db.commit()

        agent = AgentFactory.create("scheduler_agent")
        agent.pause_task(task_id)

        return Response(code=200, message="已暂停")
    finally:
        db.close()


@router.post("/{task_id}/resume", summary="启用定时任务")
async def resume_schedule_task(task_id: int, user: User = Depends(require_auth)):
    db = SessionLocal()
    try:
        task = db.query(ScheduleTask).filter(
            ScheduleTask.id == task_id, ScheduleTask.user_id == user.id
        ).first()
        if not task:
            raise HTTPException(status_code=404, detail="定时任务不存在")

        task.status = ScheduleStatus.ACTIVE
        db.commit()
        db.refresh(task)

        agent = AgentFactory.create("scheduler_agent")
        agent.remove_task(task_id)
        agent.add_task(task)

        return Response(code=200, message="已启用")
    finally:
        db.close()


@router.post("/{task_id}/trigger", summary="手动触发定时任务")
async def trigger_schedule_task(task_id: int, user: User = Depends(require_auth)):
    db = SessionLocal()
    try:
        task = db.query(ScheduleTask).filter(
            ScheduleTask.id == task_id, ScheduleTask.user_id == user.id
        ).first()
        if not task:
            raise HTTPException(status_code=404, detail="定时任务不存在")

        # 创建执行历史记录（手动触发）
        task.run_count += 1
        run_log = ScheduleRunLog(
            schedule_task_id=task_id,
            run_number=task.run_count,
            status="running",
            trigger_type="manual",
            operator=user.username or f"user#{user.id}",
            started_at=datetime.now(),
            user_id=user.id,
            created_by=user.id,
        )
        db.add(run_log)
        db.commit()
        db.refresh(run_log)

        # 通过 TaskQueue 异步触发执行（不阻塞 API 响应）
        from app.core.task_queue import TaskQueue
        queue = TaskQueue()
        if queue.started:
            # 创建 Task 和 ExecutionRecord，然后提交到 TaskQueue
            try:
                from app.agent.scheduling.task_executor import TaskExecutor
                executor = TaskExecutor()
                # 在后台异步执行
                import asyncio
                asyncio.create_task(_execute_schedule_via_queue(task_id, run_log.id, user))
            except Exception as e:
                log.warning(f"定时任务触发失败: {e}")
                # 降级：使用旧的执行方式
                import asyncio
                from app.agent.scheduling.scheduler_agent import _execute_schedule_task
                asyncio.create_task(_execute_schedule_task(task_id))
        else:
            # TaskQueue 未启动，降级为旧方式
            import asyncio
            from app.agent.scheduling.scheduler_agent import _execute_schedule_task
            asyncio.create_task(_execute_schedule_task(task_id))

        return Response(code=200, message="已触发执行")
    finally:
        db.close()


async def _execute_schedule_via_queue(schedule_task_id: int, run_log_id: int, user: User):
    """通过 TaskQueue 执行定时任务"""
    from app.agent.scheduling.task_executor import TaskExecutor
    from app.db.database import SessionLocal as SL

    db = SL()
    try:
        task = db.query(ScheduleTask).filter(ScheduleTask.id == schedule_task_id).first()
        if not task:
            return

        executor = TaskExecutor()
        result = await executor.execute(task, db.query(ScheduleRunLog).filter(ScheduleRunLog.id == run_log_id).first(), db)

        # 更新执行日志
        run_log = db.query(ScheduleRunLog).filter(ScheduleRunLog.id == run_log_id).first()
        if run_log:
            run_log.status = result.get("status", "failed")
            run_log.finished_at = datetime.now()
            run_log.duration = (run_log.finished_at - run_log.started_at).seconds if run_log.started_at else 0
            run_log.result_summary = result.get("summary", "")
            run_log.error_message = result.get("error", "")
            run_log.task_id = result.get("task_id")

        task.last_run_at = datetime.now()
        task.last_run_status = run_log.status if run_log else "failed"
        if run_log and run_log.status == "failed":
            task.fail_count += 1

        db.commit()
    except Exception as e:
        log.error(f"定时任务执行异常 | id={schedule_task_id}: {e}", exc_info=True)
        try:
            run_log = db.query(ScheduleRunLog).filter(ScheduleRunLog.id == run_log_id).first()
            if run_log:
                run_log.status = "failed"
                run_log.error_message = str(e)
                run_log.finished_at = datetime.now()
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


@router.get("/{task_id}/runs", summary="获取运行历史")
async def get_run_history(
    task_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(require_auth),
):
    db = SessionLocal()
    try:
        task = db.query(ScheduleTask).filter(
            ScheduleTask.id == task_id, ScheduleTask.user_id == user.id
        ).first()
        if not task:
            raise HTTPException(status_code=404, detail="定时任务不存在")

        query = db.query(ScheduleRunLog).filter(ScheduleRunLog.schedule_task_id == task_id)
        query = query.order_by(ScheduleRunLog.created_at.desc())

        total = query.count()
        runs = query.offset((page - 1) * page_size).limit(page_size).all()

        return Response(code=200, message="获取成功", data={
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [r.to_dict() for r in runs],
        })
    finally:
        db.close()
