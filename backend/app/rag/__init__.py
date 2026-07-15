"""
企业级 RAG 知识库系统

不是聊天机器人，而是 AI 自动测试平台的 RAG 组件。
职责：过滤真正相关的信息，不要把所有文档发送给 LLM。

管道流程：
  上传 → 解析 → Chunk → Embedding → MySQL → Milvus → Neo4j

支持知识来源：
  需求文档/设计文档/接口文档/Swagger/Postman/
  页面截图/OCR文本/数据库Schema/
  Markdown/Excel/Word/PDF/
  历史测试用例/历史脚本/历史Bug
"""
from app.rag.models import (
    DocumentType,
    DocumentStatus,
    LoadedDocument,
    ChunkStrategy,
    Chunk,
    EmbeddingResult,
    RetrievalResult,
    RAGQuery,
    RAGResponse,
)

__all__ = [
    "DocumentType",
    "DocumentStatus",
    "LoadedDocument",
    "ChunkStrategy",
    "Chunk",
    "EmbeddingResult",
    "RetrievalResult",
    "RAGQuery",
    "RAGResponse",
]
