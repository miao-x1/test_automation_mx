"""
GraphService - 图数据库查询服务

职责：
- 图谱可视化数据（节点+边）
- 页面路径查询
- 用例流程查询
- 关键词搜索
- 最短路径
- 统计信息
"""
from typing import Dict, Any, List, Optional
from app.db.neo4j_client import (
    run_query, is_available, get_statistics,
    LABEL_PAGE, LABEL_ELEMENT, LABEL_CASE, LABEL_SCRIPT,
    REL_HAS_ELEMENT, REL_NAVIGATE_TO, REL_TRIGGER,
    REL_NEXT, REL_USES, REL_TEST_ON, REL_GENERATES, REL_EXECUTES,
    ALL_REL_TYPES,
)
from app.core.logger import log


class GraphService:
    """图数据库查询服务"""

    # ========== 可视化数据 ==========

    @staticmethod
    def get_graph_data(
        node_types: Optional[List[str]] = None,
        limit: int = 500,
    ) -> Dict[str, Any]:
        """
        获取前端可视化所需的图谱数据

        Returns:
            {nodes: [{id, label, type, properties}], edges: [{source, target, type, label}]}
        """
        if not is_available():
            return {"nodes": [], "edges": [], "statistics": {}, "available": False}

        nodes = []
        edges = []

        types = node_types or [LABEL_PAGE, LABEL_ELEMENT, LABEL_CASE, LABEL_SCRIPT]

        # 收集节点
        for label in types:
            try:
                results = run_query(
                    f"MATCH (n:{label}) RETURN n LIMIT $limit",
                    {"limit": limit},
                )
                for r in results:
                    props = dict(r.get("n", {}))
                    node_id = props.get("id", "")
                    if not node_id:
                        continue

                    # 确定显示名称
                    display = (
                        props.get("title")
                        or props.get("name")
                        or props.get("url", "").split("/")[-1]
                        or label
                    )

                    nodes.append({
                        "id": node_id,
                        "label": display,
                        "type": label.lower(),
                        "properties": props,
                    })
            except Exception as e:
                log.warning(f"查询节点 {label} 失败: {e}")

        # 收集边
        node_ids = {n["id"] for n in nodes}

        edge_patterns = [
            (LABEL_PAGE, REL_HAS_ELEMENT, LABEL_ELEMENT),
            (LABEL_PAGE, REL_NAVIGATE_TO, LABEL_PAGE),
            (LABEL_ELEMENT, REL_TRIGGER, LABEL_PAGE),
            (LABEL_ELEMENT, REL_NEXT, LABEL_ELEMENT),
            (LABEL_CASE, REL_USES, LABEL_ELEMENT),
            (LABEL_CASE, REL_TEST_ON, LABEL_PAGE),
            (LABEL_CASE, REL_GENERATES, LABEL_SCRIPT),
            (LABEL_SCRIPT, REL_EXECUTES, LABEL_PAGE),
        ]

        for src_label, rel_type, tgt_label in edge_patterns:
            try:
                results = run_query(
                    f"MATCH (a:{src_label})-[r:{rel_type}]->(b:{tgt_label}) "
                    f"RETURN a.id AS src, b.id AS tgt, properties(r) AS rprops "
                    f"LIMIT $limit",
                    {"limit": limit},
                )
                for r in results:
                    src_id = r.get("src", "")
                    tgt_id = r.get("tgt", "")
                    if src_id in node_ids and tgt_id in node_ids:
                        edges.append({
                            "source": src_id,
                            "target": tgt_id,
                            "type": rel_type,
                            "label": rel_type,
                            "properties": r.get("rprops", {}),
                        })
            except Exception as e:
                log.debug(f"查询关系 {rel_type} 失败: {e}")

        stats = get_statistics()

        return {
            "nodes": nodes,
            "edges": edges,
            "statistics": stats,
            "available": True,
        }

    # ========== 页面相关 ==========

    @staticmethod
    def get_all_pages(limit: int = 100) -> List[Dict[str, Any]]:
        """获取所有页面节点"""
        if not is_available():
            return []
        results = run_query(
            f"MATCH (p:{LABEL_PAGE}) RETURN p ORDER BY p.title LIMIT $limit",
            {"limit": limit},
        )
        return [dict(r.get("p", {})) for r in results]

    @staticmethod
    def get_page_detail(page_id: str) -> Optional[Dict[str, Any]]:
        """获取页面详情 + 关联元素 + 触发跳转"""
        if not is_available():
            return None

        # 页面属性
        page_results = run_query(
            f"MATCH (p:{LABEL_PAGE}) WHERE p.id = $pid RETURN p",
            {"pid": page_id},
        )
        if not page_results:
            return None

        page = dict(page_results[0].get("p", {}))

        # HAS_ELEMENT
        elements = run_query(
            f"MATCH (p:{LABEL_PAGE})-[:{REL_HAS_ELEMENT}]->(e:{LABEL_ELEMENT}) "
            f"WHERE p.id = $pid RETURN e ORDER BY e.type, e.name",
            {"pid": page_id},
        )
        page["elements"] = [dict(r.get("e", {})) for r in elements]

        # TRIGGER (元素触发跳转)
        triggers = run_query(
            f"MATCH (p:{LABEL_PAGE})-[:{REL_HAS_ELEMENT}]->(e:{LABEL_ELEMENT})"
            f"-[:{REL_TRIGGER}]->(t:{LABEL_PAGE}) "
            f"WHERE p.id = $pid RETURN e.id AS eid, e.name AS ename, t.id AS tid, t.title AS ttitle",
            {"pid": page_id},
        )
        page["triggers"] = [
            {"element_id": r["eid"], "element_name": r["ename"],
             "target_id": r["tid"], "target_title": r["ttitle"]}
            for r in triggers
        ]

        # TEST_ON (哪些用例测试此页面)
        cases = run_query(
            f"MATCH (c:{LABEL_CASE})-[:{REL_TEST_ON}]->(p:{LABEL_PAGE}) "
            f"WHERE p.id = $pid RETURN c.id AS cid, c.name AS cname",
            {"pid": page_id},
        )
        page["test_cases"] = [dict(r) for r in cases]

        # EXECUTES (哪些脚本执行此页面)
        scripts = run_query(
            f"MATCH (s:{LABEL_SCRIPT})-[:{REL_EXECUTES}]->(p:{LABEL_PAGE}) "
            f"WHERE p.id = $pid RETURN s.id AS sid, s.language AS slang",
            {"pid": page_id},
        )
        page["scripts"] = [dict(r) for r in scripts]

        return page

    @staticmethod
    def get_page_navigation_paths(page_id: str, max_depth: int = 3) -> List[Dict[str, Any]]:
        """查询从某页面出发的导航路径"""
        if not is_available():
            return []
        results = run_query(
            f"MATCH path = (start:{LABEL_PAGE})-[:{REL_NAVIGATE_TO}*1..{max_depth}]->(end:{LABEL_PAGE}) "
            f"WHERE start.id = $pid "
            f"RETURN [n IN nodes(path) | n{{.id, .title, .url}}] AS page_list, "
            f"length(path) AS depth "
            f"ORDER BY depth LIMIT 50",
            {"pid": page_id},
        )
        return [
            {"pages": r["page_list"], "depth": r["depth"]}
            for r in results
        ]

    # ========== 用例相关 ==========

    @staticmethod
    def get_all_cases(limit: int = 100) -> List[Dict[str, Any]]:
        """获取所有用例节点"""
        if not is_available():
            return []
        results = run_query(
            f"MATCH (c:{LABEL_CASE}) RETURN c ORDER BY c.name LIMIT $limit",
            {"limit": limit},
        )
        return [dict(r.get("c", {})) for r in results]

    @staticmethod
    def get_case_detail(case_id: str) -> Optional[Dict[str, Any]]:
        """获取用例详情 + 使用的元素 + 测试的页面 + 生成的脚本"""
        if not is_available():
            return None

        case_results = run_query(
            f"MATCH (c:{LABEL_CASE}) WHERE c.id = $cid RETURN c",
            {"cid": case_id},
        )
        if not case_results:
            return None

        case = dict(case_results[0].get("c", {}))

        # USES元素
        uses = run_query(
            f"MATCH (c:{LABEL_CASE})-[r:{REL_USES}]->(e:{LABEL_ELEMENT}) "
            f"WHERE c.id = $cid RETURN e, r.action AS action, r.order AS order_num "
            f"ORDER BY r.order",
            {"cid": case_id},
        )
        case["elements"] = [
            {**dict(r.get("e", {})), "action": r.get("action", ""), "order": r.get("order_num", 0)}
            for r in uses
        ]

        # TEST_ON页面
        test_on = run_query(
            f"MATCH (c:{LABEL_CASE})-[:{REL_TEST_ON}]->(p:{LABEL_PAGE}) "
            f"WHERE c.id = $cid RETURN p.id AS pid, p.title AS ptitle, p.url AS purl",
            {"cid": case_id},
        )
        case["pages"] = [dict(r) for r in test_on]

        # GENERATES脚本
        gen = run_query(
            f"MATCH (c:{LABEL_CASE})-[:{REL_GENERATES}]->(s:{LABEL_SCRIPT}) "
            f"WHERE c.id = $cid RETURN s.id AS sid, s.language AS slang, s.content AS scontent",
            {"cid": case_id},
        )
        case["scripts"] = [dict(r) for r in gen]

        return case

    # ========== 脚本相关 ==========

    @staticmethod
    def get_all_scripts(limit: int = 100) -> List[Dict[str, Any]]:
        """获取所有脚本节点"""
        if not is_available():
            return []
        results = run_query(
            f"MATCH (s:{LABEL_SCRIPT}) RETURN s LIMIT $limit",
            {"limit": limit},
        )
        return [dict(r.get("s", {})) for r in results]

    # ========== 搜索 ==========

    @staticmethod
    def search_nodes(keyword: str, limit: int = 30) -> List[Dict[str, Any]]:
        """关键词搜索节点（模糊匹配名称/URL/定位器等）"""
        if not is_available() or not keyword.strip():
            return []

        pattern = f"(?i).*{keyword.replace('*', '.*')}.*"

        results = run_query(
            f"MATCH (n) "
            f"WHERE n.title =~ $pattern OR n.name =~ $pattern "
            f"OR n.url =~ $pattern OR n.locator =~ $pattern "
            f"OR n.text =~ $pattern "
            f"RETURN n, labels(n)[0] AS nodeType "
            f"LIMIT $limit",
            {"pattern": pattern, "limit": limit},
        )

        items = []
        for r in results:
            node_data = dict(r.get("n", {}))
            node_data["_type"] = r.get("nodeType", "Unknown")
            items.append(node_data)

        return items

    # ========== 路径查询 ==========

    @staticmethod
    def get_shortest_path(from_id: str, to_id: str) -> Optional[Dict[str, Any]]:
        """查询两个节点之间的最短路径"""
        if not is_available():
            return None

        results = run_query(
            f"MATCH (a), (b), p = shortestPath((a)-[*]-(b)) "
            f"WHERE a.id = $from_id AND b.id = $to_id "
            f"RETURN [n IN nodes(p) | n{{.id, labels(n)[0] AS type, .title, .name}}] AS path_nodes, "
            f"[r IN relationships(p) | {{type: type(r), source: startNode(r).id, target: endNode(r).id}}] AS path_rels, "
            f"length(p) AS hops",
            {"from_id": from_id, "to_id": to_id},
        )

        if not results:
            return None

        r = results[0]
        return {
            "path": r.get("path_nodes", []),
            "relationships": r.get("path_rels", []),
            "hops": r.get("hops", 0),
        }

    # ========== 统计 ==========

    @staticmethod
    def get_stat() -> Dict[str, Any]:
        """获取图谱统计（含平均度）"""
        return get_statistics()

    # ========== 邻居展开 ==========

    @staticmethod
    def get_neighbors(node_id: str, rel_types: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        获取节点的一阶邻居（用于按需展开）

        Returns:
            {
                "center": {id, label, type, properties},
                "neighbors": [{id, label, type, properties, rel_type, direction}],
                "edges": [{source, target, type, label}]
            }
        """
        if not is_available():
            return {"center": None, "neighbors": [], "edges": [], "available": False}

        # 查找中心节点（兼容整数和字符串ID）
        try:
            nid_int = int(node_id)
            center_results = run_query(
                "MATCH (n) WHERE n.id = $nid OR n.id = $nidInt RETURN n, labels(n)[0] AS nodeType",
                {"nid": node_id, "nidInt": nid_int},
            )
        except (ValueError, TypeError):
            center_results = run_query(
                "MATCH (n) WHERE n.id = $nid RETURN n, labels(n)[0] AS nodeType",
                {"nid": node_id},
            )
        if not center_results:
            return {"center": None, "neighbors": [], "edges": [], "available": True}

        cr = center_results[0]
        center_props = dict(cr.get("n", {}))
        center_type = cr.get("nodeType", "Unknown")

        display = (
            center_props.get("title")
            or center_props.get("name")
            or center_props.get("url", "").split("/")[-1]
            or center_type
        )

        center = {
            "id": str(center_props.get("id", node_id)),
            "label": display,
            "type": center_type.lower(),
            "properties": center_props,
        }

        # 构建关系过滤
        rel_filter = ""
        if rel_types:
            rel_list = "|".join(rel_types)
            rel_filter = f":{rel_list}"

        # 构建ID匹配条件（兼容整数和字符串ID）
        try:
            nid_int = int(node_id)
            id_where = "n.id = $nid OR n.id = $nidInt"
            id_params: Dict[str, Any] = {"nid": node_id, "nidInt": nid_int}
        except (ValueError, TypeError):
            id_where = "n.id = $nid"
            id_params = {"nid": node_id}

        # 查询一阶邻居（出方向）
        out_results = run_query(
            f"MATCH (n)-[r{rel_filter}]->(m) WHERE {id_where} "
            f"RETURN m, labels(m)[0] AS mType, type(r) AS relType "
            f"LIMIT 50",
            id_params,
        )

        # 查询一阶邻居（入方向）
        in_results = run_query(
            f"MATCH (m)-[r{rel_filter}]->(n) WHERE {id_where} "
            f"RETURN m, labels(m)[0] AS mType, type(r) AS relType "
            f"LIMIT 50",
            id_params,
        )

        neighbors = []
        edges = []
        seen = set()

        for r in out_results:
            props = dict(r.get("m", {}))
            nid = str(props.get("id", ""))
            if not nid or nid in seen:
                continue
            seen.add(nid)
            mtype = r.get("mType", "Unknown")
            rel_type = r.get("relType", "")
            mdisplay = (
                props.get("title")
                or props.get("name")
                or props.get("url", "").split("/")[-1]
                or mtype
            )
            neighbors.append({
                "id": nid,
                "label": mdisplay,
                "type": mtype.lower(),
                "properties": props,
                "rel_type": rel_type,
                "direction": "out",
            })
            edges.append({
                "source": str(center_props.get("id", node_id)),
                "target": nid,
                "type": rel_type,
                "label": rel_type,
            })

        for r in in_results:
            props = dict(r.get("m", {}))
            nid = str(props.get("id", ""))
            if not nid or nid in seen:
                continue
            seen.add(nid)
            mtype = r.get("mType", "Unknown")
            rel_type = r.get("relType", "")
            mdisplay = (
                props.get("title")
                or props.get("name")
                or props.get("url", "").split("/")[-1]
                or mtype
            )
            neighbors.append({
                "id": nid,
                "label": mdisplay,
                "type": mtype.lower(),
                "properties": props,
                "rel_type": rel_type,
                "direction": "in",
            })
            edges.append({
                "source": nid,
                "target": str(center_props.get("id", node_id)),
                "type": rel_type,
                "label": rel_type,
            })

        return {
            "center": center,
            "neighbors": neighbors,
            "edges": edges,
            "available": True,
        }

    # ========== 业务流查询 ==========

    @staticmethod
    def get_business_flows() -> List[Dict[str, Any]]:
        """
        获取所有业务流（页面→元素→用例→脚本的链路）

        每条业务流以一个Page为起点，展示其元素操作链、关联用例和脚本
        """
        if not is_available():
            return []

        pages = run_query(
            f"MATCH (p:{LABEL_PAGE}) RETURN p.id AS pid, p.title AS ptitle, p.url AS purl "
            f"ORDER BY p.title",
        )

        flows = []
        for pr in pages:
            pid = pr.get("pid", "")
            ptitle = pr.get("ptitle", "")
            purl = pr.get("purl", "")

            # 元素操作链
            chain = run_query(
                f"MATCH (p:{LABEL_PAGE})-[:{REL_HAS_ELEMENT}]->(e:{LABEL_ELEMENT}) "
                f"WHERE p.id = $pid "
                f"OPTIONAL MATCH (e)-[r:{REL_NEXT}]->(e2:{LABEL_ELEMENT}) "
                f"RETURN e.id AS eid, e.name AS ename, e.type AS etype, "
                f"e2.id AS next_id, e2.name AS next_name "
                f"ORDER BY r.order",
                {"pid": pid},
            )

            elements = []
            for c in chain:
                elements.append({
                    "id": c.get("eid", ""),
                    "name": c.get("ename", ""),
                    "type": c.get("etype", ""),
                    "next_id": c.get("next_id"),
                    "next_name": c.get("next_name"),
                })

            # 关联用例
            cases = run_query(
                f"MATCH (c:{LABEL_CASE})-[:{REL_TEST_ON}]->(p:{LABEL_PAGE}) "
                f"WHERE p.id = $pid RETURN c.id AS cid, c.name AS cname",
                {"pid": pid},
            )

            # 关联脚本
            scripts = run_query(
                f"MATCH (s:{LABEL_SCRIPT})-[:{REL_EXECUTES}]->(p:{LABEL_PAGE}) "
                f"WHERE p.id = $pid RETURN s.id AS sid, s.language AS slang",
                {"pid": pid},
            )

            flows.append({
                "page_id": pid,
                "page_title": ptitle,
                "page_url": purl,
                "elements": elements,
                "cases": [{"id": r["cid"], "name": r["cname"]} for r in cases],
                "scripts": [{"id": r["sid"], "language": r["slang"]} for r in scripts],
            })

        return flows

    # ========== 业务流程查询（供GraphSearchAgent使用） ==========

    @staticmethod
    def query_business_flow(keyword: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        查询业务流程

        根据关键词找到相关页面，然后返回该页面的元素操作链和关联用例
        用于RAG增强脚本生成
        """
        if not is_available() or not keyword.strip():
            return []

        pattern = f"(?i).*{keyword.replace('*', '.*')}.*"

        # 找到匹配的页面
        page_results = run_query(
            f"MATCH (p:{LABEL_PAGE}) "
            f"WHERE p.title =~ $pattern OR p.url =~ $pattern "
            f"RETURN p LIMIT $limit",
            {"pattern": pattern, "limit": limit},
        )

        flows = []
        for pr in page_results:
            page = dict(pr.get("p", {}))
            page_id = page.get("id", "")

            # 获取元素操作链 (NEXT关系)
            next_chain = run_query(
                f"MATCH (e1:{LABEL_ELEMENT})-[r:{REL_NEXT}]->(e2:{LABEL_ELEMENT}) "
                f"WHERE e1.id STARTS WITH 'elem_' AND EXISTS {{ "
                f"  MATCH (p:{LABEL_PAGE})-[:{REL_HAS_ELEMENT}]->(e1) WHERE p.id = $pid "
                f"}} "
                f"RETURN e1.id AS from_id, e1.name AS from_name, e1.type AS from_type, "
                f"e2.id AS to_id, e2.name AS to_name, e2.type AS to_type, r.order AS order_num "
                f"ORDER BY r.order",
                {"pid": page_id},
            )

            # 获取关联用例
            cases = run_query(
                f"MATCH (c:{LABEL_CASE})-[:{REL_TEST_ON}]->(p:{LABEL_PAGE}) "
                f"WHERE p.id = $pid RETURN c.id AS cid, c.name AS cname",
                {"pid": page_id},
            )

            flows.append({
                "page": page,
                "element_chain": [dict(r) for r in next_chain],
                "cases": [dict(r) for r in cases],
            })

        return flows
