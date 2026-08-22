"""
AssetCenterOrchestrator - 测试资产中心业务流编排

职责:
  链式编排 3 个 Agent, 完成完整的资产分析流程:
    1. AssetSearchAgent    - 搜索已有资产
    2. AssetReuseAgent     - 评估复用性
    3. AssetOptimizationAgent - 生成优化方案

业务流:
  用户输入需求 (如 "测试登录功能")
    ↓
  AssetSearchAgent.search(query=requirement)
    ↓ 返回 search_results
  AssetReuseAgent.evaluate(requirement, search_results)
    ↓ 返回 reuse_decision
  AssetOptimizationAgent.optimize(requirement, reuse_decision, search_results)
    ↓ 返回 optimized_plan

  最终输出: 搜索结果 + 复用决策 + 优化方案

使用方式:
  orchestrator = AssetCenterOrchestrator()
  result = await orchestrator.analyze_requirement(
      requirement="测试登录功能",
      user_id=1,
  )
"""
import logging
import time
from typing import Any, Dict, List, Optional

from autogen_core import MessageContext, CancellationToken, DefaultTopicId

from app.agents.factory.factory import AgentFactory

logger = logging.getLogger(__name__)


def _make_ctx() -> MessageContext:
    """构造 MessageContext (Orchestrator 直接调用时使用)"""
    return MessageContext(
        sender=None,
        topic_id=DefaultTopicId(),
        is_rpc=False,
        cancellation_token=CancellationToken(),
        message_id="orchestrator",
    )


