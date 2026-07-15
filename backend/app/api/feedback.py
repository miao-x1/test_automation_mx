"""
用户反馈 API路由

数据隔离：所有查询自动过滤 user_id
"""
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from typing import Optional
from app.db.database import SessionLocal
from app.models.feedback import Feedback
from app.models.requirement_task import RequirementTask, RequirementStatus
from app.models.execution_record import ExecutionRecord
from app.runtime.agent_factory import AgentFactory
from app.schemas.response import Response
from app.core.logger import log
from app.core.auth import require_auth
from app.models.user import User

router = APIRouter()


class SubmitFeedbackRequest(BaseModel):
    """提交反馈请求"""
    requirement_id: int
    score: int  # 1-5
    comment: Optional[str] = None
    accepted: Optional[bool] = None


@router.post("/submit", summary="提交用户反馈")
async def submit_feedback(request: SubmitFeedbackRequest, user: User = Depends(require_auth)):
    """提交用户反馈（仅限自己的需求任务）"""
    if request.score < 1 or request.score > 5:
        raise HTTPException(status_code=400, detail="评分必须在1-5之间")

    db = SessionLocal()
    try:
        req_task = db.query(RequirementTask).filter(
            RequirementTask.id == request.requirement_id,
            RequirementTask.user_id == user.id,
        ).first()
        if not req_task:
            raise HTTPException(status_code=404, detail="需求任务不存在")

        exec_record = None
        if req_task.execution_id:
            exec_record = db.query(ExecutionRecord).filter(
                ExecutionRecord.id == req_task.execution_id
            ).first()

        failure_analysis = None
        if request.score <= 3 or request.accepted is False:
            try:
                agent = AgentFactory.create("feedback_agent")
                exec_result = {
                    "status": exec_record.status if exec_record else "unknown",
                    "error_message": exec_record.error_message if exec_record else "",
                    "log_content": exec_record.log_content if exec_record else "",
                    "failed_count": exec_record.failed_count if exec_record else 0,
                    "success_count": exec_record.success_count if exec_record else 0,
                }
                analysis = agent.analyze_failure(
                    requirement=req_task.requirement,
                    script_content=req_task.generated_script or "",
                    exec_result=exec_result,
                    user_comment=request.comment or "",
                    score=request.score,
                )
                failure_analysis = analysis
            except Exception as e:
                log.warning(f"FeedbackAgent分析失败: {e}")

        feedback = Feedback(
            requirement_id=request.requirement_id,
            task_id=req_task.task_id,
            script_id=None,
            score=request.score,
            comment=request.comment,
            accepted=request.accepted,
            failure_analysis=failure_analysis and __import__('json').dumps(failure_analysis, ensure_ascii=False),
            regenerated=False,
            user_id=user.id,
            created_by=user.id,
        )
        db.add(feedback)
        db.commit()
        db.refresh(feedback)

        try:
            kb_agent = AgentFactory.create("knowledge_update_agent")
            kb_agent.update_after_execution(
                requirement_id=request.requirement_id,
                task_id=req_task.task_id or 0,
                execution_id=req_task.execution_id,
                feedback_id=feedback.id,
            )
            log.info(f"反馈提交后知识库自动更新 | feedback_id={feedback.id}")
        except Exception as e:
            log.warning(f"反馈提交后知识库更新失败（不影响反馈提交）: {e}")

        return Response(code=200, message="反馈提交成功", data={
            "id": feedback.id,
            "score": feedback.score,
            "accepted": feedback.accepted,
            "failure_analysis": failure_analysis,
        })
    finally:
        db.close()


@router.post("/{feedback_id}/regenerate", summary="基于反馈重新生成脚本")
async def regenerate_from_feedback(feedback_id: int, user: User = Depends(require_auth)):
    """基于用户反馈重新生成脚本"""
    db = SessionLocal()
    try:
        feedback = db.query(Feedback).filter(
            Feedback.id == feedback_id,
            Feedback.user_id == user.id,
        ).first()
        if not feedback:
            raise HTTPException(status_code=404, detail="反馈记录不存在")

        if feedback.regenerated:
            raise HTTPException(status_code=400, detail="该反馈已触发过重新生成")

        req_task = db.query(RequirementTask).filter(
            RequirementTask.id == feedback.requirement_id
        ).first()
        if not req_task:
            raise HTTPException(status_code=404, detail="关联的需求任务不存在")

        feedback.regenerated = True
        db.commit()

        feedback_context = ""
        if feedback.failure_analysis:
            try:
                analysis = __import__('json').loads(feedback.failure_analysis)
                feedback_context = analysis.get("feedback_context", "")
            except Exception:
                pass
        if not feedback_context and feedback.comment:
            feedback_context = f"用户反馈: {feedback.comment}\n请优先修复失败步骤，生成更稳定可靠的脚本。"

        req_task.status = RequirementStatus.PENDING
        req_task.error_message = None
        db.commit()

        return Response(code=200, message="已触发重新生成", data={
            "feedback_id": feedback_id,
            "requirement_id": feedback.requirement_id,
            "feedback_context": feedback_context,
        })
    finally:
        db.close()


