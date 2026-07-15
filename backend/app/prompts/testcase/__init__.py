"""
测试用例生成 Prompt 模块

包含4个独立Prompt：
- RequirementAnalysisPrompt: 需求解析
- TestPointPrompt: 测试点分析
- TestCaseGeneratePrompt: 用例生成
- ReviewPrompt: 用例审核
"""
from app.prompts.testcase.requirement_analysis_prompt import RequirementAnalysisPrompt
from app.prompts.testcase.test_point_prompt import TestPointPrompt
from app.prompts.testcase.testcase_generate_prompt import TestCaseGeneratePrompt
from app.prompts.testcase.review_prompt import ReviewPrompt

__all__ = [
    "RequirementAnalysisPrompt",
    "TestPointPrompt",
    "TestCaseGeneratePrompt",
    "ReviewPrompt",
]
