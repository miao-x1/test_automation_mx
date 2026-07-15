"""
ReviewAgent - 审查

职责：审查测试用例质量
输入：GenerationContext + CaseDTO列表
输出：ReviewResultDTO

禁止：数据库/HTTP/文件
"""
from typing import List
from app.services.generation.context import GenerationContext, CaseDTO, ReviewResultDTO
from app.core.logger import log


class ReviewAgent:
    """审查Agent"""

    def review(self, ctx: GenerationContext, cases: List[CaseDTO]) -> ReviewResultDTO:
        """
        审查测试用例质量

        Args:
            ctx: 生成上下文
            cases: 待审查用例列表

        Returns:
            ReviewResultDTO
        """
        issues = []
        suggestions = []
        quality_scores = []

        for i, case in enumerate(cases):
            score = 1.0

            # 校验标题
            if not case.title or case.title == "未命名用例":
                issues.append(f"用例{i+1}: 标题为空")
                score -= 0.2

            # 校验步骤
            if not case.steps:
                issues.append(f"用例{i+1}: 步骤为空")
                score -= 0.3
            else:
                for j, step in enumerate(case.steps):
                    if not step.get("action") and not step.get("url"):
                        issues.append(f"用例{i+1}步骤{j+1}: 缺少操作描述")
                        score -= 0.1

            # 校验断言
            if not case.assertions:
                issues.append(f"用例{i+1}: 断言为空")
                score -= 0.3
                suggestions.append(f"用例{i+1}: 建议添加至少一个断言")

            # 校验预期结果
            if not case.expected_result:
                suggestions.append(f"用例{i+1}: 建议添加预期结果")

            quality_scores.append(max(0, score))

        avg_score = sum(quality_scores) / len(quality_scores) if quality_scores else 0

        # 尝试使用AI审查
        try:
            from app.agent.case.review_agent import ReviewAgent as AIReviewAgent
            ai_agent = AIReviewAgent()
            # AI审查仅做辅助，不覆盖基础校验结果
        except Exception:
            pass

        return ReviewResultDTO(
            passed=len(issues) == 0,
            issues=issues,
            suggestions=suggestions,
            quality_score=avg_score,
        )
