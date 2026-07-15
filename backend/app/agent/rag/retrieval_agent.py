"""
RetrievalAgent - 自然语言检索相关页面元素

架构变更：
  原：Agent → Milvus（直接查询，自带 Embedding 实现）
  新：Agent → ContextRouter → Milvus + MySQL + Neo4j

  所有查询通过 ContextRouter 路由，禁止直接操作 Milvus。
  所有 Embedding 通过 EmbeddingFactory 统一获取，禁止重复实现。

流程：
1. 接收自然语言查询（如"测试登录"、"验证搜索功能"）
2. 通过 ContextRouter 检索 PAGE_ELEMENT 类型上下文
3. 返回相关元素列表
"""
from typing import AsyncGenerator, Dict, Any, List, Optional
from app.core.config import settings
from app.core.logger import log
from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability


class RetrievalAgent(NewBaseAgent):
    """检索 Agent

    通过 ContextRouter 检索页面元素，不直接操作 Milvus。
    """

    agent_name = "retrieval"
    display_name = "Retrieval Agent"
    description = "自然语言检索相关页面元素Agent"
    capabilities = [AgentCapability.RAG_RETRIEVE]

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)
        self._router = None

    @property
    def router(self):
        """延迟加载 ContextRouter"""
        if self._router is None:
            from app.services.context_router import get_context_router
            self._router = get_context_router()
        return self._router

    async def search(
        self,
        query: str,
        top_k: int = 10,
        task_id: Optional[int] = None,
        on_log: Optional[callable] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        自然语言检索相关元素

        通过 ContextRouter 路由到 Milvus + MySQL 检索 PAGE_ELEMENT 类型。

        Args:
            query: 自然语言查询（如"测试登录"、"验证搜索功能"）
            top_k: 返回最相似的K个结果
            task_id: 可选，限定搜索范围到指定任务
            on_log: 日志回调

        Yields:
            进度信息和最终检索结果
        """
        yield {"step": "开始检索", "progress": 20, "message": f"查询: {query}"}

        # 构建 filters
        filters = {}
        if task_id is not None:
            filters["task_id"] = task_id

        yield {"step": "ContextRouter检索", "progress": 50, "message": "通过 ContextRouter 路由到 Milvus..."}

        try:
            result = self.router.retrieve_sync(
                query=query,
                context_type=None,  # 自动检测：PAGE_ELEMENT
                top_k=top_k,
                filters=filters if filters else None,
                project_id="",
            )
        except Exception as e:
            log.error(f"RetrievalAgent | ContextRouter 检索失败: {e}")
            yield {
                "step": "检索失败",
                "progress": 100,
                "message": f"检索失败: {e}",
                "data": {"results": [], "total": 0, "query": query},
            }
            return

        # 解析结果
        results = result.get("results", [])
        total = result.get("total", len(results))

        log.info(f"RetrievalAgent | 检索完成 | query={query[:50]} | results={total}")

        yield {
            "step": "检索完成",
            "progress": 100,
            "message": f"召回 {total} 个相关元素",
            "data": {"results": results, "total": total, "query": query},
        }
