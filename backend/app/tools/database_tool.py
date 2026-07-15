"""Database 工具 - MySQL 查询和保存"""
import logging
from typing import Any, Dict
from app.tools.base import BaseTool, ToolResult, ToolContext

logger = logging.getLogger(__name__)


class DatabaseQueryTool(BaseTool):
    """数据库查询工具

    通过 SQLAlchemy 查询 MySQL。
    """

    def __init__(self):
        super().__init__(name="db_query", description="MySQL数据库查询")

    async def execute(self, ctx: ToolContext, **kwargs) -> ToolResult:
        table = kwargs.get("table", "")
        filters = kwargs.get("filters", {})
        limit = kwargs.get("limit", 50)

        if not table:
            return ToolResult(success=False, error="table不能为空")

        try:
            from app.db.database import SessionLocal
            from app.models.knowledge_source import KnowledgeSource
            from app.models.flow_result import FlowResult
            from app.models.agent_event import AgentEvent

            table_map = {
                "knowledge_source": KnowledgeSource,
                "flow_result": FlowResult,
                "agent_event": AgentEvent,
            }

            model = table_map.get(table)
            if model is None:
                return ToolResult(success=False, error=f"不支持的表: {table}")

            db = SessionLocal()
            try:
                q = db.query(model)
                valid_cols = {c.name for c in model.__table__.columns}
                for k, v in filters.items():
                    if k in valid_cols:
                        q = q.filter(getattr(model, k) == v)
                q = q.limit(limit)
                results = q.all()

                data = []
                for r in results:
                    item = {}
                    for c in model.__table__.columns:
                        val = getattr(r, c.name, None)
                        if hasattr(val, 'isoformat'):
                            val = val.isoformat()
                        item[c.name] = val
                    data.append(item)

                return ToolResult(success=True, data={"results": data, "total": len(data)})
            finally:
                db.close()
        except Exception as e:
            logger.error(f"[DatabaseQueryTool] 查询失败: {e}")
            return ToolResult(success=False, error=str(e))


class DatabaseSaveTool(BaseTool):
    """数据库保存工具

    通过 SQLAlchemy 保存数据到 MySQL。
    """

    def __init__(self):
        super().__init__(name="db_save", description="MySQL数据库保存")

    async def execute(self, ctx: ToolContext, **kwargs) -> ToolResult:
        table = kwargs.get("table", "")
        data = kwargs.get("data", {})

        if not table or not data:
            return ToolResult(success=False, error="table和data不能为空")

        try:
            from app.db.database import SessionLocal
            from app.models.flow_result import FlowResult
            from app.models.agent_log import AgentLog

            table_map = {
                "flow_result": FlowResult,
                "agent_log": AgentLog,
            }

            model = table_map.get(table)
            if model is None:
                return ToolResult(success=False, error=f"不支持的表: {table}")

            valid_cols = {c.name for c in model.__table__.columns}
            filtered = {k: v for k, v in data.items() if k in valid_cols}

            db = SessionLocal()
            try:
                obj = model(**filtered)
                db.add(obj)
                db.commit()
                db.refresh(obj)
                return ToolResult(success=True, data={"id": obj.id, "table": table})
            except Exception as e:
                db.rollback()
                raise
            finally:
                db.close()
        except Exception as e:
            logger.error(f"[DatabaseSaveTool] 保存失败: {e}")
            return ToolResult(success=False, error=str(e))
