"""
RAGQueryAgent - RAG 上下文查询 Agent

架构变更：
  原：Agent 内部自己实现 keyword→vector→graph→rerank 查询流水线
  新：Agent → ContextRouter → MySQL/Milvus/Neo4j（统一路由）

  禁止 RAGQueryAgent 直接调用：
    - Milvus / pymilvus
    - Neo4j / run_query
    - Embedding
    - MySQL / SessionLocal

  所有查询统一通过 ContextRouter.retrieve() 路由。

输入支持：
  - Requirement:  需求文本
  - Page:         页面 URL / 页面描述
  - API:          接口路径 / 接口描述
  - Case:         用例标题 / 用例内容
  - Keyword:      关键词

通信方式：
  # 其他 Agent 调用 RAGQueryAgent
  response = await self.send_request(
      "rag_query_agent", "retrieve",
      {
          "query": "用户登录功能",
          "query_type": "requirement",
          "top_k": 5,
          "threshold": 0.6,
          "project": "my_project",
      }
  )
  # response.data = {"context": "...", "results": [...], "total": 5}
"""
import logging
import time
from typing import Any, Dict, List, Optional

from autogen_core import message_handler, MessageContext, DefaultTopicId, default_subscription

from app.runtime.base_agent import BaseRoutedAgent
from app.runtime.messages import AgentRequest, AgentResponse

logger = logging.getLogger(__name__)


