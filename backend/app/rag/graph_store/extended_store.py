"""
Neo4j 扩展知识图谱存储

在已有的 KnowledgeDocument / KnowledgeChunk / Entity 基础上，
新增完整的业务关系链：

  页面(Page) → 元素(Element) → 接口(API) → 数据库表(DBTable)
                                      ↗
  业务流程(BusinessFlow) → 测试用例(TestCase) → 脚本(Script)

节点标签：
  - Page:              页面（复用 neo4j_client 已有标签）
  - Element:           页面元素（复用已有标签）
  - API:               接口
  - DBTable:           数据库表
  - BusinessFlow:      业务流程
  - TestCase:          测试用例（复用已有标签）
  - Script:            脚本（复用已有标签）
  - Requirement:       需求（新增）
  - Module:            模块（新增）

关系类型（完整关系链）：
  - HAS_ELEMENT:       Page → Element（已有）
  - CALLS_API:         Element → API（元素触发接口调用）
  - NAVIGATE_TO:       Page → Page（已有）
  - USES_TABLE:        API → DBTable（接口操作数据库表）
  - FLOW_STEP:         BusinessFlow → API（业务流程包含接口步骤）
  - DERIVES_TEST:      BusinessFlow → TestCase（业务流程派生测试用例）
  - TESTS_API:         TestCase → API（用例测试接口）
  - TESTS_PAGE:         TestCase → Page（用例测试页面）
  - GENERATES_SCRIPT:  TestCase → Script（用例生成脚本）
  - EXECUTES_PAGE:     Script → Page（脚本执行页面）
  - REQUIRES:           Requirement → API/DBTable/BusinessFlow（需求引用实体）
  - DEPENDS_ON:         Module → Module（模块依赖）
  - BELONGS_TO_MODULE:  Page/API/TestCase → Module（归属模块）

Neo4j 不可用时优雅降级。
"""
import json
import logging
from typing import Any, Dict, List, Optional

from app.db.neo4j_client import is_available, run_query, run_write

logger = logging.getLogger(__name__)

# ===== 扩展节点标签 =====
LABEL_PAGE = "Page"
LABEL_ELEMENT = "Element"
LABEL_API = "API"
LABEL_DBTABLE = "DBTable"
LABEL_FLOW = "BusinessFlow"
LABEL_CASE = "TestCase"
LABEL_SCRIPT = "Script"
LABEL_REQUIREMENT = "Requirement"
LABEL_MODULE = "Module"

# 复用已有的知识图谱标签
LABEL_DOC = "KnowledgeDocument"
LABEL_CHUNK = "KnowledgeChunk"
LABEL_ENTITY = "Entity"

# ===== 扩展关系类型 =====
REL_HAS_ELEMENT = "HAS_ELEMENT"           # Page → Element
REL_CALLS_API = "CALLS_API"               # Element → API
REL_NAVIGATE_TO = "NAVIGATE_TO"            # Page → Page
REL_USES_TABLE = "USES_TABLE"             # API → DBTable
REL_FLOW_STEP = "FLOW_STEP"               # BusinessFlow → API
REL_DERIVES_TEST = "DERIVES_TEST"         # BusinessFlow → TestCase
REL_TESTS_API = "TESTS_API"              # TestCase → API
REL_TESTS_PAGE = "TESTS_PAGE"            # TestCase → Page
REL_GENERATES_SCRIPT = "GENERATES_SCRIPT"  # TestCase → Script
REL_EXECUTES_PAGE = "EXECUTES_PAGE"       # Script → Page
REL_REQUIRES = "REQUIRES"                # Requirement → API/DBTable/Flow
REL_DEPENDS_ON = "DEPENDS_ON"            # Module → Module
REL_BELONGS_TO_MODULE = "BELONGS_TO_MODULE"  # → Module

# 知识图谱原有关系
REL_HAS_CHUNK = "HAS_CHUNK"
REL_MENTIONS = "MENTIONS"
REL_RELATED_TO = "RELATED_TO"
REL_DERIVED_FROM = "DERIVED_FROM"

