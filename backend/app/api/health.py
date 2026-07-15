"""
健康检查接口
"""
from fastapi import APIRouter
from app.schemas.response import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse, summary="健康检查")
async def health_check():
    """服务健康检查接口"""
    return HealthResponse(status="success")
