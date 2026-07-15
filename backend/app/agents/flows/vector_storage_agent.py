"""
VectorStorageAgent - 向量存储 Agent

职责（消息驱动）：
  - vector_insert:  插入向量到 Milvus
  - vector_search:  语义搜索 Milvus
  - vector_delete:  删除 Milvus 向量

禁止 Service 直接操作 Milvus，改为通过消息发送给 VectorStorageAgent。
向量存储 / Embedding 实例通过 StorageRouter 统一路由获取，禁止直接导入数据层客户端。

通信方式：
  # 插入向量
  response = await self.send_request(
      "vector_storage_agent", "insert",
      {
          "entity_type": "chunk",
          "source_id": "123",
          "text": "文档内容...",
          "metadata": {"source_type": "pdf"}
      }
  )

  # 语义搜索
  response = await self.send_request(
      "vector_storage_agent", "search",
      {
          "query": "用户登录功能",
          "entity_types": ["chunk", "requirement"],
          "top_k": 10
      }
  )
"""
import logging
import time
from typing import Any, Dict, List

from autogen_core import message_handler, MessageContext, DefaultTopicId, default_subscription

from app.runtime.base_agent import BaseRoutedAgent
from app.runtime.messages import AgentRequest, AgentResponse

logger = logging.getLogger(__name__)


@default_subscription
class VectorStorageAgent(BaseRoutedAgent):
    """向量存储 Agent

    所有 Milvus 向量操作统一通过此 Agent 执行。
    Milvus 不可用时优雅降级。
    """

    def __init__(self) -> None:
        super().__init__(
            description="向量存储Agent，统一处理Milvus向量插入/搜索/删除",
            display_name="VectorStorageAgent",
            capabilities=["vector_insert", "vector_search", "vector_delete"],
        )
        self._vector_store = None
        self._embedding_factory = None

    @property
    def vector_store(self):
        """懒加载向量存储"""
        if self._vector_store is None:
            from app.services.context_router.storage_router import get_storage_router
            storage = get_storage_router()
            self._vector_store = storage.get_multi_vector_store()
        return self._vector_store

    @property
    def embedding_model(self):
        """懒加载 Embedding 模型"""
        if self._embedding_factory is None:
            from app.services.context_router.storage_router import get_storage_router
            storage = get_storage_router()
            self._embedding_factory = storage.get_embedding()
        return self._embedding_factory

    async def execute(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """GraphFlow 入口"""
        operation = payload.get("operation", payload.get("action", "insert"))
        if operation == "insert":
            return await self._do_insert(payload)
        elif operation == "search":
            return await self._do_search(payload)
        elif operation == "delete":
            return await self._do_delete(payload)
        else:
            return {"status": "error", "message": f"Unknown operation: {operation}"}

    @message_handler
    async def handle_request(self, message: AgentRequest, ctx: MessageContext) -> AgentResponse:
        """处理来自其他 Agent 的向量操作请求"""
        start = time.time()
        action = message.target_action or "insert"
        logger.info(f"[VectorStorageAgent] 收到请求 action={action}")

        try:
            if action == "insert":
                result = await self._do_insert(message.payload)
            elif action == "search":
                result = await self._do_search(message.payload)
            elif action == "delete":
                result = await self._do_delete(message.payload)
            else:
                result = {"status": "error", "message": f"Unknown action: {action}"}

            duration = time.time() - start
            return AgentResponse(
                request_id=message.request_id,
                sender_type=self._agent_type,
                status="success" if result.get("status") != "error" else "error",
                data=result,
                duration=duration,
            )
        except Exception as e:
            duration = time.time() - start
            logger.error(f"[VectorStorageAgent] 处理失败: {e}", exc_info=True)
            return AgentResponse(
                request_id=message.request_id,
                sender_type=self._agent_type,
                status="error",
                error=str(e),
                duration=duration,
            )

    # ------------------------------------------------------------------
    # 操作实现
    # ------------------------------------------------------------------

    async def _do_insert(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """插入向量到 Milvus"""
        entity_type = payload.get("entity_type", "chunk")
        source_id = str(payload.get("source_id", ""))
        text = payload.get("text", "")
        metadata = payload.get("metadata", {})
        embedding = payload.get("embedding")  # 可选：直接传入向量

        if not source_id or not text:
            return {"status": "error", "message": "source_id 和 text 不能为空"}

        # 如果没有传入向量，自动生成
        if embedding is None:
            try:
                embedding = await self.embedding_model.embed(text)
            except Exception as e:
                return {"status": "error", "message": f"Embedding失败: {e}"}

        # 插入 Milvus
        try:
            milvus_id = await self.vector_store.insert_vector(
                entity_type=entity_type,
                source_id=source_id,
                text=text[:8192],
                embedding=embedding,
                metadata=metadata,
            )

            if milvus_id > 0:
                return {
                    "status": "success",
                    "entity_type": entity_type,
                    "source_id": source_id,
                    "milvus_id": milvus_id,
                    "message": "向量插入成功",
                }
            else:
                return {
                    "status": "error",
                    "message": "向量插入失败（Milvus可能不可用）",
                }
        except Exception as e:
            logger.error(f"[VectorStorageAgent] 插入失败: {e}")
            return {"status": "error", "message": str(e)}

    async def _do_search(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """语义搜索 Milvus"""
        query = payload.get("query", "")
        entity_types = payload.get("entity_types", ["chunk"])
        top_k = payload.get("top_k", 10)
        score_threshold = payload.get("score_threshold", 0.0)

        if not query:
            return {"status": "error", "message": "query 不能为空"}

        # 生成查询向量
        try:
            query_vector = await self.embedding_model.embed(query)
        except Exception as e:
            return {"status": "error", "message": f"Embedding失败: {e}"}

        # 搜索
        try:
            results = await self.vector_store.search(
                query_vector=query_vector,
                entity_types=entity_types,
                top_k=top_k,
            )

            # 格式化结果
            formatted = []
            for r in results:
                if r.score >= score_threshold:
                    formatted.append({
                        "source_id": r.source_id,
                        "entity_type": r.entity_type,
                        "text": r.text[:500],
                        "score": round(r.score, 4),
                        "metadata": r.metadata,
                    })

            return {
                "status": "success",
                "query": query,
                "results": formatted,
                "total": len(formatted),
            }
        except Exception as e:
            logger.error(f"[VectorStorageAgent] 搜索失败: {e}")
            return {"status": "error", "message": str(e)}

    async def _do_delete(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """删除 Milvus 向量"""
        entity_type = payload.get("entity_type", "chunk")
        source_id = str(payload.get("source_id", ""))

        if not source_id:
            return {"status": "error", "message": "source_id 不能为空"}

        try:
            deleted = await self.vector_store.delete_by_source(entity_type, source_id)
            return {
                "status": "success",
                "entity_type": entity_type,
                "source_id": source_id,
                "deleted": deleted,
                "message": f"删除 {deleted} 条向量",
            }
        except Exception as e:
            logger.error(f"[VectorStorageAgent] 删除失败: {e}")
            return {"status": "error", "message": str(e)}
