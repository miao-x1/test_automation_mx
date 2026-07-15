"""
APIKnowledgeAgent - 接口知识Agent

职责：
  支持 Swagger / OpenAPI / Postman / JMeter / JSON 自动解析：
    接口 → 参数 → Header → Body → Response → 数据库
  建立接口依赖关系。
  后续 API Agent 能够查询相关接口。

通信方式：
  # 其他 Agent 调用 APIKnowledgeAgent 获取接口信息
  response = await self.send_request(
      "api_knowledge_agent", "get_api",
      {"method": "POST", "path": "/api/v1/login"}
  )
  # response.data = {"api": {...}, "parameters": [...], "headers": [...], ...}

  # 查询相关接口（通过依赖关系图遍历）
  response = await self.send_request(
      "api_knowledge_agent", "get_related",
      {"api_id": 1, "depth": 2}
  )
  # response.data = {"related_apis": [...], "dependencies": {...}}

  # 上传接口文件进行解析
  response = await self.send_request(
      "api_knowledge_agent", "upload",
      {"file_path": "/path/to/swagger.json", "source_type": "swagger"}
  )
"""
import json
import logging
import time
import traceback
from typing import Any, Dict, List

from autogen_core import message_handler, MessageContext, DefaultTopicId, default_subscription

from app.runtime.base_agent import BaseRoutedAgent
from app.runtime.messages import AgentRequest, AgentResponse

logger = logging.getLogger(__name__)


