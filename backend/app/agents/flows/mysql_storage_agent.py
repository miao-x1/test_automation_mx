"""
MysqlStorageAgent - MySQL 存储 Agent

职责（消息驱动）：
  - mysql_save:    保存数据到 MySQL（指定表名）
  - mysql_query:   查询 MySQL
  - mysql_delete:  删除 MySQL 记录
  - mysql_update:  更新 MySQL 记录

禁止 Service 直接写数据库，改为通过消息发送给 MysqlStorageAgent。

通信方式：
  # 其他 Agent 发送存储消息
  response = await self.send_request(
      "mysql_storage_agent", "save",
      {"table": "task", "data": {"title": "测试任务", "status": "pending"}}
  )

  # 查询
  response = await self.send_request(
      "mysql_storage_agent", "query",
      {"table": "task", "filters": {"status": "pending"}, "limit": 10}
  )
"""
import json
import logging
import time
import traceback
from typing import Any, Dict, Optional

from autogen_core import message_handler, MessageContext, DefaultTopicId, default_subscription

from app.runtime.base_agent import BaseRoutedAgent
from app.runtime.messages import AgentRequest, AgentResponse

logger = logging.getLogger(__name__)


@default_subscription
class MysqlStorageAgent(BaseRoutedAgent):
    """MySQL 存储 Agent

    所有 MySQL 写入/查询/删除操作统一通过此 Agent 执行。
    """

    # 支持的表名 → ORM 模型映射
    TABLE_MAP = {
        "task": "app.models.task.Task",
        "session": "app.models.session.Session",
        "flow_result": "app.models.flow_result.FlowResult",
        "agent_event": "app.models.agent_event.AgentEvent",
        "agent_log": "app.models.agent_log.AgentLog",
        "session_artifact": "app.models.session_artifact.SessionArtifact",
        "feedback": "app.models.feedback.Feedback",
        "case_content": "app.models.case_content.CaseContent",
        "case_task": "app.models.case_task.CaseTask",
        "script": "app.models.script.Script",
        "knowledge_source": "app.models.knowledge_source.KnowledgeSource",
        "knowledge_chunk": "app.models.knowledge_chunk.KnowledgeChunk",
    }

    def __init__(self) -> None:
        super().__init__(
            description="MySQL存储Agent，统一处理所有数据库写入/查询/删除操作",
            display_name="MysqlStorageAgent",
            capabilities=["mysql_save", "mysql_query", "mysql_delete", "mysql_update"],
        )

    async def execute(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """GraphFlow 入口"""
        operation = payload.get("operation", payload.get("action", "save"))
        if operation == "save":
            return self._do_save(payload)
        elif operation == "query":
            return self._do_query(payload)
        elif operation == "delete":
            return self._do_delete(payload)
        elif operation == "update":
            return self._do_update(payload)
        else:
            return {"status": "error", "message": f"Unknown operation: {operation}"}

    @message_handler
    async def handle_request(self, message: AgentRequest, ctx: MessageContext) -> AgentResponse:
        """处理来自其他 Agent 的存储请求"""
        start = time.time()
        action = message.target_action or "save"
        logger.info(f"[MysqlStorageAgent] 收到请求 action={action}")

        try:
            if action == "save":
                result = self._do_save(message.payload)
            elif action == "query":
                result = self._do_query(message.payload)
            elif action == "delete":
                result = self._do_delete(message.payload)
            elif action == "update":
                result = self._do_update(message.payload)
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
            logger.error(f"[MysqlStorageAgent] 处理失败: {e}", exc_info=True)
            return AgentResponse(
                request_id=message.request_id,
                sender_type=self._agent_type,
                status="error",
                error=str(e),
                duration=duration,
            )

    # ------------------------------------------------------------------
    # 操作实现（通过 StorageRouter 统一访问 MySQL）
    # ------------------------------------------------------------------

    def _get_model_class_name(self, table: str) -> Optional[str]:
        """根据表名获取模型类名

        Args:
            table: 表名（如 "task", "flow_result"）

        Returns:
            模型类名（如 "Task", "FlowResult"），不支持时返回 None
        """
        path = self.TABLE_MAP.get(table)
        if not path:
            return None
        # 从 "app.models.task.Task" 提取 "Task"
        return path.rsplit(".", 1)[-1]

    def _do_save(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """保存数据到 MySQL"""
        from app.services.context_router.storage_router import get_storage_router

        table = payload.get("table", "")
        data = payload.get("data", {})

        if not table or not data:
            return {"status": "error", "message": "table 和 data 不能为空"}

        model_class_name = self._get_model_class_name(table)
        if model_class_name is None:
            return {"status": "error", "message": f"不支持的表: {table}"}

        storage = get_storage_router()
        try:
            record_id = storage.mysql_save(model_class_name, data)
            if record_id:
                return {
                    "status": "success",
                    "table": table,
                    "id": record_id,
                    "message": f"保存成功: {table}#{record_id}",
                }
            else:
                return {"status": "error", "message": f"保存失败: {table}"}
        except Exception as e:
            logger.error(f"[MysqlStorageAgent] 保存失败: {e}")
            return {"status": "error", "message": str(e)}

    def _do_query(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """查询 MySQL"""
        from app.services.context_router.storage_router import get_storage_router

        table = payload.get("table", "")
        filters = payload.get("filters", {})
        limit = payload.get("limit", 50)
        offset = payload.get("offset", 0)
        order_by = payload.get("order_by", "id")
        order_desc = payload.get("order_desc", False)

        if not table:
            return {"status": "error", "message": "table 不能为空"}

        model_class_name = self._get_model_class_name(table)
        if model_class_name is None:
            return {"status": "error", "message": f"不支持的表: {table}"}

        storage = get_storage_router()
        try:
            results = storage.mysql_query(
                model_class_name,
                filters=filters if filters else None,
                limit=limit,
                offset=offset,
                order_by=order_by,
                order_desc=order_desc,
            )

            return {
                "status": "success",
                "table": table,
                "results": results,
                "total": len(results),
            }
        except Exception as e:
            logger.error(f"[MysqlStorageAgent] 查询失败: {e}")
            return {"status": "error", "message": str(e)}

    def _do_delete(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """删除 MySQL 记录"""
        from app.services.context_router.storage_router import get_storage_router

        table = payload.get("table", "")
        filters = payload.get("filters", {})

        if not table or not filters:
            return {"status": "error", "message": "table 和 filters 不能为空"}

        model_class_name = self._get_model_class_name(table)
        if model_class_name is None:
            return {"status": "error", "message": f"不支持的表: {table}"}

        storage = get_storage_router()
        try:
            deleted = storage.mysql_delete(model_class_name, filters)

            return {
                "status": "success",
                "table": table,
                "deleted": deleted,
                "message": f"删除 {deleted} 条记录",
            }
        except Exception as e:
            logger.error(f"[MysqlStorageAgent] 删除失败: {e}")
            return {"status": "error", "message": str(e)}

    def _do_update(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """更新 MySQL 记录"""
        from app.services.context_router.storage_router import get_storage_router

        table = payload.get("table", "")
        filters = payload.get("filters", {})
        data = payload.get("data", {})

        if not table or not filters or not data:
            return {"status": "error", "message": "table, filters, data 不能为空"}

        model_class_name = self._get_model_class_name(table)
        if model_class_name is None:
            return {"status": "error", "message": f"不支持的表: {table}"}

        storage = get_storage_router()
        try:
            updated = storage.mysql_update_by_filters(model_class_name, filters, data)

            return {
                "status": "success",
                "table": table,
                "updated": updated,
                "message": f"更新 {updated} 条记录",
            }
        except Exception as e:
            logger.error(f"[MysqlStorageAgent] 更新失败: {e}")
            return {"status": "error", "message": str(e)}
