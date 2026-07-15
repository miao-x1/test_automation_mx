"""向量库存储模块

对接 Milvus，负责 Chunk 向量的写入、查询与删除。
作为 RAG 检索的向量召回后端。

集合 rag_knowledge_vector 与现有的 ui_element_vector / test_case_vector /
script_vector 隔离，专用于 RAG 知识库。

MultiVectorStore 统一管理5种向量集合：
  - chunk:        知识文档分片向量
  - requirement:  需求向量
  - page:         页面向量
  - case:         测试用例向量
  - script:       脚本向量
"""
from app.rag.vector_store.base import BaseVectorStore
from app.rag.vector_store.milvus_store import MilvusVectorStore, RAG_COLLECTION_NAME
from app.rag.vector_store.factory import get_vector_store, reset_vector_store
from app.rag.vector_store.multi_vector_store import (
    MultiVectorStore,
    get_multi_vector_store,
)

__all__ = [
    "BaseVectorStore",
    "MilvusVectorStore",
    "RAG_COLLECTION_NAME",
    "get_vector_store",
    "reset_vector_store",
    "MultiVectorStore",
    "get_multi_vector_store",
]
