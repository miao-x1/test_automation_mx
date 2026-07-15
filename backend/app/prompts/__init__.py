"""
Prompt模板统一管理

所有Agent的提示词统一在此模块管理，禁止在代码中硬编码Prompt
"""
from app.prompts.requirement_prompt import RequirementPrompt
from app.prompts.case_prompt import CasePrompt
from app.prompts.playwright_prompt import PlaywrightPrompt

__all__ = ["RequirementPrompt", "CasePrompt", "PlaywrightPrompt"]
