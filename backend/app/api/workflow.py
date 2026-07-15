"""
Workflow API - 事件驱动工作流管理（替代SSE流式推送）

所有工作流步骤通过 WorkflowEvent 记录到DB，
前端通过轮询 /workflow/status 和 /workflow/events 获取进度。

流程：
  Requirement → APIExtraction → RAG → CaseGenerate → Review

端点：
  POST /workflow/start             - 启动工作流
  GET  /workflow/status            - 查询工作流状态
  GET  /workflow/events            - 查询工作流事件
  GET  /workflow/result            - 获取Agent结果
  GET  /workflow/logs              - 获取工作流日志
  POST /workflow/resume            - 恢复暂停/失败的工作流
  POST /workflow/rerun             - 重跑整个工作流
"""
import json
import time
import asyncio
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel as PydanticModel
from sqlalchemy.orm import Session as DbSession

from app.core.auth import require_auth
from app.models.user import User
from app.models.session import Session, SessionStatus
from app.models.workflow_event import WorkflowEvent, WorkflowEventType
from app.models.agent_result import AgentResult
from app.models.api_metadata import ApiMetadata
from app.db.database import SessionLocal
from app.core.logger import log
from app.runtime.agent_factory import AgentFactory

router = APIRouter()


# ========== 请求模型 ==========

class StartRequest(PydanticModel):
    """启动工作流请求"""
    requirement_text: str
    project_id: str = ""
    config: dict = {}


class ResumeRequest(PydanticModel):
    """恢复工作流请求"""
    session_id: int


class RerunRequest(PydanticModel):
    """重跑工作流请求"""
    session_id: int


# ========== 辅助函数 ==========

def _emit_event(
    db: DbSession,
    session_id: int,
    agent: str,
    event_type: str,
    message: str = None,
    cost: float = None,
    duration: float = None,
):
    """写入工作流事件"""
    event = WorkflowEvent(
        session_id=session_id,
        agent=agent,
        event_type=event_type,
        message=message,
        cost=cost,
        duration=duration,
    )
    db.add(event)
    db.commit()


def _save_agent_result(
    db: DbSession,
    session_id: int,
    agent: str,
    result_data: dict,
    user_id: int,
    cost: float = None,
    duration: float = None,
    status: str = "success",
    error_message: str = None,
):
    """写入Agent执行结果"""
    result = AgentResult(
        session_id=session_id,
        agent=agent,
        result_json=json.dumps(result_data, ensure_ascii=False) if result_data else None,
        cost=cost,
        duration=duration,
        status=status,
        error_message=error_message,
        user_id=user_id,
        created_by=user_id,
    )
    db.add(result)
    db.commit()


def _update_session_step(db: DbSession, session: Session, step: str):
    """更新Session当前步骤"""
    session.current_step = step
    db.commit()


def _compute_status(db: DbSession, session_id: int) -> dict:
    """从workflow_event记录计算工作流状态"""
    events = (
        db.query(WorkflowEvent)
        .filter(WorkflowEvent.session_id == session_id)
        .order_by(WorkflowEvent.created_at)
        .all()
    )

    if not events:
        return {"status": "queued", "current_step": None, "agents": [], "total_duration": 0}

    # 按agent分组，计算每个agent的状态
    agent_order = ["Requirement", "APIExtraction", "RAG", "CaseGenerate", "Review"]
    agent_map = {}
    for ev in events:
        if ev.agent not in agent_map:
            agent_map[ev.agent] = {"events": []}
        agent_map[ev.agent]["events"].append(ev)

    agents_info = []
    has_error = False
    current_step = None
    total_duration = 0.0

    for agent_name in agent_order:
        if agent_name not in agent_map:
            continue

        agent_events = agent_map[agent_name]["events"]
        start_ev = None
        success_ev = None
        error_ev = None
        duration = None

        for ev in agent_events:
            if ev.event_type == WorkflowEventType.START:
                start_ev = ev
            elif ev.event_type == WorkflowEventType.SUCCESS:
                success_ev = ev
            elif ev.event_type == WorkflowEventType.ERROR:
                error_ev = ev

        if error_ev:
            agent_status = "error"
            has_error = True
            current_step = agent_name
        elif success_ev:
            agent_status = "success"
            if success_ev.duration:
                duration = success_ev.duration
                total_duration += duration
        elif start_ev:
            agent_status = "running"
            current_step = agent_name
        else:
            agent_status = "pending"

        agents_info.append({
            "agent": agent_name,
            "status": agent_status,
            "duration": duration,
            "message": (success_ev or error_ev or start_ev).message if (success_ev or error_ev or start_ev) else None,
        })

    # 整体状态
    if has_error:
        status = "failed"
    elif any(a["status"] == "running" for a in agents_info):
        status = "running"
    elif all(a["status"] == "success" for a in agents_info):
        status = "completed"
    else:
        status = "queued"

    return {
        "status": status,
        "current_step": current_step,
        "agents": agents_info,
        "total_duration": total_duration,
    }


