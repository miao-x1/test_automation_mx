"""
GraphBuildService - 图谱构建服务

从MySQL真实数据构建Neo4j图谱，自动创建节点和关系。

数据来源：
- task表 → Page节点
- ui_element表 → Element节点
- requirement_task表 → TestCase节点
- script表 → Script节点

关系构建：
- HAS_ELEMENT: Page -> Element（页面包含元素）
- NAVIGATE_TO: Page -> Page（同域页面跳转）
- TRIGGER: Element -> Page（按钮/链接触发跳转）
- NEXT: Element -> Element（同页面元素操作顺序）
- USES: TestCase -> Element（用例使用元素）
- TEST_ON: TestCase -> Page（用例测试页面）
- GENERATES: TestCase -> Script（用例生成脚本）
- EXECUTES: Script -> Page（脚本执行页面）
"""
import json
import time as _time
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse

from app.db.neo4j_client import (
    run_write, run_query, is_available, ensure_constraints, clear_all,
    LABEL_PAGE, LABEL_ELEMENT, LABEL_CASE, LABEL_SCRIPT,
    REL_HAS_ELEMENT, REL_NAVIGATE_TO, REL_TRIGGER,
    REL_NEXT, REL_USES, REL_TEST_ON, REL_GENERATES, REL_EXECUTES,
)
from app.db.database import SessionLocal
from app.models.task import Task
from app.models.ui_element import UIElement
from app.models.requirement_task import RequirementTask
from app.models.script import Script
from app.models.execution_record import ExecutionRecord
from app.core.logger import log


