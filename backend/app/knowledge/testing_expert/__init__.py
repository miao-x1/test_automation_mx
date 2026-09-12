"""测试专家知识底座：本地权威知识 + 任务检索，供 Agent 实际使用。"""

from app.knowledge.testing_expert.service import TestingExpertService, expert_prompt_for, get_testing_expert

__all__ = ["TestingExpertService", "expert_prompt_for", "get_testing_expert"]