@default_subscription
class APIKnowledgeAgent(BaseRoutedAgent):
    """接口知识Agent

    管理接口知识的完整生命周期：
      解析文件 → 结构化 → MySQL + Milvus + Neo4j → 依赖关系

    查询接口：
      get_api:       按ID或method+path获取接口详情
      search:        按关键词/方法/模块搜索接口
      get_dependencies: 获取接口的依赖关系
      get_related:   获取相关接口（通过依赖关系图遍历）
    """

    def __init__(self) -> None:
        super().__init__(
            description="接口知识Agent，解析Swagger/Postman/JMeter/JSON→结构化→三库存储，支持依赖查询",
            display_name="APIKnowledgeAgent",
            capabilities=["api_parse", "api_query", "dependency_analysis"],
        )

    async def execute(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """GraphFlow 入口"""
        action = payload.get("action", "search")
        if action == "upload":
            return await self._do_upload(payload)
        elif action == "get_api":
            return await self._do_get_api(payload)
        elif action == "search":
            return await self._do_search(payload)
        elif action == "get_dependencies":
            return await self._do_get_dependencies(payload)
        elif action == "get_related":
            return await self._do_get_related(payload)
        elif action == "get_stats":
            return await self._do_get_stats(payload)
        else:
            return {"status": "error", "message": f"Unknown action: {action}"}

    # ------------------------------------------------------------------
    # 消息处理器
    # ------------------------------------------------------------------

    @message_handler
    async def handle_request(self, message: AgentRequest, ctx: MessageContext) -> AgentResponse:
        """处理来自其他 Agent 的请求

        支持的 action:
          - upload:            上传接口文件解析
          - get_api:           获取接口详情
          - search:            搜索接口
          - get_dependencies:  获取接口依赖关系
          - get_related:       获取相关接口（依赖图遍历）
          - get_stats:        获取统计信息
        """
        start = time.time()
        action = message.target_action or "search"
        logger.info(f"[APIKnowledgeAgent] 收到请求 action={action}")

        try:
            if action == "upload":
                result = await self._do_upload(message.payload)
            elif action == "get_api":
                result = await self._do_get_api(message.payload)
            elif action == "search":
                result = await self._do_search(message.payload)
            elif action == "get_dependencies":
                result = await self._do_get_dependencies(message.payload)
            elif action == "get_related":
                result = await self._do_get_related(message.payload)
            elif action == "get_stats":
                result = await self._do_get_stats(message.payload)
            else:
                result = {"status": "error", "message": f"Unknown action: {action}"}

            duration = time.time() - start
            return AgentResponse(
                request_id=message.request_id,
                sender_type=self._agent_type,
                status="success" if result.get("status") != "error" else "error",
                data=result,
                duration=duration,
            )
        except Exception as e:
            duration = time.time() - start
            logger.error(f"[APIKnowledgeAgent] 处理失败: {e}", exc_info=True)
            return AgentResponse(
                request_id=message.request_id,
                sender_type=self._agent_type,
                status="error",
                error=str(e),
                duration=duration,
            )

    # ------------------------------------------------------------------
    # Action 实现
    # ------------------------------------------------------------------

    async def _do_upload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """上传接口文件并自动完成完整处理管道

        流程：自动检测来源 → 解析 → 结构化 → MySQL + Milvus + Neo4j → 依赖检测
        """
        from app.services.api_knowledge_service import get_api_knowledge_service

        service = get_api_knowledge_service()
        result = await service.parse_and_store(
            file_path=payload.get("file_path", ""),
            source_type=payload.get("source_type", ""),
            project_id=payload.get("project_id", "default"),
            user_id=payload.get("user_id"),
        )
        return result

    async def _do_get_api(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """获取接口详情

        支持两种查询方式：
          1. 按 api_id 查询
          2. 按 method + path 查询
        """
        from app.services.api_knowledge_service import get_api_knowledge_service

        service = get_api_knowledge_service()
        api_id = payload.get("api_id")
        method = payload.get("method", "")
        path = payload.get("path", "")

        if api_id:
            api = service.get_api(int(api_id))
        elif method and path:
            api = service.get_api_by_method_path(method, path)
        else:
            return {"status": "error", "message": "需要提供 api_id 或 method+path"}

        if api is None:
            return {"status": "not_found", "message": "接口不存在"}

        return {"status": "success", "api": api}

    async def _do_search(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """搜索接口

        支持按关键词、方法、模块、标签搜索。
        """
        from app.services.api_knowledge_service import get_api_knowledge_service

        service = get_api_knowledge_service()
        keyword = payload.get("keyword", "")
        method = payload.get("method", "")
        module = payload.get("module", "")
        tags = payload.get("tags", "")
        limit = payload.get("limit", 50)

        results = service.search_apis(
            keyword=keyword,
            method=method,
            module=module,
            tags=tags,
            limit=limit,
        )

        return {
            "status": "success",
            "results": results,
            "total": len(results),
        }

    async def _do_get_dependencies(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """获取接口的依赖关系

        返回：
          depends_on:  本接口依赖哪些接口
          consumed_by: 哪些接口依赖本接口
        """
        from app.services.api_knowledge_service import get_api_knowledge_service

        service = get_api_knowledge_service()
        api_id = payload.get("api_id")
        if not api_id:
            return {"status": "error", "message": "api_id 不能为空"}

        deps = service.get_dependencies(int(api_id))
        return {"status": "success", "dependencies": deps}

    async def _do_get_related(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """获取相关接口（通过依赖关系图遍历）

        API Agent 核心查询接口：
          给定一个接口ID，返回所有相关接口（依赖链路）。
        """
        from app.services.api_knowledge_service import get_api_knowledge_service

        service = get_api_knowledge_service()
        api_id = payload.get("api_id")
        depth = payload.get("depth", 1)
        if not api_id:
            return {"status": "error", "message": "api_id 不能为空"}

        # 获取相关接口
        related = service.get_related_apis(int(api_id), depth=depth)
        # 获取直接依赖
        deps = service.get_dependencies(int(api_id))

        return {
            "status": "success",
            "api_id": int(api_id),
            "depth": depth,
            "related_apis": related,
            "total_related": len(related),
            "dependencies": deps,
        }

    async def _do_get_stats(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """获取统计信息"""
        from app.services.api_knowledge_service import get_api_knowledge_service

        service = get_api_knowledge_service()
        stats = service.get_stats()
        return {"status": "success", "stats": stats}
