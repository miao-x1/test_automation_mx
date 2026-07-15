"""
RAG 系统数据模型

定义 RAG 管道中各阶段传递的数据结构。
"""
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from enum import Enum


class DocumentType(str, Enum):
    """知识来源类型"""
    REQUIREMENT = "requirement"       # 需求文档
    DESIGN = "design"                  # 设计文档
    API_DOC = "api_doc"                # 接口文档
    SWAGGER = "swagger"                # Swagger/OpenAPI
    POSTMAN = "postman"                # Postman Collection
    SCREENSHOT = "screenshot"         # 页面截图
    OCR_TEXT = "ocr_text"             # OCR文本
    DB_SCHEMA = "db_schema"            # 数据库Schema
    MARKDOWN = "markdown"              # Markdown
    EXCEL = "excel"                    # Excel
    WORD = "word"                      # Word
    PDF = "pdf"                        # PDF
    TEST_CASE = "test_case"           # 历史测试用例
    SCRIPT = "script"                  # 历史脚本
    BUG = "bug"                        # 历史Bug
    TEXT = "text"                      # 纯文本
    UNKNOWN = "unknown"


class DocumentStatus(str, Enum):
    """文档处理状态"""
    PENDING = "pending"
    LOADING = "loading"
    LOADED = "loaded"
    CHUNKING = "chunking"
    CHUNKED = "chunked"
    EMBEDDING = "embedding"
    EMBEDDED = "embedded"
    STORING = "storing"
    STORED = "stored"
    FAILED = "failed"


class LoadedDocument(BaseModel):
    """解析后的文档"""
    source_id: str = ""
    source_type: DocumentType = DocumentType.UNKNOWN
    file_path: str = ""
    file_name: str = ""
    file_size: int = 0
    mime_type: str = ""
    content: str = ""                          # 纯文本内容
    metadata: Dict[str, Any] = Field(default_factory=dict)  # 额外元数据
    sections: List[Dict[str, Any]] = Field(default_factory=list)  # 文档分节
    tables: List[Dict[str, Any]] = Field(default_factory=list)   # 表格数据
    images: List[Dict[str, Any]] = Field(default_factory=list)   # 图片信息


class ChunkStrategy(str, Enum):
    """分块策略"""
    FIXED_SIZE = "fixed_size"          # 固定大小
    SENTENCE = "sentence"              # 按句子
    PARAGRAPH = "paragraph"            # 按段落
    RECURSIVE = "recursive"            # 递归分割
    SEMANTIC = "semantic"              # 语义分块
    MARKDOWN_HEADER = "markdown_header"  # Markdown标题分块


class Chunk(BaseModel):
    """文档分块"""
    chunk_id: str = ""
    source_id: str = ""
    text: str = ""
    chunk_type: str = "content"        # content/title/table/code/api/entity
    chunk_index: int = 0
    start_char: int = 0
    end_char: int = 0
    token_count: int = 0
    embedding: List[float] = Field(default_factory=list)  # 向量
    metadata: Dict[str, Any] = Field(default_factory=dict)
    score: float = 0.0                 # 检索时填充


class EmbeddingResult(BaseModel):
    """Embedding 结果"""
    chunk_id: str = ""
    embedding: List[float] = Field(default_factory=list)
    model_name: str = ""
    token_count: int = 0
    duration: float = 0.0


class RetrievalResult(BaseModel):
    """检索结果"""
    chunk_id: str = ""
    source_id: str = ""
    text: str = ""
    score: float = 0.0
    rank: int = 0
    chunk_type: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)
    source_type: str = ""
    source_name: str = ""


class RAGQuery(BaseModel):
    """RAG 查询"""
    query: str = ""
    top_k: int = 10
    score_threshold: float = 0.6
    filters: Dict[str, Any] = Field(default_factory=dict)
    source_types: List[str] = Field(default_factory=list)
    rerank: bool = True
    rerank_top_k: int = 5
    expand_query: bool = True          # 是否扩展查询


class RAGResponse(BaseModel):
    """RAG 响应"""
    query: str = ""
    results: List[RetrievalResult] = Field(default_factory=list)
    total_found: int = 0
    returned: int = 0
    latency_ms: int = 0
    expanded_query: str = ""
    reranked: bool = False
    context: str = ""                   # 拼接的上下文文本（发送给LLM的）
    token_count: int = 0               # 上下文token数
