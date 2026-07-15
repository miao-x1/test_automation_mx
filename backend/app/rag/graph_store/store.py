"""
Neo4j 知识图谱存储

在知识图谱中建立文档 → 分片 → 实体 的结构化关系，
支持图检索与图扩展，增强 RAG 的关联发现能力。

节点标签：
  - KnowledgeDocument: 知识文档节点
  - KnowledgeChunk: 知识分片节点
  - Entity: 实体节点（接口名/关键词/模块名等）

关系类型：
  - HAS_CHUNK: KnowledgeDocument -> KnowledgeChunk
  - MENTIONS: KnowledgeChunk -> Entity
  - RELATED_TO: Entity -> Entity
  - DERIVED_FROM: KnowledgeChunk -> KnowledgeChunk

Neo4j 不可用时所有方法优雅降级。
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.db.neo4j_client import is_available, run_query, run_write
from app.rag.models import Chunk

logger = logging.getLogger(__name__)

# ===== 新增节点标签 =====
LABEL_DOC = "KnowledgeDocument"
LABEL_CHUNK = "KnowledgeChunk"
LABEL_ENTITY = "Entity"

# ===== 新增关系类型 =====
REL_HAS_CHUNK = "HAS_CHUNK"
REL_MENTIONS = "MENTIONS"
REL_RELATED_TO = "RELATED_TO"
REL_DERIVED_FROM = "DERIVED_FROM"


class Neo4jGraphStore:
    """Neo4j 知识图谱存储"""

    def __init__(self):
        self._initialized = False

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    def ensure_constraints(self):
        """创建唯一性约束（幂等）"""
        if not is_available():
            return
        constraints = [
            f"CREATE CONSTRAINT IF NOT EXISTS FOR (d:{LABEL_DOC}) REQUIRE d.source_id IS UNIQUE",
            f"CREATE CONSTRAINT IF NOT EXISTS FOR (c:{LABEL_CHUNK}) REQUIRE c.chunk_id IS UNIQUE",
            f"CREATE CONSTRAINT IF NOT EXISTS FOR (e:{LABEL_ENTITY}) REQUIRE e.name IS UNIQUE",
        ]
        for cql in constraints:
            try:
                run_query(cql)
            except Exception as e:
                logger.debug(f"[GraphStore] 约束创建提示: {e}")
        self._initialized = True
        logger.info("[GraphStore] Neo4j 约束已就绪")

    # ------------------------------------------------------------------
    # 节点创建
    # ------------------------------------------------------------------

    async def create_document_node(
        self,
        source_id: str,
        source_type: str,
        file_name: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """创建知识文档节点"""
        if not is_available():
            logger.debug("[GraphStore] Neo4j 不可用，跳过文档节点创建")
            return
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        cql = f"""
        MERGE (d:{LABEL_DOC} {{source_id: $source_id}})
        SET d.source_type = $source_type,
            d.file_name = $file_name,
            d.metadata = $metadata,
            d.updated_at = timestamp()
        """
        try:
            run_write(cql, {
                "source_id": str(source_id),
                "source_type": source_type,
                "file_name": file_name,
                "metadata": meta_json,
            })
            logger.debug(f"[GraphStore] 文档节点已创建 source_id={source_id}")
        except Exception as e:
            logger.warning(f"[GraphStore] 创建文档节点失败: {e}")

    async def create_chunk_node(
        self,
        chunk_id: str,
        source_id: str,
        text: str,
        chunk_type: str = "content",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """创建知识分片节点，并关联到文档节点"""
        if not is_available():
            return
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        # 截断文本避免超长
        truncated_text = (text or "")[:4000]
        cql = f"""
        MERGE (c:{LABEL_CHUNK} {{chunk_id: $chunk_id}})
        SET c.source_id = $source_id,
            c.text = $text,
            c.chunk_type = $chunk_type,
            c.metadata = $metadata,
            c.updated_at = timestamp()
        WITH c
        MATCH (d:{LABEL_DOC} {{source_id: $source_id}})
        MERGE (d)-[:{REL_HAS_CHUNK}]->(c)
        """
        try:
            run_write(cql, {
                "chunk_id": str(chunk_id),
                "source_id": str(source_id),
                "text": truncated_text,
                "chunk_type": chunk_type,
                "metadata": meta_json,
            })
            logger.debug(f"[GraphStore] 分片节点已创建 chunk_id={chunk_id}")
        except Exception as e:
            logger.warning(f"[GraphStore] 创建分片节点失败: {e}")

    async def create_relation(
        self,
        from_label: str,
        from_id: str,
        rel_type: str,
        to_label: str,
        to_id: str,
        id_field: str = "source_id",
        properties: Optional[Dict[str, Any]] = None,
    ):
        """创建通用关系"""
        if not is_available():
            return
        props = ""
        params: Dict[str, Any] = {
            "from_id": str(from_id),
            "to_id": str(to_id),
        }
        if properties:
            for k, v in properties.items():
                params[f"prop_{k}"] = v
            props = ", ".join(f"r.{k} = $prop_{k}" for k in properties)
            props = f"SET {props}"

        id_field_from = id_field
        id_field_to = id_field

        cql = f"""
        MATCH (a:{from_label} {{{id_field_from}: $from_id}}),
              (b:{to_label} {{{id_field_to}: $to_id}})
        MERGE (a)-[r:{rel_type}]->(b)
        {props}
        """
        try:
            run_write(cql, params)
        except Exception as e:
            logger.warning(f"[GraphStore] 创建关系失败: {e}")

    # ------------------------------------------------------------------
    # 实体提取
    # ------------------------------------------------------------------

    async def extract_and_create_entities(
        self,
        source_id: str,
        chunk_id: str,
        text: str,
    ):
        """从文本中提取实体并创建 Entity 节点 + MENTIONS 关系

        使用规则提取：
          - 接口路径（/api/xxx）
          - 大写驼峰标识符（类名/模块名）
          - 中文关键词（2-6字的名词短语）
        """
        if not is_available():
            return
        entities = self._extract_entities(text)
        if not entities:
            return

        for entity_name in entities[:20]:  # 限制每 chunk 最多 20 个实体
            try:
                # MERGE Entity 节点
                run_write(
                    f"MERGE (e:{LABEL_ENTITY} {{name: $name}})",
                    {"name": entity_name},
                )
                # MERGE MENTIONS 关系
                run_write(
                    f"""
                    MATCH (c:{LABEL_CHUNK} {{chunk_id: $chunk_id}}),
                          (e:{LABEL_ENTITY} {{name: $name}})
                    MERGE (c)-[:{REL_MENTIONS}]->(e)
                    """,
                    {"chunk_id": str(chunk_id), "name": entity_name},
                )
            except Exception as e:
                logger.debug(f"[GraphStore] 实体创建失败 entity={entity_name}: {e}")

        logger.debug(
            f"[GraphStore] 实体提取完成 chunk_id={chunk_id} count={len(entities)}"
        )

    @staticmethod
    def _extract_entities(text: str) -> List[str]:
        """从文本中提取实体关键词"""
        entities: List[str] = []
        seen = set()

        # 1. API 路径 /api/xxx
        for m in re.finditer(r"/api/[a-zA-Z0-9/_\-]+", text or ""):
            val = m.group().strip("/")
            if val and val not in seen:
                seen.add(val)
                entities.append(val)

        # 2. 大写驼峰标识符（至少 2 个大写字母）
        for m in re.finditer(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b", text or ""):
            val = m.group()
            if val not in seen:
                seen.add(val)
                entities.append(val)

        # 3. 全大写缩写（2-6 字母）
        for m in re.finditer(r"\b[A-Z]{2,6}\b", text or ""):
            val = m.group()
            if val not in seen:
                seen.add(val)
                entities.append(val)

        # 4. 中文关键词（2-6 字）
        for m in re.finditer(r"[\u4e00-\u9fff]{2,6}", text or ""):
            val = m.group()
            if val not in seen:
                seen.add(val)
                entities.append(val)

        return entities

    # ------------------------------------------------------------------
    # 图检索
    # ------------------------------------------------------------------

    async def search_graph(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """基于查询文本在知识图谱中搜索关联 chunk

        策略：
          1. 从查询中提取实体
          2. 查找这些实体关联的 chunk
          3. 返回 chunk 信息 + 图路径分数
        """
        if not is_available():
            return []
        entities = self._extract_entities(query)
        if not entities:
            return []

        results: List[Dict[str, Any]] = []
        for entity_name in entities[:10]:
            cql = f"""
            MATCH (e:{LABEL_ENTITY} {{name: $name}})<-[:{REL_MENTIONS}]-(c:{LABEL_CHUNK})
            OPTIONAL MATCH (d:{LABEL_DOC})-[:{REL_HAS_CHUNK}]->(c)
            RETURN c.chunk_id AS chunk_id,
                   c.source_id AS source_id,
                   c.text AS text,
                   c.chunk_type AS chunk_type,
                   c.metadata AS metadata,
                   d.source_type AS source_type,
                   d.file_name AS source_name,
                   0.5 AS score
            LIMIT $limit
            """
            try:
                rows = run_query(cql, {"name": entity_name, "limit": limit})
                for row in rows or []:
                    row_dict = dict(row) if not isinstance(row, dict) else row
                    # 解析 metadata
                    meta = row_dict.get("metadata", "{}")
                    if isinstance(meta, str):
                        try:
                            row_dict["metadata"] = json.loads(meta)
                        except Exception:
                            row_dict["metadata"] = {}
                    results.append(row_dict)
            except Exception as e:
                logger.debug(f"[GraphStore] 图搜索实体 {entity_name} 失败: {e}")

        # 去重（按 chunk_id）
        seen_ids = set()
        deduped: List[Dict[str, Any]] = []
        for r in results:
            cid = r.get("chunk_id", "")
            if cid and cid not in seen_ids:
                seen_ids.add(cid)
                deduped.append(r)

        logger.info(
            f"[GraphStore] 图搜索完成 query='{query[:30]}' "
            f"entities={len(entities)} results={len(deduped)}"
        )
        return deduped[:limit]

    async def get_related_chunks(
        self, chunk_id: str, depth: int = 1
    ) -> List[str]:
        """获取与指定 chunk 相关联的其他 chunk_id

        通过共享 Entity 关系查找：
          (c1)-[:MENTIONS]->(e)<-[:MENTIONS]-(c2)
        """
        if not is_available() or not chunk_id:
            return []
        cql = f"""
        MATCH (c1:{LABEL_CHUNK} {{chunk_id: $chunk_id}})-[:{REL_MENTIONS}]->(e:{LABEL_ENTITY})<-[:{REL_MENTIONS}]-(c2:{LABEL_CHUNK})
        WHERE c1 <> c2
        RETURN DISTINCT c2.chunk_id AS chunk_id
        LIMIT 20
        """
        try:
            rows = run_query(cql, {"chunk_id": str(chunk_id)})
            return [r["chunk_id"] for r in rows if r.get("chunk_id")]
        except Exception as e:
            logger.debug(f"[GraphStore] 获取关联 chunk 失败: {e}")
            return []

    # ------------------------------------------------------------------
    # 删除
    # ------------------------------------------------------------------

    async def delete_document(self, source_id: str):
        """删除文档及其所有 chunk 和 entity 节点"""
        if not is_available():
            return
        # 先删 chunk
        try:
            run_write(
                f"""
                MATCH (d:{LABEL_DOC} {{source_id: $sid}})-[:{REL_HAS_CHUNK}]->(c:{LABEL_CHUNK})
                DETACH DELETE c
                """,
                {"sid": str(source_id)},
            )
        except Exception as e:
            logger.warning(f"[GraphStore] 删除 chunk 失败: {e}")

        # 再删 document
        try:
            run_write(
                f"MATCH (d:{LABEL_DOC} {{source_id: $sid}}) DETACH DELETE d",
                {"sid": str(source_id)},
            )
        except Exception as e:
            logger.warning(f"[GraphStore] 删除文档失败: {e}")

        logger.info(f"[GraphStore] 删除文档 source_id={source_id}")

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    async def get_stats(self) -> Dict[str, Any]:
        """获取图谱统计信息"""
        if not is_available():
            return {"available": False, "documents": 0, "chunks": 0, "entities": 0}

        stats: Dict[str, Any] = {"available": True}
        for label, key in [
            (LABEL_DOC, "documents"),
            (LABEL_CHUNK, "chunks"),
            (LABEL_ENTITY, "entities"),
        ]:
            try:
                r = run_query(f"MATCH (n:{label}) RETURN COUNT(n) AS cnt")
                stats[key] = r[0]["cnt"] if r else 0
            except Exception:
                stats[key] = 0

        # 关系统计
        rel_count = 0
        for rel in [REL_HAS_CHUNK, REL_MENTIONS, REL_RELATED_TO, REL_DERIVED_FROM]:
            try:
                r = run_query(f"MATCH ()-[r:{rel}]->() RETURN COUNT(r) AS cnt")
                rel_count += r[0]["cnt"] if r else 0
            except Exception:
                pass
        stats["relationships"] = rel_count
        return stats
