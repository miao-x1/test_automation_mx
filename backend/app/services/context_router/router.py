"""
ContextRouter - 统一上下文路由实现

核心原则：
  Agent 不再直接调用 Milvus / R2R / Neo4j / MySQL。
  所有查询统一通过 ContextRouter，根据 context_type 自动路由。

数据源适配器：
  _query_mysql()    → MySQL（SQLAlchemy ORM）
  _query_milvus()   → Milvus（pymilvus MilvusClient，含 rag_knowledge_vector）
  _query_neo4j()    → Neo4j（Cypher 查询）
  _query_r2r()      → 保留方法，但 R2R 不参与运行时查询（仅入库用）

R2R 的定位：
  R2R 是知识入库工具（解析→分块→向量化→存入Milvus），不是运行时数据源。
  知识入库后，向量在 Milvus 的 rag_knowledge_vector 集合中。
  Agent 查询文档知识时走 Milvus，不走 R2R。
"""
import time
import uuid
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logger import log
from app.services.context_router.context_type import ContextType, ROUTING_TABLE


class ContextRouter:
    """统一上下文路由器

    根据 context_type 自动选择数据源，合并结果后返回。
    所有 Agent 必须通过本类查询上下文，禁止直接访问底层数据库。
    """

    def __init__(self) -> None:
        self._request_count: int = 0

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    async def retrieve(
        self,
        query: str,
        context_type: ContextType,
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        project_id: str = "",
    ) -> Dict[str, Any]:
        """异步检索入口

        Args:
            query: 查询文本
            context_type: 上下文类型（决定查询哪些数据源）
            top_k: 每个数据源返回的最大数量
            filters: 过滤条件
            project_id: 项目ID

        Returns:
            统一格式的检索结果
        """
        return self.retrieve_sync(
            query=query,
            context_type=context_type,
            top_k=top_k,
            filters=filters,
            project_id=project_id,
        )

    def retrieve_sync(
        self,
        query: str,
        context_type: ContextType,
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        project_id: str = "",
    ) -> Dict[str, Any]:
        """同步检索入口

        Args:
            query: 查询文本
            context_type: 上下文类型
            top_k: 每个数据源返回的最大数量
            filters: 过滤条件
            project_id: 项目ID

        Returns:
            {
                "query": str,
                "context_type": str,
                "sources": {source_name: [results]},
                "results": [merged_results],
                "total": int,
                "latency_ms": int,
                "request_id": str,
            }
        """
        request_id = f"ctx_{uuid.uuid4().hex[:12]}"
        start = time.time()

        # 兼容字符串和枚举
        if isinstance(context_type, str):
            context_type = ContextType(context_type)

        sources = ROUTING_TABLE.get(context_type, [])
        log.info(
            f"ContextRouter | 收到查询 | request_id={request_id} | "
            f"type={context_type.value} | sources={sources} | "
            f"top_k={top_k} | query={query[:80]}"
        )

        results_by_source: Dict[str, List[Dict[str, Any]]] = {}
        filters = filters or {}

        # 按数据源逐一查询
        for source in sources:
            try:
                source_start = time.time()
                if source == "mysql":
                    data = self._query_mysql(query, context_type, top_k, filters, project_id)
                elif source == "milvus":
                    data = self._query_milvus(query, context_type, top_k, filters, project_id)
                elif source == "neo4j":
                    data = self._query_neo4j(query, context_type, top_k, filters, project_id)
                elif source == "r2r":
                    data = self._query_r2r(query, context_type, top_k, filters, project_id)
                else:
                    log.warning(f"ContextRouter | 未知数据源: {source}")
                    data = []

                source_elapsed = (time.time() - source_start) * 1000
                results_by_source[source] = data
                log.info(
                    f"ContextRouter | 数据源={source} | 返回={len(data)}条 | "
                    f"耗时={source_elapsed:.0f}ms"
                )
            except Exception as e:
                log.error(
                    f"ContextRouter | 数据源={source} 查询失败: {e}",
                    exc_info=True,
                )
                results_by_source[source] = []

        # 合并结果
        merged = self._merge_results(results_by_source, top_k)
        latency_ms = int((time.time() - start) * 1000)

        self._request_count += 1
        log.info(
            f"ContextRouter | 查询完成 | request_id={request_id} | "
            f"total={len(merged)} | latency={latency_ms}ms"
        )

        return {
            "query": query,
            "context_type": context_type.value,
            "sources": results_by_source,
            "results": merged,
            "total": len(merged),
            "latency_ms": latency_ms,
            "request_id": request_id,
        }

    # ------------------------------------------------------------------
    # Embedding 生成（同步）
    # ------------------------------------------------------------------

    def _embed_query(self, query: str) -> List[float]:
        """生成查询向量（同步，通过 EmbeddingFactory 统一获取）

        禁止在 ContextRouter 中重复实现 DashScope Embedding。
        所有 Embedding 调用统一通过 EmbeddingFactory → DashScopeEmbedding。
        """
        try:
            from app.rag.embedding.factory import get_embedding_factory
            embedding = get_embedding_factory().get_embedding()
            vector = embedding.embed_sync(query)
            if vector:
                return vector
            log.warning("ContextRouter | Embedding 返回空向量 | 降级为零向量")
            return [0.0] * settings.EMBEDDING_DIM
        except Exception as e:
            log.warning(f"ContextRouter | Embedding 失败: {e} | 降级为零向量")
            return [0.0] * settings.EMBEDDING_DIM

    # ------------------------------------------------------------------
    # MySQL 适配器
    # ------------------------------------------------------------------

    def _query_mysql(
        self,
        query: str,
        context_type: ContextType,
        top_k: int,
        filters: Dict,
        project_id: str,
    ) -> List[Dict[str, Any]]:
        """MySQL 结构化数据查询"""
        results: List[Dict[str, Any]] = []

        try:
            from app.db.database import SessionLocal

            db = SessionLocal()
            try:
                if context_type == ContextType.PAGE_ELEMENT:
                    results = self._mysql_query_elements(db, query, top_k, project_id)

                elif context_type == ContextType.BUSINESS_FLOW:
                    results = self._mysql_query_pages(db, query, top_k, project_id)

                elif context_type == ContextType.SCRIPT:
                    results = self._mysql_query_scripts(db, query, top_k, project_id)

                elif context_type == ContextType.EXECUTION_HISTORY:
                    results = self._mysql_query_executions(db, query, top_k, project_id)

                elif context_type == ContextType.DOCUMENT:
                    results = self._mysql_query_knowledge(db, query, top_k, project_id)

                elif context_type == ContextType.REQUIREMENT_TASK:
                    results = self._mysql_query_requirement_tasks(db, query, top_k, filters)

                elif context_type == ContextType.TASK:
                    results = self._mysql_query_tasks(db, query, top_k, filters)

                elif context_type == ContextType.SCHEDULE_TASK:
                    results = self._mysql_query_schedule_tasks(db, query, top_k, filters)

                elif context_type == ContextType.FEEDBACK:
                    results = self._mysql_query_feedbacks(db, query, top_k, filters)

                elif context_type == ContextType.SESSION_EVENT:
                    results = self._mysql_query_session_events(db, query, top_k, filters)

                elif context_type == ContextType.FLOW_RESULT:
                    results = self._mysql_query_flow_results(db, query, top_k, filters)

            finally:
                db.close()

        except Exception as e:
            log.warning(f"ContextRouter | MySQL查询失败: {e}")

        return results

    # ------------------------------------------------------------------
    # 统一查询入口（Agent 调用的主接口）
    # ------------------------------------------------------------------

    def query(
        self,
        query_text: str,
        context_type: ContextType,
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        project_id: str = "",
    ) -> Dict[str, Any]:
        """统一查询入口（Agent 唯一调用方法）

        Agent 不需要知道底层使用 MySQL/Milvus/Neo4j 中的哪个，
        只需传入 context_type，ContextRouter 自动路由。

        示例：
            router = get_context_router()
            result = router.query("登录按钮", ContextType.PAGE_ELEMENT)
            # result["results"] 包含 MySQL + Milvus + Neo4j 合并结果

        Args:
            query_text: 查询文本（关键词/自然语言）
            context_type: 上下文类型（决定查哪些数据源）
            top_k: 最大返回数
            filters: 过滤条件（如 {"task_id": 123, "status": "success"}）
            project_id: 项目ID

        Returns:
            {
                "query": str,
                "context_type": str,
                "results": [...],     # 合并后的结果列表
                "sources": {...},      # 各数据源原始结果
                "total": int,
                "latency_ms": int,
            }
        """
        return self.retrieve_sync(
            query=query_text,
            context_type=context_type,
            top_k=top_k,
            filters=filters,
            project_id=project_id,
        )

    def query_one(
        self,
        context_type: ContextType,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """按条件查询单条记录

        用于 Agent 获取特定记录（如 task_id=123 的 Task）。

        Args:
            context_type: 上下文类型
            filters: 过滤条件（如 {"task_id": 123}）

        Returns:
            单条记录 dict 或 None
        """
        results = self.query(
            query_text="",
            context_type=context_type,
            top_k=1,
            filters=filters,
        )
        if results and results.get("results"):
            return results["results"][0]
        return None

    def query_by_id(
        self,
        context_type: ContextType,
        record_id: int,
    ) -> Optional[Dict[str, Any]]:
        """按 ID 查询单条记录

        Args:
            context_type: 上下文类型
            record_id: 记录ID

        Returns:
            单条记录 dict 或 None
        """
        return self.query_one(
            context_type=context_type,
            filters={"id": record_id},
        )

    def _mysql_query_elements(
        self, db, query: str, top_k: int, project_id: str
    ) -> List[Dict[str, Any]]:
        """查询页面元素（MySQL）"""
        from app.models.ui_element import UIElement
        from sqlalchemy import or_

        q = db.query(UIElement)
        if project_id:
            try:
                q = q.filter(UIElement.task_id == int(project_id))
            except (ValueError, TypeError):
                pass

        # 关键词模糊匹配
        keywords = query.split()
        if keywords:
            conditions = []
            for kw in keywords:
                conditions.append(UIElement.name.contains(kw))
                conditions.append(UIElement.text.contains(kw))
            q = q.filter(or_(*conditions))

        rows = q.limit(top_k).all()
        return [
            {
                "source": "mysql",
                "source_type": "page_element",
                "id": str(r.id),
                "text": f"{r.name} ({r.type}): {r.text or ''}",
                "element_name": r.name,
                "element_type": r.type,
                "locator": r.locator,
                "page_url": r.page_url or "",
                "score": 0.5,
            }
            for r in rows
        ]

    def _mysql_query_pages(
        self, db, query: str, top_k: int, project_id: str
    ) -> List[Dict[str, Any]]:
        """查询页面信息（MySQL）"""
        from app.models.page_element import PageElement
        from sqlalchemy import or_

        q = db.query(PageElement)
        keywords = query.split()
        if keywords:
            conditions = []
            for kw in keywords:
                conditions.append(PageElement.page_url.contains(kw))
                conditions.append(PageElement.element_text.contains(kw))
            q = q.filter(or_(*conditions))

        rows = q.limit(top_k).all()
        return [
            {
                "source": "mysql",
                "source_type": "page",
                "id": str(r.id),
                "text": f"页面: {r.page_url} (元素: {r.tag_name})",
                "page_url": r.page_url,
                "tag_name": r.tag_name,
                "score": 0.5,
            }
            for r in rows
        ]

    def _mysql_query_scripts(
        self, db, query: str, top_k: int, project_id: str
    ) -> List[Dict[str, Any]]:
        """查询脚本（MySQL）"""
        from app.models.script import Script
        from sqlalchemy import or_

        q = db.query(Script)
        keywords = query.split()
        if keywords:
            conditions = []
            for kw in keywords:
                conditions.append(Script.script_type.contains(kw))
                conditions.append(Script.script_content.contains(kw))
            q = q.filter(or_(*conditions))

        rows = q.limit(top_k).all()
        return [
            {
                "source": "mysql",
                "source_type": "script",
                "id": str(r.id),
                "text": f"脚本: {r.script_type} (语言: {r.script_language})",
                "script_name": r.script_type,
                "language": r.script_language,
                "script_content": r.script_content[:500] if r.script_content else "",
                "score": 0.5,
            }
            for r in rows
        ]

    def _mysql_query_executions(
        self, db, query: str, top_k: int, project_id: str
    ) -> List[Dict[str, Any]]:
        """查询执行历史（MySQL）"""
        from app.models.execution_record import ExecutionRecord

        q = db.query(ExecutionRecord)
        if project_id:
            try:
                q = q.filter(ExecutionRecord.task_id == int(project_id))
            except (ValueError, TypeError):
                pass

        rows = q.order_by(ExecutionRecord.created_at.desc()).limit(top_k).all()
        return [
            {
                "source": "mysql",
                "source_type": "execution",
                "id": str(r.id),
                "text": f"执行记录 #{r.id}: status={r.status}, type={r.execution_type}",
                "status": r.status,
                "execution_type": r.execution_type,
                "task_id": getattr(r, "task_id", None),
                "duration": getattr(r, "duration", None),
                "score": 0.5,
            }
            for r in rows
        ]

    def _mysql_query_knowledge(
        self, db, query: str, top_k: int, project_id: str
    ) -> List[Dict[str, Any]]:
        """查询知识文档元数据（MySQL）"""
        from app.models.knowledge_source import KnowledgeSource
        from app.models.knowledge_chunk import KnowledgeChunk
        from sqlalchemy import or_

        # 查询 knowledge_source（文档级元数据）
        q = db.query(KnowledgeSource)
        keywords = query.split()
        if keywords:
            conditions = []
            for kw in keywords:
                conditions.append(KnowledgeSource.name.contains(kw))
                conditions.append(KnowledgeSource.source_type.contains(kw))
            q = q.filter(or_(*conditions))

        rows = q.limit(top_k).all()
        return [
            {
                "source": "mysql",
                "source_type": "knowledge_source",
                "id": str(r.id),
                "text": f"知识文档: {r.name} (类型: {r.source_type}, 状态: {r.status})",
                "source_name": r.name,
                "source_type_value": r.source_type,
                "status": r.status,
                "file_path": getattr(r, "file_path", ""),
                "created_at": str(getattr(r, "created_at", "")),
                "score": 0.5,
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Milvus 适配器
    # ------------------------------------------------------------------

    def _query_milvus(
        self,
        query: str,
        context_type: ContextType,
        top_k: int,
        filters: Dict,
        project_id: str,
    ) -> List[Dict[str, Any]]:
        """Milvus 向量检索"""
        from app.db.milvus_client import (
            ensure_all_collections,
            COLLECTION_NAME,
            CASE_COLLECTION_NAME,
            SCRIPT_COLLECTION_NAME,
        )
        from app.db.collection_constants import RAG_KNOWLEDGE_COLLECTION

        results: List[Dict[str, Any]] = []

        client = ensure_all_collections()
        if client is None:
            log.warning("ContextRouter | Milvus不可用，跳过向量检索")
            return results

        # 生成查询向量
        try:
            query_embedding = self._embed_query(query)
        except Exception as e:
            log.error(f"ContextRouter | Embedding生成失败: {e}")
            return results

        # 根据 context_type 选择集合
        collection_map = {
            ContextType.PAGE_ELEMENT: COLLECTION_NAME,
            ContextType.TEST_CASE: CASE_COLLECTION_NAME,
            ContextType.SCRIPT: SCRIPT_COLLECTION_NAME,
            ContextType.DOCUMENT: RAG_KNOWLEDGE_COLLECTION,
        }

        collection_name = collection_map.get(context_type)
        if not collection_name:
            log.warning(f"ContextRouter | context_type={context_type} 无对应Milvus集合")
            return results

        # 检查集合是否存在且有数据
        if not client.has_collection(collection_name):
            return results

        stats = client.get_collection_stats(collection_name)
        if stats.get("row_count", 0) == 0:
            return results

        # 定义输出字段
        output_fields_map = {
            COLLECTION_NAME: [
                "task_id", "page_name", "element_name",
                "element_type", "locator", "description",
            ],
            CASE_COLLECTION_NAME: [
                "task_id", "case_name", "description", "steps",
            ],
            SCRIPT_COLLECTION_NAME: [
                "task_id", "script_name", "script_content", "description",
            ],
            RAG_KNOWLEDGE_COLLECTION: [
                "source_id", "chunk_id", "source_type",
                "chunk_type", "chunk_index", "text", "metadata",
            ],
        }

        output_fields = output_fields_map.get(collection_name, [])

        try:
            client.load_collection(collection_name)
            search_results = client.search(
                collection_name=collection_name,
                data=[query_embedding],
                limit=top_k,
                output_fields=output_fields,
                search_params={"metric_type": "COSINE", "params": {"nprobe": 10}},
            )

            if search_results and len(search_results) > 0:
                for hit in search_results[0]:
                    entity = hit.get("entity", {})
                    score = round(hit.get("distance", 0), 4)
                    results.append({
                        "source": "milvus",
                        "source_type": context_type.value,
                        "id": str(hit.get("id", "")),
                        "score": score,
                        "text": self._milvus_entity_to_text(entity, collection_name),
                        "entity": entity,
                    })

        except Exception as e:
            log.error(f"ContextRouter | Milvus检索失败 collection={collection_name}: {e}")

        return results

    def _milvus_entity_to_text(self, entity: Dict, collection_name: str) -> str:
        """将 Milvus 实体转为可读文本"""
        from app.db.milvus_client import COLLECTION_NAME, CASE_COLLECTION_NAME

        if collection_name == COLLECTION_NAME:
            return (
                f"页面: {entity.get('page_name', '')} | "
                f"元素: {entity.get('element_name', '')} "
                f"({entity.get('element_type', '')}) | "
                f"定位器: {entity.get('locator', '')} | "
                f"描述: {entity.get('description', '')}"
            )
        elif collection_name == CASE_COLLECTION_NAME:
            return (
                f"用例: {entity.get('case_name', '')} | "
                f"描述: {entity.get('description', '')}"
            )
        elif collection_name == RAG_KNOWLEDGE_COLLECTION:
            return (
                f"文档片段: [{entity.get('source_type', '')}] "
                f"chunk#{entity.get('chunk_index', 0)} | "
                f"{entity.get('text', '')[:200]}"
            )
        else:
            return (
                f"脚本: {entity.get('script_name', '')} | "
                f"描述: {entity.get('description', '')}"
            )

    # ------------------------------------------------------------------
    # Neo4j 适配器
    # ------------------------------------------------------------------

    def _query_neo4j(
        self,
        query: str,
        context_type: ContextType,
        top_k: int,
        filters: Dict,
        project_id: str,
    ) -> List[Dict[str, Any]]:
        """Neo4j 关系图谱查询"""
        from app.db.neo4j_client import is_available, run_query, LABEL_PAGE, LABEL_ELEMENT

        results: List[Dict[str, Any]] = []

        if not is_available():
            log.warning("ContextRouter | Neo4j不可用，跳过图谱查询")
            return results

        try:
            if context_type == ContextType.PAGE_ELEMENT:
                results = self._neo4j_query_elements(query, top_k)

            elif context_type == ContextType.BUSINESS_FLOW:
                results = self._neo4j_query_flows(query, top_k)

        except Exception as e:
            log.warning(f"ContextRouter | Neo4j查询失败: {e}")

        return results

    def _neo4j_query_elements(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        """查询页面→元素关系"""
        from app.db.neo4j_client import (
            run_query, LABEL_PAGE, LABEL_ELEMENT,
            REL_HAS_ELEMENT,
        )

        pattern = f"(?i).*{query.replace('*', '.*')}.*"
        results = run_query(
            f"MATCH (p:{LABEL_PAGE})-[:{REL_HAS_ELEMENT}]->(e:{LABEL_ELEMENT}) "
            f"WHERE p.title =~ $pattern OR p.url =~ $pattern "
            f"OR e.name =~ $pattern "
            f"RETURN p.id AS pid, p.title AS ptitle, p.url AS purl, "
            f"e.id AS eid, e.name AS ename, e.type AS etype, e.locator AS eloc "
            f"LIMIT $limit",
            {"pattern": pattern, "limit": top_k * 2},
        )

        return [
            {
                "source": "neo4j",
                "source_type": "page_element_relation",
                "id": r.get("eid", ""),
                "text": (
                    f"页面[{r.get('ptitle', '')}] → "
                    f"元素[{r.get('ename', '')}]({r.get('etype', '')}) "
                    f"定位器: {r.get('eloc', '')}"
                ),
                "page_id": r.get("pid", ""),
                "page_title": r.get("ptitle", ""),
                "element_id": r.get("eid", ""),
                "element_name": r.get("ename", ""),
                "score": 0.4,
            }
            for r in results
        ]

    def _neo4j_query_flows(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        """查询业务流程（页面导航路径）"""
        from app.db.neo4j_client import (
            run_query, LABEL_PAGE, REL_NAVIGATE_TO,
        )

        pattern = f"(?i).*{query.replace('*', '.*')}.*"
        results = run_query(
            f"MATCH path = (start:{LABEL_PAGE})-[:{REL_NAVIGATE_TO}*1..3]->(end:{LABEL_PAGE}) "
            f"WHERE start.title =~ $pattern OR start.url =~ $pattern "
            f"RETURN [n IN nodes(path) | n{{.id, .title, .url}}] AS page_list, "
            f"length(path) AS depth "
            f"ORDER BY depth LIMIT $limit",
            {"pattern": pattern, "limit": top_k},
        )

        return [
            {
                "source": "neo4j",
                "source_type": "business_flow",
                "id": f"flow_{i}",
                "text": " → ".join(
                    p.get("title", p.get("url", "")) for p in r.get("page_list", [])
                ),
                "pages": r.get("page_list", []),
                "depth": r.get("depth", 1),
                "score": 0.4,
            }
            for i, r in enumerate(results)
        ]

    def _neo4j_query_page_relations(
        self,
        query: str,
        keywords: List[str],
        target_url: str = "",
        top_k: int = 20,
    ) -> Dict[str, Any]:
        """查询页面及其关联关系（供 RelationAgent 使用）

        替代 RelationAgent._query_neo4j_pages() 的直接 Neo4j 调用。

        返回统一 ContextResult 格式：
          {
            "pages": [{page_id, title, url, score, source}],
            "relations": [{source, target, type, score, trigger, source_meta}],
            "source": "neo4j"
          }

        Args:
            query: 需求文本（用于模糊匹配页面标题/URL）
            keywords: 关键词列表（逐个查询）
            target_url: 目标URL（精确匹配）
            top_k: 每个查询的最大返回数
        """
        from app.db.neo4j_client import is_available, run_query

        pages: List[Dict[str, Any]] = []
        relations: List[Dict[str, Any]] = []

        if not is_available():
            log.warning("ContextRouter | Neo4j不可用，页面关系查询降级")
            return {"pages": [], "relations": [], "source": "neo4j", "degraded": True}

        try:
            # 查询1: 目标URL相关的页面及其导航关系
            if target_url:
                url_fragment = target_url.split("//")[-1][:50]
                cypher1 = """
                MATCH (p:Page)
                WHERE p.url CONTAINS $url OR p.title CONTAINS $url
                OPTIONAL MATCH (p)-[r:NAVIGATES_TO|CONTAINS|DEPENDS_ON]->(p2:Page)
                RETURN p, r, p2
                LIMIT $limit
                """
                results1 = run_query(cypher1, {"url": url_fragment, "limit": top_k})

                for record in results1:
                    p = record.get("p", {})
                    if p:
                        pages.append({
                            "page_id": p.get("url", str(p.get("id", ""))),
                            "title": p.get("title", ""),
                            "url": p.get("url", ""),
                            "score": 0.8,
                            "source": "neo4j",
                        })
                    p2 = record.get("p2")
                    r = record.get("r", {})
                    if p2 and r:
                        relations.append({
                            "source": p.get("url", ""),
                            "target": p2.get("url", ""),
                            "type": r.get("type", "navigation"),
                            "score": 0.7,
                            "trigger": r.get("trigger", ""),
                            "source_meta": "neo4j",
                        })

            # 查询2: 按关键词查询页面
            for kw in (keywords or [])[:3]:
                cypher2 = """
                MATCH (p:Page)
                WHERE p.title CONTAINS $kw OR p.url CONTAINS $kw
                RETURN p
                LIMIT $limit
                """
                results2 = run_query(cypher2, {"kw": kw, "limit": 5})

                for record in results2:
                    p = record.get("p", {})
                    if p:
                        pages.append({
                            "page_id": p.get("url", str(p.get("id", ""))),
                            "title": p.get("title", ""),
                            "url": p.get("url", ""),
                            "score": 0.6,
                            "source": "neo4j",
                        })

            # 去重
            seen = set()
            unique_pages = []
            for p in pages:
                key = p["page_id"]
                if key not in seen:
                    seen.add(key)
                    unique_pages.append(p)

            log.info(
                f"ContextRouter | Neo4j页面关系查询 | "
                f"pages={len(unique_pages)} | relations={len(relations)} | "
                f"query='{query[:30]}' | target_url={target_url[:30] or 'N/A'}"
            )

            return {
                "pages": unique_pages,
                "relations": relations,
                "source": "neo4j",
                "degraded": False,
            }

        except Exception as e:
            log.warning(f"ContextRouter | Neo4j页面关系查询失败: {e}")
            return {"pages": [], "relations": [], "source": "neo4j", "degraded": True,
                    "degradation_reason": str(e)}

    # ------------------------------------------------------------------
    # 页面关系专用接口（供 RelationAgent 调用）
    # ------------------------------------------------------------------

    def retrieve_page_relations(
        self,
        query: str,
        keywords: List[str] = None,
        target_url: str = "",
        top_k: int = 20,
    ) -> Dict[str, Any]:
        """检索页面关系（RelationAgent 专用接口）

        统一入口：Agent 通过此方法获取页面及其关联关系，
        禁止 Agent 直接操作 Neo4j。

        流程：
          1. Neo4j 查询页面 + 导航关系
          2. MySQL 查询历史 PageRelation 记录
          3. 合并去重

        返回 ContextResult 统一格式：
          {
            "pages": [{page_id, title, url, score, source}],
            "relations": [{source, target, type, score, trigger, source_meta}],
            "source": "neo4j" | "mysql" | "mixed",
            "degraded": bool,
            "degradation_reason": str
          }
        """
        all_pages: List[Dict[str, Any]] = []
        all_relations: List[Dict[str, Any]] = []
        sources_used: List[str] = []

        # 1. Neo4j 查询
        neo4j_result = self._neo4j_query_page_relations(
            query=query,
            keywords=keywords or [],
            target_url=target_url,
            top_k=top_k,
        )
        if neo4j_result.get("pages"):
            all_pages.extend(neo4j_result["pages"])
            all_relations.extend(neo4j_result.get("relations", []))
            sources_used.append("neo4j")

        # 2. MySQL 查询历史 PageRelation
        mysql_pages = self._mysql_query_page_relations(keywords or [])
        if mysql_pages:
            existing_ids = {p["page_id"] for p in all_pages}
            for p in mysql_pages:
                if p["page_id"] not in existing_ids:
                    all_pages.append(p)
                    existing_ids.add(p["page_id"])
            sources_used.append("mysql")

        source = "mixed" if len(sources_used) > 1 else (sources_used[0] if sources_used else "none")
        degraded = neo4j_result.get("degraded", False) and not mysql_pages
        degradation_reason = neo4j_result.get("degradation_reason", "")

        log.info(
            f"ContextRouter | retrieve_page_relations 完成 | "
            f"pages={len(all_pages)} | relations={len(all_relations)} | "
            f"source={source} | degraded={degraded}"
        )

        return {
            "pages": all_pages,
            "relations": all_relations,
            "source": source,
            "degraded": degraded,
            "degradation_reason": degradation_reason,
        }

    def _mysql_query_page_relations(self, keywords: List[str]) -> List[Dict[str, Any]]:
        """从 MySQL 查询历史 PageRelation 记录"""
        try:
            from app.db.database import SessionLocal
            from app.models.page_relation import PageRelation
            from sqlalchemy import distinct

            db = SessionLocal()
            try:
                pages: List[Dict[str, Any]] = []
                historical = db.query(
                    distinct(PageRelation.source_page),
                    PageRelation.source_page_title,
                ).limit(20).all()

                for url, title in historical:
                    if url and any(kw in (title or "") or kw in url for kw in keywords[:3]):
                        pages.append({
                            "page_id": url,
                            "title": title or url,
                            "url": url,
                            "score": 0.4,
                            "source": "mysql",
                        })

                return pages
            finally:
                db.close()

        except Exception as e:
            log.warning(f"ContextRouter | MySQL页面关系查询失败: {e}")
            return []

    # ------------------------------------------------------------------
    # 图谱推理接口（供 GraphAgent 调用）
    # ------------------------------------------------------------------

    def retrieve_graph_inference(
        self,
        requirement: str,
        keywords: List[str] = None,
        steps: List[str] = None,
    ) -> Dict[str, Any]:
        """图谱推理检索（GraphAgent 专用接口）

        替代 GraphAgent._search_pages() + _get_elements_for_pages() + _get_business_flow_for_pages()
        的直接 Neo4j 调用。

        流程：
          1. 从需求文本提取搜索关键词
          2. Neo4j 搜索匹配页面（title/url 正则匹配）
          3. 获取页面元素
          4. 获取业务流（元素链 + 关联用例 + 导航目标）

        返回：
          {
            "pages": [{id, title, url, page_type, source}],
            "elements": [{id, name, type, locator, xpath, css_selector, text, page_id, page_title, source}],
            "business_flow": [{page_id, page_title, page_url, elements, cases, navigation_targets, source}],
            "degraded": bool
          }
        """
        from app.db.neo4j_client import is_available, run_query, LABEL_PAGE, LABEL_ELEMENT, LABEL_CASE

        if not is_available():
            log.warning("ContextRouter | Neo4j不可用，图谱推理降级")
            return {"pages": [], "elements": [], "business_flow": [], "degraded": True}

        # 构建搜索关键词
        search_terms: set = set()
        if requirement:
            for word in requirement.replace("|", " ").replace(",", " ").replace("，", " ").replace("、", " ").split():
                word = word.strip()
                if len(word) >= 2:
                    search_terms.add(word)
        if keywords:
            search_terms.update(keywords)
        if steps:
            search_terms.update(steps)

        if not search_terms:
            return {"pages": [], "elements": [], "business_flow": [], "degraded": False}

        # 1. 搜索页面
        pages = self._neo4j_search_pages(search_terms, LABEL_PAGE, run_query)
        log.info(f"ContextRouter | 图谱推理 | 页面={len(pages)}")

        if not pages:
            return {"pages": [], "elements": [], "business_flow": [], "degraded": False}

        # 2. 获取元素
        elements = self._neo4j_get_elements_for_pages(pages, LABEL_PAGE, LABEL_ELEMENT, run_query)
        log.info(f"ContextRouter | 图谱推理 | 元素={len(elements)}")

        # 3. 获取业务流
        business_flow = self._neo4j_get_business_flow(pages, LABEL_PAGE, LABEL_ELEMENT, LABEL_CASE, run_query)
        log.info(f"ContextRouter | 图谱推理 | 业务流={len(business_flow)}")

        return {
            "pages": pages,
            "elements": elements,
            "business_flow": business_flow,
            "degraded": False,
        }

    @staticmethod
    def _neo4j_search_pages(search_terms: set, LABEL_PAGE: str, run_query) -> List[Dict]:
        """搜索与关键词相关的页面"""
        pages = []
        seen_ids = set()
        for term in search_terms:
            if not term or len(term) < 2:
                continue
            pattern = f"(?i).*{term.replace('*', '.*')}.*"
            try:
                results = run_query(
                    f"MATCH (p:{LABEL_PAGE}) "
                    f"WHERE p.title =~ $pattern OR p.url =~ $pattern "
                    f"RETURN p.id AS id, p.title AS title, p.url AS url, p.page_type AS page_type "
                    f"LIMIT 10",
                    {"pattern": pattern},
                )
                for r in results:
                    pid = r.get("id", "")
                    if pid and pid not in seen_ids:
                        seen_ids.add(pid)
                        pages.append({
                            "id": pid,
                            "title": r.get("title", ""),
                            "url": r.get("url", ""),
                            "page_type": r.get("page_type", "unknown"),
                            "source": "neo4j",
                        })
            except Exception:
                pass
        return pages[:20]

    @staticmethod
    def _neo4j_get_elements_for_pages(pages: List[Dict], LABEL_PAGE: str, LABEL_ELEMENT: str, run_query) -> List[Dict]:
        """获取指定页面的元素"""
        elements = []
        seen_ids = set()
        for page in pages[:10]:
            page_id = page.get("id", "")
            page_title = page.get("title", "")
            if not page_id:
                continue
            try:
                results = run_query(
                    f"MATCH (p:{LABEL_PAGE})-[:HAS_ELEMENT]->(e:{LABEL_ELEMENT}) "
                    f"WHERE p.id = $pid "
                    f"RETURN e.id AS id, e.name AS name, e.type AS type, "
                    f"e.locator AS locator, e.xpath AS xpath, "
                    f"e.css_selector AS css_selector, e.text AS text "
                    f"LIMIT 30",
                    {"pid": page_id},
                )
                for r in results:
                    eid = r.get("id", "")
                    if eid and eid not in seen_ids:
                        seen_ids.add(eid)
                        elements.append({
                            "id": eid, "name": r.get("name", ""), "type": r.get("type", ""),
                            "locator": r.get("locator", ""), "xpath": r.get("xpath", ""),
                            "css_selector": r.get("css_selector", ""), "text": r.get("text", ""),
                            "page_id": page_id, "page_title": page_title, "source": "neo4j",
                        })
            except Exception:
                pass
        return elements[:100]

    @staticmethod
    def _neo4j_get_business_flow(pages: List[Dict], LABEL_PAGE: str, LABEL_ELEMENT: str, LABEL_CASE: str, run_query) -> List[Dict]:
        """获取指定页面的业务流"""
        flows = []
        for page in pages[:10]:
            page_id = page.get("id", "")
            if not page_id:
                continue
            try:
                chain = run_query(
                    f"MATCH (p:{LABEL_PAGE})-[:HAS_ELEMENT]->(e:{LABEL_ELEMENT}) "
                    f"WHERE p.id = $pid "
                    f"OPTIONAL MATCH (e)-[r:NEXT]->(e2:{LABEL_ELEMENT}) "
                    f"RETURN e.id AS eid, e.name AS ename, e.type AS etype, "
                    f"e.locator AS elocator, e2.id AS next_id, e2.name AS next_name "
                    f"ORDER BY r.order",
                    {"pid": page_id},
                )
                flow_elements = [{
                    "id": c.get("eid", ""), "name": c.get("ename", ""),
                    "type": c.get("etype", ""), "locator": c.get("elocator", ""),
                    "next_id": c.get("next_id"), "next_name": c.get("next_name"),
                } for c in chain]

                cases = run_query(
                    f"MATCH (c:{LABEL_CASE})-[:TEST_ON]->(p:{LABEL_PAGE}) "
                    f"WHERE p.id = $pid RETURN c.id AS cid, c.name AS cname",
                    {"pid": page_id},
                )

                nav_targets = run_query(
                    f"MATCH (p:{LABEL_PAGE})-[:HAS_ELEMENT]->(e:{LABEL_ELEMENT})"
                    f"-[:TRIGGER]->(t:{LABEL_PAGE}) "
                    f"WHERE p.id = $pid "
                    f"RETURN e.id AS eid, e.name AS ename, "
                    f"t.id AS tid, t.title AS ttitle, t.url AS turl",
                    {"pid": page_id},
                )

                flows.append({
                    "page_id": page_id,
                    "page_title": page.get("title", ""),
                    "page_url": page.get("url", ""),
                    "elements": flow_elements,
                    "cases": [{"id": r["cid"], "name": r["cname"]} for r in cases],
                    "navigation_targets": [{
                        "trigger_element": r.get("ename", ""),
                        "target_page_id": r.get("tid", ""),
                        "target_page_title": r.get("ttitle", ""),
                        "target_page_url": r.get("turl", ""),
                    } for r in nav_targets],
                    "source": "neo4j",
                })
            except Exception:
                pass
        return flows

    # ------------------------------------------------------------------
    # R2R 适配器（仅用于健康检查，不参与运行时查询）
    # R2R 的职责是知识入库（解析→分块→向量化→存入Milvus）
    # 运行时查询走 Milvus(rag_knowledge_vector)，不走 R2R
    # ------------------------------------------------------------------

    def _query_r2r(
        self,
        query: str,
        context_type: ContextType,
        top_k: int,
        filters: Dict,
        project_id: str,
    ) -> List[Dict[str, Any]]:
        """R2R 不参与运行时查询

        R2R 只在 KnowledgePipeline 入库时使用：
          文档 → R2R(解析→分块→Embedding) → Milvus(rag_knowledge_vector)

        运行时查询 DOCUMENT 类型走 Milvus + MySQL，不走 R2R。
        此方法保留是为了向后兼容，但不应该被路由表调用。
        """
        log.warning(
            "ContextRouter | _query_r2r 被调用，但 R2R 不应参与运行时查询 | "
            "请检查路由表配置"
        )
        return []

    # ------------------------------------------------------------------
    # MySQL 适配器（新增 ContextType 支持）
    # ------------------------------------------------------------------

    def _mysql_query_requirement_tasks(
        self, db, query: str, top_k: int, filters: Dict
    ) -> List[Dict[str, Any]]:
        """查询需求任务（MySQL）"""
        from app.models.requirement_task import RequirementTask
        from sqlalchemy import or_

        q = db.query(RequirementTask)

        # 应用 filters
        if filters:
            for key, val in filters.items():
                col = getattr(RequirementTask, key, None)
                if col is not None and val is not None:
                    q = q.filter(col == val)

        # 关键词搜索
        keywords = [w for w in query.split() if len(w) >= 2] if query else []
        if keywords:
            conditions = []
            for kw in keywords:
                conditions.append(RequirementTask.requirement.contains(kw))
                conditions.append(RequirementTask.additional_info.contains(kw))
            q = q.filter(or_(*conditions))

        rows = q.order_by(RequirementTask.id.desc()).limit(top_k).all()
        return [
            {
                "source": "mysql",
                "source_type": "requirement_task",
                "id": str(r.id),
                "text": f"需求: {r.requirement[:100] if r.requirement else ''}",
                "requirement": r.requirement,
                "status": r.status,
                "task_id": r.task_id,
                "additional_info": r.additional_info,
                "script_format": r.script_format,
                "image_paths": r.image_paths,
                "generated_case": r.generated_case,
                "user_id": r.user_id,
                "created_at": str(r.created_at) if r.created_at else "",
                "score": 0.5,
            }
            for r in rows
        ]

    def _mysql_query_tasks(
        self, db, query: str, top_k: int, filters: Dict
    ) -> List[Dict[str, Any]]:
        """查询测试任务（MySQL）"""
        from app.models.task import Task, TaskStatus
        from sqlalchemy import or_

        q = db.query(Task)

        # 应用 filters
        if filters:
            for key, val in filters.items():
                if key == "id":
                    q = q.filter(Task.id == val)
                elif key == "task_id":
                    q = q.filter(Task.id == val)
                elif key == "status":
                    q = q.filter(Task.status == val)
                elif key == "user_id":
                    q = q.filter(Task.user_id == val)
                else:
                    col = getattr(Task, key, None)
                    if col is not None and val is not None:
                        q = q.filter(col == val)

        # 关键词搜索
        keywords = [w for w in query.split() if len(w) >= 2] if query else []
        if keywords:
            conditions = []
            for kw in keywords:
                conditions.append(Task.task_name.contains(kw))
                conditions.append(Task.page_url.contains(kw))
            q = q.filter(or_(*conditions))

        rows = q.order_by(Task.id.desc()).limit(top_k).all()
        return [
            {
                "source": "mysql",
                "source_type": "task",
                "id": str(r.id),
                "text": f"任务: {r.task_name} (状态: {r.status})",
                "task_name": r.task_name,
                "status": r.status,
                "input_mode": r.input_mode,
                "page_url": r.page_url or "",
                "user_id": r.user_id,
                "created_at": str(r.created_at) if r.created_at else "",
                "score": 0.5,
            }
            for r in rows
        ]

    def _mysql_query_schedule_tasks(
        self, db, query: str, top_k: int, filters: Dict
    ) -> List[Dict[str, Any]]:
        """查询定时任务（MySQL）"""
        from app.models.schedule_task import ScheduleTask, ScheduleStatus

        q = db.query(ScheduleTask)

        # 应用 filters
        if filters:
            for key, val in filters.items():
                if key == "status":
                    q = q.filter(ScheduleTask.status == val)
                else:
                    col = getattr(ScheduleTask, key, None)
                    if col is not None and val is not None:
                        q = q.filter(col == val)

        rows = q.order_by(ScheduleTask.id.desc()).limit(top_k).all()
        return [
            {
                "source": "mysql",
                "source_type": "schedule_task",
                "id": str(r.id),
                "text": f"定时任务: {r.name} (状态: {r.status})",
                "name": r.name,
                "status": r.status,
                "cron_expression": r.cron_expression,
                "task_type": r.task_type,
                "user_id": r.user_id,
                "created_at": str(r.created_at) if r.created_at else "",
                "score": 0.5,
            }
            for r in rows
        ]

    def _mysql_query_feedbacks(
        self, db, query: str, top_k: int, filters: Dict
    ) -> List[Dict[str, Any]]:
        """查询用户反馈（MySQL）"""
        from app.models.feedback import Feedback

        q = db.query(Feedback)

        if filters:
            for key, val in filters.items():
                col = getattr(Feedback, key, None)
                if col is not None and val is not None:
                    q = q.filter(col == val)

        rows = q.order_by(Feedback.id.desc()).limit(top_k).all()
        return [
            {
                "source": "mysql",
                "source_type": "feedback",
                "id": str(r.id),
                "text": f"反馈: score={r.score}, comment={r.comment[:80] if r.comment else ''}",
                "score": r.score,
                "comment": r.comment,
                "accepted": r.accepted,
                "user_id": r.user_id,
                "created_at": str(r.created_at) if r.created_at else "",
                "score": 0.5,
            }
            for r in rows
        ]

    def _mysql_query_session_events(
        self, db, query: str, top_k: int, filters: Dict
    ) -> List[Dict[str, Any]]:
        """查询会话事件（MySQL）"""
        from app.models.session_event import SessionEvent

        q = db.query(SessionEvent)

        if filters:
            for key, val in filters.items():
                col = getattr(SessionEvent, key, None)
                if col is not None and val is not None:
                    q = q.filter(col == val)

        rows = q.order_by(SessionEvent.id.desc()).limit(top_k).all()
        return [
            {
                "source": "mysql",
                "source_type": "session_event",
                "id": str(r.id),
                "text": f"事件: {r.event_type} - {r.message[:80] if r.message else ''}",
                "session_id": r.session_id,
                "event_type": r.event_type,
                "message": r.message,
                "agent_name": r.agent_name,
                "status": r.status,
                "created_at": str(r.created_at) if r.created_at else "",
                "score": 0.5,
            }
            for r in rows
        ]

    def _mysql_query_flow_results(
        self, db, query: str, top_k: int, filters: Dict
    ) -> List[Dict[str, Any]]:
        """查询流程结果（MySQL）"""
        from app.models.flow_result import FlowResult
        from sqlalchemy import or_

        q = db.query(FlowResult)

        if filters:
            for key, val in filters.items():
                col = getattr(FlowResult, key, None)
                if col is not None and val is not None:
                    q = q.filter(col == val)

        keywords = [w for w in query.split() if len(w) >= 2] if query else []
        if keywords:
            conditions = []
            for kw in keywords:
                conditions.append(FlowResult.agent_name.contains(kw))
                conditions.append(FlowResult.step_name.contains(kw))
            q = q.filter(or_(*conditions))

        rows = q.order_by(FlowResult.id.desc()).limit(top_k).all()
        return [
            {
                "source": "mysql",
                "source_type": "flow_result",
                "id": str(r.id),
                "text": f"流程结果: {r.agent_name} / {r.step_name}",
                "agent_name": r.agent_name,
                "step_name": r.step_name,
                "status": r.status,
                "result_data": r.result_data,
                "created_at": str(r.created_at) if r.created_at else "",
                "score": 0.5,
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # 结果合并
    # ------------------------------------------------------------------

    def _merge_results(
        self,
        results_by_source: Dict[str, List[Dict[str, Any]]],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """合并多数据源结果，按 score 降序排列"""
        all_results: List[Dict[str, Any]] = []

        for source, items in results_by_source.items():
            for item in items:
                item.setdefault("source", source)
                all_results.append(item)

        # 按 score 降序
        all_results.sort(key=lambda x: x.get("score", 0), reverse=True)

        # 截取 top_k
        return all_results[:top_k]

    # ------------------------------------------------------------------
    # 健康检查
    # ------------------------------------------------------------------

    def health_check(self) -> Dict[str, Any]:
        """检查各数据源可用性"""
        health: Dict[str, Any] = {}

        # MySQL
        try:
            from app.db.database import SessionLocal
            from sqlalchemy import text as sql_text
            db = SessionLocal()
            db.execute(sql_text("SELECT 1"))
            db.close()
            health["mysql"] = {"status": "healthy"}
        except Exception as e:
            health["mysql"] = {"status": "unavailable", "error": str(e)}

        # Milvus
        try:
            from app.db.milvus_client import get_milvus_client
            client = get_milvus_client(allow_fail=True)
            if client:
                collections = client.list_collections()
                health["milvus"] = {
                    "status": "healthy",
                    "collections": collections,
                }
            else:
                health["milvus"] = {"status": "unavailable"}
        except Exception as e:
            health["milvus"] = {"status": "unavailable", "error": str(e)}

        # Neo4j
        try:
            from app.db.neo4j_client import is_available
            health["neo4j"] = {
                "status": "healthy" if is_available() else "unavailable",
            }
        except Exception as e:
            health["neo4j"] = {"status": "unavailable", "error": str(e)}

        # R2R
        try:
            from app.services.knowledge.client import get_knowledge_client
            client = get_knowledge_client()
            result = client.health()
            health["r2r"] = {
                "status": result.get("status", "unknown"),
                "base_url": result.get("base_url", ""),
            }
        except Exception as e:
            health["r2r"] = {"status": "unavailable", "error": str(e)}

        health["request_count"] = self._request_count
        return health


# ------------------------------------------------------------------
# 单例
# ------------------------------------------------------------------

_context_router: Optional[ContextRouter] = None


def get_context_router() -> ContextRouter:
    """获取 ContextRouter 单例"""
    global _context_router
    if _context_router is None:
        _context_router = ContextRouter()
    return _context_router
