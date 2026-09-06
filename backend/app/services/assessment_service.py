"""项目效能测评：真实采集页面指标 + 统计已有 Job/回归。"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.assessment import PerformanceAssessment, PerformanceAssessmentMetric
from app.models.test_environment import TestEnvironment
from app.models.test_job import JobStatus, RegressionRun, TestJob
from app.models.user import User
from app.services.assessment_scoring import (
    job_score,
    network_score,
    overall_score,
    page_score,
    regression_score,
    resource_score,
    summarize_advice,
)
from app.services.test_job_service import run_out


def assessment_out(row: PerformanceAssessment) -> dict:
    report = {}
    issues = []
    advice = None
    if row.report_json:
        try:
            report = json.loads(row.report_json)
        except Exception:
            report = {}
    if row.issues_json:
        try:
            issues = json.loads(row.issues_json)
        except Exception:
            issues = []
    if row.advice_json:
        try:
            advice = json.loads(row.advice_json)
        except Exception:
            advice = row.advice_json
    return {
        "id": row.id,
        "project_id": row.project_id,
        "creator_id": row.creator_id,
        "name": row.name,
        "target_url": row.target_url,
        "environment_id": row.environment_id,
        "rounds": row.rounds,
        "scenario": row.scenario,
        "status": row.status,
        "score_total": row.score_total,
        "score_page": row.score_page,
        "score_resource": row.score_resource,
        "score_network": row.score_network,
        "score_job": row.score_job,
        "score_regression": row.score_regression,
        "report": report,
        "issues": issues,
        "advice": advice,
        "error_message": row.error_message,
        "created_at": str(row.created_at) if row.created_at else None,
        "finished_at": str(row.finished_at) if row.finished_at else None,
    }


def create_assessment(
    db: Session,
    project_id: int,
    user: User,
    name: str,
    target_url: str,
    environment_id: Optional[int] = None,
    rounds: int = 1,
    scenario: str = "page",
) -> PerformanceAssessment:
    if not name.strip():
        raise HTTPException(status_code=400, detail="请填写测评名称")
    url = (target_url or "").strip()
    env = None
    if environment_id:
        env = db.query(TestEnvironment).filter(
            TestEnvironment.id == environment_id,
            TestEnvironment.project_id == project_id,
        ).first()
        if not env:
            raise HTTPException(status_code=400, detail="测试环境不存在或不属于当前项目")
        url = url or (env.base_url or env.web_url or "")
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="请填写可访问的页面地址，或先配置测试环境")
    row = PerformanceAssessment(
        project_id=project_id,
        creator_id=user.id,
        name=name.strip(),
        target_url=url,
        environment_id=environment_id,
        rounds=max(1, min(int(rounds or 1), 3)),
        scenario=scenario or "page",
        status="CREATED",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _avg_page(rounds_data: list[dict]) -> dict:
    keys = ["ttfb_ms", "dom_ready_ms", "load_complete_ms", "fcp_ms", "lcp_ms"]
    acc = {k: [] for k in keys}
    for item in rounds_data:
        page = (item.get("page") or {})
        for key in keys:
            val = page.get(key)
            if isinstance(val, (int, float)) and val > 0:
                acc[key].append(val)
    return {k: round(sum(v) / len(v), 2) if v else 0 for k, v in acc.items()}


def execute_assessment(db: Session, row: PerformanceAssessment, collector=None, on_step=None) -> PerformanceAssessment:
    from app.domains.performance.cdp_collector import collect_browser_performance
    import asyncio

    def step(message: str) -> None:
        if on_step:
            on_step(message)

    step("正在准备测试环境")
    row.status = "RUNNING"
    row.started_at = datetime.now()
    row.error_message = None
    db.commit()

    rounds_data = []
    collect = collector or collect_browser_performance
    try:
        step("正在打开页面")
        for _ in range(row.rounds):
            if asyncio.iscoroutinefunction(collect):
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                            collected = pool.submit(asyncio.run, collect(row.target_url)).result(timeout=90)
                    else:
                        collected = loop.run_until_complete(collect(row.target_url))
                except RuntimeError:
                    collected = asyncio.run(collect(row.target_url))
            else:
                collected = collect(row.target_url)
            if not isinstance(collected, dict):
                collected = {}
            rounds_data.append(collected)
        step("正在采集页面性能")
    except Exception as exc:
        row.status = "FAILED"
        row.error_message = str(exc)[:2000]
        row.finished_at = datetime.now()
        db.commit()
        db.refresh(row)
        return row

    step("正在分析资源加载")
    page = _avg_page(rounds_data)
    network = (rounds_data[-1].get("network") if rounds_data else {}) or {}
    s_page, page_issues = page_score(page)
    s_res, res_issues = resource_score(network)
    s_net, net_issues, network_supported = network_score(network)

    step("正在统计测试执行情况")
    jobs = [{"status": j.status} for j in db.query(TestJob).filter(TestJob.project_id == row.project_id).all()]
    s_job, job_issues = job_score(jobs)
    runs = (
        db.query(RegressionRun)
        .filter(RegressionRun.project_id == row.project_id)
        .order_by(RegressionRun.created_at.desc())
        .limit(5)
        .all()
    )
    s_reg, reg_issues = regression_score([run_out(r) or {} for r in runs])

    scores = {
        "page": s_page,
        "resource": s_res,
        "network": s_net if network_supported else None,
        "job": s_job,
        "regression": s_reg,
    }
    issues = page_issues + res_issues + net_issues + job_issues + reg_issues
    total = overall_score(scores)
    advice = summarize_advice(issues, {
        "页面性能": s_page,
        "资源加载": s_res,
        "接口响应": s_net if network_supported else None,
        "测试执行效率": s_job,
        "回归效率": s_reg,
    })

    step("正在生成测评报告")
    row.score_total = total
    row.score_page = s_page
    row.score_resource = s_res
    row.score_network = s_net if network_supported else None
    row.score_job = s_job
    row.score_regression = s_reg
    row.issues_json = json.dumps(issues, ensure_ascii=False)
    row.advice_json = json.dumps({"summary": advice, "source": "rule"}, ensure_ascii=False)
    row.report_json = json.dumps({
        "page": page,
        "network": {
            "total_requests": network.get("total_requests"),
            "failed_requests": len(network.get("failed_requests") or []),
            "avg_duration_ms": network.get("avg_duration_ms"),
            "by_resource_type": network.get("by_resource_type") or {},
            "slowest_requests": (network.get("slowest_requests") or [])[:5],
        },
        "rounds": len(rounds_data),
        "unsupported": [] if network_supported else ["接口响应：当前采集未识别到 xhr/fetch 请求"],
        "jobs": {"total": len(jobs), "success": sum(1 for j in jobs if j["status"] == JobStatus.SUCCESS), "failed": sum(1 for j in jobs if j["status"] == JobStatus.FAILED)},
        "regression": run_out(runs[0]) if runs else None,
        "scoring": {
            "page": "TTFB/DOM/Load/FCP/LCP 越低越好，取已采集项平均",
            "resource": "失败率和平均耗时",
            "network": "仅当存在 xhr/fetch 时计分",
            "job": "SUCCESS 任务占比",
            "regression": "最近一次回归通过率",
            "total": "按已有维度加权：页面30% 资源20% 接口15% 任务20% 回归15%",
        },
    }, ensure_ascii=False)
    row.status = "SUCCESS"
    row.finished_at = datetime.now()
    db.query(PerformanceAssessmentMetric).filter(PerformanceAssessmentMetric.assessment_id == row.id).delete()
    metrics = [
        ("ttfb_ms", page.get("ttfb_ms"), "ms", bool(page.get("ttfb_ms"))),
        ("dom_ready_ms", page.get("dom_ready_ms"), "ms", bool(page.get("dom_ready_ms"))),
        ("load_complete_ms", page.get("load_complete_ms"), "ms", bool(page.get("load_complete_ms"))),
        ("fcp_ms", page.get("fcp_ms"), "ms", bool(page.get("fcp_ms"))),
        ("lcp_ms", page.get("lcp_ms"), "ms", bool(page.get("lcp_ms"))),
        ("score_total", total, "score", total is not None),
    ]
    for name, value, unit, supported in metrics:
        db.add(PerformanceAssessmentMetric(
            assessment_id=row.id,
            project_id=row.project_id,
            name=name,
            value=value,
            unit=unit,
            supported=1 if supported else 0,
        ))
    db.commit()
    db.refresh(row)
    return row


def list_assessments(db: Session, project_id: int) -> list[PerformanceAssessment]:
    return (
        db.query(PerformanceAssessment)
        .filter(PerformanceAssessment.project_id == project_id)
        .order_by(PerformanceAssessment.created_at.desc())
        .all()
    )


def get_assessment(db: Session, project_id: int, assessment_id: int) -> PerformanceAssessment:
    row = db.query(PerformanceAssessment).filter(
        PerformanceAssessment.id == assessment_id,
        PerformanceAssessment.project_id == project_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="测评不存在")
    return row


def delete_assessment(db: Session, project_id: int, assessment_id: int) -> None:
    row = get_assessment(db, project_id, assessment_id)
    db.query(PerformanceAssessmentMetric).filter(PerformanceAssessmentMetric.assessment_id == row.id).delete()
    db.delete(row)
    db.commit()


def env_count(db: Session, project_id: int) -> int:
    return db.query(TestEnvironment).filter(
        TestEnvironment.project_id == project_id,
        TestEnvironment.is_deleted.is_(False),
    ).count()
