"""
RagAgent - RAG检索

职责：从知识库检索相关上下文
输入：GenerationContext
输出：RAGResultDTO

禁止：数据库/HTTP/文件（通过knowledge client）
"""
from typing import Any, Dict, Optional
from app.services.generation.context import GenerationContext, RAGResultDTO
from app.core.logger import log


class RagAgent:
    """RAG检索Agent"""

    def retrieve(self, ctx: GenerationContext) -> RAGResultDTO:
        """
        从知识库检索相关上下文

        Args:
            ctx: 生成上下文

        Returns:
            RAGResultDTO
        """
        if not ctx.config.get("use_rag", True):
            return RAGResultDTO(has_context=False)

        try:
            from app.agent.case.rag_context_agent import RAGContextAgent
            agent = RAGContextAgent()
            result = agent.retrieve_for_l1(
                requirement_context=ctx.requirement_summary or ctx.requirement,
                source_type=ctx.config.get("source_type", "text"),
                project_id=ctx.config.get("project_id", ""),
            )

            if result and result.get("total", 0) > 0:
                return RAGResultDTO(
                    context=result.get("context", ""),
                    elements=result.get("elements", []),
                    total=result.get("total", 0),
                    has_context=True,
                )

            # 降级：使用默认业务规则
            from app.services.case.compiler_utils import get_default_business_rules
            default_rules = get_default_business_rules()
            return RAGResultDTO(
                context=str(default_rules),
                total=0,
                has_context=bool(default_rules),
            )

        except Exception as e:
            log.warning(f"RagAgent | RAG检索失败: {e}")
            return RAGResultDTO(has_context=False)