ALL_NODE_LABELS = [
    LABEL_PAGE, LABEL_ELEMENT, LABEL_API, LABEL_DBTABLE,
    LABEL_FLOW, LABEL_CASE, LABEL_SCRIPT, LABEL_REQUIREMENT, LABEL_MODULE,
    LABEL_DOC, LABEL_CHUNK, LABEL_ENTITY,
]

ALL_REL_TYPES = [
    REL_HAS_ELEMENT, REL_CALLS_API, REL_NAVIGATE_TO, REL_USES_TABLE,
    REL_FLOW_STEP, REL_DERIVES_TEST, REL_TESTS_API, REL_TESTS_PAGE,
    REL_GENERATES_SCRIPT, REL_EXECUTES_PAGE, REL_REQUIRES,
    REL_DEPENDS_ON, REL_BELONGS_TO_MODULE,
    REL_HAS_CHUNK, REL_MENTIONS, REL_RELATED_TO, REL_DERIVED_FROM,
]


class ExtendedGraphStore:
    """扩展知识图谱存储

    提供完整的关系链管理：
    页面 → 元素 → 接口 → 数据库表
                 ↗
    业务流程 → 测试用例 → 脚本

    以及需求/模块的关联关系。
    """

    def __init__(self):
        self._initialized = False

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    def ensure_constraints(self):
        """创建所有节点标签的唯一性约束（幂等）"""
        if not is_available():
            return
        constraints = [
            f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{LABEL_PAGE}) REQUIRE n.page_id IS UNIQUE",
            f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{LABEL_API}) REQUIRE n.api_id IS UNIQUE",
            f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{LABEL_DBTABLE}) REQUIRE n.table_name IS UNIQUE",
            f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{LABEL_FLOW}) REQUIRE n.flow_id IS UNIQUE",
            f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{LABEL_REQUIREMENT}) REQUIRE n.req_id IS UNIQUE",
            f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{LABEL_MODULE}) REQUIRE n.name IS UNIQUE",
        ]
        for cql in constraints:
            try:
                run_query(cql)
            except Exception as e:
                logger.debug(f"[ExtendedGraph] 约束提示: {e}")
        self._initialized = True
        logger.info("[ExtendedGraph] Neo4j 约束已就绪")

    # ------------------------------------------------------------------
    # 通用节点创建
    # ------------------------------------------------------------------

    async def create_node(
        self,
        label: str,
        node_id: str,
        id_field: str = "source_id",
        properties: Optional[Dict[str, Any]] = None,
    ):
        """创建或更新图节点（MERGE 语义）

        Args:
            label: 节点标签
            node_id: 节点唯一标识值
            id_field: 标识字段名
            properties: 其他属性
        """
        if not is_available():
            return
        # 构建 SET 子句
        set_parts = [f"n.{id_field} = $node_id"]
        params: Dict[str, Any] = {"node_id": str(node_id)}
        if properties:
            for k, v in properties.items():
                if isinstance(v, (str, int, float, bool)):
                    params[f"prop_{k}"] = v
                    set_parts.append(f"n.{k} = $prop_{k}")
                elif isinstance(v, dict):
                    params[f"prop_{k}"] = json.dumps(v, ensure_ascii=False)
                    set_parts.append(f"n.{k} = $prop_{k}")
        set_clause = ", ".join(set_parts)

        cql = f"""
        MERGE (n:{label} {{{id_field}: $node_id}})
        SET {set_clause}, n.updated_at = timestamp()
        """
        try:
            run_write(cql, params)
            logger.debug(f"[ExtendedGraph] 节点已创建 {label}:{node_id}")
        except Exception as e:
            logger.warning(f"[ExtendedGraph] 创建节点 {label}:{node_id} 失败: {e}")

    async def create_edge(
        self,
        from_label: str,
        from_id: str,
        rel_type: str,
        to_label: str,
        to_id: str,
        from_id_field: str = "source_id",
        to_id_field: str = "source_id",
        properties: Optional[Dict[str, Any]] = None,
    ):
        """创建或更新图关系（MERGE 语义）"""
        if not is_available():
            return
        set_clause = ""
        params: Dict[str, Any] = {"from_id": str(from_id), "to_id": str(to_id)}
        if properties:
            set_parts = []
            for k, v in properties.items():
                if isinstance(v, (str, int, float, bool)):
                    params[f"prop_{k}"] = v
                    set_parts.append(f"r.{k} = $prop_{k}")
            if set_parts:
                set_clause = "SET " + ", ".join(set_parts)

        cql = f"""
        MATCH (a:{from_label} {{{from_id_field}: $from_id}}),
              (b:{to_label} {{{to_id_field}: $to_id}})
        MERGE (a)-[r:{rel_type}]->(b)
        {set_clause}
        """
        try:
            run_write(cql, params)
            logger.debug(
                f"[ExtendedGraph] 关系已创建 {from_label}:{from_id} "
                f"-[{rel_type}]-> {to_label}:{to_id}"
            )
        except Exception as e:
            logger.warning(f"[ExtendedGraph] 创建关系失败: {e}")

    # ------------------------------------------------------------------
    # 业务实体节点创建
    # ------------------------------------------------------------------

    async def create_page_node(
        self,
        page_id: str,
        url: str = "",
        title: str = "",
        module: str = "",
    ):
        """创建页面节点"""
        await self.create_node(LABEL_PAGE, page_id, "page_id", {
            "url": url, "title": title,
        })
        if module:
            await self.create_node(LABEL_MODULE, module, "name", {})
            await self.create_edge(
                LABEL_PAGE, page_id, REL_BELONGS_TO_MODULE,
                LABEL_MODULE, module, "page_id", "name",
            )

    async def create_element_node(
        self,
        element_id: str,
        page_id: str,
        tag_name: str = "",
        text: str = "",
        locator: str = "",
    ):
        """创建元素节点并关联到页面"""
        await self.create_node(LABEL_ELEMENT, element_id, "element_id", {
            "tag_name": tag_name, "text": text[:200] if text else "",
            "locator": locator,
        })
        await self.create_edge(
            LABEL_PAGE, page_id, REL_HAS_ELEMENT,
            LABEL_ELEMENT, element_id, "page_id", "element_id",
        )

    async def create_api_node(
        self,
        api_id: str,
        method: str = "",
        url: str = "",
        summary: str = "",
        module: str = "",
    ):
        """创建接口节点"""
        await self.create_node(LABEL_API, api_id, "api_id", {
            "method": method, "url": url, "summary": summary[:500] if summary else "",
        })
        if module:
            await self.create_node(LABEL_MODULE, module, "name", {})
            await self.create_edge(
                LABEL_API, api_id, REL_BELONGS_TO_MODULE,
                LABEL_MODULE, module, "api_id", "name",
            )

    async def create_dbtable_node(
        self,
        table_name: str,
        schema: str = "",
        columns: str = "",
    ):
        """创建数据库表节点"""
        await self.create_node(LABEL_DBTABLE, table_name, "table_name", {
            "schema": schema, "columns": columns[:2000] if columns else "",
        })

    async def create_flow_node(
        self,
        flow_id: str,
        name: str = "",
        description: str = "",
        steps: str = "",
    ):
        """创建业务流程节点"""
        await self.create_node(LABEL_FLOW, flow_id, "flow_id", {
            "name": name,
            "description": description[:500] if description else "",
            "steps": steps[:4000] if steps else "",
        })

    async def create_case_node(
        self,
        case_id: str,
        title: str = "",
        case_type: str = "",
        priority: str = "",
    ):
        """创建测试用例节点"""
        await self.create_node(LABEL_CASE, case_id, "case_id", {
            "title": title, "case_type": case_type, "priority": priority,
        })

    async def create_script_node(
        self,
        script_id: str,
        name: str = "",
        language: str = "python",
        content: str = "",
    ):
        """创建脚本节点"""
        await self.create_node(LABEL_SCRIPT, script_id, "script_id", {
            "name": name, "language": language,
            "content": content[:4000] if content else "",
        })

    async def create_requirement_node(
        self,
        req_id: str,
        title: str = "",
        description: str = "",
    ):
        """创建需求节点"""
        await self.create_node(LABEL_REQUIREMENT, req_id, "req_id", {
            "title": title,
            "description": description[:2000] if description else "",
        })

    # ------------------------------------------------------------------
    # 关系链构建
    # ------------------------------------------------------------------

    async def link_element_to_api(
        self, element_id: str, api_id: str, action: str = ""
    ):
        """元素 → 接口（元素触发接口调用）"""
        await self.create_edge(
            LABEL_ELEMENT, element_id, REL_CALLS_API,
            LABEL_API, api_id, "element_id", "api_id",
            {"action": action} if action else None,
        )

    async def link_api_to_table(
        self, api_id: str, table_name: str, operation: str = ""
    ):
        """接口 → 数据库表（接口操作表）"""
        await self.create_edge(
            LABEL_API, api_id, REL_USES_TABLE,
            LABEL_DBTABLE, table_name, "api_id", "table_name",
            {"operation": operation} if operation else None,
        )

    async def link_page_navigate(self, from_page: str, to_page: str):
        """页面 → 页面（页面跳转）"""
        await self.create_edge(
            LABEL_PAGE, from_page, REL_NAVIGATE_TO,
            LABEL_PAGE, to_page, "page_id", "page_id",
        )

    async def link_flow_to_api(
        self, flow_id: str, api_id: str, step_order: int = 0
    ):
        """业务流程 → 接口（流程步骤）"""
        await self.create_edge(
            LABEL_FLOW, flow_id, REL_FLOW_STEP,
            LABEL_API, api_id, "flow_id", "api_id",
            {"step_order": step_order},
        )

    async def link_flow_to_case(
        self, flow_id: str, case_id: str
    ):
        """业务流程 → 测试用例（流程派生用例）"""
        await self.create_edge(
            LABEL_FLOW, flow_id, REL_DERIVES_TEST,
            LABEL_CASE, case_id, "flow_id", "case_id",
        )

    async def link_case_to_api(self, case_id: str, api_id: str):
        """测试用例 → 接口（用例测试接口）"""
        await self.create_edge(
            LABEL_CASE, case_id, REL_TESTS_API,
            LABEL_API, api_id, "case_id", "api_id",
        )

    async def link_case_to_page(self, case_id: str, page_id: str):
        """测试用例 → 页面（用例测试页面）"""
        await self.create_edge(
            LABEL_CASE, case_id, REL_TESTS_PAGE,
            LABEL_PAGE, page_id, "case_id", "page_id",
        )

    async def link_case_to_script(self, case_id: str, script_id: str):
        """测试用例 → 脚本（用例生成脚本）"""
        await self.create_edge(
            LABEL_CASE, case_id, REL_GENERATES_SCRIPT,
            LABEL_SCRIPT, script_id, "case_id", "script_id",
        )

    async def link_script_to_page(self, script_id: str, page_id: str):
        """脚本 → 页面（脚本执行页面）"""
        await self.create_edge(
            LABEL_SCRIPT, script_id, REL_EXECUTES_PAGE,
            LABEL_PAGE, page_id, "script_id", "page_id",
        )

    async def link_requirement_to_entity(
        self, req_id: str, target_label: str, target_id: str, target_id_field: str = "source_id"
    ):
        """需求 → 实体（需求引用接口/表/流程等）"""
        await self.create_edge(
            LABEL_REQUIREMENT, req_id, REL_REQUIRES,
            target_label, target_id, "req_id", target_id_field,
        )

    async def link_module_dependency(self, from_module: str, to_module: str):
        """模块 → 模块（模块依赖）"""
        await self.create_edge(
            LABEL_MODULE, from_module, REL_DEPENDS_ON,
            LABEL_MODULE, to_module, "name", "name",
        )

    # ------------------------------------------------------------------
    # 完整关系链构建
    # ------------------------------------------------------------------

    async def build_full_chain(
        self,
        page_id: str,
        element_id: str,
        api_id: str,
        table_name: str,
        flow_id: str,
        case_id: str,
        script_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """一次性建立完整关系链

        页面 → 元素 → 接口 → 数据库表
                     ↗
        业务流程 → 测试用例 → 脚本
        """
        meta = metadata or {}

        # 创建节点
        if meta.get("page"):
            await self.create_page_node(page_id, **meta["page"])
        if meta.get("element"):
            await self.create_element_node(element_id, page_id, **meta["element"])
        if meta.get("api"):
            await self.create_api_node(api_id, **meta["api"])
        if meta.get("table"):
            await self.create_dbtable_node(table_name, **meta["table"])
        if meta.get("flow"):
            await self.create_flow_node(flow_id, **meta["flow"])
        if meta.get("case"):
            await self.create_case_node(case_id, **meta["case"])
        if meta.get("script"):
            await self.create_script_node(script_id, **meta["script"])

        # 建立关系链
        await self.link_element_to_api(element_id, api_id)
        await self.link_api_to_table(api_id, table_name)
        await self.link_flow_to_api(flow_id, api_id)
        await self.link_flow_to_case(flow_id, case_id)
        await self.link_case_to_api(case_id, api_id)
        await self.link_case_to_script(case_id, script_id)
        await self.link_script_to_page(script_id, page_id)

        logger.info(
            f"[ExtendedGraph] 完整关系链已建立: "
            f"Page({page_id}) → Element({element_id}) → API({api_id}) "
            f"→ DBTable({table_name}) | Flow({flow_id}) → Case({case_id}) "
            f"→ Script({script_id})"
        )

    # ------------------------------------------------------------------
    # 图检索
    # ------------------------------------------------------------------

    async def search_entities(
        self, query: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """全文搜索图中的实体节点

        在所有业务节点中搜索匹配的实体。
        """
        if not is_available():
            return []

        # 在多个标签中搜索
        search_labels = [
            (LABEL_PAGE, "page_id", ["url", "title"]),
            (LABEL_API, "api_id", ["url", "summary", "method"]),
            (LABEL_DBTABLE, "table_name", ["schema", "columns"]),
            (LABEL_FLOW, "flow_id", ["name", "description"]),
            (LABEL_CASE, "case_id", ["title"]),
            (LABEL_REQUIREMENT, "req_id", ["title", "description"]),
        ]

        results: List[Dict[str, Any]] = []
        for label, id_field, search_fields in search_labels:
            for field in search_fields:
                cql = f"""
                MATCH (n:{label})
                WHERE n.{field} CONTAINS $query
                RETURN n.{id_field} AS entity_id,
                       labels(n) AS labels,
                       n.{field} AS matched_field,
                       0.5 AS score
                LIMIT $limit
                """
                try:
                    rows = run_query(cql, {"query": query, "limit": limit})
                    for row in rows or []:
                        r = dict(row) if not isinstance(row, dict) else row
                        r["entity_type"] = label
                        results.append(r)
                except Exception:
                    pass

        # 去重
        seen = set()
        deduped = []
        for r in results:
            eid = r.get("entity_id", "")
            if eid and eid not in seen:
                seen.add(eid)
                deduped.append(r)

        logger.info(
            f"[ExtendedGraph] 实体搜索 query='{query[:30]}' "
            f"results={len(deduped)}"
        )
        return deduped[:limit]

    async def get_entity_relations(
        self,
        label: str,
        entity_id: str,
        id_field: str = "source_id",
        depth: int = 2,
    ) -> Dict[str, Any]:
        """获取实体的关系图（BFS 遍历）

        返回该实体的所有出边和入边关联节点。
        """
        if not is_available():
            return {"nodes": [], "edges": []}

        cql = f"""
        MATCH path = (n:{label} {{{id_field}: $entity_id}})-[*1..{depth}]-(m)
        WITH collect(DISTINCT m) AS nodes, collect(DISTINCT relationships(path)) AS rels
        UNWIND nodes AS node
        WITH collect(DISTINCT {{id: id(node), labels: labels(node), props: properties(node)}}) AS allNodes,
             rels
        UNWIND rels AS relList
        UNWIND relList AS rel
        WITH allNodes,
             collect(DISTINCT {{
               source: id(startNode(rel)),
               target: id(endNode(rel)),
               type: type(rel),
               props: properties(rel)
             }}) AS allEdges
        RETURN allNodes AS nodes, allEdges AS edges
        LIMIT 100
        """
        try:
            rows = run_query(cql, {"entity_id": str(entity_id)})
            if rows:
                row = rows[0]
                return {
                    "nodes": row.get("nodes", []) if isinstance(row, dict) else [],
                    "edges": row.get("edges", []) if isinstance(row, dict) else [],
                }
        except Exception as e:
            logger.warning(f"[ExtendedGraph] 获取关系图失败: {e}")

        return {"nodes": [], "edges": []}

    async def get_traceability(
        self, label: str, entity_id: str, id_field: str = "source_id"
    ) -> Dict[str, Any]:
        """获取可追溯性链路

        返回从指定实体出发的完整追溯路径。
        例如：从需求追溯到页面→接口→表→流程→用例→脚本。
        """
        if not is_available():
            return {"traces": []}

        cql = f"""
        MATCH path = (n:{label} {{{id_field}: $entity_id}})-[*1..5]->(m)
        RETURN [
          node IN nodes(path) | {{
            labels: labels(node),
            id: coalesce(node.page_id, node.api_id, node.table_name,
                         node.flow_id, node.case_id, node.script_id,
                         node.req_id, node.source_id, node.name, ''),
            props: properties(node)
          }}
        ] AS trace,
        [rel IN relationships(path) | type(rel)] AS rel_types
        LIMIT 50
        """
        try:
            rows = run_query(cql, {"entity_id": str(entity_id)})
            traces = []
            for row in rows or []:
                r = dict(row) if not isinstance(row, dict) else row
                traces.append({
                    "nodes": r.get("trace", []),
                    "relations": r.get("rel_types", []),
                })
            return {"traces": traces}
        except Exception as e:
            logger.warning(f"[ExtendedGraph] 追溯链路查询失败: {e}")
            return {"traces": []}

    # ------------------------------------------------------------------
    # 删除
    # ------------------------------------------------------------------

    async def delete_entity(self, label: str, entity_id: str, id_field: str = "source_id"):
        """删除指定实体节点及其所有关系"""
        if not is_available():
            return
        try:
            run_write(
                f"MATCH (n:{label} {{{id_field}: $eid}}) DETACH DELETE n",
                {"eid": str(entity_id)},
            )
            logger.info(f"[ExtendedGraph] 删除实体 {label}:{entity_id}")
        except Exception as e:
            logger.warning(f"[ExtendedGraph] 删除失败: {e}")

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    async def get_full_stats(self) -> Dict[str, Any]:
        """获取完整图谱统计信息"""
        if not is_available():
            return {"available": False, "nodes": {}, "relationships": {}}

        stats: Dict[str, Any] = {"available": True}
        node_counts: Dict[str, int] = {}
        rel_counts: Dict[str, int] = {}

        for label in ALL_NODE_LABELS:
            try:
                r = run_query(f"MATCH (n:{label}) RETURN COUNT(n) AS cnt")
                node_counts[label] = r[0]["cnt"] if r else 0
            except Exception:
                node_counts[label] = 0

        for rel in ALL_REL_TYPES:
            try:
                r = run_query(f"MATCH ()-[r:{rel}]->() RETURN COUNT(r) AS cnt")
                rel_counts[rel] = r[0]["cnt"] if r else 0
            except Exception:
                rel_counts[rel] = 0

        stats["nodes"] = node_counts
        stats["relationships"] = rel_counts
        stats["total_nodes"] = sum(node_counts.values())
        stats["total_relationships"] = sum(rel_counts.values())
        return stats


# ===== 单例 =====
_extended_graph_store: Optional[ExtendedGraphStore] = None


def get_extended_graph_store() -> ExtendedGraphStore:
    global _extended_graph_store
    if _extended_graph_store is None:
        _extended_graph_store = ExtendedGraphStore()
    return _extended_graph_store
