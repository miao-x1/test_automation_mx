"""
ContextFusion - 上下文融合器

职责：
    将MySQL、Milvus、Neo4j三库检索结果融合为统一的上下文，
    供Agent使用。

融合策略：
    1. 业务数据（MySQL）→ 提供任务/用例/元素的结构化信息
    2. 知识参考（Milvus）→ 提供历史案例和文档片段
    3. 业务关系（Neo4j）→ 提供页面/元素/API的关系链路

输出结构：
    FusedContext {
        business_context: {...}   # MySQL数据
        knowledge_context: {...}  # Milvus数据
        graph_context: {...}      # Neo4j数据
        sources: [...]             # 使用的数据源
        summary: "..."            # 摘要
    }
"""
import logging
from typing import Any, Dict, List, Optional

from app.context.models import FusedContext

logger = logging.getLogger(__name__)


class ContextFusion:
    """上下文融合器

    将三库检索结果合并为统一上下文，
    按业务数据、知识参考、业务关系三类组织。
    """

    def __init__(self):
        logger.info("[ContextFusion] 初始化完成")

    def fuse(
        self,
        mysql_results: Dict[str, Any],
        milvus_results: Dict[str, Any],
        neo4j_results: Dict[str, Any],
    ) -> FusedContext:
        """
        融合三库检索结果

        Args:
            mysql_results: MySQL检索结果（按表名分组）
            milvus_results: Milvus检索结果（按集合名分组）
            neo4j_results: Neo4j检索结果（节点和关系）

        Returns:
            FusedContext: 融合后的统一上下文
        """
        sources = []

        # 1. 组织MySQL业务数据
        business_context = self._organize_mysql(mysql_results)
        if business_context:
            sources.append("MySQL")

        # 2. 组织Milvus知识参考
        knowledge_context = self._organize_milvus(milvus_results)
        if knowledge_context:
            sources.append("Milvus")

        # 3. 组织Neo4j业务关系
        graph_context = self._organize_neo4j(neo4j_results)
        if graph_context:
            sources.append("Neo4j")

        # 4. 生成摘要
        summary = self._generate_summary(business_context, knowledge_context, graph_context)

        fused = FusedContext(
            business_context=business_context,
            knowledge_context=knowledge_context,
            graph_context=graph_context,
            sources=sources,
            summary=summary,
        )

        logger.info(
            f"[ContextFusion] 融合完成 | "
            f"来源: {sources} | "
            f"业务数据项: {len(business_context)} | "
            f"知识参考项: {len(knowledge_context)} | "
            f"关系数据项: {len(graph_context)}"
        )

        return fused

    def _organize_mysql(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """组织MySQL结果为业务上下文"""
        if not results:
            return {}

        organized = {}
        for table_name, rows in results.items():
            if not rows:
                continue
            if isinstance(rows, list):
                organized[table_name] = {
                    "count": len(rows),
                    "data": rows[:50],  # 限制返回量
                }
            else:
                organized[table_name] = rows

        return organized

    def _organize_milvus(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """组织Milvus结果为知识上下文"""
        if not results:
            return {}

        organized = {}
        for collection, items in results.items():
            if not items:
                continue
            if isinstance(items, list):
                # 提取关键信息
                references = []
                for item in items[:10]:  # TopK限制
                    if isinstance(item, dict):
                        references.append({
                            "text": item.get("text", item.get("content", ""))[:500],
                            "score": item.get("score", item.get("distance", 0)),
                            "source_type": item.get("source_type", ""),
                            "entity_type": item.get("entity_type", ""),
                            "metadata": item.get("metadata", {}),
                        })
                organized[collection] = {
                    "count": len(references),
                    "references": references,
                }

        return organized

    def _organize_neo4j(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """组织Neo4j结果为关系上下文"""
        if not results:
            return {}

        organized = {}
        for key, value in results.items():
            if not value:
                continue
            if key == "nodes" and isinstance(value, list):
                organized["nodes"] = {
                    "count": len(value),
                    "data": value[:30],  # 限制返回量
                }
            elif key == "relationships" and isinstance(value, list):
                organized["relationships"] = {
                    "count": len(value),
                    "data": value[:30],
                }
            elif key == "paths" and isinstance(value, list):
                organized["paths"] = {
                    "count": len(value),
                    "data": value[:10],
                }
            else:
                organized[key] = value

        return organized

    def _generate_summary(
        self,
        business: Dict[str, Any],
        knowledge: Dict[str, Any],
        graph: Dict[str, Any],
    ) -> str:
        """生成上下文摘要"""
        parts = []

        if business:
            table_counts = {k: v.get("count", 0) for k, v in business.items() if isinstance(v, dict)}
            parts.append(f"业务数据({table_counts})")

        if knowledge:
            ref_counts = {k: v.get("count", 0) for k, v in knowledge.items() if isinstance(v, dict)}
            parts.append(f"知识参考({ref_counts})")

        if graph:
            node_count = graph.get("nodes", {}).get("count", 0) if isinstance(graph.get("nodes"), dict) else 0
            rel_count = graph.get("relationships", {}).get("count", 0) if isinstance(graph.get("relationships"), dict) else 0
            parts.append(f"关系数据(节点{node_count}/关系{rel_count})")

        return " | ".join(parts) if parts else "无可用上下文"


# 单例
_fusion: Optional[ContextFusion] = None


def get_context_fusion() -> ContextFusion:
    """获取ContextFusion单例"""
    global _fusion
    if _fusion is None:
        _fusion = ContextFusion()
    return _fusion
