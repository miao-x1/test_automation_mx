"""
GraphStorageAgent - 图谱存储 Agent

职责（消息驱动）：
  - graph_create:  创建 Neo4j 节点
  - graph_link:    创建 Neo4j 关系
  - graph_query:   查询 Neo4j 图谱
  - graph_delete:  删除 Neo4j 节点
  - graph_trace:   追溯链路

禁止 Service 直接操作 Neo4j，改为通过消息发送给 GraphStorageAgent。

通信方式：
  # 创建节点
  response = await self.send_request(
      "graph_storage_agent", "create",
      {
          "label": "Page",
          "entity_id": "page_001",
          "properties": {"url": "/login", "title": "登录页"}
      }
  )

  # 创建关系
  response = await self.send_request(
      "graph_storage_agent", "link",
      {
          "from_label": "Page",
          "from_id": "page_001",
          "rel_type": "HAS_ELEMENT",
          "to_label": "Element",
          "to_id": "elem_001"
      }
  )

  # 追溯链路
  response = await self.send_request(
      "graph_storage_agent", "trace",
      {"label": "TestCase", "entity_id": "case_001"}
  )
"""
import logging
import time
from typing import Any, Dict

from autogen_core import message_handler, MessageContext, DefaultTopicId, default_subscription

from app.runtime.base_agent import BaseRoutedAgent
from app.runtime.messages import AgentRequest, AgentResponse

logger = logging.getLogger(__name__)