class AssetCenterOrchestrator:
    """测试资产中心业务流编排

    链式调用 3 个 Agent, 不涉及 AutoGen Core Runtime (简化版)。
    若需接入 Runtime, 可通过 TaskRuntime.execute_pipeline() 定义步骤。
    """

    def __init__(self):
        self._factory = None
        self._search_agent = None
        self._reuse_agent = None
        self._optimization_agent = None

    @property
    def factory(self):
        """延迟加载 AgentFactory"""
        if self._factory is None:
            self._factory = AgentFactory()
        return self._factory

    async def _get_search_agent(self):
        if self._search_agent is None:
            self._search_agent = await self.factory.create("asset_search_agent")
        return self._search_agent

    async def _get_reuse_agent(self):
        if self._reuse_agent is None:
            self._reuse_agent = await self.factory.create("asset_reuse_agent")
        return self._reuse_agent

    async def _get_optimization_agent(self):
        if self._optimization_agent is None:
            self._optimization_agent = await self.factory.create(
                "asset_optimization_agent"
            )
        return self._optimization_agent

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------

    async def analyze_requirement(
        self,
        requirement: str,
        *,
        asset_types: Optional[List[str]] = None,
        module: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 10,
        use_vector: bool = True,
        use_relation: bool = True,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """完整资产分析流程

        步骤:
          1. AssetSearchAgent: 搜索已有资产
          2. AssetReuseAgent: 评估复用性
          3. AssetOptimizationAgent: 生成优化方案

        返回:
          {
            "status": "success" / "error",
            "requirement": <原始需求>,
            "search_results": [...],
            "reuse_decision": {...},
            "optimized_plan": {...},
            "elapsed_ms": <总耗时>,
            "steps": [
              {"step": "search", "status": "success", "duration_ms": ..., "total": ...},
              {"step": "reuse", "status": "success", "duration_ms": ..., "can_reuse": ...},
              {"step": "optimize", "status": "success", "duration_ms": ..., "quality_score": ...},
            ]
          }
        """
        start_time = time.time()
        steps_result: List[Dict[str, Any]] = []

        logger.info(
            f"[AssetCenterOrchestrator] 开始资产分析: requirement='{requirement[:50]}'"
        )

        # === 步骤 1: AssetSearchAgent - 搜索已有资产 ===
        step_start = time.time()
        try:
            search_agent = await self._get_search_agent()
            search_payload = {
                "query": requirement,
                "asset_types": asset_types,
                "module": module,
                "tags": tags,
                "limit": limit,
                "use_vector": use_vector,
                "use_relation": use_relation,
                "user_id": user_id,
            }

            # 直接调用 execute (绕过消息系统, 简化)
            ctx = _make_ctx()
            search_result = await search_agent.execute(search_payload, ctx)

            if search_result.get("status") == "error":
                return self._build_error_response(
                    requirement, f"搜索失败: {search_result.get('message')}",
                    steps_result, start_time,
                )

            search_results = search_result.get("hits", [])
            steps_result.append({
                "step": "search",
                "status": "success",
                "duration_ms": int((time.time() - step_start) * 1000),
                "total": search_result.get("total", 0),
                "sources_used": search_result.get("sources_used", []),
            })

            logger.info(
                f"[AssetCenterOrchestrator] 搜索完成: "
                f"{len(search_results)} 条结果, "
                f"sources={search_result.get('sources_used')}"
            )

        except Exception as e:
            logger.error(f"[AssetCenterOrchestrator] 搜索步骤失败: {e}", exc_info=True)
            return self._build_error_response(
                requirement, f"搜索步骤异常: {str(e)}", steps_result, start_time,
            )

        # === 步骤 2: AssetReuseAgent - 评估复用性 ===
        step_start = time.time()
        try:
            reuse_agent = await self._get_reuse_agent()
            reuse_payload = {
                "requirement": requirement,
                "search_results": search_results,
            }

            ctx = _make_ctx()
            reuse_result = await reuse_agent.execute(reuse_payload, ctx)

            if reuse_result.get("status") == "error":
                steps_result.append({
                    "step": "reuse",
                    "status": "error",
                    "duration_ms": int((time.time() - step_start) * 1000),
                    "error": reuse_result.get("message", "评估失败"),
                })
                # 复用评估失败, 使用降级决策
                reuse_decision = {
                    "requirement": requirement,
                    "can_reuse": False,
                    "suggestions": [],
                    "missing_assets": [],
                    "summary": "复用评估失败, 跳过此步骤",
                    "degraded": True,
                }
            else:
                reuse_decision = reuse_result
                steps_result.append({
                    "step": "reuse",
                    "status": "success",
                    "duration_ms": int((time.time() - step_start) * 1000),
                    "can_reuse": reuse_result.get("can_reuse", False),
                    "suggestions_count": len(reuse_result.get("suggestions", [])),
                })

            logger.info(
                f"[AssetCenterOrchestrator] 复用评估完成: "
                f"can_reuse={reuse_decision.get('can_reuse')}"
            )

        except Exception as e:
            logger.error(f"[AssetCenterOrchestrator] 复用步骤失败: {e}", exc_info=True)
            steps_result.append({
                "step": "reuse",
                "status": "error",
                "duration_ms": int((time.time() - step_start) * 1000),
                "error": str(e),
            })
            reuse_decision = {
                "requirement": requirement,
                "can_reuse": False,
                "suggestions": [],
                "missing_assets": [],
                "summary": f"复用评估异常: {str(e)}",
                "degraded": True,
            }

        # === 步骤 3: AssetOptimizationAgent - 生成优化方案 ===
        step_start = time.time()
        try:
            opt_agent = await self._get_optimization_agent()
            opt_payload = {
                "requirement": requirement,
                "reuse_decision": reuse_decision,
                "search_results": search_results,
            }

            ctx = _make_ctx()
            opt_result = await opt_agent.execute(opt_payload, ctx)

            if opt_result.get("status") == "error":
                steps_result.append({
                    "step": "optimize",
                    "status": "error",
                    "duration_ms": int((time.time() - step_start) * 1000),
                    "error": opt_result.get("message", "优化失败"),
                })
                optimized_plan = None
            else:
                optimized_plan = opt_result.get("optimized_plan")
                steps_result.append({
                    "step": "optimize",
                    "status": "success",
                    "duration_ms": int((time.time() - step_start) * 1000),
                    "quality_score": opt_result.get("quality_score", 0),
                })

            logger.info(
                f"[AssetCenterOrchestrator] 优化方案生成完成: "
                f"quality_score={opt_result.get('quality_score', 0)}"
            )

        except Exception as e:
            logger.error(f"[AssetCenterOrchestrator] 优化步骤失败: {e}", exc_info=True)
            steps_result.append({
                "step": "optimize",
                "status": "error",
                "duration_ms": int((time.time() - step_start) * 1000),
                "error": str(e),
            })
            optimized_plan = None

        # === 汇总结果 ===
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.info(
            f"[AssetCenterOrchestrator] 资产分析完成: "
            f"elapsed={elapsed_ms}ms, steps={len(steps_result)}"
        )

        return {
            "status": "success",
            "requirement": requirement,
            "search_results": search_results,
            "reuse_decision": reuse_decision,
            "optimized_plan": optimized_plan,
            "elapsed_ms": elapsed_ms,
            "steps": steps_result,
        }

    # ------------------------------------------------------------------
    # 单步调用 (供外部按需调用)
    # ------------------------------------------------------------------

    async def search_assets(
        self,
        query: str,
        *,
        asset_types: Optional[List[str]] = None,
        module: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 10,
        use_vector: bool = True,
        use_relation: bool = True,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """仅执行资产搜索步骤"""
        search_agent = await self._get_search_agent()
        payload = {
            "query": query,
            "asset_types": asset_types,
            "module": module,
            "tags": tags,
            "limit": limit,
            "use_vector": use_vector,
            "use_relation": use_relation,
            "user_id": user_id,
        }
        ctx = _make_ctx()
        return await search_agent.execute(payload, ctx)

    async def evaluate_reuse(
        self,
        requirement: str,
        search_results: List[Dict],
    ) -> Dict[str, Any]:
        """仅执行复用评估步骤"""
        reuse_agent = await self._get_reuse_agent()
        payload = {
            "requirement": requirement,
            "search_results": search_results,
        }
        ctx = _make_ctx()
        return await reuse_agent.execute(payload, ctx)

    async def optimize_plan(
        self,
        requirement: str,
        reuse_decision: Dict,
        search_results: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """仅执行方案优化步骤"""
        opt_agent = await self._get_optimization_agent()
        payload = {
            "requirement": requirement,
            "reuse_decision": reuse_decision,
            "search_results": search_results or [],
        }
        ctx = _make_ctx()
        return await opt_agent.execute(payload, ctx)

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _build_error_response(
        requirement: str,
        error: str,
        steps_result: List[Dict],
        start_time: float,
    ) -> Dict[str, Any]:
        """构建错误响应"""
        return {
            "status": "error",
            "requirement": requirement,
            "error": error,
            "elapsed_ms": int((time.time() - start_time) * 1000),
            "steps": steps_result,
        }


# ============================================================
# 单例
# ============================================================

_orchestrator: Optional[AssetCenterOrchestrator] = None


def get_asset_center_orchestrator() -> AssetCenterOrchestrator:
    """获取 AssetCenterOrchestrator 单例"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AssetCenterOrchestrator()
    return _orchestrator
