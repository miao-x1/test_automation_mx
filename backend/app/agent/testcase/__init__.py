"""
测试用例生成 Agent 模块

包含4个核心Agent：
- RequirementAnalysisAgent: 需求解析
- TestPointAnalysisAgent: 测试点分析
- TestCaseGeneratorAgent: 用例生成（含RAG检索集成）
- TestCaseReviewAgent: 用例审核

调用流程：
    需求输入
      → RequirementAnalysisAgent (解析需求)
      → TestPointAnalysisAgent (分析测试点)
      → RAG检索 (检索历史知识)
      → TestCaseGeneratorAgent (生成用例)
      → TestCaseReviewAgent (审核用例)
      → StorageAgent (保存数据库)
      → MindMapAgent (生成思维导图)

所有Agent继承 BaseAgent，通过 AgentFactory 创建，
由 TaskOrchestrator 编排执行。
"""
from app.agent.testcase.requirement_analysis_agent import RequirementAnalysisAgent
from app.agent.testcase.test_point_analysis_agent import TestPointAnalysisAgent
from app.agent.testcase.testcase_generator_agent import TestCaseGeneratorAgent
from app.agent.testcase.testcase_review_agent import TestCaseReviewAgent
from app.agent.testcase.knowledge_sync_agent import KnowledgeSyncAgent

__all__ = [
    "RequirementAnalysisAgent",
    "TestPointAnalysisAgent",
    "TestCaseGeneratorAgent",
    "TestCaseReviewAgent",
    "KnowledgeSyncAgent",
]
