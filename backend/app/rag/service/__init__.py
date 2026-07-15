"""RAG 服务模块

管道编排层，将 document_loader / chunker / embedding /
vector_store / mysql_store / graph_store / retriever /
reranker / query 全部串联。

核心流程：
  入库：解析 → Chunk → Embedding → MySQL → Milvus → Neo4j
  查询：查询处理 → 向量检索 → 重排序 → 上下文构建

三库协同：
  MySQL:   文档/需求/页面/接口/脚本/用例/Chunk/Meta/Tag/Session
  Milvus:  Embedding 向量（Chunk/Page/Case/Requirement Vector）
  Neo4j:   关系（页面→元素→接口→表→流程→用例→脚本）

主要组件：
  - RAGPipeline: RAG 管道编排器
  - TriStoreCoordinator: 三库协同管理器
  - get_rag_service: RAG 管道单例
  - get_tri_store_coordinator: 三库协同单例
"""
from app.rag.service.pipeline import RAGPipeline
from app.rag.service.factory import get_rag_service, reset_rag_service
from app.rag.service.tri_store_coordinator import (
    TriStoreCoordinator,
    get_tri_store_coordinator,
)

__all__ = [
    "RAGPipeline",
    "get_rag_service",
    "reset_rag_service",
    "TriStoreCoordinator",
    "get_tri_store_coordinator",
]