# ========== 后台工作流执行 ==========

async def _run_workflow(session_id: int, requirement_text: str, config: dict, user_id: int):
    """后台工作流执行"""
    db = SessionLocal()
    try:
        session = db.query(Session).filter(Session.id == session_id).first()
        if not session:
            _emit_event(db, session_id, "Workflow", WorkflowEventType.ERROR, message="会话不存在")
            return

        # Step 1: Requirement Understanding
        _update_session_step(db, session, "requirement")
        _emit_event(db, session_id, "Requirement", WorkflowEventType.START)
        t0 = time.time()
        try:
            from app.services.generation.requirement_agent import RequirementAgent
            from app.services.generation.context import GenerationContext

            ctx = GenerationContext(
                session_id=session_id,
                requirement=requirement_text,
                requirement_summary=requirement_text[:500],
                config=config,
                user_id=user_id,
            )
            req_agent = RequirementAgent()
            features = req_agent.analyze(ctx)
            duration = round(time.time() - t0, 2)

            _save_agent_result(
                db, session_id, "Requirement",
                {"features": features, "requirement_summary": requirement_text[:500]},
                user_id=user_id, duration=duration,
            )
            _emit_event(
                db, session_id, "Requirement", WorkflowEventType.SUCCESS,
                message="需求理解完成", duration=duration,
            )
        except Exception as e:
            duration = round(time.time() - t0, 2)
            _emit_event(
                db, session_id, "Requirement", WorkflowEventType.ERROR,
                message=str(e), duration=duration,
            )
            _save_agent_result(
                db, session_id, "Requirement", None,
                user_id=user_id, duration=duration, status="error", error_message=str(e),
            )
            raise

        # Step 2: API Extraction
        _update_session_step(db, session, "api_extraction")
        _emit_event(db, session_id, "APIExtraction", WorkflowEventType.START)
        t0 = time.time()
        try:
            # 从需求中提取API信息
            api_list = _extract_apis(requirement_text, features)
            duration = round(time.time() - t0, 2)

            # 保存API元数据
            for api_info in api_list:
                api_meta = ApiMetadata(
                    session_id=session_id,
                    method=api_info.get("method", "GET"),
                    url=api_info.get("url", ""),
                    summary=api_info.get("summary", ""),
                    request_schema=json.dumps(api_info.get("request_schema"), ensure_ascii=False) if api_info.get("request_schema") else None,
                    response_schema=json.dumps(api_info.get("response_schema"), ensure_ascii=False) if api_info.get("response_schema") else None,
                    source="ai",
                    user_id=user_id,
                    created_by=user_id,
                )
                db.add(api_meta)
            db.commit()

            _save_agent_result(
                db, session_id, "APIExtraction",
                {"api_count": len(api_list), "apis": api_list},
                user_id=user_id, duration=duration,
            )
            _emit_event(
                db, session_id, "APIExtraction", WorkflowEventType.SUCCESS,
                message=f"提取{len(api_list)}个API", duration=duration,
            )
        except Exception as e:
            duration = round(time.time() - t0, 2)
            _emit_event(
                db, session_id, "APIExtraction", WorkflowEventType.ERROR,
                message=str(e), duration=duration,
            )
            _save_agent_result(
                db, session_id, "APIExtraction", None,
                user_id=user_id, duration=duration, status="error", error_message=str(e),
            )
            raise

        # Step 3: RAG
        _update_session_step(db, session, "rag")
        _emit_event(db, session_id, "RAG", WorkflowEventType.START)
        t0 = time.time()
        try:
            from app.services.generation.rag_agent import RagAgent
            from app.services.generation.context import GenerationContext

            ctx = GenerationContext(
                session_id=session_id,
                requirement=requirement_text,
                requirement_summary=requirement_text[:500],
                features=features,
                config=config,
                user_id=user_id,
            )
            rag_agent = RagAgent()
            rag_result = rag_agent.retrieve(ctx)
            duration = round(time.time() - t0, 2)

            _save_agent_result(
                db, session_id, "RAG",
                {
                    "has_context": rag_result.has_context,
                    "total": rag_result.total,
                    "context_preview": rag_result.context[:500] if rag_result.context else "",
                },
                user_id=user_id, duration=duration,
            )
            _emit_event(
                db, session_id, "RAG", WorkflowEventType.SUCCESS,
                message="RAG检索完成", duration=duration,
            )
        except Exception as e:
            duration = round(time.time() - t0, 2)
            _emit_event(
                db, session_id, "RAG", WorkflowEventType.ERROR,
                message=str(e), duration=duration,
            )
            _save_agent_result(
                db, session_id, "RAG", None,
                user_id=user_id, duration=duration, status="error", error_message=str(e),
            )
            raise

        # Step 4: Case Generate
        _update_session_step(db, session, "case")
        _emit_event(db, session_id, "CaseGenerate", WorkflowEventType.START)
        t0 = time.time()
        try:
            from app.services.generation.case_generate_agent import CaseGenerateAgent
            from app.services.generation.context import GenerationContext

            ctx = GenerationContext(
                session_id=session_id,
                requirement=requirement_text,
                requirement_summary=requirement_text[:500],
                features=features,
                rag={"context": rag_result.context, "elements": rag_result.elements} if rag_result.has_context else None,
                config=config,
                user_id=user_id,
            )
            gen_agent = CaseGenerateAgent()
            cases = gen_agent.generate(ctx)
            duration = round(time.time() - t0, 2)

            cases_data = [c.__dict__ if hasattr(c, "__dict__") else c for c in cases]
            _save_agent_result(
                db, session_id, "CaseGenerate",
                {"case_count": len(cases), "cases": cases_data},
                user_id=user_id, duration=duration,
            )
            _emit_event(
                db, session_id, "CaseGenerate", WorkflowEventType.SUCCESS,
                message=f"生成{len(cases)}条用例", duration=duration,
            )
        except Exception as e:
            duration = round(time.time() - t0, 2)
            _emit_event(
                db, session_id, "CaseGenerate", WorkflowEventType.ERROR,
                message=str(e), duration=duration,
            )
            _save_agent_result(
                db, session_id, "CaseGenerate", None,
                user_id=user_id, duration=duration, status="error", error_message=str(e),
            )
            raise

        # Step 5: Review
        _update_session_step(db, session, "review")
        _emit_event(db, session_id, "Review", WorkflowEventType.START)
        t0 = time.time()
        try:
            from app.services.generation.review_agent import ReviewAgent
            from app.services.generation.context import GenerationContext

            ctx = GenerationContext(
                session_id=session_id,
                requirement=requirement_text,
                requirement_summary=requirement_text[:500],
                features=features,
                config=config,
                user_id=user_id,
            )
            review_agent = ReviewAgent()
            review_result = review_agent.review(ctx, cases)
            duration = round(time.time() - t0, 2)

            _save_agent_result(
                db, session_id, "Review",
                {
                    "passed": review_result.passed,
                    "issues": review_result.issues,
                    "suggestions": review_result.suggestions,
                    "quality_score": review_result.quality_score,
                },
                user_id=user_id, duration=duration,
            )
            _emit_event(
                db, session_id, "Review", WorkflowEventType.SUCCESS,
                message="审查完成", duration=duration,
            )
        except Exception as e:
            duration = round(time.time() - t0, 2)
            _emit_event(
                db, session_id, "Review", WorkflowEventType.ERROR,
                message=str(e), duration=duration,
            )
            _save_agent_result(
                db, session_id, "Review", None,
                user_id=user_id, duration=duration, status="error", error_message=str(e),
            )
            raise

        # 工作流完成，更新Session状态
        session.status = SessionStatus.COMPLETED
        db.commit()

    except Exception as e:
        # 整体工作流异常（子步骤已记录ERROR事件）
        log.error(f"_run_workflow | session_id={session_id} error={e}")
        try:
            session = db.query(Session).filter(Session.id == session_id).first()
            if session:
                session.status = SessionStatus.PAUSED
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _extract_apis(requirement_text: str, features: list) -> list:
    """从需求文本和特性中提取API信息"""
    api_list = []
    try:
        agent = AgentFactory.create("api_extraction_agent")
        result = agent.extract(requirement_text, features)
        if isinstance(result, list):
            api_list = result
        elif isinstance(result, dict):
            api_list = result.get("apis", [])
    except Exception as e:
        log.warning(f"_extract_apis | API提取失败，使用默认: {e}")
        # 降级：从features中提取简单API信息
        for feat in features:
            if isinstance(feat, dict):
                api_list.append({
                    "method": "POST",
                    "url": f"/api/{feat.get('feature_name', 'unknown')}".replace(" ", "_").lower(),
                    "summary": feat.get("description", ""),
                })
    return api_list