@router.get("/requirement/{requirement_id}", summary="获取需求的反馈列表")
async def get_requirement_feedbacks(requirement_id: int, user: User = Depends(require_auth)):
    """获取指定需求的反馈列表（仅自己的）"""
    db = SessionLocal()
    try:
        # 验证需求归属
        req_task = db.query(RequirementTask).filter(
            RequirementTask.id == requirement_id,
            RequirementTask.user_id == user.id,
        ).first()
        if not req_task:
            raise HTTPException(status_code=404, detail="需求任务不存在")

        feedbacks = db.query(Feedback).filter(
            Feedback.requirement_id == requirement_id,
            Feedback.user_id == user.id,
        ).order_by(Feedback.created_at.desc()).all()

        data = []
        for f in feedbacks:
            item = {
                "id": f.id,
                "requirement_id": f.requirement_id,
                "task_id": f.task_id,
                "score": f.score,
                "comment": f.comment,
                "accepted": f.accepted,
                "regenerated": f.regenerated,
                "created_at": str(f.created_at) if f.created_at else None,
            }
            if f.failure_analysis:
                try:
                    item["failure_analysis"] = __import__('json').loads(f.failure_analysis)
                except Exception:
                    item["failure_analysis"] = None
            data.append(item)

        return Response(code=200, message="获取成功", data=data)
    finally:
        db.close()


@router.get("/stats", summary="获取脚本通过率统计")
async def get_feedback_stats(user: User = Depends(require_auth)):
    """获取当前用户的脚本通过率统计"""
    db = SessionLocal()
    try:
        from sqlalchemy import func

        total_feedbacks = db.query(func.count(Feedback.id)).filter(
            Feedback.user_id == user.id
        ).scalar() or 0
        accepted_count = db.query(func.count(Feedback.id)).filter(
            Feedback.accepted == True,
            Feedback.user_id == user.id,
        ).scalar() or 0
        rejected_count = db.query(func.count(Feedback.id)).filter(
            Feedback.accepted == False,
            Feedback.user_id == user.id,
        ).scalar() or 0
        avg_score = db.query(func.avg(Feedback.score)).filter(
            Feedback.user_id == user.id
        ).scalar() or 0

        total_executions = db.query(func.count(ExecutionRecord.id)).filter(
            ExecutionRecord.user_id == user.id
        ).scalar() or 0
        success_executions = db.query(func.count(ExecutionRecord.id)).filter(
            ExecutionRecord.status == "success",
            ExecutionRecord.user_id == user.id,
        ).scalar() or 0
        failed_executions = db.query(func.count(ExecutionRecord.id)).filter(
            ExecutionRecord.status == "failed",
            ExecutionRecord.user_id == user.id,
        ).scalar() or 0

        pass_rate = (success_executions / total_executions * 100) if total_executions > 0 else 0
        feedback_pass_rate = (accepted_count / total_feedbacks * 100) if total_feedbacks > 0 else 0

        score_dist = {}
        for s in range(1, 6):
            count = db.query(func.count(Feedback.id)).filter(
                Feedback.score == s,
                Feedback.user_id == user.id,
            ).scalar() or 0
            score_dist[str(s)] = count

        return Response(code=200, message="获取成功", data={
            "execution_stats": {
                "total": total_executions,
                "success": success_executions,
                "failed": failed_executions,
                "pass_rate": round(pass_rate, 1),
            },
            "feedback_stats": {
                "total": total_feedbacks,
                "accepted": accepted_count,
                "rejected": rejected_count,
                "avg_score": round(float(avg_score), 1),
                "pass_rate": round(feedback_pass_rate, 1),
                "score_distribution": score_dist,
            },
        })
    finally:
        db.close()
