"""
ScriptReuseAgent - 脚本复用Agent

架构变更：
  原：Agent → Milvus（直接调用 script_vector 集合）
  新：Agent → ContextRouter → Milvus + MySQL

职责：判断当前需求与历史脚本是否高度相似，如果相似度>=阈值则直接复用

流程：
1. 通过 ContextRouter 检索 SCRIPT 类型上下文
2. 取 Top1 结果
3. 如果相似度 >= 0.90，直接返回历史脚本
4. 否则继续生成新脚本
"""
from typing import Dict, Any, Optional, List
from app.core.logger import log
from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability


class ScriptReuseAgent(NewBaseAgent):
    """脚本复用Agent

    所有查询通过 ContextRouter 路由，禁止直接调用 Milvus。
    """

    agent_name = "script_reuse"
    display_name = "Script Reuse Agent"
    description = "脚本复用Agent - 通过ContextRouter判断历史脚本相似度，相似则直接复用"
    capabilities = [AgentCapability.REUSE_CHECK]

    # 复用相似度阈值
    REUSE_THRESHOLD = 0.90

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)
        self.agent_type = "script_reuse"
        self.model = None
        self.system_prompt = None
        self._router = None

    @property
    def router(self):
        """延迟加载 ContextRouter"""
        if self._router is None:
            from app.services.context_router import get_context_router
            self._router = get_context_router()
        return self._router

    def check_reuse(self, requirement: str, top_k: int = 1) -> Dict[str, Any]:
        """
        检查是否可以复用历史脚本

        通过 ContextRouter 检索 SCRIPT 类型上下文，
        不再直接调用 Milvus。

        Args:
            requirement: 需求文本
            top_k: 检索数量（默认1，只取最相似的）

        Returns:
            {
                "reuse": bool,
                "similarity": float,
                "script_id": Optional[int],
                "script_content": Optional[str],
                "script_name": Optional[str],
                "task_id": Optional[int],
            }
        """
        from app.services.context_router import ContextType

        log.info(f"ScriptReuseAgent | 检查脚本复用(via ContextRouter) | requirement={requirement[:50]}")

        try:
            # 通过 ContextRouter 检索脚本
            ctx_result = self.router.retrieve_sync(
                query=requirement,
                context_type=ContextType.SCRIPT,
                top_k=top_k,
            )

            results = ctx_result.get("results", [])
            if not results:
                log.info("ScriptReuseAgent | 无历史脚本，继续生成新脚本")
                return {"reuse": False, "similarity": 0}

            # 取Top1结果
            top_hit = results[0]
            similarity = round(top_hit.get("score", 0), 4)
            entity = top_hit.get("entity", {})

            script_content = entity.get("script_content", "")
            script_name = entity.get("script_name", top_hit.get("text", ""))
            task_id = entity.get("task_id")

            log.info(
                f"ScriptReuseAgent | 最相似脚本: {script_name} | "
                f"相似度: {similarity} | 阈值: {self.REUSE_THRESHOLD} | "
                f"来源: {top_hit.get('source', '')}"
            )

            if similarity >= self.REUSE_THRESHOLD and script_content:
                log.info(f"ScriptReuseAgent | 命中脚本复用! 相似度={similarity}")
                return {
                    "reuse": True,
                    "similarity": similarity,
                    "script_id": top_hit.get("id"),
                    "script_content": script_content,
                    "script_name": script_name,
                    "task_id": task_id,
                }
            else:
                log.info(f"ScriptReuseAgent | 相似度不足，继续生成新脚本")
                return {
                    "reuse": False,
                    "similarity": similarity,
                    "script_id": top_hit.get("id"),
                    "script_content": None,
                    "script_name": script_name,
                    "task_id": task_id,
                }

        except Exception as e:
            log.warning(f"ScriptReuseAgent | 复用检查失败: {e}，继续生成新脚本")
            return {"reuse": False, "similarity": 0}

    # ==================== 管道兼容入口 ====================

    def execute(self, **kwargs) -> Dict[str, Any]:
        """管道兼容入口，供 TaskOrchestrator 统一调用

        从 kwargs 中提取 requirement，调用 check_reuse()。
        """
        requirement = kwargs.get("requirement", "")
        if not requirement:
            # 尝试从需求解析结果中获取
            parsed = kwargs.get("requirement_analysis", {})
            if isinstance(parsed, dict):
                requirement = parsed.get("requirement", parsed.get("raw_text", ""))
        top_k = kwargs.get("top_k", 1)
        return self.check_reuse(requirement=requirement, top_k=top_k)
