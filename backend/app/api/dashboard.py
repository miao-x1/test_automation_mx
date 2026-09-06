"""
Dashboard API路由

数据隔离：所有统计自动过滤 user_id
"""
import asyncio
from typing import Optional
from fastapi import APIRouter, Query, Depends
from sqlalchemy.orm import Session
from app.core.logger import log
from app.db.database import get_db
from app.schemas.response import Response
from app.core.auth import require_auth
from app.models.user import User

router = APIRouter()


@router.get("/stats", summary="获取仪表盘统计")
async def get_dashboard_stats(
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """
    获取仪表盘核心统计数据（当前用户）

    返回：任务数、成功率、脚本数、知识库数量、图谱数量、平均执行耗时
    """
    try:
        import json as _json
        from app.models.requirement_task import RequirementTask, RequirementStatus
        from app.models.script import Script
        from app.models.test_asset import TestAsset
        from app.models.execution_record import ExecutionRecord, ExecutionStatus
        from sqlalchemy import func

        uid = user.id

        # 任务统计
        total_tasks = db.query(func.count(RequirementTask.id)).filter(RequirementTask.user_id == uid).scalar() or 0
        completed_tasks = db.query(func.count(RequirementTask.id)).filter(
            RequirementTask.user_id == uid, RequirementTask.status == RequirementStatus.COMPLETED
        ).scalar() or 0
        failed_tasks = db.query(func.count(RequirementTask.id)).filter(
            RequirementTask.user_id == uid, RequirementTask.status == RequirementStatus.FAILED
        ).scalar() or 0

        # 成功率
        finished_tasks = completed_tasks + failed_tasks
        success_rate = round(completed_tasks / finished_tasks * 100, 1) if finished_tasks > 0 else 0

        # 用例数：统一资产 + 需求任务里已生成的用例 JSON
        asset_count = db.query(func.count(TestAsset.id)).filter(
            TestAsset.user_id == uid, TestAsset.is_deleted == False,
        ).scalar() or 0
        generated_cases = 0
        for (raw,) in db.query(RequirementTask.generated_case).filter(
            RequirementTask.user_id == uid,
            RequirementTask.generated_case.isnot(None),
            RequirementTask.generated_case != "",
        ).all():
            try:
                parsed = _json.loads(raw)
                if isinstance(parsed, list):
                    generated_cases += len(parsed)
                elif isinstance(parsed, dict):
                    inner = parsed.get("cases") or parsed.get("test_cases") or parsed.get("items")
                    generated_cases += len(inner) if isinstance(inner, list) else 1
                else:
                    generated_cases += 1
            except Exception:
                generated_cases += 1
        case_count = max(asset_count, generated_cases)

        # 脚本数：Script 表 + 需求任务已落脚本 + 资产里的脚本
        total_scripts = db.query(func.count(Script.id)).filter(Script.user_id == uid).scalar() or 0
        req_scripts = db.query(func.count(RequirementTask.id)).filter(
            RequirementTask.user_id == uid,
            RequirementTask.generated_script.isnot(None),
            RequirementTask.generated_script != "",
        ).scalar() or 0
        asset_scripts = db.query(func.count(TestAsset.id)).filter(
            TestAsset.user_id == uid,
            TestAsset.is_deleted == False,
            TestAsset.script_content.isnot(None),
            TestAsset.script_content != "",
        ).scalar() or 0
        total_scripts = max(total_scripts, req_scripts, asset_scripts)

        # 执行统计
        total_executions = db.query(func.count(ExecutionRecord.id)).filter(ExecutionRecord.user_id == uid).scalar() or 0
        success_executions = db.query(func.count(ExecutionRecord.id)).filter(
            ExecutionRecord.user_id == uid, ExecutionRecord.status == ExecutionStatus.SUCCESS
        ).scalar() or 0
        failed_executions = db.query(func.count(ExecutionRecord.id)).filter(
            ExecutionRecord.user_id == uid, ExecutionRecord.status == ExecutionStatus.FAILED
        ).scalar() or 0

        # 平均执行耗时
        avg_duration = db.query(func.avg(ExecutionRecord.duration)).filter(
            ExecutionRecord.duration.isnot(None)
        ).scalar()
        avg_duration = round(float(avg_duration), 1) if avg_duration else 0

        # 知识库数量（Milvus） — 异步执行，避免阻塞事件循环
        kb_counts = {"elements": 0, "cases": 0, "scripts": 0}
        try:

            def _query_milvus():
                from app.db.milvus_client import (
                    get_milvus_client, COLLECTION_NAME, CASE_COLLECTION_NAME, SCRIPT_COLLECTION_NAME,
                )
                counts = {"elements": 0, "cases": 0, "scripts": 0}
                client = get_milvus_client(allow_fail=True)
                if client:
                    for col_name, key in [(COLLECTION_NAME, "elements"), (CASE_COLLECTION_NAME, "cases"), (SCRIPT_COLLECTION_NAME, "scripts")]:
                        try:
                            if client.has_collection(col_name):
                                client.load_collection(col_name)
                                result = client.query(col_name, filter="id >= 0", output_fields=["id"], limit=100000)
                                counts[key] = len(result)
                        except Exception:
                            pass
                return counts

            kb_counts = await asyncio.to_thread(_query_milvus)
        except Exception as e:
            log.warning(f"Dashboard获取Milvus统计失败: {e}")

        # 图谱数量（Neo4j） — 异步执行，避免阻塞事件循环
        graph_counts = {"pages": 0, "elements": 0, "cases": 0, "scripts": 0, "relationships": 0}
        try:

            def _query_neo4j():
                from app.db.neo4j_client import is_available, run_query
                counts = {"pages": 0, "elements": 0, "cases": 0, "scripts": 0, "relationships": 0}
                if is_available():
                    for label, key in [("Page", "pages"), ("Element", "elements"), ("TestCase", "cases"), ("Script", "scripts")]:
                        try:
                            result = run_query(f"MATCH (n:{label}) RETURN count(n) as cnt")
                            counts[key] = result[0]["cnt"] if result else 0
                        except Exception:
                            pass
                    try:
                        result = run_query("MATCH ()-[r]->() RETURN count(r) as cnt")
                        counts["relationships"] = result[0]["cnt"] if result else 0
                    except Exception:
                        pass
                return counts

            graph_counts = await asyncio.to_thread(_query_neo4j)
        except Exception as e:
            log.warning(f"Dashboard获取Neo4j统计失败: {e}")

        # 反馈统计
        from app.models.feedback import Feedback
        total_feedbacks = db.query(func.count(Feedback.id)).scalar() or 0
        avg_score = db.query(func.avg(Feedback.score)).scalar()
        avg_score = round(float(avg_score), 1) if avg_score else 0

        return Response(code=200, message="获取成功", data={
            # 扁平字段（兼容前端 DashboardPage 直接读取）
            "task_count": total_tasks,
            "case_count": case_count,
            "script_count": total_scripts,
            "success_rate": success_rate,
            "execution_count": total_executions,
            "avg_duration": avg_duration,
            # 嵌套结构（保留以兼容已有调用方）
            "tasks": {
                "total": total_tasks,
                "completed": completed_tasks,
                "failed": failed_tasks,
                "pending": total_tasks - completed_tasks - failed_tasks,
                "success_rate": success_rate,
            },
            "scripts": {
                "total": total_scripts,
            },
            "executions": {
                "total": total_executions,
                "success": success_executions,
                "failed": failed_executions,
                "avg_duration": avg_duration,
            },
            "knowledge_base": {
                "total": kb_counts["elements"] + kb_counts["cases"] + kb_counts["scripts"],
                **kb_counts,
            },
            "graph": {
                "total": sum(graph_counts.values()),
                **graph_counts,
            },
            "feedback": {
                "total": total_feedbacks,
                "avg_score": avg_score,
            },
        })
    except Exception as e:
        log.opt(exception=e).error("Dashboard统计异常")
        return Response(code=500, message=str(e))


@router.get("/trend", summary="获取趋势数据")
async def get_dashboard_trend(
    days: int = Query(7, ge=1, le=30, description="统计天数"),
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """
    获取最近N天的任务/执行趋势数据

    返回：每日任务数、成功数、失败数、执行耗时
    """
    try:
        from app.models.requirement_task import RequirementTask, RequirementStatus
        from app.models.execution_record import ExecutionRecord, ExecutionStatus
        from sqlalchemy import func, cast, Date, Integer
        from datetime import datetime, timedelta

        # 计算日期范围
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days - 1)

        # 按天统计任务
        task_trend = db.query(
            cast(RequirementTask.created_at, Date).label("date"),
            func.count(RequirementTask.id).label("total"),
            func.sum(func.cast(RequirementTask.status == RequirementStatus.COMPLETED, type_=Integer)).label("completed"),
            func.sum(func.cast(RequirementTask.status == RequirementStatus.FAILED, type_=Integer)).label("failed"),
        ).filter(
            cast(RequirementTask.created_at, Date) >= start_date,
            RequirementTask.user_id == user.id,
        ).group_by(
            cast(RequirementTask.created_at, Date)
        ).all()

        # 按天统计执行耗时
        exec_trend = db.query(
            cast(ExecutionRecord.created_at, Date).label("date"),
            func.count(ExecutionRecord.id).label("exec_count"),
            func.avg(ExecutionRecord.duration).label("avg_duration"),
        ).filter(
            cast(ExecutionRecord.created_at, Date) >= start_date,
            ExecutionRecord.duration.isnot(None),
            ExecutionRecord.user_id == user.id,
        ).group_by(
            cast(ExecutionRecord.created_at, Date)
        ).all()

        # 构建日期映射
        task_map = {}
        for row in task_trend:
            d = str(row.date)
            task_map[d] = {
                "date": d,
                "tasks": row.total,
                "completed": int(row.completed or 0),
                "failed": int(row.failed or 0),
            }

        exec_map = {}
        for row in exec_trend:
            d = str(row.date)
            exec_map[d] = {
                "exec_count": row.exec_count,
                "avg_duration": round(float(row.avg_duration), 1) if row.avg_duration else 0,
            }

        # 填充空日期
        trend = []
        current = start_date
        while current <= end_date:
            d = str(current)
            t = task_map.get(d, {"date": d, "tasks": 0, "completed": 0, "failed": 0})
            e = exec_map.get(d, {"exec_count": 0, "avg_duration": 0})
            trend.append({**t, **e})
            current += timedelta(days=1)

        return Response(code=200, message="获取成功", data=trend)
    except Exception as e:
        log.opt(exception=e).error("Dashboard趋势异常")
        return Response(code=500, message=str(e))


@router.get("/recent", summary="获取最近任务")
async def get_recent_tasks(
    limit: int = Query(10, ge=1, le=50, description="返回条数"),
    status: Optional[str] = Query(None, description="筛选状态: completed/failed/executing"),
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """
    获取最近的需求任务列表

    返回：任务ID、需求、状态、创建时间、执行耗时
    """
    try:
        from app.models.requirement_task import RequirementTask, RequirementStatus
        from app.models.execution_record import ExecutionRecord, ExecutionStatus

        query = db.query(RequirementTask).filter(
            RequirementTask.user_id == user.id
        ).order_by(RequirementTask.created_at.desc())

        if status:
            query = query.filter(RequirementTask.status == status)

        tasks = query.limit(limit).all()

        result = []
        for t in tasks:
            # 获取执行耗时
            duration = None
            if t.execution_id:
                exec_record = db.query(ExecutionRecord).filter(ExecutionRecord.id == t.execution_id).first()
                if exec_record and exec_record.duration:
                    duration = round(exec_record.duration, 1)

            result.append({
                "id": t.id,
                "task_name": (t.requirement or "")[:60] or f"任务 #{t.id}",
                "requirement": (t.requirement or "")[:80],
                "status": t.status,
                "intent": t.intent,
                "script_source": t.script_source,
                "created_at": str(t.created_at) if t.created_at else None,
                "duration": duration,
            })

        return Response(code=200, message="获取成功", data={"items": result, "total": len(result)})
    except Exception as e:
        log.opt(exception=e).error("Dashboard最近任务异常")
        return Response(code=500, message=str(e))
