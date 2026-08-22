"""
MindmapAgent - 思维导图

职责：根据需求生成思维导图
输入：GenerationContext
输出：MindmapDTO

禁止：数据库/HTTP/文件
"""
from typing import Any, Dict
from app.services.generation.context import GenerationContext, MindmapDTO
from app.core.logger import log


class MindmapAgent:
    """思维导图Agent"""

    def generate(self, ctx: GenerationContext) -> MindmapDTO:
        """
        根据需求生成思维导图

        Args:
            ctx: 生成上下文

        Returns:
            MindmapDTO
        """
        try:
            from app.agent.case.mindmap_agent import MindmapAgent as AIMindmapAgent
            agent = AIMindmapAgent()
            result = agent.generate(
                requirement_context=ctx.requirement_summary or ctx.requirement,
                features=ctx.features,
            )

            if isinstance(result, dict):
                return MindmapDTO(
                    nodes=result.get("nodes", []),
                    edges=result.get("edges", []),
                    summary=result.get("summary", ""),
                )

            return MindmapDTO(summary=str(result))

        except Exception as e:
            log.warning(f"MindmapAgent | 思维导图生成失败: {e}")
            # 降级：基于features构建简单结构
            nodes = [{"id": "root", "label": "需求", "type": "root"}]
            edges = []
            for i, feature in enumerate(ctx.features):
                fid = f"f{i}"
                nodes.append({"id": fid, "label": feature.get("feature_name", f"特性{i+1}"), "type": "feature"})
                edges.append({"source": "root", "target": fid})
            return MindmapDTO(nodes=nodes, edges=edges, summary=ctx.requirement_summary[:200])