@default_subscription
class GraphStorageAgent(BaseRoutedAgent):
    """图谱存储 Agent

    所有 Neo4j 图谱操作统一通过此 Agent 执行。
    Neo4j 不可用时优雅降级。
    """

    def __init__(self) -> None:
        super().__init__(
            description="图谱存储Agent，统一处理Neo4j节点/关系/查询/删除/追溯",
            display_name="GraphStorageAgent",
            capabilities=["graph_create", "graph_link", "graph_query", "graph_delete", "graph_trace"],
        )
        self._graph_store = None
        self._storage = None

    @property
    def storage(self):
        """懒加载 StorageRouter（统一写入路由）"""
        if self._storage is None:
            from app.services.context_router.storage_router import get_storage_router
            self._storage = get_storage_router()
        return self._storage

    @property
    def graph_store(self):
        """懒加载图谱存储（通过 StorageRouter 统一路由）"""
        if self._graph_store is None:
            self._graph_store = self.storage.get_extended_graph_store()
        return self._graph_store

    async def execute(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """GraphFlow 入口"""
        operation = payload.get("operation", payload.get("action", "create"))
        if operation == "create":
            return await self._do_create(payload)
        elif operation == "link":
            return await self._do_link(payload)
        elif operation == "query":
            return await self._do_query(payload)
        elif operation == "delete":
            return await self._do_delete(payload)
        elif operation == "trace":
            return await self._do_trace(payload)
        else:
            return {"status": "error", "message": f"Unknown operation: {operation}"}

    @message_handler
    async def handle_request(self, message: AgentRequest, ctx: MessageContext) -> AgentResponse:
        """处理来自其他 Agent 的图谱操作请求"""
        start = time.time()
        action = message.target_action or "create"
        logger.info(f"[GraphStorageAgent] 收到请求 action={action}")

        try:
            if action == "create":
                result = await self._do_create(message.payload)
            elif action == "link":
                result = await self._do_link(message.payload)
            elif action == "query":
                result = await self._do_query(message.payload)
            elif action == "delete":
                result = await self._do_delete(message.payload)
            elif action == "trace":
                result = await self._do_trace(message.payload)
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
            logger.error(f"[GraphStorageAgent] 处理失败: {e}", exc_info=True)
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

    async def _do_create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """创建 Neo4j 节点"""
        if not self.storage.neo4j_available():
            return {"status": "unavailable", "message": "Neo4j不可用"}

        label = payload.get("label", "")
        entity_id = str(payload.get("entity_id", ""))
        properties = payload.get("properties", {})
        id_field = payload.get("id_field", "source_id")

        if not label or not entity_id:
            return {"status": "error", "message": "label 和 entity_id 不能为空"}

        try:
            await self.graph_store.create_node(
                label=label,
                node_id=entity_id,
                id_field=id_field,
                properties=properties,
            )
            return {
                "status": "success",
                "label": label,
                "entity_id": entity_id,
                "message": f"节点 {label}:{entity_id} 创建成功",
            }
        except Exception as e:
            logger.error(f"[GraphStorageAgent] 创建节点失败: {e}")
            return {"status": "error", "message": str(e)}

    async def _do_link(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """创建 Neo4j 关系"""
        if not self.storage.neo4j_available():
            return {"status": "unavailable", "message": "Neo4j不可用"}

        from_label = payload.get("from_label", "")
        from_id = str(payload.get("from_id", ""))
        rel_type = payload.get("rel_type", "")
        to_label = payload.get("to_label", "")
        to_id = str(payload.get("to_id", ""))
        properties = payload.get("properties", {})
        from_id_field = payload.get("from_id_field", "source_id")
        to_id_field = payload.get("to_id_field", "source_id")

        if not from_label or not from_id or not rel_type or not to_label or not to_id:
            return {"status": "error", "message": "from_label, from_id, rel_type, to_label, to_id 不能为空"}

        try:
            await self.graph_store.create_edge(
                from_label=from_label,
                from_id=from_id,
                rel_type=rel_type,
                to_label=to_label,
                to_id=to_id,
                from_id_field=from_id_field,
                to_id_field=to_id_field,
                properties=properties,
            )
            return {
                "status": "success",
                "from": f"{from_label}:{from_id}",
                "rel_type": rel_type,
                "to": f"{to_label}:{to_id}",
                "message": f"关系 {rel_type} 创建成功",
            }
        except Exception as e:
            logger.error(f"[GraphStorageAgent] 创建关系失败: {e}")
            return {"status": "error", "message": str(e)}

    async def _do_query(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """查询 Neo4j 图谱"""
        if not self.storage.neo4j_available():
            return {"status": "unavailable", "message": "Neo4j不可用"}

        query_text = payload.get("query", "")
        label = payload.get("label", "")
        entity_id = str(payload.get("entity_id", ""))
        depth = payload.get("depth", 2)

        try:
            if label and entity_id:
                # 查询实体关系
                relations = await self.graph_store.get_entity_relations(
                    label, entity_id, depth=depth
                )
                return {
                    "status": "success",
                    "label": label,
                    "entity_id": entity_id,
                    "relations": relations,
                }
            elif query_text:
                # 全文搜索
                results = await self.graph_store.search_entities(query_text)
                return {
                    "status": "success",
                    "query": query_text,
                    "results": results,
                    "total": len(results),
                }
            else:
                # 返回全量统计
                stats = await self.graph_store.get_full_stats()
                return {
                    "status": "success",
                    "stats": stats,
                }
        except Exception as e:
            logger.error(f"[GraphStorageAgent] 查询失败: {e}")
            return {"status": "error", "message": str(e)}

    async def _do_delete(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """删除 Neo4j 节点"""
        if not self.storage.neo4j_available():
            return {"status": "unavailable", "message": "Neo4j不可用"}

        label = payload.get("label", "")
        entity_id = str(payload.get("entity_id", ""))
        id_field = payload.get("id_field", "source_id")

        if not label or not entity_id:
            return {"status": "error", "message": "label 和 entity_id 不能为空"}

        try:
            await self.graph_store.delete_entity(label, entity_id, id_field=id_field)
            return {
                "status": "success",
                "label": label,
                "entity_id": entity_id,
                "message": f"节点 {label}:{entity_id} 已删除",
            }
        except Exception as e:
            logger.error(f"[GraphStorageAgent] 删除节点失败: {e}")
            return {"status": "error", "message": str(e)}

    async def _do_trace(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """追溯链路"""
        if not self.storage.neo4j_available():
            return {"status": "unavailable", "message": "Neo4j不可用"}

        label = payload.get("label", "")
        entity_id = str(payload.get("entity_id", ""))
        id_field = payload.get("id_field", "source_id")

        if not label or not entity_id:
            return {"status": "error", "message": "label 和 entity_id 不能为空"}

        try:
            traces = await self.graph_store.get_traceability(label, entity_id, id_field=id_field)
            return {
                "status": "success",
                "label": label,
                "entity_id": entity_id,
                "traces": traces,
            }
        except Exception as e:
            logger.error(f"[GraphStorageAgent] 追溯失败: {e}")
            return {"status": "error", "message": str(e)}
