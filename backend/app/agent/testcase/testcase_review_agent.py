"""
TestCaseReviewAgent - 用例审核Agent

职责：审核测试用例质量，检查步骤完整性、预期明确性、异常覆盖度。

输入：测试用例（case_name, precondition, steps, expected_result, priority, type）
输出：{
    score: int,               # 质量评分（0-100）
    review_result: str,       # 审核结果（pass/need_revision/reject）
    suggestions: List[str],   # 改进建议列表
    issues: List[Dict]         # 问题列表
}

检查维度：
    1. 步骤完整性
    2. 预期明确性
    3. 异常覆盖
    4. 前置条件
    5. 可执行性
    6. 优先级合理性
"""
import json
from typing import Any, Dict, List

from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability
from app.prompts.testcase.review_prompt import ReviewPrompt


class TestCaseReviewAgent(NewBaseAgent):
    """测试用例审核Agent

    对生成的测试用例进行质量审核，
    检查步骤完整性、预期明确性、异常覆盖等维度，
    给出评分和改进建议。
    """

    agent_name = "testcase_review_agent"
    display_name = "用例审核Agent"
    description = "审核测试用例质量，检查步骤完整性、预期明确性、异常覆盖度"
    capabilities = [AgentCapability.FEEDBACK]

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        执行用例审核

        Args:
            test_case: 单个测试用例
            test_cases: 测试用例列表（批量审核）
            test_point_info: 关联的测试点信息（可选）

        Returns:
            {
                status: "success",
                reviews: List[Dict],  # 审核结果列表
                total: int,           # 审核用例数
                avg_score: float,     # 平均分
            }
        """
        test_case = kwargs.get("test_case", {})
        test_cases = kwargs.get("test_cases", [])
        test_point_info = kwargs.get("test_point_info", {})

        # 批量审核
        if test_cases:
            return await self._review_batch(test_cases, test_point_info)

        # 单个审核
        if not test_case:
            return {
                "status": "error",
                "error": "缺少test_case参数",
            }

        return await self._review_single(test_case, test_point_info)

    async def _review_single(
        self,
        test_case: Dict[str, Any],
        test_point_info: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """审核单个测试用例"""
        case_name = test_case.get("case_name", "")
        self.logger.info(f"[用例审核] 开始 | 用例: {case_name}")

        # 解析steps（可能是JSON字符串或列表）
        steps = test_case.get("steps", [])
        if isinstance(steps, str):
            try:
                steps = json.loads(steps)
            except json.JSONDecodeError:
                steps = []

        # 基础规则检查（不依赖LLM）
        basic_issues = self._basic_rule_check(test_case, steps)

        # 构建提示词
        user_prompt = ReviewPrompt.build(
            case_name=case_name,
            precondition=test_case.get("precondition", ""),
            steps=steps,
            expected_result=test_case.get("expected_result", ""),
            priority=test_case.get("priority", "P1"),
            case_type=test_case.get("type", "functional"),
            test_point_info=test_point_info,
        )

        # 调用LLM审核
        try:
            response = await self.call_llm(
                system_prompt=ReviewPrompt.SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.2,
            )

            review = self._parse_json_response(response)

            # 合并基础规则检查的问题
            if basic_issues:
                existing_issues = review.get("issues", [])
                existing_issues.extend(basic_issues)
                review["issues"] = existing_issues

            # 确保score在0-100范围
            score = review.get("score", 0)
            review["score"] = max(0, min(100, int(score)))

            # 确保review_result与score一致
            if review["score"] >= 80:
                review["review_result"] = "pass"
            elif review["score"] >= 50:
                review["review_result"] = "need_revision"
            else:
                review["review_result"] = "reject"

            self.logger.info(
                f"[用例审核] 完成 | 用例: {case_name} | 评分: {review['score']} | "
                f"结果: {review['review_result']}"
            )

            return {
                "status": "success",
                "case_name": case_name,
                "score": review["score"],
                "review_result": review["review_result"],
                "suggestions": review.get("suggestions", []),
                "issues": review.get("issues", []),
            }

        except Exception as e:
            self.logger.error(f"[用例审核] 失败 | 用例: {case_name} | 错误: {e}")
            return {
                "status": "error",
                "error": str(e),
                "case_name": case_name,
            }

    async def _review_batch(
        self,
        test_cases: List[Dict[str, Any]],
        test_point_info: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """批量审核测试用例"""
        self.logger.info(f"[用例审核] 批量审核 | 用例数: {len(test_cases)}")

        reviews = []
        total_score = 0

        for case in test_cases:
            result = await self._review_single(case, test_point_info)
            if result.get("status") == "success":
                reviews.append(result)
                total_score += result["score"]

        avg_score = total_score / len(reviews) if reviews else 0

        return {
            "status": "success",
            "reviews": reviews,
            "total": len(reviews),
            "avg_score": round(avg_score, 1),
        }

    def _basic_rule_check(
        self,
        test_case: Dict[str, Any],
        steps: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """基础规则检查（不依赖LLM）

        检查一些明显的规则问题，作为LLM审核的补充。
        """
        issues = []

        # 检查步骤数量
        if len(steps) < 2:
            issues.append({
                "severity": "high",
                "category": "step_completeness",
                "description": f"步骤数过少（{len(steps)}步），建议至少3步",
                "suggestion": "增加测试步骤，确保覆盖完整流程",
            })

        # 检查前置条件
        if not test_case.get("precondition"):
            issues.append({
                "severity": "medium",
                "category": "precondition",
                "description": "未设置前置条件",
                "suggestion": "添加数据准备和环境要求",
            })

        # 检查预期结果
        if not test_case.get("expected_result"):
            issues.append({
                "severity": "high",
                "category": "expected_clarity",
                "description": "未设置预期结果",
                "suggestion": "添加可验证的预期结果",
            })

        # 检查每步是否有expected
        for i, step in enumerate(steps, 1):
            if isinstance(step, dict) and not step.get("expected"):
                issues.append({
                    "severity": "low",
                    "category": "expected_clarity",
                    "description": f"步骤{i}缺少预期结果",
                    "suggestion": f"为步骤{i}添加预期结果",
                })

        return issues

    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """解析LLM返回的JSON响应"""
        if not response:
            return {}

        text = response.strip()

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
            self.logger.warning("[用例审核] JSON解析失败，返回默认结果")
            return {
                "score": 50,
                "review_result": "need_revision",
                "suggestions": ["JSON解析失败，建议人工审核"],
                "issues": [],
            }