@default_subscription
class RAGQueryAgent(BaseRoutedAgent):
    """RAG 上下文查询 Agent

    ContextRouter 是唯一查询入口。
    本 Agent 仅负责：
      1. 解析 query_type → ContextType 映射
      2. 调用 ContextRouter.retrieve()
      3. 构建 LLM 上下文文本
      4. 返回统一结果

    禁止直接操作 Milvus / Neo4j / Embedding / MySQL。
    """

    def __init__(self) -> None:
        super().__init__(
            description="RAG上下文查询Agent，通过ContextRouter统一检索",
            display_name="RAGQueryAgent",
            capabilities=["rag_query", "context_retrieve"],
        )
        self._router = None

    @property
    def router(self):
        """延迟加载 ContextRouter"""
        if self._router is None:
            from app.services.context_router import get_context_router
            self._router = get_context_router()
        return self._router

    # ------------------------------------------------------------------
    # GraphFlow 入口
    # ------------------------------------------------------------------

    async def execute(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """GraphFlow 入口：执行 RAG 查询"""
        return await self._do_query(payload)

    # ------------------------------------------------------------------
    # 消息处理器：retrieve
    # ------------------------------------------------------------------

    @message_handler
    async def handle_retrieve(
        self, message: AgentRequest, ctx: MessageContext
    ) -> AgentResponse:
        """处理 retrieve 请求（其他 Agent 调用入口）

        Args (message.payload):
            query:       查询文本（必填）
            query_type:  查询类型 requirement/page/api/case/keyword（默认 keyword）
            top_k:       返回数量（默认 5）
            threshold:   分数阈值（默认 0.0）
            filter:      过滤条件 dict
            tags:        标签过滤 list
            project:     项目ID
            session:     会话ID
        """
        start = time.time()
        request_id = message.request_id
        logger.info(f"[RAGQueryAgent] 收到查询请求 request_id={request_id}")

        try:
            result = await self._do_query(message.payload)
            duration = time.time() - start

            return AgentResponse(
                request_id=request_id,
                sender_type=self._agent_type,
                status="success",
                data=result,
                duration=duration,
            )
        except Exception as e:
            duration = time.time() - start
            logger.error(f"[RAGQueryAgent] 查询失败: {e}", exc_info=True)
            return AgentResponse(
                request_id=request_id,
                sender_type=self._agent_type,
                status="error",
                error=str(e),
                duration=duration,
            )

    # ------------------------------------------------------------------
    # 核心查询逻辑 — 通过 ContextRouter
    # ------------------------------------------------------------------

    async def _do_query(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """执行 RAG 查询

        流程：
          1. 解析参数 + 映射 query_type → ContextType
          2. 调用 ContextRouter.retrieve()（唯一查询入口）
          3. 构建 LLM 上下文文本
          4. 返回统一结果

        禁止：
          - 直接调用 Milvus / Neo4j / Embedding / MySQL
          - 重复实现 keyword/vector/graph/rerank 逻辑
        """
        start_time = time.time()

        # 解析参数
        query: str = payload.get("query", "")
        query_type: str = payload.get("query_type", "keyword")
        top_k: int = payload.get("top_k", 5)
        threshold: float = payload.get("threshold", 0.0)
        filter_dict: Dict = payload.get("filter", {})
        tags: List[str] = payload.get("tags", [])
        project_id: str = payload.get("project", "")
        session_id: str = payload.get("session", "")
        build_context: bool = payload.get("build_context", True)

        if not query:
            return {
                "status": "error",
                "message": "query 不能为空",
                "results": [],
                "context": "",
                "total": 0,
            }

        # 映射 query_type → ContextType
        context_type = self._map_query_type(query_type)

        logger.info(
            f"[RAGQueryAgent] 查询开始 | query='{query[:50]}' | "
            f"type={query_type}→{context_type.value} | "
            f"top_k={top_k} | threshold={threshold} | "
            f"tags={tags} | project={project_id}"
        )

        # 构建 ContextRouter filters
        filters: Dict[str, Any] = {}
        if filter_dict:
            filters.update(filter_dict)
        if tags:
            filters["tags"] = tags

        # === 调用 ContextRouter（唯一查询入口）===
        ctx_result = self.router.retrieve_sync(
            query=query,
            context_type=context_type,
            top_k=top_k,
            filters=filters if filters else None,
            project_id=project_id,
        )

        # 解析 ContextRouter 返回
        raw_results: List[Dict[str, Any]] = ctx_result.get("results", [])
        source_breakdown = {
            source: len(items) for source, items in ctx_result.get("sources", {}).items()
        }

        logger.info(
            f"[RAGQueryAgent] ContextRouter 返回 | "
            f"total={len(raw_results)} | "
            f"sources={source_breakdown} | "
            f"latency={ctx_result.get('latency_ms', 0)}ms | "
            f"request_id={ctx_result.get('request_id', '')}"
        )

        # 分数阈值过滤
        if threshold > 0:
            raw_results = [r for r in raw_results if r.get("score", 0) >= threshold]
            logger.info(
                f"[RAGQueryAgent] 阈值过滤 threshold={threshold} | "
                f"保留={len(raw_results)}"
            )

        # 截取 Top K
        final_results = raw_results[:top_k]

        # 构建 LLM 上下文文本
        context_text = ""
        if build_context:
            context_text = self._build_context_text(final_results)

        latency_ms = int((time.time() - start_time) * 1000)

        result = {
            "status": "success",
            "query": query,
            "query_type": query_type,
            "context_type": context_type.value,
            "results": final_results,
            "context": context_text,
            "total": len(final_results),
            "latency_ms": latency_ms,
            "context_router_latency_ms": ctx_result.get("latency_ms", 0),
            "context_router_request_id": ctx_result.get("request_id", ""),
            "source_breakdown": source_breakdown,
            "filters": {
                "tags": tags,
                "project": project_id,
                "session": session_id,
                "threshold": threshold,
            },
            "degraded": ctx_result.get("degraded", False),
            "degradation_reason": ctx_result.get("degradation_reason", ""),
        }

        logger.info(
            f"[RAGQueryAgent] 查询完成 | total={len(final_results)} | "
            f"latency={latency_ms}ms | context_len={len(context_text)}"
        )
        return result

    # ------------------------------------------------------------------
    # query_type → ContextType 映射
    # ------------------------------------------------------------------

    @staticmethod
    def _map_query_type(query_type: str):
        """将 query_type 映射为 ContextType

        RAGQueryAgent 支持的 query_type：
          requirement → DOCUMENT (知识文档检索)
          page        → PAGE_ELEMENT (页面元素检索)
          api         → DOCUMENT (接口文档检索)
          case        → TEST_CASE (测试用例检索)
          keyword     → DOCUMENT (默认走文档检索)
          all         → DOCUMENT (全类型检索)

        返回 ContextType 枚举值。
        """
        from app.services.context_router import ContextType

        type_map = {
            "requirement": ContextType.DOCUMENT,
            "page": ContextType.PAGE_ELEMENT,
            "api": ContextType.DOCUMENT,
            "case": ContextType.TEST_CASE,
            "keyword": ContextType.DOCUMENT,
            "all": ContextType.DOCUMENT,
            "script": ContextType.SCRIPT,
            "flow": ContextType.BUSINESS_FLOW,
        }
        return type_map.get(query_type, ContextType.DOCUMENT)

    # ------------------------------------------------------------------
    # 降级提示构建
    # ------------------------------------------------------------------

    @staticmethod
    def _build_degradation_notice(ctx_result: Dict[str, Any]) -> Optional[str]:
        """如果 ContextRouter 发生了降级，构建用户可见的提示信息

        当某个数据源不可用时，ContextRouter 会跳过该数据源并继续查询。
        此方法检测降级情况，返回用户可读的提示信息。
        """
        sources = ctx_result.get("sources", {})
        expected_sources = ["mysql", "milvus", "neo4j"]

        missing_sources = []
        for src in expected_sources:
            if src not in sources:
                missing_sources.append(src)

        if not missing_sources:
            return None

        source_names = {
            "mysql": "MySQL 结构化数据",
            "milvus": "Milvus 向量检索",
            "neo4j": "Neo4j 图谱扩展",
        }

        missing_names = [source_names.get(s, s) for s in missing_sources]
        return (
            f"⚠️ 降级提示：以下数据源不可用，检索结果可能不完整："
            f"{', '.join(missing_names)}。"
            f"请检查对应数据库服务是否正常运行。"
        )

    # ------------------------------------------------------------------
    # 上下文文本构建
    # ------------------------------------------------------------------

    @staticmethod
    def _build_context_text(results: List[Dict[str, Any]]) -> str:
        """将检索结果拼接为 LLM 上下文文本

        每个 result 的统一格式：
          {
            "source": "mysql" | "milvus" | "neo4j",
            "source_type": "page_element" | "knowledge_source" | ...,
            "id": str,
            "text": str,
            "score": float,
            ... 其他字段
          }
        """
        if not results:
            return ""

        parts: List[str] = []
        for r in results:
            source = r.get("source", "unknown")
            source_type = r.get("source_type", "")
            text = r.get("text", "")
            score = r.get("score", 0)

            if not text:
                continue

            header = f"[来源: {source}"
            if source_type:
                header += f" | 类型: {source_type}"
            header += f" | 相关度: {score:.2f}"
            header += "]"

            parts.append(f"{header}\n{text}\n---")

        return "\n".join(parts)
