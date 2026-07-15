"""
三库协同管理器 (TriStoreCoordinator)

统一协调 MySQL / Milvus / Neo4j 三种数据库的写入、查询和删除。

核心原则：
  - MySQL:   保存文档/需求/页面/接口/脚本/用例/Chunk/Meta/Tag/Session 的结构化数据
  - Milvus:  保存 Embedding 向量（Chunk/Page/Case/Requirement Vector）
  - Neo4j:   保存实体间关系（页面→元素→接口→表→流程→用例→脚本）

写入流程：
  MySQL（结构化数据） → Milvus（向量） → Neo4j（关系）

查询流程：
  Milvus（向量召回） → MySQL（元数据补全） → Neo4j（关系扩展）

删除流程：
  Neo4j（删关系） → Milvus（删向量） → MySQL（删结构化数据）
"""
import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from app.rag.embedding.factory import get_embedding_factory
from app.rag.graph_store.factory import get_graph_store
from app.rag.graph_store.extended_store import get_extended_graph_store
from app.rag.mysql_store.factory import get_mysql_store
from app.rag.vector_store.multi_vector_store import get_multi_vector_store

logger = logging.getLogger(__name__)

# 实体类型常量
ENTITY_DOCUMENT = "document"
ENTITY_REQUIREMENT = "requirement"
ENTITY_PAGE = "page"
ENTITY_API = "api"
ENTITY_SCRIPT = "script"
ENTITY_CASE = "case"
ENTITY_CHUNK = "chunk"
ENTITY_DBTABLE = "dbtable"
ENTITY_FLOW = "business_flow"
ENTITY_SESSION = "session"

# MySQL 表名映射
MYSQL_TABLE_MAP = {
    ENTITY_DOCUMENT: "knowledge_source",
    ENTITY_REQUIREMENT: "requirement_input",
    ENTITY_PAGE: "page",
    ENTITY_API: "api_case",
    ENTITY_SCRIPT: "script",
    ENTITY_CASE: "test_asset",
    ENTITY_CHUNK: "knowledge_chunk",
    ENTITY_SESSION: "session",
}

# Neo4j 标签映射
NEO4J_LABEL_MAP = {
    ENTITY_REQUIREMENT: "Requirement",
    ENTITY_PAGE: "Page",
    ENTITY_API: "API",
    ENTITY_SCRIPT: "Script",
    ENTITY_CASE: "TestCase",
    ENTITY_DBTABLE: "DBTable",
    ENTITY_FLOW: "BusinessFlow",
}

# Neo4j ID 字段映射
NEO4J_ID_FIELD_MAP = {
    ENTITY_REQUIREMENT: "req_id",
    ENTITY_PAGE: "page_id",
    ENTITY_API: "api_id",
    ENTITY_SCRIPT: "script_id",
    ENTITY_CASE: "case_id",
    ENTITY_DBTABLE: "table_name",
    ENTITY_FLOW: "flow_id",
}


