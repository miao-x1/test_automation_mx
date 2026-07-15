"""
GraphAgent - 图数据库构建Agent

架构变更：
  原：Agent → Neo4j (直接 run_query × 5 + is_available × 3)
  新：Agent → ContextRouter.retrieve_graph_inference() → Neo4j (读取)
        Agent → StorageRouter.neo4j_available() (可用性检查)
        Agent → GraphBuildService (写入操作，已封装)

  禁止 GraphAgent 直接导入：
    - app.db.neo4j_client
    - app.db.milvus_client
    - app.rag.embedding

职责：
- 全量构建图谱（委托 GraphBuildService）
- 增量同步单个任务（委托 GraphBuildService）
- 图谱查询辅助（通过 ContextRouter）
- Graph推理：根据需求推断页面路径（通过 ContextRouter）
"""
import time
from typing import Dict, Any, List, Optional

from app.core.logger import log
from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability


class GraphAgent(NewBaseAgent):
    """图数据库构建Agent

    读取操作通过 ContextRouter，写入操作通过 GraphBuildService + StorageRouter。
    禁止直接导入 neo4j_client / milvus_client / embedding。
    """

    agent_name = "graph_agent"
    display_name = "图谱推理Agent"
    description = "全量构建图谱、增量同步任务，并基于图数据库推理页面操作路径"
    capabilities = [AgentCapability.GRAPH_INFER]

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)
        self.agent_type = "graph"
        self.model = None
        self.system_prompt = None
        self._router = None
        self._storage = None
        self._build_svc = None

    @property
    def router(self):
        """延迟加载 ContextRouter（读取）"""
        if self._router is None:
            from app.services.context_router import get_context_router
            self._router = get_context_router()
        return self._router

    @property
    def storage(self):
        """延迟加载 StorageRouter（写入）"""
        if self._storage is None:
            from app.services.context_router.storage_router import get_storage_router
            self._storage = get_storage_router()
        return self._storage

    @property
    def build_svc(self):
        """延迟加载 GraphBuildService"""
        if self._build_svc is None:
            from app.services.graph_build_service import GraphBuildService
            self._build_svc = GraphBuildService()
        return self._build_svc

    def build_full_graph(self, clean_first: bool = True) -> Dict[str, Any]:
        """全量构建图谱（写入操作，委托 GraphBuildService）"""
        if not self.storage.neo4j_available():
            return {"success": False, "error": "Neo4j不可用"}

        log.info("GraphAgent | 开始全量构建图谱")
        return self.build_svc.build_all(clean_first=clean_first)

    def sync_single_task(self, task_id: int) -> Dict[str, Any]:
        """增量同步单个任务（写入操作，委托 GraphBuildService）"""
        if not self.storage.neo4j_available():
            return {"success": False, "error": "Neo4j不可用"}

        log.info(f"GraphAgent | 增量同步任务 {task_id}")
        return self.build_svc.build_task(task_id)

    def infer_flow(
        self,
        requirement: str,
        keywords: List[str] = None,
        steps: List[str] = None,
    ) -> Dict[str, Any]:
        """Graph推理：根据需求推断页面路径

        通过 ContextRouter.retrieve_graph_inference() 查询 Neo4j，
        禁止直接调用 neo4j_client.run_query()。

        Args:
            requirement: 自然语言需求
            keywords: 需求解析出的关键词列表
            steps: 需求解析出的步骤列表

        Returns:
            {
                "pages": [{id, title, url, page_type, source}],
                "elements": [{id, name, type, locator, ...}],
                "business_flow": [{page_id, page_title, page_url, elements, cases, navigation_targets}],
                "degraded": bool
            }
        """
        start_time = time.time()

        if not self.storage.neo4j_available():
            log.warning("GraphAgent.infer_flow | Neo4j不可用，跳过Graph推理")
            return {"pages": [], "elements": [], "business_flow": [], "degraded": True,
                    "degradation_reason": "Neo4j 不可用"}

        log.info(f"GraphAgent.infer_flow | 需求: {requirement[:50]}...")

        # 通过 ContextRouter 统一查询（唯一入口）
        result = self.router.retrieve_graph_inference(
            requirement=requirement,
            keywords=keywords,
            steps=steps,
        )

        latency_ms = int((time.time() - start_time) * 1000)

        pages = result.get("pages", [])
        elements = result.get("elements", [])
        business_flow = result.get("business_flow", [])
        degraded = result.get("degraded", False)

        log.info(
            f"GraphAgent.infer_flow | 推理完成 | "
            f"页面: {len(pages)} | 元素: {len(elements)} | 业务流: {len(business_flow)} | "
            f"latency={latency_ms}ms | degraded={degraded}"
        )

        return {
            "pages": pages,
            "elements": elements,
            "business_flow": business_flow,
            "degraded": degraded,
            "latency_ms": latency_ms,
        }

    # ==================== 管道兼容入口 ====================

    def execute(self, **kwargs) -> Dict[str, Any]:
        """管道兼容入口，供 TaskOrchestrator 统一调用

        根据 kwargs 内容分发到对应方法：
        - 有 requirement → infer_flow()（推理页面路径）
        - 无 requirement → build_full_graph()（全量构建图谱）
        """
        requirement = kwargs.get("requirement", "")
        if not requirement:
            parsed = kwargs.get("requirement_analysis", {})
            if isinstance(parsed, dict):
                requirement = parsed.get("requirement", parsed.get("raw_text", ""))

        if requirement:
            keywords = kwargs.get("keywords")
            steps = kwargs.get("steps")
            return self.infer_flow(requirement=requirement, keywords=keywords, steps=steps)
        else:
            return self.build_full_graph()