class GraphBuildService:
    """图谱构建服务 - 从MySQL读取真实数据写入Neo4j"""

    def __init__(self):
        self.stats = {
            "pages": 0, "elements": 0, "cases": 0, "scripts": 0,
            "relationships": 0, "errors": [],
        }

    # ========== 全量构建 ==========

    def build_all(self, clean_first: bool = True) -> Dict[str, Any]:
        """
        全量构建图谱

        流程：清空 → 约束 → Page → Element → TestCase → Script → 关系
        """
        # [DEBUG] 图谱构建入口
        _start = _time.time()
        log.info(f"[DEBUG] 开始：GraphBuildService.build_all | 输入：clean_first={clean_first}")

        if not is_available():
            return {"success": False, "error": "Neo4j不可用"}

        try:
            if clean_first:
                clear_all()
                self.stats = {
                    "pages": 0, "elements": 0, "cases": 0, "scripts": 0,
                    "relationships": 0, "errors": [],
                }

            ensure_constraints()

            # 阶段1: 写入节点
            self._build_pages()
            self._build_elements()
            self._build_cases()
            self._build_scripts()

            # 阶段2: 写入关系
            self._build_has_element_rels()
            self._build_navigate_to_rels()
            self._build_trigger_rels()
            self._build_next_rels()
            self._build_uses_rels()
            self._build_test_on_rels()
            self._build_generates_rels()
            self._build_executes_rels()

            self.stats["success"] = True
            log.info(
                f"GraphBuild | 全量构建完成 | "
                f"Page:{self.stats['pages']} Element:{self.stats['elements']} "
                f"Case:{self.stats['cases']} Script:{self.stats['scripts']} "
                f"Rel:{self.stats['relationships']}"
            )
        except Exception as e:
            log.error(f"GraphBuild | 构建异常: {e}", exc_info=True)
            self.stats["success"] = False
            self.stats["errors"].append(str(e))

        return self.stats

    # ========== 单任务构建 ==========

    def build_task(self, task_id: int) -> Dict[str, Any]:
        """增量构建单个任务"""
        if not is_available():
            return {"success": False, "error": "Neo4j不可用"}

        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task:
                return {"success": False, "error": f"任务 {task_id} 不存在"}

            ensure_constraints()

            # 写入Page节点
            if task.page_url:
                self._upsert_page(task.id, task.task_name or "", task.page_url)

            # 写入Element节点 + HAS_ELEMENT
            elements = db.query(UIElement).filter(UIElement.task_id == task_id).all()
            for elem in elements:
                self._upsert_element(elem)
                if task.page_url:
                    self._merge_rel(
                        f"MATCH (p:{LABEL_PAGE}), (e:{LABEL_ELEMENT}) "
                        f"WHERE p.id = $pid AND e.id = $eid "
                        f"MERGE (p)-[:{REL_HAS_ELEMENT}]->(e)",
                        {"pid": f"page_{task.id}", "eid": f"elem_{elem.id}"},
                    )

            # 写入Script节点
            script = db.query(Script).filter(Script.task_id == task_id).first()
            if script:
                self._upsert_script(script)
                if task.page_url:
                    self._merge_rel(
                        f"MATCH (s:{LABEL_SCRIPT}), (p:{LABEL_PAGE}) "
                        f"WHERE s.id = $sid AND p.id = $pid "
                        f"MERGE (s)-[:{REL_EXECUTES}]->(p)",
                        {"sid": f"script_{script.id}", "pid": f"page_{task.id}"},
                    )

            self.stats["success"] = True
            log.info(f"GraphBuild | 任务 {task_id} 增量构建完成")
        except Exception as e:
            log.error(f"GraphBuild | 任务 {task_id} 构建失败: {e}")
            self.stats["success"] = False
            self.stats["errors"].append(str(e))
        finally:
            db.close()

        return self.stats

    # ========== 节点构建 ==========

    def _build_pages(self):
        """从task表构建Page节点"""
        db = SessionLocal()
        try:
            tasks = db.query(Task).filter(
                Task.page_url.isnot(None),
                Task.page_url != "",
            ).all()

            for task in tasks:
                self._upsert_page(task.id, task.task_name or "", task.page_url)
                self.stats["pages"] += 1

            log.info(f"GraphBuild | Page节点: {self.stats['pages']}")
        finally:
            db.close()

    def _build_elements(self):
        """从ui_element表构建Element节点"""
        db = SessionLocal()
        try:
            elements = db.query(UIElement).all()
            for elem in elements:
                self._upsert_element(elem)
                self.stats["elements"] += 1

            log.info(f"GraphBuild | Element节点: {self.stats['elements']}")
        finally:
            db.close()

    def _build_cases(self):
        """从requirement_task表构建TestCase节点"""
        db = SessionLocal()
        try:
            reqs = db.query(RequirementTask).filter(
                RequirementTask.generated_case.isnot(None),
            ).all()

            for req in reqs:
                self._upsert_case(req)
                self.stats["cases"] += 1

            log.info(f"GraphBuild | TestCase节点: {self.stats['cases']}")
        finally:
            db.close()

    def _build_scripts(self):
        """从script表构建Script节点"""
        db = SessionLocal()
        try:
            scripts = db.query(Script).all()
            for s in scripts:
                self._upsert_script(s)
                self.stats["scripts"] += 1

            log.info(f"GraphBuild | Script节点: {self.stats['scripts']}")
        finally:
            db.close()

    # ========== 节点Upsert ==========
    #如果节点存在:更新
    #如果节点不存在:插入

    def _upsert_page(self, task_id: int, task_name: str, page_url: str):
        """MERGE Page节点"""
        parsed = urlparse(page_url) if page_url else None
        title = task_name or (parsed.netloc if parsed else page_url)
        page_type = "unknown"
        if parsed and parsed.path:
            path = parsed.path.strip("/")
            if path:
                page_type = path.split("/")[0]

        run_write(
            f"MERGE (p:{LABEL_PAGE} {{id: $id}}) "
            f"SET p.url = $url, p.title = $title, "
            f"p.task_id = $task_id, p.page_type = $page_type",
            {
                "id": f"page_{task_id}",
                "url": page_url,
                "title": title,
                "task_id": task_id,
                "page_type": page_type,
            },
        )

    def _upsert_element(self, elem: UIElement):
        """MERGE Element节点"""
        name = elem.name or elem.element_name or f"元素_{elem.id}"
        run_write(
            f"MERGE (e:{LABEL_ELEMENT} {{id: $id}}) "
            f"SET e.name = $name, e.type = $type, "
            f"e.locator = $locator, e.text = $text, "
            f"e.source = $source, e.confidence = $confidence",
            {
                "id": f"elem_{elem.id}",
                "name": name,
                "type": elem.type or "unknown",
                "locator": elem.locator or "",
                "text": (elem.text or "")[:200],
                "source": elem.source or "",
                "confidence": elem.confidence or 0,
            },
        )

    def _upsert_case(self, req: RequirementTask):
        """MERGE TestCase节点"""
        # 解析用例名
        case_name = f"用例_{req.id}"
        steps_str = ""
        try:
            case_data = json.loads(req.generated_case) if isinstance(req.generated_case, str) else req.generated_case
            if isinstance(case_data, dict):
                case_name = case_data.get("case_name", case_name)
                steps = case_data.get("steps", [])
                steps_str = json.dumps(steps, ensure_ascii=False)[:500]
            elif isinstance(case_data, list):
                steps_str = json.dumps(case_data, ensure_ascii=False)[:500]
        except (json.JSONDecodeError, TypeError):
            pass

        run_write(
            f"MERGE (c:{LABEL_CASE} {{id: $id}}) "
            f"SET c.name = $name, c.steps = $steps",
            {
                "id": f"case_{req.id}",
                "name": case_name,
                "steps": steps_str,
            },
        )

    def _upsert_script(self, s: Script):
        """MERGE Script节点"""
        content_preview = (s.script_content or "")[:300]
        run_write(
            f"MERGE (s:{LABEL_SCRIPT} {{id: $id}}) "
            f"SET s.language = $language, s.content = $content, "
            f"s.reuse_count = $reuse_count",
            {
                "id": f"script_{s.id}",
                "language": s.script_language or "python",
                "content": content_preview,
                "reuse_count": s.reuse_count or 0,
            },
        )

    # ========== 关系构建 ==========

    def _build_has_element_rels(self):
        """Page -[:HAS_ELEMENT]-> Element"""
        db = SessionLocal()
        count = 0
        try:
            elements = db.query(UIElement).filter(
                UIElement.task_id.isnot(None),
            ).all()

            for elem in elements:
                count += self._merge_rel(
                    f"MATCH (p:{LABEL_PAGE}), (e:{LABEL_ELEMENT}) "
                    f"WHERE p.id = $pid AND e.id = $eid "
                    f"MERGE (p)-[:{REL_HAS_ELEMENT}]->(e)",
                    {"pid": f"page_{elem.task_id}", "eid": f"elem_{elem.id}"},
                )
        finally:
            db.close()

        self.stats["relationships"] += count
        log.info(f"GraphBuild | HAS_ELEMENT: {count}")

    def _build_navigate_to_rels(self):
        """Page -[:NAVIGATE_TO]-> Page（同域不同路径）"""
        count = 0
        db = SessionLocal()
        try:
            tasks = db.query(Task).filter(
                Task.page_url.isnot(None),
                Task.page_url != "",
            ).all()

            # 按域名分组
            domain_pages: Dict[str, List[tuple]] = {}
            for task in tasks:
                parsed = urlparse(task.page_url)
                domain = parsed.netloc
                if domain not in domain_pages:
                    domain_pages[domain] = []
                domain_pages[domain].append((task.id, task.page_url, parsed.path))

            # 同域不同路径之间建立导航
            for domain, pages in domain_pages.items():
                if len(pages) < 2:
                    continue
                for i in range(len(pages)):
                    for j in range(i + 1, len(pages)):
                        id_a, url_a, path_a = pages[i]
                        id_b, url_b, path_b = pages[j]
                        if path_a == path_b:
                            continue
                        count += self._merge_rel(
                            f"MATCH (a:{LABEL_PAGE}), (b:{LABEL_PAGE}) "
                            f"WHERE a.id = $aid AND b.id = $bid "
                            f"MERGE (a)-[:{REL_NAVIGATE_TO} {{url: $url}}]->(b)",
                            {"aid": f"page_{id_a}", "bid": f"page_{id_b}", "url": url_b},
                        )
                        count += self._merge_rel(
                            f"MATCH (a:{LABEL_PAGE}), (b:{LABEL_PAGE}) "
                            f"WHERE a.id = $aid AND b.id = $bid "
                            f"MERGE (b)-[:{REL_NAVIGATE_TO} {{url: $url}}]->(a)",
                            {"aid": f"page_{id_b}", "bid": f"page_{id_a}", "url": url_a},
                        )
        finally:
            db.close()

        self.stats["relationships"] += count
        log.info(f"GraphBuild | NAVIGATE_TO: {count}")

    def _build_trigger_rels(self):
        """Element -[:TRIGGER]-> Page（按钮/链接触发跳转）"""
        count = 0
        trigger_types = {"button", "link", "a", "submit"}
        trigger_keywords = [
            "login", "submit", "next", "search", "go", "register",
            "登录", "提交", "下一步", "搜索", "注册", "进入",
            "购买", "结算", "加入购物车",
        ]

        try:
            # 查找所有触发类元素
            results = run_query(
                f"MATCH (e:{LABEL_ELEMENT}) "
                f"WHERE e.type IN $types OR e.name CONTAINS '登录' OR e.name CONTAINS '提交' "
                f"OR e.name CONTAINS 'login' OR e.name CONTAINS 'submit' "
                f"RETURN e.id AS eid, e.name AS name, e.type AS etype, e.text AS text",
                {"types": list(trigger_types)},
            )

            # 查找所有页面
            page_results = run_query(
                f"MATCH (p:{LABEL_PAGE}) RETURN p.id AS pid, p.url AS url"
            )
            pages = {r["pid"]: r["url"] for r in page_results}

            for r in results:
                eid = r["eid"]
                name = (r.get("name") or "").lower()
                text = (r.get("text") or "").lower()
                etype = (r.get("etype") or "").lower()

                # 判断是否为触发类元素
                is_trigger = (
                    etype in trigger_types
                    or any(kw in name or kw in text for kw in trigger_keywords)
                )
                if not is_trigger:
                    continue

                # 找到与该元素同页面的其他页面作为跳转目标
                # 从元素ID提取task_id: elem_123 -> page_123
                parts = eid.replace("elem_", "")
                try:
                    task_id = int(parts)
                    source_page_id = f"page_{task_id}"
                except ValueError:
                    continue

                for pid, url in pages.items():
                    if pid == source_page_id:
                        continue
                    count += self._merge_rel(
                        f"MATCH (e:{LABEL_ELEMENT}), (p:{LABEL_PAGE}) "
                        f"WHERE e.id = $eid AND p.id = $pid "
                        f"MERGE (e)-[:{REL_TRIGGER} {{confidence: 0.6}}]->(p)",
                        {"eid": eid, "pid": pid},
                    )
        except Exception as e:
            log.warning(f"TRIGGER关系构建异常: {e}")

        self.stats["relationships"] += count
        log.info(f"GraphBuild | TRIGGER: {count}")

    def _build_next_rels(self):
        """Element -[:NEXT]-> Element（同页面元素操作顺序）"""
        count = 0
        db = SessionLocal()
        try:
            # 按task_id分组元素，同页面的元素按ID排序建立NEXT链
            tasks_with_elements = db.query(Task).filter(
                Task.page_url.isnot(None),
                Task.page_url != "",
            ).all()

            for task in tasks_with_elements:
                elems = (
                    db.query(UIElement)
                    .filter(UIElement.task_id == task.id)
                    .order_by(UIElement.id)
                    .all()
                )

                if len(elems) < 2:
                    continue

                # 按类型排序：input → button（操作顺序）
                type_order = {
                    "input": 1, "textarea": 1, "select": 2,
                    "checkbox": 2, "radio": 2, "button": 3,
                    "submit": 4, "link": 4, "a": 4,
                }
                sorted_elems = sorted(
                    elems,
                    key=lambda e: (type_order.get(e.type, 5), e.id),
                )

                for i in range(len(sorted_elems) - 1):
                    count += self._merge_rel(
                        f"MATCH (a:{LABEL_ELEMENT}), (b:{LABEL_ELEMENT}) "
                        f"WHERE a.id = $aid AND b.id = $bid "
                        f"MERGE (a)-[:{REL_NEXT} {{order: $order}}]->(b)",
                        {
                            "aid": f"elem_{sorted_elems[i].id}",
                            "bid": f"elem_{sorted_elems[i + 1].id}",
                            "order": i,
                        },
                    )
        finally:
            db.close()

        self.stats["relationships"] += count
        log.info(f"GraphBuild | NEXT: {count}")

    def _build_uses_rels(self):
        """TestCase -[:USES]-> Element（用例使用元素）"""
        count = 0
        db = SessionLocal()
        try:
            reqs = db.query(RequirementTask).filter(
                RequirementTask.generated_case.isnot(None),
            ).all()

            for req in reqs:
                try:
                    case_data = json.loads(req.generated_case) if isinstance(req.generated_case, str) else req.generated_case
                except (json.JSONDecodeError, TypeError):
                    continue

                if not isinstance(case_data, dict):
                    continue

                steps = case_data.get("steps", [])
                if not steps:
                    continue

                # 从步骤中提取locator，匹配已有元素
                for i, step in enumerate(steps[:20]):
                    if isinstance(step, dict):
                        locator = step.get("locator", "")
                        action = step.get("action", "")
                    elif isinstance(step, str):
                        locator = ""
                        action = step
                    else:
                        continue

                    if not locator:
                        continue

                    # 按locator匹配元素
                    match = run_query(
                        f"MATCH (e:{LABEL_ELEMENT}) "
                        f"WHERE e.locator = $locator OR e.locator CONTAINS $locator "
                        f"RETURN e.id AS eid LIMIT 1",
                        {"locator": locator},
                    )

                    if match:
                        count += self._merge_rel(
                            f"MATCH (c:{LABEL_CASE}), (e:{LABEL_ELEMENT}) "
                            f"WHERE c.id = $cid AND e.id = $eid "
                            f"MERGE (c)-[:{REL_USES} {{action: $action, order: $order}}]->(e)",
                            {
                                "cid": f"case_{req.id}",
                                "eid": match[0]["eid"],
                                "action": action,
                                "order": i,
                            },
                        )
        finally:
            db.close()

        self.stats["relationships"] += count
        log.info(f"GraphBuild | USES: {count}")

    def _build_test_on_rels(self):
        """TestCase -[:TEST_ON]-> Page"""
        count = 0
        db = SessionLocal()
        try:
            reqs = db.query(RequirementTask).filter(
                RequirementTask.task_id.isnot(None),
            ).all()

            for req in reqs:
                if not req.task_id:
                    continue
                # 查找关联任务的page_url
                task = db.query(Task).filter(Task.id == req.task_id).first()
                if task and task.page_url:
                    count += self._merge_rel(
                        f"MATCH (c:{LABEL_CASE}), (p:{LABEL_PAGE}) "
                        f"WHERE c.id = $cid AND p.id = $pid "
                        f"MERGE (c)-[:{REL_TEST_ON}]->(p)",
                        {"cid": f"case_{req.id}", "pid": f"page_{task.id}"},
                    )
        finally:
            db.close()

        self.stats["relationships"] += count
        log.info(f"GraphBuild | TEST_ON: {count}")

    def _build_generates_rels(self):
        """TestCase -[:GENERATES]-> Script"""
        count = 0
        db = SessionLocal()
        try:
            reqs = db.query(RequirementTask).filter(
                RequirementTask.task_id.isnot(None),
            ).all()

            for req in reqs:
                if not req.task_id:
                    continue
                script = db.query(Script).filter(Script.task_id == req.task_id).first()
                if script:
                    count += self._merge_rel(
                        f"MATCH (c:{LABEL_CASE}), (s:{LABEL_SCRIPT}) "
                        f"WHERE c.id = $cid AND s.id = $sid "
                        f"MERGE (c)-[:{REL_GENERATES}]->(s)",
                        {"cid": f"case_{req.id}", "sid": f"script_{script.id}"},
                    )
        finally:
            db.close()

        self.stats["relationships"] += count
        log.info(f"GraphBuild | GENERATES: {count}")

    def _build_executes_rels(self):
        """Script -[:EXECUTES]-> Page"""
        count = 0
        db = SessionLocal()
        try:
            scripts = db.query(Script).all()

            for s in scripts:
                task = db.query(Task).filter(Task.id == s.task_id).first()
                if task and task.page_url:
                    count += self._merge_rel(
                        f"MATCH (s:{LABEL_SCRIPT}), (p:{LABEL_PAGE}) "
                        f"WHERE s.id = $sid AND p.id = $pid "
                        f"MERGE (s)-[:{REL_EXECUTES}]->(p)",
                        {"sid": f"script_{s.id}", "pid": f"page_{task.id}"},
                    )
        finally:
            db.close()

        self.stats["relationships"] += count
        log.info(f"GraphBuild | EXECUTES: {count}")

    # ========== 工具方法 ==========

    @staticmethod
    def _merge_rel(cypher: str, params: Dict[str, Any]) -> int:
        """执行MERGE关系，返回是否成功(1/0)"""
        try:
            run_write(cypher, params)
            return 1
        except Exception as e:
            log.debug(f"关系MERGE失败: {e}")
            return 0