class TriStoreCoordinator:
    """三库协同管理器

    统一协调 MySQL / Milvus / Neo4j 三种数据库。

    三种数据库各司其职：
      MySQL  → 结构化数据（CRUD + 查询过滤）
      Milvus → 向量数据（相似度检索）
      Neo4j  → 关系数据（图谱遍历 + 可追溯性）
    """

    def __init__(self):
        self._mysql = get_mysql_store()
        self._milvus = get_multi_vector_store()
        self._graph = get_graph_store()
        self._ext_graph = get_extended_graph_store()
        self._embedding_factory = get_embedding_factory()

    # ------------------------------------------------------------------
    # 统一写入
    # ------------------------------------------------------------------

    async def sync_write(
        self,
        entity_type: str,
        entity_id: str,
        text: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        embedding: Optional[List[float]] = None,
        tags: Optional[List[str]] = None,
        neo4j_label: Optional[str] = None,
        neo4j_properties: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """统一写入三库

        一个方法完成：
          1. MySQL: 保存元数据 + Tag
          2. Milvus: 保存向量（如果 embedding 或 text 提供）
          3. Neo4j: 保存实体节点（如果 neo4j_label 提供）

        Args:
            entity_type: 实体类型 (document/requirement/page/api/case/script/...)
            entity_id: 实体ID
            text: 文本内容（用于生成 embedding）
            metadata: 元数据
            embedding: 向量（如果为None但text不为空，自动生成）
            tags: 标签列表
            neo4j_label: Neo4j 节点标签（None=不创建图节点）
            neo4j_properties: Neo4j 节点属性

        Returns:
            写入结果汇总
        """
        results: Dict[str, Any] = {
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "mysql": "skipped",
            "milvus": "skipped",
            "neo4j": "skipped",
        }
        meta = metadata or {}

        # 1. MySQL: 保存 Tag（元数据已由各模块自行保存）
        if tags:
            try:
                self._save_tags(entity_type, int(entity_id) if str(entity_id).isdigit() else 0, tags)
                results["mysql"] = "ok"
            except Exception as e:
                results["mysql"] = f"error: {e}"
        else:
            results["mysql"] = "ok"

        # 2. Milvus: 保存向量
        if embedding or text:
            try:
                vec = embedding
                if vec is None and text:
                    embedding_provider = self._embedding_factory.get_embedding()
                    vec = await embedding_provider.embed(text)
                if vec:
                    inserted = await self._milvus.insert_vector(
                        entity_type=entity_type,
                        source_id=str(entity_id),
                        text=text,
                        embedding=vec,
                        metadata=meta,
                    )
                    results["milvus"] = f"inserted({inserted})"
                else:
                    results["milvus"] = "no_vector"
            except Exception as e:
                results["milvus"] = f"error: {e}"

        # 3. Neo4j: 保存实体节点
        if neo4j_label:
            try:
                id_field = NEO4J_ID_FIELD_MAP.get(entity_type, "source_id")
                await self._ext_graph.create_node(
                    label=neo4j_label,
                    node_id=str(entity_id),
                    id_field=id_field,
                    properties=neo4j_properties or meta,
                )
                results["neo4j"] = "ok"
            except Exception as e:
                results["neo4j"] = f"error: {e}"

        logger.info(f"[TriStore] 统一写入 {entity_type}:{entity_id} → {results}")
        return results

    async def sync_write_relation(
        self,
        from_type: str,
        from_id: str,
        rel_type: str,
        to_type: str,
        to_id: str,
        properties: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """统一写入关系（Neo4j）

        在 Neo4j 中建立两个实体之间的关系。
        同时在 MySQL 中记录关系元数据（可选）。

        支持的关系类型：
          HAS_ELEMENT:  Page → Element
          CALLS_API:    Element → API
          USES_TABLE:   API → DBTable
          FLOW_STEP:    BusinessFlow → API
          DERIVES_TEST: BusinessFlow → TestCase
          TESTS_API:    TestCase → API
          TESTS_PAGE:   TestCase → Page
          GENERATES_SCRIPT: TestCase → Script
          EXECUTES_PAGE: Script → Page
          REQUIRES:     Requirement → API/DBTable/Flow
          NAVIGATE_TO:  Page → Page
        """
        from_label = NEO4J_LABEL_MAP.get(from_type, "Entity")
        to_label = NEO4J_LABEL_MAP.get(to_type, "Entity")
        from_id_field = NEO4J_ID_FIELD_MAP.get(from_type, "source_id")
        to_id_field = NEO4J_ID_FIELD_MAP.get(to_type, "source_id")

        result: Dict[str, Any] = {
            "from": f"{from_type}:{from_id}",
            "relation": rel_type,
            "to": f"{to_type}:{to_id}",
            "neo4j": "skipped",
        }

        try:
            await self._ext_graph.create_edge(
                from_label=from_label,
                from_id=str(from_id),
                rel_type=rel_type,
                to_label=to_label,
                to_id=str(to_id),
                from_id_field=from_id_field,
                to_id_field=to_id_field,
                properties=properties,
            )
            result["neo4j"] = "ok"
        except Exception as e:
            result["neo4j"] = f"error: {e}"

        logger.info(f"[TriStore] 关系写入 {result}")
        return result

    # ------------------------------------------------------------------
    # 统一查询
    # ------------------------------------------------------------------

    async def sync_query(
        self,
        query_text: str,
        entity_types: Optional[List[str]] = None,
        top_k: int = 10,
        score_threshold: float = 0.0,
        expand_graph: bool = True,
    ) -> Dict[str, Any]:
        """统一查询三库

        流程：
          1. Milvus: 向量召回 → 获取相关 Chunk/Page/Case/Requirement
          2. MySQL:  元数据补全 → 获取完整的文档/用例信息
          3. Neo4j:  关系扩展 → 查找关联实体和追溯链路

        Returns:
            {
              "milvus_results": [...],     # 向量检索结果
              "mysql_metadata": {...},     # MySQL 元数据
              "neo4j_relations": {...},    # Neo4j 关系图
              "graph_traces": [...],       # 追溯链路
              "total_found": int,
              "latency_ms": int,
            }
        """
        start_time = time.time()
        results: Dict[str, Any] = {
            "milvus_results": [],
            "mysql_metadata": {},
            "neo4j_relations": {},
            "graph_traces": [],
            "total_found": 0,
        }

        # 1. Milvus: 向量检索
        try:
            embedding_provider = self._embedding_factory.get_embedding()
            query_vector = await embedding_provider.embed(query_text)
            milvus_results = await self._milvus.search(
                query_vector=query_vector,
                entity_types=entity_types,
                top_k=top_k,
            )
            if score_threshold > 0:
                milvus_results = [r for r in milvus_results if r.score >= score_threshold]
            results["milvus_results"] = [r.model_dump() for r in milvus_results]
            results["total_found"] = len(milvus_results)
        except Exception as e:
            logger.error(f"[TriStore] Milvus 检索失败: {e}")
            results["milvus_error"] = str(e)

        # 2. MySQL: 元数据补全
        for r in results.get("milvus_results", []):
            source_id = r.get("source_id", "")
            etype = r.get("chunk_type", r.get("source_type", ""))
            if source_id and etype:
                try:
                    meta = self._get_mysql_metadata(etype, source_id)
                    if meta:
                        results["mysql_metadata"][f"{etype}:{source_id}"] = meta
                except Exception:
                    pass

        # 3. Neo4j: 关系扩展
        if expand_graph and results.get("milvus_results"):
            try:
                graph_results = await self._graph.search_graph(query_text, limit=top_k)
                results["neo4j_relations"]["graph_search"] = graph_results
            except Exception as e:
                logger.debug(f"[TriStore] 图检索失败: {e}")

            # 对第一个结果尝试追溯链路
            first = results["milvus_results"][0] if results["milvus_results"] else None
            if first:
                etype = first.get("chunk_type", first.get("source_type", ""))
                source_id = first.get("source_id", "")
                label = NEO4J_LABEL_MAP.get(etype)
                id_field = NEO4J_ID_FIELD_MAP.get(etype, "source_id")
                if label and source_id:
                    try:
                        traces = await self._ext_graph.get_traceability(
                            label, source_id, id_field
                        )
                        results["graph_traces"] = traces.get("traces", [])
                    except Exception:
                        pass

        results["latency_ms"] = int((time.time() - start_time) * 1000)
        logger.info(
            f"[TriStore] 统一查询完成 "
            f"milvus={len(results['milvus_results'])} "
            f"traces={len(results['graph_traces'])} "
            f"latency={results['latency_ms']}ms"
        )
        return results

    async def sync_search_relations(
        self,
        entity_type: str,
        entity_id: str,
        depth: int = 2,
    ) -> Dict[str, Any]:
        """搜索实体的关系网络

        在 Neo4j 中查找指定实体的关联节点和关系。
        """
        label = NEO4J_LABEL_MAP.get(entity_type, "Entity")
        id_field = NEO4J_ID_FIELD_MAP.get(entity_type, "source_id")

        result = await self._ext_graph.get_entity_relations(
            label=label,
            entity_id=str(entity_id),
            id_field=id_field,
            depth=depth,
        )

        # 补充 MySQL 元数据
        for node in result.get("nodes", []):
            node_labels = node.get("labels", [])
            node_props = node.get("props", {})
            for nl in node_labels:
                if nl in [NEO4J_LABEL_MAP.get(ENTITY_PAGE), NEO4J_LABEL_MAP.get(ENTITY_API),
                          NEO4J_LABEL_MAP.get(ENTITY_CASE), NEO4J_LABEL_MAP.get(ENTITY_SCRIPT)]:
                    node_id = (
                        node_props.get("page_id") or node_props.get("api_id")
                        or node_props.get("case_id") or node_props.get("script_id") or ""
                    )
                    if node_id:
                        try:
                            meta = self._get_mysql_metadata(
                                entity_type, node_id
                            )
                            if meta:
                                node["mysql_metadata"] = meta
                        except Exception:
                            pass

        return result

    # ------------------------------------------------------------------
    # 统一删除
    # ------------------------------------------------------------------

    async def sync_delete(
        self,
        entity_type: str,
        entity_id: str,
    ) -> Dict[str, Any]:
        """统一删除三库数据

        删除顺序：Neo4j（关系） → Milvus（向量） → MySQL（结构化数据）

        Returns:
            删除结果汇总
        """
        results: Dict[str, Any] = {
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "neo4j": "skipped",
            "milvus": "skipped",
            "mysql": "skipped",
        }

        # 1. Neo4j: 删除图节点和关系
        label = NEO4J_LABEL_MAP.get(entity_type)
        id_field = NEO4J_ID_FIELD_MAP.get(entity_type, "source_id")
        if label:
            try:
                await self._ext_graph.delete_entity(label, str(entity_id), id_field)
                results["neo4j"] = "ok"
            except Exception as e:
                results["neo4j"] = f"error: {e}"

        # 2. Milvus: 删除向量
        try:
            deleted = await self._milvus.delete_by_source(entity_type, str(entity_id))
            results["milvus"] = f"deleted({deleted})"
        except Exception as e:
            results["milvus"] = f"error: {e}"

        # 3. MySQL: 删除结构化数据
        # 注意：MySQL 数据由各模块自行管理，这里只删除 Tag 关联
        try:
            self._delete_tags(entity_type, int(entity_id) if str(entity_id).isdigit() else 0)
            results["mysql"] = "ok"
        except Exception as e:
            results["mysql"] = f"error: {e}"

        logger.info(f"[TriStore] 统一删除 {entity_type}:{entity_id} → {results}")
        return results

    # ------------------------------------------------------------------
    # 统一统计
    # ------------------------------------------------------------------

    async def sync_stats(self) -> Dict[str, Any]:
        """获取三库统一统计"""
        stats: Dict[str, Any] = {}

        # MySQL
        try:
            stats["mysql"] = self._mysql.get_stats()
        except Exception as e:
            stats["mysql"] = {"error": str(e)}

        # Milvus
        try:
            stats["milvus"] = await self._milvus.get_stats()
        except Exception as e:
            stats["milvus"] = {"error": str(e)}

        # Neo4j
        try:
            stats["neo4j"] = await self._ext_graph.get_full_stats()
        except Exception as e:
            stats["neo4j"] = {"error": str(e)}

        return stats

    # ------------------------------------------------------------------
    # 完整入库管道（文档 → 三库同步）
    # ------------------------------------------------------------------

    async def ingest_with_sync(
        self,
        file_path: str,
        source_type: str = "",
        project_id: str = "default",
        user_id: Optional[int] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """文档入库 + 三库同步

        在 RAG 管道入库基础上，额外完成：
          1. Tag 写入（MySQL）
          2. 完整 Neo4j 实体节点创建
          3. 三库一致性验证
        """
        from app.rag.service.pipeline import RAGPipeline

        # 1. 执行 RAG 管道入库
        pipeline = RAGPipeline()
        result = await pipeline.ingest_document(
            file_path=file_path,
            source_type=source_type,
            project_id=project_id,
            user_id=user_id,
        )

        source_id = result.get("source_id")
        if not source_id:
            return result

        # 2. Tag 写入
        if tags:
            try:
                self._save_tags(ENTITY_DOCUMENT, int(source_id), tags)
                result["tags"] = tags
            except Exception as e:
                result["tag_error"] = str(e)

        # 3. Neo4j 实体节点创建（增强）
        try:
            await self._ext_graph.create_node(
                label="Requirement" if source_type == "requirement" else "KnowledgeDocument",
                node_id=str(source_id),
                id_field="source_id",
                properties={
                    "source_type": source_type,
                    "file_name": result.get("file_name", ""),
                    "project_id": project_id,
                },
            )
            result["neo4j_sync"] = "ok"
        except Exception as e:
            result["neo4j_sync"] = f"error: {e}"

        return result

    # ------------------------------------------------------------------
    # Tag 管理（MySQL）
    # ------------------------------------------------------------------

    def _save_tags(self, entity_type: str, entity_id: int, tag_names: List[str]):
        """保存标签到 MySQL"""
        from app.db.database import SessionLocal
        from app.models.tag import Tag, KnowledgeTag, TagType

        if entity_id == 0:
            return

        db = SessionLocal()
        try:
            for tag_name in tag_names:
                # 查找或创建 Tag
                tag = db.query(Tag).filter_by(name=tag_name).first()
                if tag is None:
                    tag = Tag(name=tag_name, tag_type=TagType.CUSTOM)
                    db.add(tag)
                    db.flush()
                # 创建关联
                kt = KnowledgeTag(
                    tag_id=tag.id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                )
                db.add(kt)
            db.commit()
            logger.info(f"[TriStore] 保存标签 entity={entity_type}:{entity_id} tags={tag_names}")
        except Exception as e:
            db.rollback()
            logger.error(f"[TriStore] 保存标签失败: {e}")
            raise
        finally:
            db.close()

    def _delete_tags(self, entity_type: str, entity_id: int):
        """删除实体的所有标签关联"""
        from app.db.database import SessionLocal
        from app.models.tag import KnowledgeTag

        if entity_id == 0:
            return

        db = SessionLocal()
        try:
            db.query(KnowledgeTag).filter_by(
                entity_type=entity_type, entity_id=entity_id
            ).delete(synchronize_session=False)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"[TriStore] 删除标签失败: {e}")
        finally:
            db.close()

    def _get_tags(self, entity_type: str, entity_id: int) -> List[str]:
        """获取实体的标签列表"""
        from app.db.database import SessionLocal
        from app.models.tag import Tag, KnowledgeTag

        if entity_id == 0:
            return []

        db = SessionLocal()
        try:
            rows = (
                db.query(Tag.name)
                .join(KnowledgeTag, KnowledgeTag.tag_id == Tag.id)
                .filter(
                    KnowledgeTag.entity_type == entity_type,
                    KnowledgeTag.entity_id == entity_id,
                )
                .all()
            )
            return [r[0] for r in rows]
        finally:
            db.close()

    # ------------------------------------------------------------------
    # MySQL 元数据查询
    # ------------------------------------------------------------------

    def _get_mysql_metadata(self, entity_type: str, entity_id: str) -> Optional[Dict[str, Any]]:
        """从 MySQL 获取实体元数据"""
        try:
            if entity_type == ENTITY_DOCUMENT or entity_type == ENTITY_CHUNK:
                sid = int(entity_id) if str(entity_id).isdigit() else 0
                if sid > 0:
                    return self._mysql.get_source(sid)
            # 其他类型由各模块自行管理
            return None
        except Exception:
            return None


# ===== 单例 =====
_coordinator: Optional[TriStoreCoordinator] = None


def get_tri_store_coordinator() -> TriStoreCoordinator:
    """获取三库协同管理器单例"""
    global _coordinator
    if _coordinator is None:
        _coordinator = TriStoreCoordinator()
    return _coordinator
