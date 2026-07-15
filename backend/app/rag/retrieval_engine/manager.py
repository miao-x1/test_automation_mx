"""
统一检索管理器

职责：
    根据ContextRouter生成的检索计划（RetrievalPlan），
    调度三个检索器（MySQL/Milvus/Neo4j）并行执行检索，
    并返回融合后的统一上下文。

调用链路：
    RetrievalPlan → RetrievalManager.retrieve()
    → MysqlRetriever.search()
    + MilvusRetriever.search()
    + Neo4jRetriever.search()
    → ContextFusion.fuse()
    → FusedContext
"""
import logging
import time
from typing import Any, Dict, Optional

from app.rag.retrieval_engine.base import BaseRetriever, RetrievalResult
from app.rag.retrieval_engine.mysql_retriever import MysqlRetriever
from app.rag.retrieval_engine.milvus_retriever import MilvusRetriever
from app.rag.retrieval_engine.neo4j_retriever import Neo4jRetriever
from app.context.models import RetrievalPlan, FusedContext
from app.context.fusion import get_context_fusion

logger = logging.getLogger(__name__)


class RetrievalManager:
    """统一检索管理器

    根据检索计划调度三库检索器，
    融合结果返回统一上下文。
    """

    def __init__(self):
        """初始化检索管理器"""
        self._mysql_retriever = MysqlRetriever()
        self._milvus_retriever = MilvusRetriever()
        self._neo4j_retriever = Neo4jRetriever()
        self._fusion = get_context_fusion()
        logger.info("[RetrievalManager] 初始化完成")

    def retrieve(self, plan: RetrievalPlan) -> FusedContext:
        """
        根据检索计划执行三库检索

        Args:
            plan: 检索计划（包含mysql/milvus/neo4j三类查询）

        Returns:
            FusedContext: 融合后的统一上下文
        """
        start_time = time.time()
        logger.info(f"[RetrievalManager] 开始检索 | 任务类型: {plan.task_type}")

        # 执行MySQL检索
        mysql_result = self._retrieve_mysql(plan)
        logger.info(f"[RetrievalManager] MySQL检索完成 | 数据量: {mysql_result.count}")

        # 执行Milvus检索
        milvus_result = self._retrieve_milvus(plan)
        logger.info(f"[RetrievalManager] Milvus检索完成 | 数据量: {milvus_result.count}")

        # 执行Neo4j检索
        neo4j_result = self._retrieve_neo4j(plan)
        logger.info(f"[RetrievalManager] Neo4j检索完成 | 数据量: {neo4j_result.count}")

        # 融合结果
        fused = self._fusion.fuse(
            mysql_results=mysql_result.data if mysql_result.success else {},
            milvus_results=milvus_result.data if milvus_result.success else {},
            neo4j_results=neo4j_result.data if neo4j_result.success else {},
        )

        duration = time.time() - start_time
        logger.info(
            f"[RetrievalManager] 检索完成 | 总耗时: {duration:.2f}s | "
            f"来源: {fused.sources}"
        )

        return fused

    def retrieve_with_trace(self, plan: RetrievalPlan) -> Dict[str, Any]:
        """
        执行检索并返回详细追踪信息（用于API调试）

        Returns:
            {
                "plan": RetrievalPlan.to_dict(),
                "mysql_result": RetrievalResult.to_dict(),
                "milvus_result": RetrievalResult.to_dict(),
                "neo4j_result": RetrievalResult.to_dict(),
                "fused_context": FusedContext.to_dict(),
                "duration": total_seconds,
            }
        """
        start_time = time.time()

        # 执行检索
        mysql_result = self._retrieve_mysql(plan)
        milvus_result = self._retrieve_milvus(plan)
        neo4j_result = self._retrieve_neo4j(plan)

        # 融合
        fused = self._fusion.fuse(
            mysql_results=mysql_result.data if mysql_result.success else {},
            milvus_results=milvus_result.data if milvus_result.success else {},
            neo4j_results=neo4j_result.data if neo4j_result.success else {},
        )

        duration = time.time() - start_time

        return {
            "plan": plan.to_dict(),
            "mysql_result": mysql_result.to_dict(),
            "milvus_result": milvus_result.to_dict(),
            "neo4j_result": neo4j_result.to_dict(),
            "fused_context": fused.to_dict(),
            "duration": round(duration, 3),
        }

    def _retrieve_mysql(self, plan: RetrievalPlan) -> RetrievalResult:
        """执行MySQL检索"""
        if not plan.mysql.tables:
            return RetrievalResult(source="mysql", success=True, data={}, count=0)
        return self._mysql_retriever._safe_execute(plan.mysql.to_dict())

    def _retrieve_milvus(self, plan: RetrievalPlan) -> RetrievalResult:
        """执行Milvus检索"""
        if not plan.milvus.queries or not plan.milvus.collections:
            return RetrievalResult(source="milvus", success=True, data={}, count=0)
        return self._milvus_retriever._safe_execute(plan.milvus.to_dict())

    def _retrieve_neo4j(self, plan: RetrievalPlan) -> RetrievalResult:
        """执行Neo4j检索"""
        if not plan.neo4j.node_labels and not plan.neo4j.start_nodes:
            return RetrievalResult(source="neo4j", success=True, data={}, count=0)
        return self._neo4j_retriever._safe_execute(plan.neo4j.to_dict())


# 单例
_manager: Optional[RetrievalManager] = None


def get_retrieval_manager() -> RetrievalManager:
    """获取RetrievalManager单例"""
    global _manager
    if _manager is None:
        _manager = RetrievalManager()
    return _manager
