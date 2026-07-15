"""
ContextRouter - RAG 统一上下文路由层

职责：
  统一决定 Agent 应该查询哪个数据源。
  禁止 Agent 直接调用 Milvus / R2R / Neo4j。

路由规则：
  PAGE_ELEMENT       → MySQL + Milvus + Neo4j
  DOCUMENT           → R2R
  TEST_CASE          → Milvus
  BUSINESS_FLOW      → Neo4j + MySQL
  SCRIPT             → Milvus + MySQL
  EXECUTION_HISTORY  → MySQL

使用方式：
  router = get_context_router()
  result = router.retrieve_sync(
      query="用户登录页面元素",
      context_type=ContextType.PAGE_ELEMENT,
      top_k=10,
  )
"""
from app.services.context_router.context_type import ContextType
from app.services.context_router.router import ContextRouter, get_context_router
from app.services.context_router.storage_router import StorageRouter, get_storage_router
from app.services.context_router.access_checker import RAGAccessChecker

__all__ = [
    "ContextType",
    "ContextRouter",
    "get_context_router",
    "StorageRouter",
    "get_storage_router",
    "RAGAccessChecker",
]
