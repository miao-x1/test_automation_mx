"""
ContextRouter API - 上下文路由查询接口

提供统一的数据源查询入口，前端和外部服务可通过此 API
查询任意类型的上下文，由 ContextRouter 自动路由到正确数据源。

接口：
  POST /context/retrieve   — 统一上下文检索
  GET  /context/health     — 数据源健康检查
  GET  /context/types      — 支持的上下文类型
"""
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel as PydanticModel
from app.core.logger import log
from app.core.auth import require_auth
from app.models.user import User

router = APIRouter()


class RetrieveRequest(PydanticModel):
    """上下文检索请求"""
    query: str
    context_type: str = "test_case"
    top_k: int = 10
    filters: Optional[Dict[str, Any]] = None
    project_id: str = ""


@router.post("/retrieve")
def retrieve_context(
    request: RetrieveRequest,
    user: User = Depends(require_auth),
):
    """
    统一上下文检索

    根据 context_type 自动路由到对应数据源：
      page_element       → MySQL + Milvus + Neo4j
      document           → R2R
      test_case          → Milvus
      business_flow      → Neo4j + MySQL
      script             → Milvus + MySQL
      execution_history  → MySQL
    """
    from app.services.context_router import get_context_router, ContextType

    try:
        router_instance = get_context_router()
        result = router_instance.retrieve_sync(
            query=request.query,
            context_type=request.context_type,
            top_k=request.top_k,
            filters=request.filters,
            project_id=request.project_id,
        )
        return result
    except ValueError as e:
        log.warning(f"ContextRouter API | 无效的context_type: {request.context_type}")
        return {
            "error": str(e),
            "valid_types": [t.value for t in ContextType],
        }
    except Exception as e:
        log.error(f"ContextRouter API | 检索失败: {e}", exc_info=True)
        return {"error": str(e), "results": [], "total": 0}


@router.get("/health")
def context_health(user: User = Depends(require_auth)):
    """数据源健康检查"""
    from app.services.context_router import get_context_router

    router_instance = get_context_router()
    return router_instance.health_check()


@router.get("/types")
def context_types(user: User = Depends(require_auth)):
    """支持的上下文类型"""
    from app.services.context_router import ContextType, ROUTING_TABLE

    return {
        "types": [
            {
                "name": ct.value,
                "sources": ROUTING_TABLE.get(ct, []),
                "description": ct.__doc__.strip().split("\n")[0] if ct.__doc__ else "",
            }
            for ct in ContextType
        ]
    }
