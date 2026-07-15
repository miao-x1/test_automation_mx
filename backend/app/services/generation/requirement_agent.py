"""
RequirementAgent - 需求理解

职责：理解需求，提取特性/功能点
输入：GenerationContext
输出：List[Dict]（特性列表）

禁止：数据库/HTTP/文件
"""
from typing import Any, Dict, List
from app.services.generation.context import GenerationContext
from app.core.logger import log


class RequirementAgent:
    """需求理解Agent"""

    def analyze(self, ctx: GenerationContext) -> List[Dict[str, Any]]:
        """
        理解需求，提取特性/功能点

        Args:
            ctx: 生成上下文

        Returns:
            特性列表 [{"feature_name", "description", "test_points"}]
        """
        try:
            from app.agent.case.requirement_understanding_agent import RequirementUnderstandingAgent
            agent = RequirementUnderstandingAgent()
            result = agent.understand(
                requirement_context=ctx.requirement_summary or ctx.requirement,
                source_type=ctx.config.get("source_type", "text"),
            )
            if isinstance(result, list):
                return result
            if isinstance(result, dict):
                return result.get("features", [result])
            return [{"feature_name": "默认特性", "description": ctx.requirement_summary[:200], "test_points": []}]
        except Exception as e:
            log.warning(f"RequirementAgent | 需求理解失败: {e}")
            return [{"feature_name": "默认特性", "description": ctx.requirement_summary[:200], "test_points": []}]
