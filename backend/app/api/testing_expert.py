from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.auth import require_auth
from app.knowledge.testing_expert import get_testing_expert
from app.models.user import User
from app.schemas.response import Response

router = APIRouter()


class ExpertQuery(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=6, ge=1, le=12)


@router.get("/stats", summary="测试专家知识统计")
def expert_stats(user: User = Depends(require_auth)):
    return Response(data=get_testing_expert().stats())


@router.post("/query", summary="检索测试专家知识")
def expert_query(payload: ExpertQuery, user: User = Depends(require_auth)):
    return Response(data=get_testing_expert().retrieve(payload.query, top_k=payload.top_k))


@router.post("/answer", summary="用测试专家知识回答问题")
def expert_answer(payload: ExpertQuery, user: User = Depends(require_auth)):
    return Response(data=get_testing_expert().answer(payload.query))


@router.post("/analyze", summary="把一句话测试任务分析成风险导向测试点")
def expert_analyze(payload: ExpertQuery, user: User = Depends(require_auth)):
    return Response(data=get_testing_expert().analyze_task(payload.query))
