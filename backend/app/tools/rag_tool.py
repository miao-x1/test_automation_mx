"""RAG 工具 - 向量检索和索引"""
import logging
from typing import Any, Dict, List
from app.tools.base import BaseTool, ToolResult, ToolContext

logger = logging.getLogger(__name__)


class RAGSearchTool(BaseTool):
    """RAG 语义检索工具

    通过向量搜索从知识库中检索相关内容。
    底层调用 MultiVectorStore + Embedding。
    """

    def __init__(self):
        super().__init__(name="rag_search", description="RAG语义检索，从Milvus向量库搜索")
        self._vector_store = None
        self._embedding_model = None

    def _do_initialize(self):
        from app.rag.vector_store.multi_vector_store import get_multi_vector_store
        from app.rag.embedding.factory import get_embedding_factory
        self._vector_store = get_multi_vector_store()
        self._embedding_model = get_embedding_factory().get_embedding()

    def can_handle(self) -> bool:
        return self._embedding_model is not None

    async def execute(self, ctx: ToolContext, **kwargs) -> ToolResult:
        query = kwargs.get("query", "")
        entity_types = kwargs.get("entity_types", ["chunk"])
        top_k = kwargs.get("top_k", 10)

        if not query:
            return ToolResult(success=False, error="query不能为空")

        try:
            query_vector = await self._embedding_model.embed(query)
            results = await self._vector_store.search(
                query_vector=query_vector,
                entity_types=entity_types,
                top_k=top_k,
            )
            formatted = [
                {
                    "source_id": r.source_id,
                    "entity_type": r.entity_type,
                    "text": r.text[:500],
                    "score": round(r.score, 4),
                }
                for r in results
            ]
            return ToolResult(success=True, data={"results": formatted, "total": len(formatted)})
        except Exception as e:
            logger.error(f"[RAGSearchTool] 搜索失败: {e}")
            return ToolResult(success=False, error=str(e), data={"results": [], "total": 0})


class RAGIndexTool(BaseTool):
    """RAG 索引工具

    将文档内容索引到 Milvus 向量库。
    """

    def __init__(self):
        super().__init__(name="rag_index", description="RAG索引，将文本向量化并存入Milvus")

    async def execute(self, ctx: ToolContext, **kwargs) -> ToolResult:
        text = kwargs.get("text", "")
        source_id = kwargs.get("source_id", "")
        entity_type = kwargs.get("entity_type", "chunk")

        if not text or not source_id:
            return ToolResult(success=False, error="text和source_id不能为空")

        try:
            from app.rag.embedding.factory import get_embedding_factory
            from app.rag.vector_store.multi_vector_store import get_multi_vector_store

            embedding_model = get_embedding_factory().get_embedding()
            vector = await embedding_model.embed(text)

            store = get_multi_vector_store()
            milvus_id = await store.insert_vector(
                entity_type=entity_type,
                source_id=str(source_id),
                text=text[:8192],
                embedding=vector,
            )
            return ToolResult(
                success=milvus_id > 0,
                data={"milvus_id": milvus_id, "entity_type": entity_type},
            )
        except Exception as e:
            logger.error(f"[RAGIndexTool] 索引失败: {e}")
            return ToolResult(success=False, error=str(e))
