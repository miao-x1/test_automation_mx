"""
RAGAgent - 检索增强Agent

架构变更：
  原：Agent → Milvus（直接调用）
  新：Agent → ContextRouter → Milvus + MySQL + Neo4j

职责：根据测试步骤，通过 ContextRouter 召回：
1. 页面元素（ContextType.PAGE_ELEMENT → MySQL + Milvus + Neo4j）
2. 历史测试用例（ContextType.TEST_CASE → Milvus）
3. 历史脚本（ContextType.SCRIPT → Milvus + MySQL）

输入：需求步骤列表
输出：召回的元素、用例、脚本
"""
import json
import time as _time
from typing import Dict, Any, List, Optional
from app.core.config import settings
from app.core.logger import log
from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability


class RAGAgent(NewBaseAgent):
    """RAG检索Agent

    所有查询通过 ContextRouter 路由，禁止直接调用 Milvus。
    """

    agent_name = "rag_agent"
    display_name = "RAG检索Agent"
    description = "通过ContextRouter从UI元素、用例、脚本三个知识库中做相似检索"
    capabilities = [AgentCapability.RAG_RETRIEVE]

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)
        self.agent_type = "rag"
        self.model = None
        self.system_prompt = None
        self._router = None

    @property
    def router(self):
        """延迟加载 ContextRouter"""
        if self._router is None:
            from app.services.context_router import get_context_router
            self._router = get_context_router()
        return self._router

    # ------------------------------------------------------------------
    # 核心检索（通过 ContextRouter）
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        top_k: int = 10
    ) -> Dict[str, Any]:
        """
        根据查询文本检索相关元素、用例和脚本

        所有查询通过 ContextRouter 路由：
          - 页面元素 → ContextType.PAGE_ELEMENT (MySQL + Milvus + Neo4j)
          - 测试用例 → ContextType.TEST_CASE (Milvus)
          - 历史脚本 → ContextType.SCRIPT (Milvus + MySQL)

        Args:
            query: 查询文本（需求描述或步骤）
            top_k: 每类返回的最大数量

        Returns:
            检索结果，包含elements、cases、scripts
        """
        from app.services.context_router import ContextType

        _retrieve_start = _time.time()
        log.info(f"[DEBUG] 开始：RAGAgent.retrieve | 输入：query={query[:50]}, top_k={top_k}")

        # 通过 ContextRouter 检索三类上下文
        elements_result = self.router.retrieve_sync(
            query=query,
            context_type=ContextType.PAGE_ELEMENT,
            top_k=top_k,
        )
        cases_result = self.router.retrieve_sync(
            query=query,
            context_type=ContextType.TEST_CASE,
            top_k=max(3, top_k // 2),
        )
        scripts_result = self.router.retrieve_sync(
            query=query,
            context_type=ContextType.SCRIPT,
            top_k=3,
        )

        # 转换为原有输出格式（向后兼容）
        elements = self._extract_elements(elements_result)
        cases = self._extract_cases(cases_result)
        scripts = self._extract_scripts(scripts_result)

        result = {
            "elements": elements,
            "cases": cases,
            "scripts": scripts,
            "element_count": len(elements),
            "case_count": len(cases),
            "script_count": len(scripts),
        }

        _retrieve_elapsed = _time.time() - _retrieve_start
        log.info(
            f"[DEBUG] 结束：RAGAgent.retrieve | "
            f"elements={len(elements)}, cases={len(cases)}, scripts={len(scripts)} | "
            f"耗时：{_retrieve_elapsed:.2f}s"
        )
        log.info(
            f"RAGAgent | 检索完成(via ContextRouter) | "
            f"elements={len(elements)}, cases={len(cases)}, scripts={len(scripts)}"
        )
        return result

    # ------------------------------------------------------------------
    # 结果转换（ContextRouter → RAGAgent 格式）
    # ------------------------------------------------------------------

    def _extract_elements(self, ctx_result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """从 ContextRouter 结果中提取页面元素"""
        elements: List[Dict[str, Any]] = []
        seen_ids: set = set()

        for item in ctx_result.get("results", []):
            item_id = item.get("id", "")
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)

            entity = item.get("entity", {})
            elements.append({
                "id": item_id,
                "score": item.get("score", 0),
                "task_id": entity.get("task_id"),
                "page_name": entity.get("page_name", item.get("page_name", "")),
                "element_name": entity.get("element_name", item.get("element_name", "")),
                "element_type": entity.get("element_type", ""),
                "locator": entity.get("locator", item.get("locator", "")),
                "description": entity.get("description", ""),
                "source": item.get("source", ""),
            })

        return elements

    def _extract_cases(self, ctx_result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """从 ContextRouter 结果中提取测试用例"""
        cases: List[Dict[str, Any]] = []
        seen_ids: set = set()

        for item in ctx_result.get("results", []):
            item_id = item.get("id", "")
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)

            entity = item.get("entity", {})
            steps_raw = entity.get("steps", "[]")
            try:
                steps = json.loads(steps_raw) if isinstance(steps_raw, str) else steps_raw
            except (json.JSONDecodeError, TypeError):
                steps = []

            cases.append({
                "id": item_id,
                "score": item.get("score", 0),
                "task_id": entity.get("task_id"),
                "case_name": entity.get("case_name", ""),
                "description": entity.get("description", ""),
                "steps": steps,
                "source": item.get("source", ""),
            })

        return cases

    def _extract_scripts(self, ctx_result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """从 ContextRouter 结果中提取脚本"""
        scripts: List[Dict[str, Any]] = []
        seen_ids: set = set()

        for item in ctx_result.get("results", []):
            item_id = item.get("id", "")
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)

            entity = item.get("entity", {})
            scripts.append({
                "id": item_id,
                "score": item.get("score", 0),
                "task_id": entity.get("task_id"),
                "script_name": entity.get("script_name", ""),
                "script_content": entity.get("script_content", ""),
                "description": entity.get("description", ""),
                "source": item.get("source", ""),
            })

        return scripts

    # ------------------------------------------------------------------
    # 批量检索
    # ------------------------------------------------------------------

    def retrieve_batch(
        self,
        steps: List[str],
        top_k: int = 5,
    ) -> Dict[str, Any]:
        """
        按步骤逐个检索，合并去重后返回

        比retrieve()更精准：每个步骤单独通过ContextRouter检索，
        避免多个意图混合导致检索不准。

        Args:
            steps: 拆解后的步骤列表，如 ["打开登录页", "输入错误密码", "验证错误提示"]
            top_k: 每个步骤每类返回的最大数量

        Returns:
            合并去重后的检索结果，格式与retrieve()一致
        """
        if not steps:
            return self.retrieve("", top_k=top_k)

        _batch_start = _time.time()
        log.info(f"RAGAgent | 批量检索开始 | steps={len(steps)}, top_k={top_k}")

        all_elements: List[Dict[str, Any]] = []
        all_cases: List[Dict[str, Any]] = []
        all_scripts: List[Dict[str, Any]] = []
        seen_element_ids: set = set()
        seen_case_ids: set = set()
        seen_script_ids: set = set()

        for i, step in enumerate(steps):
            if not step or not step.strip():
                continue

            # 复用已有的retrieve方法查单个步骤（内部走ContextRouter）
            result = self.retrieve(step, top_k=top_k)

            # 元素去重合并（按id去重，保留score更高的）
            for elem in result.get("elements", []):
                eid = elem.get("id")
                if eid not in seen_element_ids:
                    elem["matched_step"] = step
                    all_elements.append(elem)
                    seen_element_ids.add(eid)

            # 用例去重合并
            for case in result.get("cases", []):
                cid = case.get("id")
                if cid not in seen_case_ids:
                    case["matched_step"] = step
                    all_cases.append(case)
                    seen_case_ids.add(cid)

            # 脚本去重合并
            for script in result.get("scripts", []):
                sid = script.get("id")
                if sid not in seen_script_ids:
                    script["matched_step"] = step
                    all_scripts.append(script)
                    seen_script_ids.add(sid)

        # 按score降序排序
        all_elements.sort(key=lambda x: x.get("score", 0), reverse=True)
        all_cases.sort(key=lambda x: x.get("score", 0), reverse=True)
        all_scripts.sort(key=lambda x: x.get("score", 0), reverse=True)

        _elapsed = _time.time() - _batch_start
        log.info(
            f"RAGAgent | 批量检索完成 | "
            f"steps={len(steps)}, "
            f"elements={len(all_elements)}, "
            f"cases={len(all_cases)}, "
            f"scripts={len(all_scripts)} | "
            f"耗时：{_elapsed:.2f}s"
        )

        return {
            "elements": all_elements,
            "cases": all_cases,
            "scripts": all_scripts,
            "element_count": len(all_elements),
            "case_count": len(all_cases),
            "script_count": len(all_scripts),
            "query_steps": steps,
        }

    def execute(self, **kwargs) -> Dict[str, Any]:
        """
        统一执行入口（BaseAgent接口）

        支持两种模式：
        - 传 steps 参数：按步骤逐个检索（retrieve_batch）
        - 传 query 参数：整条文本一次检索（retrieve）
        """
        steps = kwargs.get("steps")
        if steps:
            top_k = kwargs.get("top_k", 5)
            result = self.retrieve_batch(steps, top_k=top_k)
        else:
            query = kwargs.get("query", "")
            if not query:
                # 管道兼容：从 requirement / target_url 中提取检索词
                query = kwargs.get("requirement", "") or kwargs.get("target_url", "")
            top_k = kwargs.get("top_k", 10)
            result = self.retrieve(query, top_k=top_k)
        self.emit("retrieved", result)
        return result

    def emit(self, event: str, data: Any = None) -> None:
        """发布消息到MessageBus"""
        from app.agent.core.message_bus import MessageBus
        bus = MessageBus()
        bus.publish(f"{self.agent_name}.{event}", self.agent_name, data)
