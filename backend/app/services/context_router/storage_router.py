"""
StorageRouter - 统一写入路由

Agent 禁止直接导入数据层客户端（milvus_client、neo4j_client、embedding_factory）。
所有写入操作通过 StorageRouter 统一路由。

职责：
  - Milvus 向量写入/删除
  - Neo4j 图谱写入
  - Embedding 获取（写入前向量化）

使用方式：
  from app.services.context_router.storage_router import get_storage_router
  storage = get_storage_router()

  # Milvus 写入
  storage.milvus_insert("test_case_vector", data_list)

  # Neo4j 写入
  storage.neo4j_write("CREATE (n:Page {url: $url})", url="/login")

  # Embedding
  vector = storage.embed_sync("文本内容")

设计原则：
  - StorageRouter 是唯一的写入入口，与 ContextRouter（读取）对应
  - 内部封装直接 DB 导入，Agent 层无感知
  - 所有方法都有日志和异常处理
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class StorageRouter:
    """统一写入路由

    封装 Milvus / Neo4j / Embedding 的直接客户端调用。
    Agent 层禁止导入 milvus_client / neo4j_client / embedding_factory。
    """

    # ------------------------------------------------------------------
    # Neo4j
    # ------------------------------------------------------------------

    @staticmethod
    def neo4j_available() -> bool:
        """检查 Neo4j 是否可用"""
        try:
            from app.db.neo4j_client import is_available
            return is_available()
        except Exception as e:
            logger.warning(f"StorageRouter | Neo4j 可用性检查失败: {e}")
            return False

    @staticmethod
    def neo4j_write(cypher: str, **params) -> bool:
        """执行 Neo4j 写入 Cypher

        Args:
            cypher: Cypher 语句
            **params: Cypher 参数（以关键字形式传入，内部组装为 dict 传给 run_write）

        Returns:
            True 成功 / False 失败
        """
        try:
            from app.db.neo4j_client import run_write
            # run_write(cypher, parameters: Dict) 期望一个 dict 而非展开的 kwargs，
            # 因此将 **params 重新打包为 dict 传入，避免 unexpected keyword argument。
            run_write(cypher, params)
            return True
        except Exception as e:
            logger.warning(f"StorageRouter | Neo4j 写入失败: {e}")
            return False

    @staticmethod
    def neo4j_ensure_constraints() -> bool:
        """确保 Neo4j 约束存在"""
        try:
            from app.db.neo4j_client import ensure_constraints
            ensure_constraints()
            return True
        except Exception as e:
            logger.warning(f"StorageRouter | Neo4j 约束创建失败: {e}")
            return False

    # ------------------------------------------------------------------
    # Milvus
    # ------------------------------------------------------------------

    @staticmethod
    def milvus_ensure_collections():
        """确保 Milvus 集合已创建，返回 client"""
        try:
            from app.db.milvus_client import ensure_all_collections
            return ensure_all_collections()
        except Exception as e:
            logger.warning(f"StorageRouter | Milvus 集合初始化失败: {e}")
            return None

    @staticmethod
    def milvus_get_client():
        """获取 Milvus 客户端"""
        try:
            from app.db.milvus_client import get_milvus_client
            return get_milvus_client()
        except Exception as e:
            logger.warning(f"StorageRouter | Milvus 客户端获取失败: {e}")
            return None

    @staticmethod
    def milvus_insert(collection_name: str, data: List[Dict]) -> int:
        """插入向量到 Milvus

        Returns:
            插入数量
        """
        try:
            client = StorageRouter.milvus_ensure_collections()
            if client is None:
                return 0
            result = client.insert(collection_name=collection_name, data=data)
            count = result.get("insert_count", len(data)) if isinstance(result, dict) else len(data)
            logger.info(f"StorageRouter | Milvus 写入 | collection={collection_name} | count={count}")
            return count
        except Exception as e:
            logger.warning(f"StorageRouter | Milvus 写入失败: {e}")
            return 0

    @staticmethod
    def milvus_delete(collection_name: str, filter_expr: str) -> int:
        """从 Milvus 删除

        Returns:
            删除数量
        """
        try:
            client = StorageRouter.milvus_get_client()
            if client is None:
                return 0
            result = client.delete(collection_name=collection_name, filter=filter_expr)
            count = result.get("delete_count", 0) if isinstance(result, dict) else 0
            logger.info(f"StorageRouter | Milvus 删除 | collection={collection_name} | count={count}")
            return count
        except Exception as e:
            logger.warning(f"StorageRouter | Milvus 删除失败: {e}")
            return 0

    @staticmethod
    def milvus_query(collection_name: str, filter_expr: str, output_fields: List[str] = None) -> List[Dict]:
        """查询 Milvus（写入前的增量去重检查用）

        注意：运行时检索应通过 ContextRouter，此方法仅用于写入前的去重检查。
        """
        try:
            client = StorageRouter.milvus_get_client()
            if client is None:
                return []
            results = client.query(
                collection_name=collection_name,
                filter=filter_expr,
                output_fields=output_fields or [],
            )
            return results
        except Exception as e:
            logger.warning(f"StorageRouter | Milvus 查询失败: {e}")
            return []

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    @staticmethod
    def get_embedding():
        """获取统一 Embedding 实例"""
        try:
            from app.rag.embedding.factory import get_embedding_factory
            return get_embedding_factory().get_embedding()
        except Exception as e:
            logger.warning(f"StorageRouter | Embedding 获取失败: {e}")
            return None

    @staticmethod
    def embed_sync(text: str) -> List[float]:
        """同步生成单条文本向量"""
        embedding = StorageRouter.get_embedding()
        if embedding is None:
            return [0.0] * 1024
        return embedding.embed_sync(text)

    @staticmethod
    def embed_batch_sync(texts: List[str]) -> List[List[float]]:
        """同步批量生成向量"""
        embedding = StorageRouter.get_embedding()
        if embedding is None:
            return [[0.0] * 1024 for _ in texts]
        return embedding.embed_batch_sync(texts)

    @staticmethod
    async def embed(text: str) -> List[float]:
        """异步生成单条文本向量"""
        embedding = StorageRouter.get_embedding()
        if embedding is None:
            return [0.0] * 1024
        return await embedding.embed(text)

    @staticmethod
    async def embed_batch(texts: List[str]) -> List[List[float]]:
        """异步批量生成向量"""
        embedding = StorageRouter.get_embedding()
        if embedding is None:
            return [[0.0] * 1024 for _ in texts]
        return await embedding.embed_batch(texts)

    # ------------------------------------------------------------------
    # 向量存储（通过抽象层）
    # ------------------------------------------------------------------

    @staticmethod
    def get_vector_store():
        """获取 MilvusVectorStore（抽象层）"""
        try:
            from app.rag.vector_store.milvus_store import get_milvus_store
            return get_milvus_store()
        except Exception as e:
            logger.warning(f"StorageRouter | VectorStore 获取失败: {e}")
            return None

    @staticmethod
    def get_multi_vector_store():
        """获取 MultiVectorStore（抽象层）"""
        try:
            from app.rag.vector_store.multi_vector_store import get_multi_vector_store
            return get_multi_vector_store()
        except Exception as e:
            logger.warning(f"StorageRouter | MultiVectorStore 获取失败: {e}")
            return None

    @staticmethod
    def get_extended_graph_store():
        """获取 ExtendedGraphStore（抽象层）"""
        try:
            from app.rag.graph_store.extended_store import get_extended_graph_store
            return get_extended_graph_store()
        except Exception as e:
            logger.warning(f"StorageRouter | ExtendedGraphStore 获取失败: {e}")
            return None

    # ------------------------------------------------------------------
    # MySQL 统一读写（Agent 不应直接使用 SessionLocal）
    # ------------------------------------------------------------------

    # 统一模型类映射表
    MODEL_MAP: Dict[str, tuple] = {
        # 通用业务模型
        "Script": ("app.models.script", "Script"),
        "Task": ("app.models.task", "Task"),
        "RequirementTask": ("app.models.requirement_task", "RequirementTask"),
        "ExecutionRecord": ("app.models.execution_record", "ExecutionRecord"),
        "Feedback": ("app.models.feedback", "Feedback"),
        "ScheduleTask": ("app.models.schedule_task", "ScheduleTask"),
        "ScheduleRunLog": ("app.models.schedule_task", "ScheduleRunLog"),
        "PageRelation": ("app.models.page_relation", "PageRelation"),
        "SessionEvent": ("app.models.session_event", "SessionEvent"),
        "FlowResult": ("app.models.flow_result", "FlowResult"),
        # 测试用例流程模型
        "TestCasePoint": ("app.models.test_case_point", "TestCasePoint"),
        "TestCase": ("app.models.test_case", "TestCase"),
        "TestCaseReview": ("app.models.test_case_review", "TestCaseReview"),
        "MindMap": ("app.models.mind_map", "MindMap"),
        "TestRequirement": ("app.models.test_requirement", "TestRequirement"),
        # 会话与日志模型
        "Session": ("app.models.session", "Session"),
        "AgentEvent": ("app.models.agent_event", "AgentEvent"),
        "AgentLog": ("app.models.agent_log", "AgentLog"),
        "SessionArtifact": ("app.models.session_artifact", "SessionArtifact"),
        # 用例内容模型
        "CaseContent": ("app.models.case_content", "CaseContent"),
        "CaseTask": ("app.models.case_task", "CaseTask"),
        # 知识模型
        "KnowledgeSource": ("app.models.knowledge_source", "KnowledgeSource"),
        "KnowledgeChunk": ("app.models.knowledge_chunk", "KnowledgeChunk"),
    }

    @staticmethod
    def _resolve_model(model_class_name: str):
        """根据模型类名解析 ORM 模型类

        Args:
            model_class_name: 模型类名（如 "Task", "FlowResult"）

        Returns:
            ORM 模型类，失败返回 None
        """
        import importlib

        entry = StorageRouter.MODEL_MAP.get(model_class_name)
        if entry is None:
            logger.warning(f"StorageRouter | 未知模型: {model_class_name}")
            return None
        try:
            module = importlib.import_module(entry[0])
            return getattr(module, entry[1])
        except Exception as e:
            logger.error(f"StorageRouter | 模型加载失败: {model_class_name}: {e}")
            return None

    def mysql_save(
        self,
        model_class_name: str,
        data: Dict[str, Any],
    ) -> Optional[int]:
        """统一 MySQL 写入入口

        Agent 不应直接导入 SessionLocal 和 Model 类，
        通过此方法统一写入。

        Args:
            model_class_name: 模型类名（如 "Script", "Task", "FlowResult"）
            data: 字段字典

        Returns:
            记录 ID（失败返回 None）
        """
        from app.db.database import SessionLocal

        model_cls = self._resolve_model(model_class_name)
        if model_cls is None:
            return None

        db = SessionLocal()
        try:
            # 过滤掉不存在的字段
            valid_columns = {c.name for c in model_cls.__table__.columns}
            filtered_data = {k: v for k, v in data.items() if k in valid_columns}

            record = model_cls(**filtered_data)
            db.add(record)
            db.commit()
            db.refresh(record)
            logger.debug(
                f"StorageRouter | MySQL写入 | "
                f"model={model_class_name} | id={record.id}"
            )
            return record.id
        except Exception as e:
            db.rollback()
            logger.error(
                f"StorageRouter | MySQL写入失败 | "
                f"model={model_class_name} | error={e}",
                exc_info=True,
            )
            return None
        finally:
            db.close()

    def mysql_update(
        self,
        model_class_name: str,
        record_id: int,
        data: Dict[str, Any],
    ) -> bool:
        """统一 MySQL 更新入口（按 ID 更新）

        Args:
            model_class_name: 模型类名
            record_id: 记录 ID
            data: 要更新的字段字典

        Returns:
            True/False
        """
        from app.db.database import SessionLocal

        model_cls = self._resolve_model(model_class_name)
        if model_cls is None:
            return False

        db = SessionLocal()
        try:
            record = db.query(model_cls).filter(model_cls.id == record_id).first()
            if record is None:
                logger.warning(f"StorageRouter | 记录不存在: {model_class_name}#{record_id}")
                return False

            # 过滤掉不存在的字段
            valid_columns = {c.name for c in model_cls.__table__.columns}
            for key, val in data.items():
                if key in valid_columns:
                    setattr(record, key, val)

            db.commit()
            logger.debug(
                f"StorageRouter | MySQL更新 | "
                f"model={model_class_name} | id={record_id}"
            )
            return True
        except Exception as e:
            db.rollback()
            logger.error(
                f"StorageRouter | MySQL更新失败 | "
                f"model={model_class_name} | id={record_id} | error={e}",
                exc_info=True,
            )
            return False
        finally:
            db.close()

    def mysql_update_by_filters(
        self,
        model_class_name: str,
        filters: Dict[str, Any],
        data: Dict[str, Any],
    ) -> int:
        """统一 MySQL 更新入口（按条件批量更新）

        Args:
            model_class_name: 模型类名
            filters: 过滤条件（如 {"status": "pending"}）
            data: 要更新的字段字典

        Returns:
            更新的记录数（失败返回 0）
        """
        from app.db.database import SessionLocal

        model_cls = self._resolve_model(model_class_name)
        if model_cls is None:
            return 0

        db = SessionLocal()
        try:
            q = db.query(model_cls)

            # 应用过滤条件
            valid_columns = {c.name for c in model_cls.__table__.columns}
            for key, value in filters.items():
                if key in valid_columns:
                    q = q.filter(getattr(model_cls, key) == value)

            # 过滤数据
            filtered_data = {k: v for k, v in data.items() if k in valid_columns}
            updated = q.update(filtered_data, synchronize_session=False)
            db.commit()

            logger.debug(
                f"StorageRouter | MySQL条件更新 | "
                f"model={model_class_name} | updated={updated}"
            )
            return updated
        except Exception as e:
            db.rollback()
            logger.error(
                f"StorageRouter | MySQL条件更新失败 | "
                f"model={model_class_name} | error={e}",
                exc_info=True,
            )
            return 0
        finally:
            db.close()

    def mysql_query(
        self,
        model_class_name: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 50,
        offset: int = 0,
        order_by: str = "id",
        order_desc: bool = False,
    ) -> List[Dict[str, Any]]:
        """统一 MySQL 查询入口（按条件查询多条记录）

        Args:
            model_class_name: 模型类名
            filters: 过滤条件（如 {"status": "success"}）
            limit: 最大返回数
            offset: 偏移量
            order_by: 排序字段
            order_desc: 是否降序

        Returns:
            记录字典列表（空列表表示无结果或出错）
        """
        from app.db.database import SessionLocal

        model_cls = self._resolve_model(model_class_name)
        if model_cls is None:
            return []

        db = SessionLocal()
        try:
            q = db.query(model_cls)

            # 应用过滤条件
            valid_columns = {c.name for c in model_cls.__table__.columns}
            if filters:
                for key, value in filters.items():
                    if key in valid_columns:
                        q = q.filter(getattr(model_cls, key) == value)

            # 排序
            if order_by in valid_columns:
                col = getattr(model_cls, order_by)
                q = q.order_by(col.desc() if order_desc else col.asc())

            # 分页
            q = q.offset(offset).limit(limit)
            results = q.all()

            # 转换为字典
            data_list = []
            for r in results:
                item = {}
                for c in model_cls.__table__.columns:
                    val = getattr(r, c.name, None)
                    if val is not None and hasattr(val, "isoformat"):
                        val = val.isoformat()
                    item[c.name] = val
                data_list.append(item)

            return data_list
        except Exception as e:
            logger.error(
                f"StorageRouter | MySQL查询失败 | "
                f"model={model_class_name} | error={e}",
                exc_info=True,
            )
            return []
        finally:
            db.close()

    def mysql_query_one(
        self,
        model_class_name: str,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """统一 MySQL 查询单条记录入口

        Args:
            model_class_name: 模型类名
            filters: 过滤条件（如 {"task_id": "abc", "name": "测试点1"}）

        Returns:
            单条记录字典或 None
        """
        results = self.mysql_query(
            model_class_name=model_class_name,
            filters=filters,
            limit=1,
        )
        if results:
            return results[0]
        return None

    def mysql_delete(
        self,
        model_class_name: str,
        filters: Dict[str, Any],
    ) -> int:
        """统一 MySQL 删除入口（按条件删除）

        Args:
            model_class_name: 模型类名
            filters: 过滤条件（如 {"task_id": "abc"}）

        Returns:
            删除的记录数（失败返回 0）
        """
        from app.db.database import SessionLocal

        model_cls = self._resolve_model(model_class_name)
        if model_cls is None:
            return 0

        db = SessionLocal()
        try:
            q = db.query(model_cls)

            # 应用过滤条件
            valid_columns = {c.name for c in model_cls.__table__.columns}
            for key, value in filters.items():
                if key in valid_columns:
                    q = q.filter(getattr(model_cls, key) == value)

            deleted = q.delete(synchronize_session=False)
            db.commit()

            logger.debug(
                f"StorageRouter | MySQL删除 | "
                f"model={model_class_name} | deleted={deleted}"
            )
            return deleted
        except Exception as e:
            db.rollback()
            logger.error(
                f"StorageRouter | MySQL删除失败 | "
                f"model={model_class_name} | error={e}",
                exc_info=True,
            )
            return 0
        finally:
            db.close()


# ------------------------------------------------------------------
# 单例
# ------------------------------------------------------------------

_storage_router: Optional[StorageRouter] = None


def get_storage_router() -> StorageRouter:
    """获取 StorageRouter 单例"""
    global _storage_router
    if _storage_router is None:
        _storage_router = StorageRouter()
    return _storage_router
