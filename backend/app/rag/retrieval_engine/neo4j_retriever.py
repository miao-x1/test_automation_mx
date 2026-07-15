"""
Neo4j图检索器

从Neo4j图数据库检索实体关系数据。
支持节点查询、关系遍历、路径搜索。

查询模式：
    1. 按节点标签查询
    2. 按节点名称/属性查询
    3. 按关系类型遍历
    4. 多跳路径搜索
"""
import logging
from typing import Any, Dict, List

from app.rag.retrieval_engine.base import BaseRetriever, RetrievalResult

logger = logging.getLogger(__name__)


class Neo4jRetriever(BaseRetriever):
    """Neo4j图关系检索器

    根据查询计划从Neo4j检索业务关系数据。
    支持节点查询、关系遍历、路径搜索。
    """

    def __init__(self):
        super().__init__("neo4j")

    def search(self, query: Dict[str, Any]) -> RetrievalResult:
        """
        从Neo4j检索图关系数据

        Args:
            query: {
                node_labels: ["Page", "Element"],       # 节点标签
                node_names: ["登录页面", "登录按钮"],     # 节点名称
                relation_types: ["HAS_ELEMENT"],         # 关系类型
                depth: 2,                                # 遍历深度
                start_nodes: [{"label": "Page", "name": "登录"}]
            }

        Returns:
            RetrievalResult: {
                data: {nodes: [...], relationships: [...], paths: [...]},
                count: total
            }
        """
        node_labels = query.get("node_labels", [])
        node_names = query.get("node_names", [])
        relation_types = query.get("relation_types", [])
        depth = query.get("depth", 2)
        start_nodes = query.get("start_nodes", [])

        if not node_labels and not node_names and not start_nodes:
            return RetrievalResult(source="neo4j", success=True, data={}, count=0)

        try:
            from app.db.neo4j_client import get_driver
            driver = get_driver()
            if not driver:
                logger.warning("[neo4j] Neo4j未连接，跳过图查询")
                return RetrievalResult(
                    source="neo4j",
                    success=True,
                    data={},
                    count=0,
                    error="Neo4j未连接",
                )

            all_nodes = []
            all_relationships = []
            all_paths = []

            with driver.session() as session:
                # 1. 按标签查询节点
                if node_labels:
                    nodes = self._query_nodes_by_labels(session, node_labels, node_names)
                    all_nodes.extend(nodes)

                # 2. 按起始节点遍历关系
                if start_nodes:
                    for start in start_nodes:
                        rels = self._query_relationships(session, start, depth)
                        all_relationships.extend(rels)

                # 3. 按关系类型查询
                if relation_types and not start_nodes and all_nodes:
                    # 用查询到的节点作为起点
                    for node in all_nodes[:5]:
                        rels = self._query_relationships(
                            session,
                            {"label": list(node.get("labels", ["Page"]))[0], "name": node.get("name", "")},
                            depth,
                        )
                        all_relationships.extend(rels)

                # 4. 去重
                all_nodes = self._deduplicate_nodes(all_nodes)
                all_relationships = self._deduplicate_relationships(all_relationships)

            total = len(all_nodes) + len(all_relationships)

            return RetrievalResult(
                source="neo4j",
                success=True,
                data={
                    "nodes": all_nodes,
                    "relationships": all_relationships,
                    "paths": all_paths,
                },
                count=total,
            )

        except Exception as e:
            logger.error(f"[neo4j] 检索失败: {e}")
            return RetrievalResult(
                source="neo4j",
                success=False,
                error=str(e),
                data={},
                count=0,
            )

    def _query_nodes_by_labels(self, session, labels: List[str], names: List[str]) -> List[Dict]:
        """按标签查询节点"""
        nodes = []

        for label in labels:
            if names:
                # 按名称查询
                for name in names:
                    cypher = f"MATCH (n:{label}) WHERE n.name CONTAINS $name OR n.title CONTAINS $name RETURN n LIMIT 10"
                    result = session.run(cypher, name=name)
                    for record in result:
                        node = dict(record["n"])
                        node["labels"] = list(record["n"].labels) if hasattr(record["n"], "labels") else [label]
                        nodes.append(node)
            else:
                # 查询所有节点（限制数量）
                cypher = f"MATCH (n:{label}) RETURN n LIMIT 20"
                result = session.run(cypher)
                for record in result:
                    node = dict(record["n"])
                    node["labels"] = list(record["n"].labels) if hasattr(record["n"], "labels") else [label]
                    nodes.append(node)

        return nodes

    def _query_relationships(self, session, start_node: Dict, depth: int) -> List[Dict]:
        """查询节点的相关关系"""
        label = start_node.get("label", "Page")
        name = start_node.get("name", "")

        if not name:
            return []

        rels = []
        try:
            cypher = f"""
                MATCH (n:{label})-[*1..{depth}]-(m)
                WHERE n.name CONTAINS $name OR n.title CONTAINS $name
                RETURN n, m, relationships(p) as rels
                LIMIT 20
            """
            result = session.run(cypher, name=name)
            for record in result:
                rel = {
                    "start_node": dict(record["n"]) if record["n"] else {},
                    "end_node": dict(record["m"]) if record["m"] else {},
                    "type": "RELATED",
                }
                rels.append(rel)
        except Exception as e:
            logger.warning(f"[neo4j] 关系查询失败: {e}")

        return rels

    def _deduplicate_nodes(self, nodes: List[Dict]) -> List[Dict]:
        """节点去重"""
        seen = set()
        unique = []
        for n in nodes:
            key = f"{n.get('name', n.get('title', ''))}_{n.get('id', '')}"
            if key not in seen:
                seen.add(key)
                unique.append(n)
        return unique

    def _deduplicate_relationships(self, rels: List[Dict]) -> List[Dict]:
        """关系去重"""
        seen = set()
        unique = []
        for r in rels:
            start = r.get("start_node", {}).get("name", r.get("start_node", {}).get("title", ""))
            end = r.get("end_node", {}).get("name", r.get("end_node", {}).get("title", ""))
            key = f"{start}_{r.get('type', '')}_{end}"
            if key not in seen:
                seen.add(key)
                unique.append(r)
        return unique
