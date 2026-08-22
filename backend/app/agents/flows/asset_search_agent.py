"""
AssetSearchAgent - 测试资产搜索 Agent

职责:
  根据自然语言查询, 通过三源融合搜索 (MySQL + Milvus + Neo4j) 检索已有测试资产。

架构:
  Agent → AssetSearchService → AssetSearchRepository (MySQL)
                              → Milvus (Phase 3, 向量召回)
                              → Neo4j (Phase 3, 关系扩展)

  禁止 Agent 直接操作数据库, 所有查询统一通过 AssetSearchService。

输入 (AgentRequest.payload):
  query:           自然语言查询 (必填)
  asset_types:     限定资产类型 (可选)
  module:          模块过滤 (可选)
  tags:            标签过滤 (可选)
  include_inactive: 是否包含非 active 资产 (默认 False)
  limit:           返回数量上限 (默认 10)
  use_vector:      是否启用 Milvus 向量召回 (默认 True)
  use_relation:    是否启用 Neo4j 关系扩展 (默认 True)

输出 (AgentResponse.data):
  status:          success / error
  query:           原始查询
  total:           命中总数
  hits:            搜索结果列表 (含三源得分与命中原因)
  elapsed_ms:      查询耗时
  sources_used:    实际使用的检索源
"""
import logging
import time
from typing import Any, Dict, List, Optional

from autogen_core import message_handler, MessageContext, default_subscription

from app.runtime.base_agent import BaseRoutedAgent
from app.runtime.messages import AgentRequest, AgentResponse
from app.schemas.asset_registry import SearchRequest

logger = logging.getLogger(__name__)


@default_subscription
class AssetSearchAgent(BaseRoutedAgent):
    """测试资产搜索 Agent

    三源融合搜索编排:
      1. MySQL 关键词匹配 (同步, 必执行)
      2. Milvus 向量召回 (Phase 2 stub, Phase 3 接入)
      3. Neo4j 关系扩展 (Phase 2 stub, Phase 3 接入)
      4. 融合得分: 0.5 * mysql + 0.3 * milvus + 0.2 * relation

    使用方式:
      直接调用:  await agent.execute({"query": "登录接口"}, ctx)
      消息驱动:  await self.send_request("asset_search_agent", "search", payload)
    """

    def __init__(self) -> None:
        super().__init__(
            description="测试资产搜索Agent, 三源融合检索已有资产",
            display_name="AssetSearchAgent",
            capabilities=["asset_search", "asset_retrieve"],
        )
        self._search_service = None

    @property
    def search_service(self):
        """延迟加载 AssetSearchService"""
        if self._search_service is None:
            from app.services.asset_search_service import AssetSearchService
            self._search_service = AssetSearchService()
        return self._search_service

    # ------------------------------------------------------------------
    # GraphFlow 入口
    # ------------------------------------------------------------------

    async def execute(
        self, payload: Dict[str, Any], ctx: MessageContext
    ) -> Dict[str, Any]:
        """GraphFlow 入口: 执行资产搜索"""
        return await self._do_search(payload)

    # ------------------------------------------------------------------
    # 消息处理器: search
    # ------------------------------------------------------------------

    @message_handler
    async def handle_search(
        self, message: AgentRequest, ctx: MessageContext
    ) -> AgentResponse:
        """处理 search 请求 (其他 Agent 调用入口)

        Args (message.payload):
            query:            自然语言查询 (必填)
            asset_types:      限定资产类型 (可选)
            module:           模块过滤 (可选)
            tags:             标签过滤 (可选)
            include_inactive:  是否包含非 active 资产 (默认 False)
            limit:            返回数量上限 (默认 10)
            use_vector:       是否启用 Milvus (默认 True)
            use_relation:     是否启用 Neo4j (默认 True)
        """
        start = time.time()
        request_id = message.request_id
        logger.info(
            f"[AssetSearchAgent] 收到搜索请求 request_id={request_id} "
            f"query={message.payload.get('query', '')[:50]}"
        )

        try:
            result = await self._do_search(message.payload)
            duration = time.time() - start

            if result.get("status") == "error":
                return AgentResponse(
                    request_id=request_id,
                    sender_type=self._agent_type,
                    status="error",
                    error=result.get("message", "搜索失败"),
                    duration=duration,
                )

            return AgentResponse(
                request_id=request_id,
                sender_type=self._agent_type,
                status="success",
                data=result,
                duration=duration,
            )
        except Exception as e:
            duration = time.time() - start
            logger.error(f"[AssetSearchAgent] 搜索失败: {e}", exc_info=True)
            return AgentResponse(
                request_id=request_id,
                sender_type=self._agent_type,
                status="error",
                error=str(e),
                duration=duration,
            )

    # ------------------------------------------------------------------
    # 核心搜索逻辑
    # ------------------------------------------------------------------

    async def _do_search(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """执行资产搜索

        流程:
          1. 解析参数, 构建 SearchRequest
          2. 调用 AssetSearchService.search() (唯一查询入口)
          3. 返回统一结果
        """
        # 解析参数
        query: str = payload.get("query", "").strip()
        if not query:
            return {
                "status": "error",
                "message": "query 不能为空",
                "hits": [],
                "total": 0,
            }

        asset_types: Optional[List[str]] = payload.get("asset_types")
        module: Optional[str] = payload.get("module")
        tags: Optional[List[str]] = payload.get("tags")
        include_inactive: bool = payload.get("include_inactive", False)
        limit: int = min(payload.get("limit", 10), 50)
        use_vector: bool = payload.get("use_vector", True)
        use_relation: bool = payload.get("use_relation", True)
        user_id = payload.get("user_id")

        # 构建 SearchRequest
        search_req = SearchRequest(
            query=query,
            asset_types=asset_types,
            module=module,
            tags=tags,
            include_inactive=include_inactive,
            limit=limit,
            use_vector=use_vector,
            use_relation=use_relation,
        )

        # 调用 AssetSearchService (唯一查询入口)
        result = self.search_service.search(search_req, user_id=user_id)

        logger.info(
            f"[AssetSearchAgent] 搜索完成 query='{query[:30]}' "
            f"total={result.get('total', 0)} "
            f"sources={result.get('sources_used', [])} "
            f"elapsed={result.get('elapsed_ms', 0)}ms"
        )

        return {
            "status": "success",
            "query": result.get("query", query),
            "total": result.get("total", 0),
            "hits": result.get("hits", []),
            "elapsed_ms": result.get("elapsed_ms", 0),
            "sources_used": result.get("sources_used", ["mysql"]),
        }
