"""
RequirementAnalysisAgent - 需求解析Agent

职责：理解用户输入的测试需求，提取业务模块、功能点、业务流程、测试范围。

输入：{
    requirement_text: str,          # 需求文本
    document_context: str (可选),    # 文档解析结果
    image_description: str (可选)     # 图片描述信息
}

输出：{
    business_module: str,            # 业务模块
    function_points: List[Dict],     # 功能点列表
    business_flow: List[Dict],       # 业务流程
    test_scope: Dict                  # 测试范围
}
"""
import json
from typing import Any, Dict, Optional

from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability
from app.prompts.testcase.requirement_analysis_prompt import RequirementAnalysisPrompt


class RequirementAnalysisAgent(NewBaseAgent):
    """需求解析Agent

    将用户输入的自然语言/文档/图片需求解析为结构化的测试信息。
    输出包含：业务模块、功能点、业务流程、测试范围。
    """

    agent_name = "requirement_analysis_agent"
    display_name = "需求解析Agent"
    description = "理解用户测试需求，提取业务模块、功能点、业务流程和测试范围"
    capabilities = [AgentCapability.REQUIREMENT_PARSE]

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        执行需求解析

        Args:
            requirement_text: 需求文本（必需）
            document_context: 文档解析结果（可选）
            image_description: 图片描述信息（可选）

        Returns:
            结构化需求解析结果
        """
        requirement_text = kwargs.get("requirement_text", "")
        document_context = kwargs.get("document_context", "")
        image_description = kwargs.get("image_description", "")

        if not requirement_text and not document_context and not image_description:
            return {
                "status": "error",
                "error": "缺少需求输入：requirement_text, document_context, image_description 至少需要一个",
            }

        self.logger.info(f"[需求解析] 开始解析需求: {requirement_text[:50]}...")

        from app.knowledge.testing_expert import expert_prompt_for

        user_prompt = RequirementAnalysisPrompt.build(
            requirement_text=requirement_text,
            document_context=document_context or None,
            image_description=image_description or None,
            expert_context=expert_prompt_for(requirement_text or document_context or image_description),
        )

        # 调用LLM
        try:
            response = await self.call_llm(
                system_prompt=RequirementAnalysisPrompt.SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.3,
            )

            # 解析JSON响应
            result = self._parse_json_response(response)

            self.logger.info(
                f"[需求解析] 完成 | 模块: {result.get('business_module', '')} | "
                f"功能点数: {len(result.get('function_points', []))}"
            )

            return {
                "status": "success",
                "business_module": result.get("business_module", ""),
                "function_points": result.get("function_points", []),
                "business_flow": result.get("business_flow", []),
                "test_scope": result.get("test_scope", {}),
            }

        except Exception as e:
            self.logger.error(f"[需求解析] 失败: {e}")
            return {
                "status": "error",
                "error": str(e),
            }

    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """解析LLM返回的JSON响应

        处理LLM可能返回的markdown代码块包裹的JSON。
        """
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
            # 尝试提取第一个JSON对象
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    pass
            self.logger.warning(f"[需求解析] JSON解析失败，返回空结果")
            return {}
