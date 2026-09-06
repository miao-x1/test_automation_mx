"""把现有需求任务映射为项目内的 Jenkins Job，并编排回归管线。"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.execution_record import ExecutionRecord, ExecutionStatus
from app.models.requirement_task import RequirementTask, RequirementStatus
from app.models.script import Script
from app.models.test_job import (
    JobStatus,
    RegressionPipeline,
    RegressionPipelineItem,
    RegressionRun,
    TestJob,
)
from app.models.user import User


_REQ_RUNNING = {
    RequirementStatus.ANALYZING,
    RequirementStatus.GENERATING_CASE,
    RequirementStatus.RETRIEVING,
    RequirementStatus.GENERATING_SCRIPT,
    RequirementStatus.EXECUTING,
    "analyzing",
    "generating_case",
    "retrieving",
    "generating_script",
    "executing",
}


def map_requirement_status(status: Optional[str], exec_status: Optional[str] = None) -> str:
    if exec_status in {ExecutionStatus.SUCCESS, "success"}:
        return JobStatus.SUCCESS
    if exec_status in {ExecutionStatus.FAILED, "failed"}:
        return JobStatus.FAILED
    if exec_status in {ExecutionStatus.RUNNING, ExecutionStatus.WAITING, "running", "waiting"}:
        return JobStatus.RUNNING
    if status in _REQ_RUNNING:
        return JobStatus.RUNNING
    if status in {RequirementStatus.COMPLETED, "completed"}:
        return JobStatus.SUCCESS
    if status in {RequirementStatus.FAILED, "failed"}:
        return JobStatus.FAILED
    return JobStatus.CREATED


def ensure_job_for_requirement(db: Session, req: RequirementTask, creator_id: Optional[int] = None) -> TestJob:
    job = db.query(TestJob).filter(TestJob.requirement_id == req.id).first()
    name = ((req.requirement or "")[:60] or f"测试任务 #{req.id}").strip()
    last_exec = None
    if req.task_id:
        last_exec = (
            db.query(ExecutionRecord)
            .filter(ExecutionRecord.task_id == req.task_id)
            .order_by(ExecutionRecord.created_at.desc())
            .first()
        )
    status = map_requirement_status(req.status, last_exec.status if last_exec else None)
    result = None
    if last_exec:
        total = (last_exec.success_count or 0) + (last_exec.failed_count or 0)
        result = f"{last_exec.success_count or 0} Passed / {last_exec.failed_count or 0} Failed" if total else last_exec.status
    if not job:
        job = TestJob(
            project_id=req.project_id,
            creator_id=creator_id or req.user_id,
            name=name,
            job_type=getattr(req, "task_type", None) or "web",
            requirement_id=req.id,
            task_id=req.task_id,
            status=status,
            result=result,
            last_execution_id=last_exec.id if last_exec else req.execution_id,
        )
        db.add(job)
        db.flush()
        return job
    job.name = name
    job.task_id = req.task_id or job.task_id
    job.status = status
    job.result = result or job.result
    if last_exec:
        job.last_execution_id = last_exec.id
    return job


def sync_project_jobs(db: Session, project_id: int) -> list[TestJob]:
    reqs = (
        db.query(RequirementTask)
        .filter(RequirementTask.project_id == project_id)
        .order_by(RequirementTask.created_at.desc())
        .all()
    )
    jobs = [ensure_job_for_requirement(db, req) for req in reqs]
    db.commit()
    return jobs


def job_out(job: TestJob) -> dict:
    return {
        "id": job.id,
        "project_id": job.project_id,
        "creator_id": job.creator_id,
        "name": job.name,
        "job_type": job.job_type,
        "requirement_id": job.requirement_id,
        "task_id": job.task_id,
        "status": job.status,
        "result": job.result,
        "last_execution_id": job.last_execution_id,
        "created_at": str(job.created_at) if job.created_at else None,
    }


def pipeline_out(db: Session, pipeline: RegressionPipeline) -> dict:
    items = (
        db.query(RegressionPipelineItem)
        .filter(RegressionPipelineItem.pipeline_id == pipeline.id)
        .order_by(RegressionPipelineItem.sort_order.asc())
        .all()
    )
    last = (
        db.query(RegressionRun)
        .filter(RegressionRun.pipeline_id == pipeline.id)
        .order_by(RegressionRun.created_at.desc())
        .first()
    )
    return {
        "id": pipeline.id,
        "project_id": pipeline.project_id,
        "name": pipeline.name,
        "description": pipeline.description,
        "job_ids": [item.job_id for item in items],
        "job_count": len(items),
        "last_run": run_out(last) if last else None,
        "created_at": str(pipeline.created_at) if pipeline.created_at else None,
    }


def run_out(run: Optional[RegressionRun]) -> Optional[dict]:
    if not run:
        return None
    details = []
    if run.result_json:
        try:
            details = json.loads(run.result_json)
        except Exception:
            details = []
    duration = None
    if run.created_at and run.updated_at:
        duration = max(0, int((run.updated_at - run.created_at).total_seconds()))
    return {
        "id": run.id,
        "pipeline_id": run.pipeline_id,
        "project_id": run.project_id,
        "status": run.status,
        "passed_count": run.passed_count,
        "failed_count": run.failed_count,
        "duration_seconds": duration,
        "number": run.id,
        "title": f"Regression #{run.id:03d}",
        "details": details,
        "created_at": str(run.created_at) if run.created_at else None,
    }


def create_pipeline(db: Session, project_id: int, user: User, name: str, job_ids: list[int], description: Optional[str] = None) -> RegressionPipeline:
    if not name.strip():
        raise HTTPException(status_code=400, detail="请填写回归流程名称")
    jobs = db.query(TestJob).filter(TestJob.id.in_(job_ids or [0]), TestJob.project_id == project_id).all()
    if not jobs:
        raise HTTPException(status_code=400, detail="请选择当前项目中的测试任务")
    pipeline = RegressionPipeline(project_id=project_id, created_by=user.id, name=name.strip(), description=description)
    db.add(pipeline)
    db.flush()
    wanted = {job.id: job for job in jobs}
    for index, job_id in enumerate(job_ids):
        if job_id in wanted:
            db.add(RegressionPipelineItem(pipeline_id=pipeline.id, job_id=job_id, sort_order=index))
    db.commit()
    db.refresh(pipeline)
    return pipeline


def _start_job_execution(db: Session, job: TestJob, user: User) -> tuple[Optional[ExecutionRecord], Optional[str]]:
    from app.models.execution_record import ExecutionType
    from app.models.task import Task
    from app.models.test_asset import TestAsset

    if not job.task_id:
        return None, "还没有关联执行任务"
    task = db.query(Task).filter(Task.id == job.task_id).first()
    if not task:
        return None, "执行任务不存在"
    script = db.query(Script).filter(Script.task_id == job.task_id).first()
    if not script:
        return None, "还没有可执行脚本"

    asset = db.query(TestAsset).filter(TestAsset.task_id == job.task_id).first()
    record = ExecutionRecord(
        task_id=job.task_id,
        asset_id=asset.id if asset else None,
        execution_type=ExecutionType.WEB,
        status=ExecutionStatus.WAITING,
        trigger_source="regression",
        user_id=user.id,
        created_by=user.id,
        project_id=job.project_id,
    )
    db.add(record)
    db.flush()
    job.last_execution_id = record.id
    job.status = JobStatus.RUNNING
    return record, None


def refresh_run(db: Session, run: RegressionRun) -> RegressionRun:
    details = []
    if run.result_json:
        try:
            details = json.loads(run.result_json)
        except Exception:
            details = []
    passed = failed = running = 0
    for item in details:
        exec_id = item.get("execution_id")
        if exec_id:
            record = db.query(ExecutionRecord).filter(ExecutionRecord.id == exec_id).first()
            if record:
                if record.status == ExecutionStatus.SUCCESS:
                    item["status"] = JobStatus.SUCCESS
                    item["message"] = "执行通过"
                elif record.status in {ExecutionStatus.FAILED, ExecutionStatus.CANCELLED}:
                    item["status"] = JobStatus.FAILED
                    item["message"] = record.error_message or "执行失败"
                else:
                    item["status"] = JobStatus.RUNNING
                    item["message"] = "执行中"
        if item.get("status") == JobStatus.SUCCESS:
            passed += 1
        elif item.get("status") == JobStatus.RUNNING:
            running += 1
        else:
            failed += 1
    run.passed_count = passed
    run.failed_count = failed
    if running:
        run.status = JobStatus.RUNNING
    else:
        run.status = JobStatus.SUCCESS if failed == 0 else JobStatus.FAILED
    run.result_json = json.dumps(details, ensure_ascii=False)
    db.commit()
    db.refresh(run)
    return run


def run_pipeline(db: Session, pipeline: RegressionPipeline, user: User) -> RegressionRun:
    items = (
        db.query(RegressionPipelineItem)
        .filter(RegressionPipelineItem.pipeline_id == pipeline.id)
        .order_by(RegressionPipelineItem.sort_order.asc())
        .all()
    )
    if not items:
        raise HTTPException(status_code=400, detail="回归流程还没有测试任务")
    run = RegressionRun(
        pipeline_id=pipeline.id,
        project_id=pipeline.project_id,
        created_by=user.id,
        status=JobStatus.RUNNING,
    )
    db.add(run)
    db.flush()

    details = []
    for item in items:
        job = db.query(TestJob).filter(TestJob.id == item.job_id).first()
        if not job:
            details.append({"job_id": item.job_id, "name": "未知任务", "status": JobStatus.FAILED, "message": "任务不存在"})
            continue
        record, err = _start_job_execution(db, job, user)
        if err:
            job.status = JobStatus.FAILED
            details.append({"job_id": job.id, "name": job.name, "status": JobStatus.FAILED, "message": err})
            continue
        details.append({
            "job_id": job.id,
            "name": job.name,
            "status": JobStatus.RUNNING,
            "message": "已提交执行",
            "execution_id": record.id if record else None,
        })

    run.result_json = json.dumps(details, ensure_ascii=False)
    db.commit()
    return refresh_run(db, run)


def project_overview(db: Session, project_id: int) -> dict:
    sync_project_jobs(db, project_id)
    jobs = db.query(TestJob).filter(TestJob.project_id == project_id).all()
    runs = (
        db.query(RegressionRun)
        .filter(RegressionRun.project_id == project_id)
        .order_by(RegressionRun.created_at.desc())
        .limit(5)
        .all()
    )
    success = sum(1 for job in jobs if job.status == JobStatus.SUCCESS)
    failed = sum(1 for job in jobs if job.status == JobStatus.FAILED)
    running = sum(1 for job in jobs if job.status == JobStatus.RUNNING)
    total = len(jobs)
    last_job = max(jobs, key=lambda j: j.updated_at or j.created_at) if jobs else None
    rate = int(round(success * 100 / total)) if total else None
    if running:
        status = "RUNNING"
    elif failed and success:
        status = "UNSTABLE"
    elif failed:
        status = "FAILED"
    elif success:
        status = "SUCCESS"
    else:
        status = "IDLE"
    return {
        "job_count": total,
        "success_count": success,
        "failed_count": failed,
        "running_count": running,
        "success_rate": rate,
        "status": status,
        "last_test_at": str(last_job.updated_at or last_job.created_at) if last_job else None,
        "recent_runs": [run_out(run) for run in runs],
    }


def dashboard_activity(db: Session, project_ids: list[int], limit: int = 8) -> dict:
    if not project_ids:
        return {"recent_jobs": [], "recent_failures": []}
    jobs = (
        db.query(TestJob)
        .filter(TestJob.project_id.in_(project_ids))
        .order_by(TestJob.updated_at.desc())
        .limit(limit)
        .all()
    )
    failures = (
        db.query(TestJob)
        .filter(TestJob.project_id.in_(project_ids), TestJob.status == JobStatus.FAILED)
        .order_by(TestJob.updated_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "recent_jobs": [job_out(job) for job in jobs],
        "recent_failures": [job_out(job) for job in failures],
    }
