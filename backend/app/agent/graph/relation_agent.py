"""
RelationAgent - 页面关联推理Agent

架构变更：
  原：Agent → Neo4j (直接 run_query) + MySQL (直接 SessionLocal)
  新：Agent → ContextRouter.retrieve_page_relations() → Neo4j + MySQL

  禁止 RelationAgent 直接调用：
    - Neo4j / neo4j_client / run_query
    - MySQL / SessionLocal (历史页面查询部分)

  所有数据库查询统一通过 ContextRouter 路由。

职责：
1. find_related_pages(): 从需求文本中识别涉及的页面，发现页面间关联
2. rank_pages(): 对关联页面按置信度排序
3. build_flow(): 构建完整的页面流程图

数据来源（通过 ContextRouter）：
- Neo4j 图数据库中的页面节点和关系
- MySQL 中的历史 PageRelation 记录
- LLM 推理（从需求文本中提取页面流，不查数据库）
"""
import json
import time
from typing import Dict, Any, List, Optional

from app.core.logger import log
from app.core.config import settings
from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability


class RelationAgent(NewBaseAgent):
    """页面关联推理Agent

    通过 ContextRouter 查询页面关系，不直接操作 Neo4j / MySQL。
    """

    agent_name = "relation"
    display_name = "Relation Agent"
    description = "页面关联推理Agent - 通过ContextRouter查询页面关系，构建流程图"
    capabilities = [AgentCapability.RELATION]

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)
        self.agent_type = "relation"
        self._router = None

    @property
    def router(self):
        """延迟加载 ContextRouter"""
        if self._router is None:
            from app.services.context_router import get_context_router
            self._router = get_context_router()
        return self._router

    def find_related_pages(
        self,
        requirement: str,
        keywords: List[str] = None,
        steps: List[str] = None,
        target_url: str = "",
    ) -> Dict[str, Any]:
        """
        从需求中识别关联页面

        策略（按优先级）：
        1. ContextRouter 查询 Neo4j + MySQL（页面关系）
        2. LLM 推理：从需求文本中提取页面流

        所有数据库查询通过 ContextRouter，禁止直接操作 Neo4j。

        Returns:
            {
                "pages": [{"page_id": str, "title": str, "url": str, "confidence": float}],
                "relations": [{"source": str, "target": str, "type": str, "confidence": float, "trigger": str}],
                "source": "neo4j" | "llm" | "mixed" | "none",
                "degraded": bool,
                "degradation_reason": str
            }
        """
        start_time = time.time()
        all_pages: List[Dict[str, Any]] = []
        all_relations: List[Dict[str, Any]] = []
        source = "none"

        # === 策略1: ContextRouter 查询（Neo4j + MySQL）===
        try:
            ctx_result = self.router.retrieve_page_relations(
                query=requirement,
                keywords=keywords or [],
                target_url=target_url,
                top_k=20,
            )

            ctx_pages = ctx_result.get("pages", [])
            ctx_relations = ctx_result.get("relations", [])

            if ctx_pages:
                all_pages.extend(ctx_pages)
                all_relations.extend(ctx_relations)
                source = ctx_result.get("source", "neo4j")

                log.info(
                    f"RelationAgent | ContextRouter 查询完成 | "
                    f"pages={len(ctx_pages)} | relations={len(ctx_relations)} | "
                    f"source={source}"
                )
            else:
                log.info("RelationAgent | ContextRouter 未返回页面")

            # 降级提示
            if ctx_result.get("degraded"):
                degradation_reason = ctx_result.get("degradation_reason", "")
                log.warning(
                    f"RelationAgent | ⚠️ 降级提示：ContextRouter 数据源不可用 | "
                    f"reason={degradation_reason} | "
                    f"检索结果可能不完整，请检查 Neo4j/MySQL 服务状态"
                )

        except Exception as e:
            log.warning(f"RelationAgent | ContextRouter 查询失败: {e}")

        # === 策略2: LLM 推理（不查数据库）===
        llm_result = self._infer_pages_from_llm(requirement, steps or [], target_url)
        if llm_result.get("pages"):
            existing_ids = {p["page_id"] for p in all_pages}
            for p in llm_result["pages"]:
                if p["page_id"] not in existing_ids:
                    all_pages.append(p)
                    existing_ids.add(p["page_id"])
            all_relations.extend(llm_result.get("relations", []))
            if source == "none":
                source = "llm"
            elif source != "llm":
                source = "mixed"

        latency_ms = int((time.time() - start_time) * 1000)

        result = {
            "pages": all_pages,
            "relations": all_relations,
            "source": source,
            "latency_ms": latency_ms,
            "degraded": len(all_pages) == 0,
            "degradation_reason": "所有数据源均未返回结果" if len(all_pages) == 0 else "",
        }

        log.info(
            f"RelationAgent | find_related_pages 完成 | "
            f"pages={len(all_pages)} | relations={len(all_relations)} | "
            f"source={source} | latency={latency_ms}ms"
        )
        return result

    def rank_pages(
        self,
        pages: List[Dict],
        requirement: str,
    ) -> List[Dict]:
        """
        对页面按置信度排序

        排序因素：
        1. 与需求的语义相关性
        2. 页面在流程中的位置（入口页面优先）
        3. 历史使用频率
        """
        for page in pages:
            score = page.get("score", page.get("confidence", 0.5))

            # 入口页面加分
            title = page.get("title", "").lower()
            url = page.get("url", "").lower()
            entry_keywords = ["登录", "首页", "主页", "login", "home", "index", "landing"]
            for kw in entry_keywords:
                if kw in title or kw in url:
                    score += 0.15
                    break

            # 需求关键词匹配加分
            req_lower = requirement.lower()
            page_text = f"{title} {url}".lower()
            for word in req_lower.split():
                if len(word) > 1 and word in page_text:
                    score += 0.05

            page["confidence"] = min(score, 1.0)

        return sorted(pages, key=lambda p: p.get("confidence", 0), reverse=True)

    def build_flow(
        self,
        requirement: str,
        pages: List[Dict],
        relations: List[Dict],
        elements: List[Dict] = None,
        target_url: str = "",
    ) -> Dict[str, Any]:
        """
        构建完整的页面流程

        输入：页面列表 + 关联关系
        输出：有序的页面流程图
        """
        if not pages:
            return {"page_flow": [], "transitions": [], "entry_url": target_url, "variables": {}}

        ranked_pages = self.rank_pages(pages, requirement)

        page_flow = []
        transitions = []
        variables = {}

        for i, page in enumerate(ranked_pages):
            page_entry = {
                "page_id": page.get("page_id", f"page_{i}"),
                "title": page.get("title", f"页面{i+1}"),
                "url": page.get("url", ""),
                "order": i,
                "actions": page.get("actions", []),
                "state_vars": page.get("state_vars", {}),
                "source": page.get("source", ""),
                "score": page.get("confidence", page.get("score", 0)),
            }
            page_flow.append(page_entry)

            for key, val in page_entry.get("state_vars", {}).items():
                variables[key] = val

        if relations:
            for rel in relations:
                transitions.append({
                    "from_page": rel.get("source", ""),
                    "to_page": rel.get("target", ""),
                    "trigger": rel.get("trigger", ""),
                    "trigger_locator": rel.get("trigger_locator", ""),
                    "confidence": rel.get("score", rel.get("confidence", 0.5)),
                    "source": rel.get("source_meta", rel.get("source", "")),
                })
        else:
            for i in range(len(ranked_pages) - 1):
                transitions.append({
                    "from_page": ranked_pages[i].get("page_id", f"page_{i}"),
                    "to_page": ranked_pages[i+1].get("page_id", f"page_{i+1}"),
                    "trigger": "",
                    "trigger_locator": "",
                    "confidence": 0.5,
                    "source": "inferred",
                })

        entry_url = target_url
        if not entry_url and page_flow:
            entry_url = page_flow[0].get("url", "")

        if elements:
            elem_by_page = {}
            for elem in elements:
                page_url = elem.get("page_url", "")
                if page_url not in elem_by_page:
                    elem_by_page[page_url] = []
                elem_by_page[page_url].append(elem)

            for pf in page_flow:
                page_url = pf.get("url", "")
                if page_url in elem_by_page:
                    pf["elements"] = elem_by_page[page_url]

        return {
            "page_flow": page_flow,
            "transitions": transitions,
            "entry_url": entry_url,
            "variables": variables,
        }

    def save_relations(
        self,
        db,
        task_id: int,
        relations: List[Dict],
    ) -> int:
        """保存页面关联关系到数据库（通过 StorageRouter 写入）

        Note: db 参数保留用于向后兼容，内部使用 StorageRouter。
        """
        from app.services.context_router.storage_router import get_storage_router

        storage = get_storage_router()
        saved = 0
        for i, rel in enumerate(relations):
            try:
                record_id = storage.mysql_save("PageRelation", {
                    "task_id": task_id,
                    "source_page": rel.get("source", rel.get("from_page", "")),
                    "source_page_title": rel.get("source_title", ""),
                    "target_page": rel.get("target", rel.get("to_page", "")),
                    "target_page_title": rel.get("target_title", ""),
                    "relation_type": rel.get("type", rel.get("relation_type", "flow")),
                    "confidence": rel.get("confidence", rel.get("score", 0.5)),
                    "trigger": rel.get("trigger", ""),
                    "trigger_locator": rel.get("trigger_locator", ""),
                    "sort_order": i,
                    "metadata_json": json.dumps(rel.get("metadata", {}), ensure_ascii=False) if rel.get("metadata") else None,
                })
                if record_id:
                    saved += 1
            except Exception as e:
                log.warning(f"保存页面关联失败: {e}")

        return saved

    # ==================== 内部方法 ====================

    def _infer_pages_from_llm(
        self,
        requirement: str,
        steps: List[str],
        target_url: str = "",
    ) -> Dict[str, Any]:
        """使用LLM从需求文本中推理页面流（不查数据库，纯 LLM 推理）"""
        try:
            import httpx

            api_key = settings.QWEN_API_KEY
            if not api_key:
                return {"pages": [], "relations": []}

            prompt = f"""分析以下测试需求，识别涉及的页面和页面之间的流转关系。

需求：{requirement}

步骤：{json.dumps(steps, ensure_ascii=False)}

目标URL：{target_url or '未知'}

请输出JSON格式：
{{
  "pages": [
    {{"page_id": "login", "title": "登录页", "url": "/login", "confidence": 0.9, "actions": ["输入用户名", "输入密码", "点击登录"]}}
  ],
  "relations": [
    {{"source": "login", "target": "home", "type": "form_submit", "trigger": "点击登录按钮", "confidence": 0.9}}
  ]
}}

注意：
1. page_id用英文简短标识
2. 只输出JSON，不要其他内容
3. 每个页面列出主要操作(actions)
4. 关系类型：navigation/form_submit/redirect/flow/dependency"""

            url = settings.QWEN_API_URL
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": settings.QWEN_MODEL.replace("-vl-plus", "-plus").replace("-vl-max", "-max"),
                "messages": [
                    {"role": "system", "content": "你是测试页面分析专家，擅长从需求中识别页面和页面流转关系。只输出JSON。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
            }

            response = httpx.post(url, json=payload, headers=headers, timeout=30)
            result = response.json()

            if "choices" not in result:
                return {"pages": [], "relations": []}

            content = result["choices"][0]["message"]["content"].strip()

            if content.startswith("```json"):
                content = content[len("```json"):]
            elif content.startswith("```"):
                content = content[len("```"):]
            if content.endswith("```"):
                content = content[:-3]

            parsed = json.loads(content.strip())
            return {
                "pages": parsed.get("pages", []),
                "relations": parsed.get("relations", []),
            }

        except Exception as e:
            log.warning(f"LLM页面推理失败: {e}")
            return {"pages": [], "relations": []}

    # ==================== 管道兼容入口 ====================

    def execute(self, **kwargs) -> Dict[str, Any]:
        """管道兼容入口，供 TaskOrchestrator 统一调用

        从 kwargs 中提取参数，调用 find_related_pages()。
        """
        requirement = kwargs.get("requirement", "")
        if not requirement:
            parsed = kwargs.get("requirement_analysis", {})
            if isinstance(parsed, dict):
                requirement = parsed.get("requirement", parsed.get("raw_text", ""))

        keywords = kwargs.get("keywords")
        steps = kwargs.get("steps")
        target_url = kwargs.get("target_url", "")

        return self.find_related_pages(
            requirement=requirement,
            keywords=keywords,
            steps=steps,
            target_url=target_url,
        )
