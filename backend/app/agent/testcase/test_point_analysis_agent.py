"""
TestPointAnalysisAgent - 测试点分析Agent

职责：根据需求解析结果，分析并生成全面的测试点列表。

输入：RequirementAnalysisResult（business_module, function_points, business_flow, test_scope）
输出：测试点列表，覆盖：
  - 正常流程（functional）
  - 异常流程（error）
  - 边界条件（boundary）
  - 权限验证（permission）
  - 数据校验（data_validation）
"""
import json
from typing import Any, Dict, List

from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability
from app.prompts.testcase.test_point_prompt import TestPointPrompt


class TestPointAnalysisAgent(NewBaseAgent):
    """测试点分析Agent

    从需求解析结果中提取全面的测试点，
    确保覆盖正常流程、异常流程、边界条件、权限验证、数据校验。
    """

    agent_name = "test_point_analysis_agent"
    display_name = "测试点分析Agent"
    description = "根据需求解析结果分析测试点，覆盖功能/异常/边界/权限/数据校验"
    capabilities = [AgentCapability.CASE_GENERATE]

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        执行测试点分析

        Args:
            business_module: 业务模块名称
            function_points: 功能点列表
            business_flow: 业务流程列表
            test_scope: 测试范围

        Returns:
            {
                status: "success",
                test_points: List[Dict],  # 测试点列表
                total: int                # 测试点总数
            }
        """
        business_module = kwargs.get("business_module", "")
        function_points = kwargs.get("function_points", [])
        business_flow = kwargs.get("business_flow", [])
        test_scope = kwargs.get("test_scope", {})

        # 兼容：如果传入的是上一步的完整结果
        if not business_module and "result" in kwargs:
            result = kwargs["result"]
            if isinstance(result, dict):
                business_module = result.get("business_module", "")
                function_points = result.get("function_points", [])
                business_flow = result.get("business_flow", [])
                test_scope = result.get("test_scope", {})

        if not business_module:
            return {
                "status": "error",
                "error": "缺少business_module，无法分析测试点",
            }

        self.logger.info(f"[测试点分析] 开始分析 | 模块: {business_module}")

        from app.knowledge.testing_expert import expert_prompt_for

        user_prompt = TestPointPrompt.build(
            business_module=business_module,
            function_points=function_points,
            business_flow=business_flow,
            test_scope=test_scope,
            expert_context=expert_prompt_for(f"{business_module} {function_points}"),
        )

        # 调用LLM
        try:
            response = await self.call_llm(
                system_prompt=TestPointPrompt.SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.4,
            )

            # 解析JSON响应
            test_points = self._parse_json_list_response(response)

            self.logger.info(
                f"[测试点分析] 完成 | 测试点数: {len(test_points)}"
            )

            return {
                "status": "success",
                "test_points": test_points,
                "total": len(test_points),
            }

        except Exception as e:
            self.logger.error(f"[测试点分析] 失败: {e}")
            return {
                "status": "error",
                "error": str(e),
            }

    def _parse_json_list_response(self, response: str) -> List[Dict[str, Any]]:
        """解析LLM返回的JSON数组响应"""
        if not response:
            return []

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
            result = json.loads(text)
            if isinstance(result, list):
                return result
            elif isinstance(result, dict) and "test_points" in result:
                return result["test_points"]
            else:
                return [result] if isinstance(result, dict) else []
        except json.JSONDecodeError:
            # 尝试提取JSON数组
            start = text.find("[")
            end = text.rfind("]")
            if start != -1 and end != -1:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    pass
            self.logger.warning("[测试点分析] JSON解析失败，返回空列表")
            return []
