"""
PageKnowledgeAgent - 页面知识Agent

职责：
  上传页面截图后自动完成：
    OCR → 页面描述 → 页面元素（按钮/输入框/菜单）→ 页面关系
    → MySQL + Milvus + Neo4j

  以后 CaseAgent 可以直接查询「登录页面」返回所有元素，不需要再次OCR。

通信方式：
  # 其他 Agent 调用 PageKnowledgeAgent 获取页面元素
  response = await self.send_request(
      "page_knowledge_agent", "get_elements",
      {"page_name": "登录页面"}
  )
  # response.data = {"elements": [...], "page_info": {...}}

  # 上传截图进行处理
  response = await self.send_request(
      "page_knowledge_agent", "upload",
      {"screenshot_path": "/path/to/screenshot.png", "page_name": "登录页面"}
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
class PageKnowledgeAgent(BaseRoutedAgent):
    """页面知识Agent

    管理页面知识的完整生命周期：
      上传截图 → OCR → LLM分析 → 元素提取 → 关系建模 → 三库存储

    查询接口：
      get_elements: 按页面名称返回所有元素（不需要再次OCR）
      get_page: 按页面名称返回完整页面知识
      search: 搜索页面
    """

    def __init__(self) -> None:
        super().__init__(
            description="页面知识Agent，截图→OCR→元素→关系→三库存储，支持按名称查询元素",
            display_name="PageKnowledgeAgent",
            capabilities=["page_ocr", "page_analysis", "page_query"],
        )

    async def execute(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """GraphFlow 入口"""
        action = payload.get("action", "upload")
        if action == "upload":
            return await self._do_upload(payload)
        elif action == "get_elements":
            return await self._do_get_elements(payload)
        elif action == "get_page":
            return await self._do_get_page(payload)
        elif action == "search":
            return await self._do_search(payload)
        else:
            return {"status": "error", "message": f"Unknown action: {action}"}

    # ------------------------------------------------------------------
    # 消息处理器
    # ------------------------------------------------------------------

    @message_handler
    async def handle_request(self, message: AgentRequest, ctx: MessageContext) -> AgentResponse:
        """处理来自其他 Agent 的请求

        支持的 action:
          - upload:       上传截图处理
          - get_elements: 获取页面元素（不需要再次OCR）
          - get_page:     获取完整页面知识
          - search:       搜索页面
        """
        start = time.time()
        action = message.target_action or "upload"
        logger.info(f"[PageKnowledgeAgent] 收到请求 action={action}")

        try:
            if action == "upload":
                result = await self._do_upload(message.payload)
            elif action == "get_elements":
                result = await self._do_get_elements(message.payload)
            elif action == "get_page":
                result = await self._do_get_page(message.payload)
            elif action == "search":
                result = await self._do_search(message.payload)
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
            logger.error(f"[PageKnowledgeAgent] 处理失败: {e}", exc_info=True)
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
        """上传截图并自动完成完整处理管道

        流程：OCR → 页面描述 → 元素提取 → 关系建模 → MySQL + Milvus + Neo4j
        """
        from app.services.page_knowledge_service import get_page_knowledge_service

        service = get_page_knowledge_service()
        result = await service.upload_screenshot(
            screenshot_path=payload.get("screenshot_path", ""),
            page_name=payload.get("page_name", ""),
            page_url=payload.get("page_url", ""),
            project_id=payload.get("project_id", "default"),
            user_id=payload.get("user_id"),
        )
        return result

    async def _do_get_elements(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """获取页面的所有元素（不需要再次OCR）

        CaseAgent 核心查询接口：
          查询「登录页面」→ 返回所有元素（按钮/输入框/菜单等）
        """
        from app.services.page_knowledge_service import get_page_knowledge_service

        service = get_page_knowledge_service()
        page_name = payload.get("page_name", "")
        element_type = payload.get("element_type", "")  # 可选过滤

        if not page_name:
            return {"status": "error", "message": "page_name 不能为空"}

        if element_type:
            elements = service.get_page_elements_by_type(page_name, element_type)
        else:
            elements = service.get_page_elements(page_name)

        page_info = service.get_page_by_name(page_name)

        return {
            "status": "success",
            "page_name": page_name,
            "page_info": page_info,
            "elements": elements,
            "total": len(elements),
        }

    async def _do_get_page(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """获取完整页面知识"""
        from app.services.page_knowledge_service import get_page_knowledge_service

        service = get_page_knowledge_service()
        page_name = payload.get("page_name", "")

        if not page_name:
            return {"status": "error", "message": "page_name 不能为空"}

        page_info = service.get_page_by_name(page_name)
        if page_info is None:
            return {
                "status": "not_found",
                "message": f"页面 '{page_name}' 不存在，请先上传截图",
            }

        relations = service.get_page_relations(page_name)

        return {
            "status": "success",
            "page_info": page_info,
            "relations": relations,
        }

    async def _do_search(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """搜索页面"""
        from app.services.page_knowledge_service import get_page_knowledge_service

        service = get_page_knowledge_service()
        keyword = payload.get("keyword", "")
        page_type = payload.get("page_type", "")
        module = payload.get("module", "")
        limit = payload.get("limit", 50)

        # 关键词搜索（MySQL）
        results = service.search_pages(
            keyword=keyword,
            page_type=page_type,
            module=module,
            limit=limit,
        )

        # 如果有关键词且没有 MySQL 结果，尝试向量搜索（Milvus）
        if keyword and not results:
            vector_results = await service.search_pages_by_vector(keyword, top_k=limit)
            if vector_results:
                return {
                    "status": "success",
                    "search_method": "vector",
                    "results": vector_results,
                    "total": len(vector_results),
                }

        return {
            "status": "success",
            "search_method": "keyword",
            "results": results,
            "total": len(results),
        }
