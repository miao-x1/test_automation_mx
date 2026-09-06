"""
健康检查接口

/health、/api/health — 进程存活（liveness），不探外部依赖。
/ready、/api/ready   — 就绪（readiness）：Database / Milvus / AI 配置。
不调用昂贵的 LLM。
"""
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.schemas.response import HealthResponse

router = APIRouter()


def check_database() -> dict[str, Any]:
    """探测数据库连通性：SELECT 1。"""
    try:
        from app.db.database import sync_engine

        with sync_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "PASS"}
    except Exception as exc:
        return {"status": "FAIL", "error": str(exc)}


def check_milvus() -> dict[str, Any]:
    """探测 Milvus 是否可连接，不执行检索/写入。"""
    try:
        from app.db.milvus_client import get_milvus_client

        client = get_milvus_client(allow_fail=True)
        if client is None:
            return {"status": "FAIL", "error": "Milvus unreachable"}
        client.list_collections()
        return {"status": "PASS"}
    except Exception as exc:
        return {"status": "FAIL", "error": str(exc)}


def check_ai() -> dict[str, Any]:
    """只检查 Key 是否已配置，不调用 LLM。"""
    if settings.ai_configured:
        return {"status": "CONFIGURED"}
    return {"status": "NOT_CONFIGURED"}


def build_readiness() -> dict[str, Any]:
    database = check_database()
    milvus = check_milvus()
    ai = check_ai()
    ready = database.get("status") == "PASS" and milvus.get("status") == "PASS"
    return {
        "ready": ready,
        "app_ready": ready,
        "ai_ready": ai.get("status") == "CONFIGURED",
        "checks": {
            "database": database,
            "milvus": milvus,
            "ai": ai,
        },
    }


@router.get("/health", response_model=HealthResponse, summary="存活探活")
@router.get("/api/health", response_model=HealthResponse, summary="存活探活（探针别名）", include_in_schema=False)
async def health_check():
    """进程存活。不检查数据库 / Milvus / AI。"""
    return HealthResponse(status="success")


@router.get("/ready", summary="就绪探活")
@router.get("/api/ready", summary="就绪探活（探针别名）", include_in_schema=False)
async def readiness_check():
    """核心依赖是否具备提供服务的条件。"""
    payload = build_readiness()
    status_code = 200 if payload["ready"] else 503
    return JSONResponse(status_code=status_code, content=payload)
