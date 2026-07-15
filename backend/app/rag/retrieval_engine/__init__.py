"""
统一检索模块

提供标准化的三库检索接口：
    - MysqlRetriever: MySQL业务数据检索
    - MilvusRetriever: Milvus向量语义检索
    - Neo4jRetriever: Neo4j图关系检索
    - RetrievalManager: 统一检索管理器（根据计划调度三库）

调用方式：
    from app.rag.retrieval_engine import get_retrieval_manager
    manager = get_retrieval_manager()
    results = manager.retrieve(plan)
"""
from app.rag.retrieval_engine.base import BaseRetriever, RetrievalResult
from app.rag.retrieval_engine.mysql_retriever import MysqlRetriever
from app.rag.retrieval_engine.milvus_retriever import MilvusRetriever
from app.rag.retrieval_engine.neo4j_retriever import Neo4jRetriever
from app.rag.retrieval_engine.manager import RetrievalManager, get_retrieval_manager

__all__ = [
    "BaseRetriever",
    "RetrievalResult",
    "MysqlRetriever",
    "MilvusRetriever",
    "Neo4jRetriever",
    "RetrievalManager",
    "get_retrieval_manager",
]
