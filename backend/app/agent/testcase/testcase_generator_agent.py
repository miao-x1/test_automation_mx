"""
TestCaseGeneratorAgent - 测试用例生成Agent

职责：根据测试点 + RAG上下文，生成结构化的标准测试用例。

输入：测试点 + RAG检索结果（历史用例、业务规则等）
输出：结构化测试用例（case_name, precondition, steps, expected_result, priority, type）

RAG集成（第四步）：
    1. 根据测试点名称、业务模块、关键词构建查询
    2. 调用RAGAgent检索TopK结果
    3. 过滤低相似度结果
    4. 将过滤后的结果作为上下文发送给LLM
    5. 生成测试用例

设计原则：
    - 不直接把全部知识库发送给LLM
    - 必须经过：检索 → TopK → 过滤 → 生成
"""
import json
from typing import Any, Dict, List, Optional

from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability
from app.prompts.testcase.testcase_generate_prompt import TestCaseGeneratePrompt


class TestCaseGeneratorAgent(NewBaseAgent):
    """测试用例生成Agent

    根据测试点 + RAG上下文生成标准化测试用例。
    内置RAG检索集成：自动根据测试点查询知识库，过滤后作为上下文。

    流程：
        测试点 → RAG检索(TopK) → 过滤 → LLM生成 → 结构化用例
    """

    agent_name = "testcase_generator_agent"
    display_name = "用例生成Agent"
    description = "根据测试点+RAG上下文生成结构化测试用例，内置RAG检索集成"
    capabilities = [AgentCapability.CASE_GENERATE]

    # RAG配置
    RAG_TOP_K = 10          # 每类检索最大数量
    RAG_MIN_SCORE = 0.3     # 最低相似度阈值
    RAG_MAX_CASES = 5       # 发送给LLM的历史用例最大数
    RAG_MAX_ELEMENTS = 10   # 发送给LLM的元素最大数

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        执行测试用例生成

        Args:
            test_point: 测试点信息（name, type, priority, scenario, description）
            test_points: 测试点列表（批量生成时使用）
            business_module: 业务模块名称（用于RAG查询）
            rag_context: 预检索的RAG上下文（可选，如果不传则自动检索）

        Returns:
            {
                status: "success",
                test_cases: List[Dict],  # 生成的测试用例列表
                total: int,              # 用例总数
                rag_used: bool,          # 是否使用了RAG
            }
        """
        # 支持单个测试点和批量测试点
        test_point = kwargs.get("test_point", {})
        test_points = kwargs.get("test_points", [])
        business_module = kwargs.get("business_module", "")
        pre_rag_context = kwargs.get("rag_context")

        # 如果传入了test_points列表，批量处理
        if test_points:
            return await self._generate_batch(
                test_points=test_points,
                business_module=business_module,
                pre_rag_context=pre_rag_context,
            )

        # 单个测试点处理
        if not test_point:
            return {
                "status": "error",
                "error": "缺少test_point参数",
            }

        return await self._generate_single(
            test_point=test_point,
            business_module=business_module,
            pre_rag_context=pre_rag_context,
        )

    async def _generate_single(
        self,
        test_point: Dict[str, Any],
        business_module: str = "",
        pre_rag_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """为单个测试点生成用例"""
        point_name = test_point.get("name", "")
        self.logger.info(f"[用例生成] 开始 | 测试点: {point_name}")

        # === RAG检索集成（第四步）===
        rag_context = None
        rag_used = False

        if pre_rag_context:
            # 使用预检索的上下文
            rag_context = self._filter_rag_context(pre_rag_context)
            rag_used = True
            self.logger.info(f"[用例生成] 使用预检索RAG上下文")
        else:
            # 自动检索RAG
            rag_context = await self._retrieve_rag(test_point, business_module)
            if rag_context:
                rag_used = True
                self.logger.info(f"[用例生成] RAG检索完成 | 用例数: {len(rag_context.get('cases', []))}")

        # 构建提示词
        user_prompt = TestCaseGeneratePrompt.build(
            test_point=test_point,
            rag_context=rag_context,
        )

        # 调用LLM生成用例
        try:
            response = await self.call_llm(
                system_prompt=TestCaseGeneratePrompt.SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.4,
            )

            # 解析JSON响应
            case = self._parse_json_response(response)

            # 补充RAG引用信息
            rag_refs = []
            if rag_context:
                for c in rag_context.get("cases", [])[:3]:
                    rag_refs.append({"id": c.get("id"), "case_name": c.get("case_name"), "score": c.get("score")})

            case["rag_references"] = rag_refs

            self.logger.info(
                f"[用例生成] 完成 | 用例: {case.get('case_name', '')} | "
                f"步骤数: {len(case.get('steps', []))}"
            )

            return {
                "status": "success",
                "test_case": case,
                "rag_used": rag_used,
            }

        except Exception as e:
            self.logger.error(f"[用例生成] 失败: {e}")
            return {
                "status": "error",
                "error": str(e),
                "test_point": point_name,
            }

    async def _generate_batch(
        self,
        test_points: List[Dict[str, Any]],
        business_module: str = "",
        pre_rag_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """批量生成测试用例"""
        self.logger.info(f"[用例生成] 批量生成 | 测试点数: {len(test_points)}")

        test_cases = []
        for point in test_points:
            result = await self._generate_single(
                test_point=point,
                business_module=business_module,
                pre_rag_context=pre_rag_context,
            )
            if result.get("status") == "success":
                test_cases.append(result["test_case"])
            else:
                self.logger.warning(f"[用例生成] 跳过测试点: {point.get('name', '')}")

        return {
            "status": "success",
            "test_cases": test_cases,
            "total": len(test_cases),
            "rag_used": pre_rag_context is not None,
        }

    async def _retrieve_rag(
        self,
        test_point: Dict[str, Any],
        business_module: str = "",
    ) -> Optional[Dict[str, Any]]:
        """
        RAG检索集成

        流程：检索 → TopK → 过滤

        Args:
            test_point: 测试点信息
            business_module: 业务模块名称

        Returns:
            过滤后的RAG上下文
        """
        try:
            # 构建查询文本
            query_parts = [
                test_point.get("name", ""),
                business_module,
                test_point.get("scenario", ""),
                test_point.get("description", ""),
            ]
            query = " ".join(p for p in query_parts if p)

            if not query:
                return None

            # 直接实例化RAGAgent
            from app.agent.rag.rag_agent import RAGAgent
            agent = RAGAgent()

            # 调用RAG检索
            rag_result = agent.retrieve(query=query, top_k=self.RAG_TOP_K)

            # 过滤低相似度结果
            filtered = self._filter_rag_context(rag_result)

            self.logger.info(
                f"[用例生成] RAG检索 | 查询: {query[:50]} | "
                f"用例: {len(filtered.get('cases', []))} | "
                f"元素: {len(filtered.get('elements', []))} | "
                f"脚本: {len(filtered.get('scripts', []))}"
            )

            return filtered

        except Exception as e:
            self.logger.warning(f"[用例生成] RAG检索失败: {e}")
            return None

    def _filter_rag_context(self, rag_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        过滤RAG检索结果

        - 去除相似度低于阈值的结果
        - 限制每类结果数量（TopK过滤）
        """
        if not rag_context:
            return {}

        filtered_cases = []
        for case in rag_context.get("cases", []):
            score = case.get("score", 0)
            if score >= self.RAG_MIN_SCORE:
                filtered_cases.append(case)
        filtered_cases = filtered_cases[:self.RAG_MAX_CASES]

        filtered_elements = []
        for elem in rag_context.get("elements", []):
            score = elem.get("score", 0)
            if score >= self.RAG_MIN_SCORE:
                filtered_elements.append(elem)
        filtered_elements = filtered_elements[:self.RAG_MAX_ELEMENTS]

        filtered_scripts = rag_context.get("scripts", [])[:3]

        return {
            "cases": filtered_cases,
            "elements": filtered_elements,
            "scripts": filtered_scripts,
        }

    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """解析LLM返回的JSON响应"""
        if not response:
            return {}

        text = response.strip()

        # 去除markdown代码块
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]

        if text.endswith("```"):
            text = text[:-3]

        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    pass
            self.logger.warning("[用例生成] JSON解析失败，返回空结果")
            return {}
