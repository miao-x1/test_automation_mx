"""
MySQL检索器

从MySQL业务数据库检索结构化数据。
根据查询计划中的表名和过滤条件执行查询。

注意：不直接暴露ORM模型给外部，通过to_dict()序列化返回。
"""
import logging
from typing import Any, Dict, List

from app.rag.retrieval_engine.base import BaseRetriever, RetrievalResult

logger = logging.getLogger(__name__)


class MysqlRetriever(BaseRetriever):
    """MySQL业务数据检索器

    根据查询计划从MySQL检索业务数据。
    支持按表名查询、过滤条件筛选。
    """

    # 表名 → ORM模型类名映射
    TABLE_MODEL_MAP = {
        "task": ("app.models.task", "Task"),
        "test_case": ("app.models.test_case", "TestCase"),
        "test_case_point": ("app.models.test_case_point", "TestCasePoint"),
        "test_requirement": ("app.models.test_requirement", "TestRequirement"),
        "requirement_task": ("app.models.requirement_task", "RequirementTask"),
        "requirement_input": ("app.models.requirement_input", "RequirementInput"),
        "script": ("app.models.script", "Script"),
        "ui_element": ("app.models.ui_element", "UIElement"),
        "page_element": ("app.models.page_element", "PageElement"),
        "api_case": ("app.models.api_case", "ApiCase"),
        "api_metadata": ("app.models.api_metadata", "ApiMetadata"),
        "execution_record": ("app.models.execution_record", "ExecutionRecord"),
        "agent_execution_log": ("app.models.agent_execution_log", "AgentExecutionLog"),
    }

    def __init__(self):
        super().__init__("mysql")

    def search(self, query: Dict[str, Any]) -> RetrievalResult:
        """
        从MySQL检索业务数据

        Args:
            query: {
                tables: ["task", "test_case"],  # 要查询的表名
                filters: {"task_id": "xxx"},     # 过滤条件
                fields: [],                       # 返回字段（空=全部）
                limit: 100
            }

        Returns:
            RetrievalResult: {
                data: {table_name: [row1, row2, ...]},
                count: total_rows
            }
        """
        tables = query.get("tables", [])
        filters = query.get("filters", {})
        fields = query.get("fields", [])
        limit = query.get("limit", 100)

        if not tables:
            return RetrievalResult(source="mysql", success=True, data={}, count=0)

        results = {}
        total_count = 0

        from app.db.database import SessionLocal
        db = SessionLocal()

        try:
            for table_name in tables:
                model_info = self.TABLE_MODEL_MAP.get(table_name)
                if not model_info:
                    logger.warning(f"[mysql] 未知的表名: {table_name}")
                    continue

                module_path, class_name = model_info
                try:
                    # 动态导入模型
                    import importlib
                    module = importlib.import_module(module_path)
                    model_class = getattr(module, class_name)

                    # 构建查询
                    db_query = db.query(model_class)

                    # 应用过滤条件
                    for key, value in filters.items():
                        if hasattr(model_class, key):
                            col = getattr(model_class, key)
                            if isinstance(value, list):
                                db_query = db_query.filter(col.in_(value))
                            else:
                                db_query = db_query.filter(col == value)

                    # 限制返回数量
                    db_query = db_query.limit(limit)

                    # 执行查询
                    rows = db_query.all()

                    # 序列化
                    serialized = []
                    for row in rows:
                        if hasattr(row, "to_dict"):
                            serialized.append(row.to_dict())
                        else:
                            # 手动序列化
                            data = {}
                            for col in model_class.__table__.columns:
                                val = getattr(row, col.name, None)
                                if val is not None:
                                    data[col.name] = str(val) if not isinstance(val, (int, float, bool, str, type(None))) else val
                            serialized.append(data)

                    results[table_name] = serialized
                    total_count += len(serialized)

                except Exception as e:
                    logger.error(f"[mysql] 查询表 {table_name} 失败: {e}")
                    results[table_name] = []

        finally:
            db.close()

        return RetrievalResult(
            source="mysql",
            success=True,
            data=results,
            count=total_count,
        )