# ========== API端点 ==========

@router.post("/start")
async def start_workflow(
    request: StartRequest,
    user: User = Depends(require_auth),
):
    """
    启动工作流

    创建Session并启动后台工作流任务，返回session_id和状态。
    """
    db = SessionLocal()
    try:
        # 创建Session
        session = Session(
            session_name=request.requirement_text[:50] + "..." if len(request.requirement_text) > 50 else request.requirement_text,
            project_id=request.project_id or None,
            status=SessionStatus.ACTIVE,
            current_step="queued",
            requirement_summary=request.requirement_text[:500],
            config_json=json.dumps(request.config, ensure_ascii=False) if request.config else None,
            user_id=user.id,
            created_by=user.id,
        )
        db.add(session)
        db.commit()
        db.refresh(session)

        session_id = session.id

        # 记录初始事件
        _emit_event(db, session_id, "Workflow", WorkflowEventType.START, message="工作流已启动")

        # 启动后台任务
        asyncio.create_task(
            _run_workflow(session_id, request.requirement_text, request.config, user.id)
        )

        return {"session_id": session_id, "status": "queued"}
    finally:
        db.close()


@router.get("/status")
async def get_workflow_status(
    session_id: int = Query(..., description="会话ID"),
    user: User = Depends(require_auth),
):
    """
    获取工作流状态

    从workflow_event记录计算当前状态、各Agent进度和总耗时。
    """
    db = SessionLocal()
    try:
        session = db.query(Session).filter(Session.id == session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")

        status_info = _compute_status(db, session_id)

        return {
            "session_id": session_id,
            "status": status_info["status"],
            "current_step": status_info["current_step"],
            "agents": status_info["agents"],
            "total_duration": status_info["total_duration"],
        }
    finally:
        db.close()


@router.get("/events")
async def get_workflow_events(
    session_id: int = Query(..., description="会话ID"),
    agent: Optional[str] = Query(None, description="Agent名称过滤"),
    event_type: Optional[str] = Query(None, description="事件类型过滤"),
    user: User = Depends(require_auth),
):
    """
    获取工作流事件列表

    支持按agent和event_type过滤。
    """
    db = SessionLocal()
    try:
        session = db.query(Session).filter(Session.id == session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")

        query = db.query(WorkflowEvent).filter(WorkflowEvent.session_id == session_id)
        if agent:
            query = query.filter(WorkflowEvent.agent == agent)
        if event_type:
            query = query.filter(WorkflowEvent.event_type == event_type)

        events = query.order_by(WorkflowEvent.created_at).all()

        return [
            {
                "id": e.id,
                "session_id": e.session_id,
                "agent": e.agent,
                "event_type": e.event_type,
                "message": e.message,
                "cost": e.cost,
                "duration": e.duration,
                "created_at": str(e.created_at) if e.created_at else None,
            }
            for e in events
        ]
    finally:
        db.close()


@router.get("/result")
async def get_agent_result(
    session_id: int = Query(..., description="会话ID"),
    agent: str = Query(..., description="Agent名称"),
    user: User = Depends(require_auth),
):
    """
    获取指定Agent的执行结果

    返回AgentResult记录，包含结构化输出数据。
    """
    db = SessionLocal()
    try:
        session = db.query(Session).filter(Session.id == session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")

        result = (
            db.query(AgentResult)
            .filter(AgentResult.session_id == session_id, AgentResult.agent == agent)
            .order_by(AgentResult.created_at.desc())
            .first()
        )

        if not result:
            raise HTTPException(status_code=404, detail=f"Agent {agent} 的结果不存在")

        result_data = None
        if result.result_json:
            try:
                result_data = json.loads(result.result_json)
            except (json.JSONDecodeError, TypeError):
                result_data = result.result_json

        return {
            "id": result.id,
            "session_id": result.session_id,
            "agent": result.agent,
            "result": result_data,
            "cost": result.cost,
            "duration": result.duration,
            "status": result.status,
            "error_message": result.error_message,
            "created_at": str(result.created_at) if result.created_at else None,
        }
    finally:
        db.close()


@router.get("/logs")
async def get_workflow_logs(
    session_id: int = Query(..., description="会话ID"),
    download: bool = Query(False, description="是否下载为文本文件"),
    user: User = Depends(require_auth),
):
    """
    获取工作流日志

    返回所有事件和结果，用于调试。支持下载为文本文件。
    """
    db = SessionLocal()
    try:
        session = db.query(Session).filter(Session.id == session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")

        # 获取所有事件
        events = (
            db.query(WorkflowEvent)
            .filter(WorkflowEvent.session_id == session_id)
            .order_by(WorkflowEvent.created_at)
            .all()
        )

        # 获取所有结果
        results = (
            db.query(AgentResult)
            .filter(AgentResult.session_id == session_id)
            .order_by(AgentResult.created_at)
            .all()
        )

        events_data = [
            {
                "id": e.id,
                "agent": e.agent,
                "event_type": e.event_type,
                "message": e.message,
                "cost": e.cost,
                "duration": e.duration,
                "created_at": str(e.created_at) if e.created_at else None,
            }
            for e in events
        ]

        results_data = []
        for r in results:
            r_data = None
            if r.result_json:
                try:
                    r_data = json.loads(r.result_json)
                except (json.JSONDecodeError, TypeError):
                    r_data = r.result_json
            results_data.append({
                "id": r.id,
                "agent": r.agent,
                "status": r.status,
                "duration": r.duration,
                "error_message": r.error_message,
                "result": r_data,
                "created_at": str(r.created_at) if r.created_at else None,
            })

        log_data = {
            "session_id": session_id,
            "session_name": session.session_name,
            "session_status": session.status,
            "events": events_data,
            "results": results_data,
        }

        if download:
            # 格式化为可读文本
            lines = []
            lines.append(f"=== 工作流日志 (Session #{session_id}) ===")
            lines.append(f"会话名称: {session.session_name}")
            lines.append(f"状态: {session.status}")
            lines.append("")
            lines.append("--- 事件 ---")
            for e in events_data:
                lines.append(f"[{e['created_at']}] {e['agent']} | {e['event_type']} | {e['message'] or ''}")
            lines.append("")
            lines.append("--- 结果 ---")
            for r in results_data:
                lines.append(f"[{r['created_at']}] {r['agent']} | {r['status']} | duration={r['duration']}s")
                if r["error_message"]:
                    lines.append(f"  错误: {r['error_message']}")
            lines.append("")
            lines.append("=== 日志结束 ===")
            return PlainTextResponse("\n".join(lines), media_type="text/plain; charset=utf-8")

        return log_data
    finally:
        db.close()


@router.post("/resume")
async def resume_workflow(
    request: ResumeRequest,
    user: User = Depends(require_auth),
):
    """
    恢复暂停/失败的工作流

    从最后一个失败的步骤继续执行。
    """
    db = SessionLocal()
    try:
        session = db.query(Session).filter(Session.id == request.session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")

        if session.status not in (SessionStatus.PAUSED, "paused"):
            raise HTTPException(status_code=400, detail="只能恢复暂停或失败的工作流")

        # 找到最后一个ERROR事件对应的agent
        last_error = (
            db.query(WorkflowEvent)
            .filter(
                WorkflowEvent.session_id == request.session_id,
                WorkflowEvent.event_type == WorkflowEventType.ERROR,
            )
            .order_by(WorkflowEvent.created_at.desc())
            .first()
        )

        if not last_error:
            raise HTTPException(status_code=400, detail="未找到失败步骤，无法恢复")

        # 清除失败步骤及之后的事件和结果
        failed_agent = last_error.agent
        _clear_agent_data(db, request.session_id, failed_agent)

        # 更新Session状态
        session.status = SessionStatus.ACTIVE
        session.current_step = failed_agent.lower()
        db.commit()

        # 获取之前成功步骤的结果
        requirement_text = session.requirement_summary or ""
        config = {}
        if session.config_json:
            try:
                config = json.loads(session.config_json)
            except (json.JSONDecodeError, TypeError):
                config = {}

        # 重新启动后台任务（从失败步骤继续）
        _emit_event(db, request.session_id, "Workflow", WorkflowEventType.START, message=f"从{failed_agent}步骤恢复")

        asyncio.create_task(
            _run_workflow_resume(request.session_id, requirement_text, config, user.id, failed_agent)
        )

        return {"session_id": request.session_id, "status": "resumed", "resume_from": failed_agent}
    finally:
        db.close()


@router.post("/rerun")
async def rerun_workflow(
    request: RerunRequest,
    user: User = Depends(require_auth),
):
    """
    重跑整个工作流

    清除所有结果，从头开始执行。
    """
    db = SessionLocal()
    try:
        session = db.query(Session).filter(Session.id == request.session_id).first()
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")

        # 清除所有事件和结果
        db.query(WorkflowEvent).filter(WorkflowEvent.session_id == request.session_id).delete()
        db.query(AgentResult).filter(AgentResult.session_id == request.session_id).delete()
        db.query(ApiMetadata).filter(ApiMetadata.session_id == request.session_id).delete()

        # 重置Session状态
        session.status = SessionStatus.ACTIVE
        session.current_step = "queued"
        db.commit()

        requirement_text = session.requirement_summary or ""
        config = {}
        if session.config_json:
            try:
                config = json.loads(session.config_json)
            except (json.JSONDecodeError, TypeError):
                config = {}

        # 记录初始事件
        _emit_event(db, request.session_id, "Workflow", WorkflowEventType.START, message="工作流重新启动")

        # 启动后台任务
        asyncio.create_task(
            _run_workflow(request.session_id, requirement_text, config, user.id)
        )

        return {"session_id": request.session_id, "status": "queued"}
    finally:
        db.close()


def _clear_agent_data(db: DbSession, session_id: int, agent: str):
    """清除指定agent的事件和结果（用于恢复时清理失败步骤）"""
    # 获取agent顺序
    agent_order = ["Requirement", "APIExtraction", "RAG", "CaseGenerate", "Review"]
    try:
        start_idx = agent_order.index(agent)
    except ValueError:
        start_idx = 0

    # 清除该agent及之后所有agent的事件和结果
    agents_to_clear = agent_order[start_idx:]
    for a in agents_to_clear:
        db.query(WorkflowEvent).filter(
            WorkflowEvent.session_id == session_id,
            WorkflowEvent.agent == a,
        ).delete()
        db.query(AgentResult).filter(
            AgentResult.session_id == session_id,
            AgentResult.agent == a,
        ).delete()
    # 同时清除Workflow级别的ERROR事件
    db.query(WorkflowEvent).filter(
        WorkflowEvent.session_id == session_id,
        WorkflowEvent.agent == "Workflow",
        WorkflowEvent.event_type == WorkflowEventType.ERROR,
    ).delete()
    db.commit()


async def _run_workflow_resume(
    session_id: int, requirement_text: str, config: dict, user_id: int, resume_from: str
):
    """从指定步骤恢复工作流执行"""
    db = SessionLocal()
    try:
        session = db.query(Session).filter(Session.id == session_id).first()
        if not session:
            _emit_event(db, session_id, "Workflow", WorkflowEventType.ERROR, message="会话不存在")
            return

        # 获取之前成功步骤的结果
        req_result = None
        api_result = None
        rag_result_obj = None

        req_ar = (
            db.query(AgentResult)
            .filter(AgentResult.session_id == session_id, AgentResult.agent == "Requirement")
            .first()
        )
        if req_ar and req_ar.result_json:
            try:
                req_result = json.loads(req_ar.result_json)
            except (json.JSONDecodeError, TypeError):
                req_result = None

        api_ar = (
            db.query(AgentResult)
            .filter(AgentResult.session_id == session_id, AgentResult.agent == "APIExtraction")
            .first()
        )
        if api_ar and api_ar.result_json:
            try:
                api_result = json.loads(api_ar.result_json)
            except (json.JSONDecodeError, TypeError):
                api_result = None

        rag_ar = (
            db.query(AgentResult)
            .filter(AgentResult.session_id == session_id, AgentResult.agent == "RAG")
            .first()
        )
        if rag_ar and rag_ar.result_json:
            try:
                rag_result_obj = json.loads(rag_ar.result_json)
            except (json.JSONDecodeError, TypeError):
                rag_result_obj = None

        features = req_result.get("features", []) if req_result else []
        api_list = api_result.get("apis", []) if api_result else []

        # 根据恢复步骤执行
        agent_order = ["Requirement", "APIExtraction", "RAG", "CaseGenerate", "Review"]
        try:
            start_idx = agent_order.index(resume_from)
        except ValueError:
            start_idx = 0

        for step_idx in range(start_idx, len(agent_order)):
            agent_name = agent_order[step_idx]

            if agent_name == "Requirement":
                _update_session_step(db, session, "requirement")
                _emit_event(db, session_id, "Requirement", WorkflowEventType.START)
                t0 = time.time()
                try:
                    from app.services.generation.requirement_agent import RequirementAgent
                    from app.services.generation.context import GenerationContext
                    ctx = GenerationContext(
                        session_id=session_id,
                        requirement=requirement_text,
                        requirement_summary=requirement_text[:500],
                        config=config,
                        user_id=user_id,
                    )
                    req_agent = RequirementAgent()
                    features = req_agent.analyze(ctx)
                    duration = round(time.time() - t0, 2)
                    _save_agent_result(
                        db, session_id, "Requirement",
                        {"features": features, "requirement_summary": requirement_text[:500]},
                        user_id=user_id, duration=duration,
                    )
                    _emit_event(db, session_id, "Requirement", WorkflowEventType.SUCCESS, message="需求理解完成", duration=duration)
                except Exception as e:
                    duration = round(time.time() - t0, 2)
                    _emit_event(db, session_id, "Requirement", WorkflowEventType.ERROR, message=str(e), duration=duration)
                    _save_agent_result(db, session_id, "Requirement", None, user_id=user_id, duration=duration, status="error", error_message=str(e))
                    raise

            elif agent_name == "APIExtraction":
                _update_session_step(db, session, "api_extraction")
                _emit_event(db, session_id, "APIExtraction", WorkflowEventType.START)
                t0 = time.time()
                try:
                    api_list = _extract_apis(requirement_text, features)
                    duration = round(time.time() - t0, 2)
                    for api_info in api_list:
                        api_meta = ApiMetadata(
                            session_id=session_id,
                            method=api_info.get("method", "GET"),
                            url=api_info.get("url", ""),
                            summary=api_info.get("summary", ""),
                            request_schema=json.dumps(api_info.get("request_schema"), ensure_ascii=False) if api_info.get("request_schema") else None,
                            response_schema=json.dumps(api_info.get("response_schema"), ensure_ascii=False) if api_info.get("response_schema") else None,
                            source="ai",
                            user_id=user_id,
                            created_by=user_id,
                        )
                        db.add(api_meta)
                    db.commit()
                    _save_agent_result(
                        db, session_id, "APIExtraction",
                        {"api_count": len(api_list), "apis": api_list},
                        user_id=user_id, duration=duration,
                    )
                    _emit_event(db, session_id, "APIExtraction", WorkflowEventType.SUCCESS, message=f"提取{len(api_list)}个API", duration=duration)
                except Exception as e:
                    duration = round(time.time() - t0, 2)
                    _emit_event(db, session_id, "APIExtraction", WorkflowEventType.ERROR, message=str(e), duration=duration)
                    _save_agent_result(db, session_id, "APIExtraction", None, user_id=user_id, duration=duration, status="error", error_message=str(e))
                    raise

            elif agent_name == "RAG":
                _update_session_step(db, session, "rag")
                _emit_event(db, session_id, "RAG", WorkflowEventType.START)
                t0 = time.time()
                try:
                    from app.services.generation.rag_agent import RagAgent
                    from app.services.generation.context import GenerationContext
                    ctx = GenerationContext(
                        session_id=session_id,
                        requirement=requirement_text,
                        requirement_summary=requirement_text[:500],
                        features=features,
                        config=config,
                        user_id=user_id,
                    )
                    rag_agent = RagAgent()
                    rag_result = rag_agent.retrieve(ctx)
                    duration = round(time.time() - t0, 2)
                    _save_agent_result(
                        db, session_id, "RAG",
                        {
                            "has_context": rag_result.has_context,
                            "total": rag_result.total,
                            "context_preview": rag_result.context[:500] if rag_result.context else "",
                        },
                        user_id=user_id, duration=duration,
                    )
                    _emit_event(db, session_id, "RAG", WorkflowEventType.SUCCESS, message="RAG检索完成", duration=duration)
                except Exception as e:
                    duration = round(time.time() - t0, 2)
                    _emit_event(db, session_id, "RAG", WorkflowEventType.ERROR, message=str(e), duration=duration)
                    _save_agent_result(db, session_id, "RAG", None, user_id=user_id, duration=duration, status="error", error_message=str(e))
                    raise

            elif agent_name == "CaseGenerate":
                _update_session_step(db, session, "case")
                _emit_event(db, session_id, "CaseGenerate", WorkflowEventType.START)
                t0 = time.time()
                try:
                    from app.services.generation.case_generate_agent import CaseGenerateAgent
                    from app.services.generation.context import GenerationContext
                    # 重建RAG上下文
                    rag_ctx = None
                    if rag_result_obj and rag_result_obj.get("has_context"):
                        # 尝试从RAG Agent结果获取context
                        try:
                            from app.services.generation.rag_agent import RagAgent
                            rag_a = RagAgent()
                            tmp_ctx = GenerationContext(
                                session_id=session_id,
                                requirement=requirement_text,
                                requirement_summary=requirement_text[:500],
                                features=features,
                                config=config,
                                user_id=user_id,
                            )
                            rag_retrieve = rag_a.retrieve(tmp_ctx)
                            rag_ctx = {"context": rag_retrieve.context, "elements": rag_retrieve.elements} if rag_retrieve.has_context else None
                        except Exception:
                            pass

                    ctx = GenerationContext(
                        session_id=session_id,
                        requirement=requirement_text,
                        requirement_summary=requirement_text[:500],
                        features=features,
                        rag=rag_ctx,
                        config=config,
                        user_id=user_id,
                    )
                    gen_agent = CaseGenerateAgent()
                    cases = gen_agent.generate(ctx)
                    duration = round(time.time() - t0, 2)
                    cases_data = [c.__dict__ if hasattr(c, "__dict__") else c for c in cases]
                    _save_agent_result(
                        db, session_id, "CaseGenerate",
                        {"case_count": len(cases), "cases": cases_data},
                        user_id=user_id, duration=duration,
                    )
                    _emit_event(db, session_id, "CaseGenerate", WorkflowEventType.SUCCESS, message=f"生成{len(cases)}条用例", duration=duration)
                except Exception as e:
                    duration = round(time.time() - t0, 2)
                    _emit_event(db, session_id, "CaseGenerate", WorkflowEventType.ERROR, message=str(e), duration=duration)
                    _save_agent_result(db, session_id, "CaseGenerate", None, user_id=user_id, duration=duration, status="error", error_message=str(e))
                    raise

            elif agent_name == "Review":
                _update_session_step(db, session, "review")
                _emit_event(db, session_id, "Review", WorkflowEventType.START)
                t0 = time.time()
                try:
                    from app.services.generation.review_agent import ReviewAgent
                    from app.services.generation.context import GenerationContext
                    # 获取CaseGenerate结果
                    case_ar = (
                        db.query(AgentResult)
                        .filter(AgentResult.session_id == session_id, AgentResult.agent == "CaseGenerate")
                        .first()
                    )
                    cases = []
                    if case_ar and case_ar.result_json:
                        try:
                            case_data = json.loads(case_ar.result_json)
                            # 重建CaseDTO列表用于review
                            cases = case_data.get("cases", [])
                        except (json.JSONDecodeError, TypeError):
                            pass

                    ctx = GenerationContext(
                        session_id=session_id,
                        requirement=requirement_text,
                        requirement_summary=requirement_text[:500],
                        features=features,
                        config=config,
                        user_id=user_id,
                    )
                    review_agent = ReviewAgent()
                    review_result = review_agent.review(ctx, cases)
                    duration = round(time.time() - t0, 2)
                    _save_agent_result(
                        db, session_id, "Review",
                        {
                            "passed": review_result.passed,
                            "issues": review_result.issues,
                            "suggestions": review_result.suggestions,
                            "quality_score": review_result.quality_score,
                        },
                        user_id=user_id, duration=duration,
                    )
                    _emit_event(db, session_id, "Review", WorkflowEventType.SUCCESS, message="审查完成", duration=duration)
                except Exception as e:
                    duration = round(time.time() - t0, 2)
                    _emit_event(db, session_id, "Review", WorkflowEventType.ERROR, message=str(e), duration=duration)
                    _save_agent_result(db, session_id, "Review", None, user_id=user_id, duration=duration, status="error", error_message=str(e))
                    raise

        # 工作流完成
        session.status = SessionStatus.COMPLETED
        db.commit()

    except Exception as e:
        log.error(f"_run_workflow_resume | session_id={session_id} error={e}")
        try:
            session = db.query(Session).filter(Session.id == session_id).first()
            if session:
                session.status = SessionStatus.PAUSED
                db.commit()
        except Exception:
            pass
    finally:
        db.close()
