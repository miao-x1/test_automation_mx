"""
RAGContextAgent - L1 RAG知识增强Agent

架构变更：
  原：Agent → R2R（直接调用 get_knowledge_client().retrieve()）
  新：Agent → ContextRouter → Milvus(rag_knowledge_vector) + MySQL(knowledge_source)

职责：通过 ContextRouter 检索 DOCUMENT 类型上下文，为 L1 和 L2 提供上下文补全

数据流说明：
  R2R 只在知识入库时使用（KnowledgePipeline 调用 R2R 解析→分块→向量化→存入Milvus）
  运行时检索时，DOCUMENT 类型走 Milvus(rag_knowledge_vector) + MySQL(元数据)
  R2R 不参与运行时查询。

禁止行为：
- 不允许直接生成用例
- 不允许直接生成脚本
- 不允许直接调用 R2R / Milvus
"""
from typing import Any, Dict, List, Optional
from app.core.logger import log
from app.agent.core.base import BaseAgent


class RAGContextAgent(BaseAgent):
    """RAG 知识增强 Agent

    所有查询通过 ContextRouter 路由，禁止直接调用 R2R。
    只提供上下文，不生成用例或脚本。
    """

    agent_name = "rag_context"

    def __init__(self):
        super().__init__()
        self.model = None
        self._router = None

    @property
    def router(self):
        """延迟加载 ContextRouter"""
        if self._router is None:
            from app.services.context_router import get_context_router
            self._router = get_context_router()
        return self._router

    def execute(self, **kwargs) -> Any:
        return self.retrieve(**kwargs)

    def retrieve(
        self,
        query_text: str,
        project_id: str = "",
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        通过 ContextRouter 检索文档知识

        ContextRouter 根据 DOCUMENT 类型路由到 R2R。

        Args:
            query_text: 查询文本
            project_id: 项目ID
            top_k: 返回数量
            filters: 过滤条件

        Returns:
            {
                "context": {
                    "apis": [...],
                    "entities": [...],
                    "constraints": [...],
                    "flows": [...]
                },
                "raw_chunks": [...],
                "total": int
            }
        """
        from app.services.context_router import ContextType

        log.info(
            f"RAGContextAgent | 检索(via ContextRouter) | "
            f"project={project_id}, top_k={top_k}"
        )

        try:
            # 通过 ContextRouter 检索 DOCUMENT 类型（路由到 R2R）
            ctx_result = self.router.retrieve_sync(
                query=query_text,
                context_type=ContextType.DOCUMENT,
                top_k=top_k,
                filters=filters,
                project_id=project_id,
            )

            results = ctx_result.get("results", [])

            # 标准化为统一上下文格式
            context = self._normalize_to_context(results)
            total = ctx_result.get("total", len(results))

            self.emit("retrieved", {"total": total})
            log.info(
                f"RAGContextAgent | 检索完成(via ContextRouter) | total={total} | "
                f"latency={ctx_result.get('latency_ms', 0)}ms"
            )

            return {
                "context": context,
                "raw_chunks": results,
                "total": total,
                "request_id": ctx_result.get("request_id", ""),
            }

        except Exception as e:
            log.warning(
                f"RAGContextAgent | 检索失败（降级为默认业务规则）: {e}"
            )
            return {
                "context": {
                    "apis": [],
                    "entities": [],
                    "constraints": [
                        {"text": "所有接口必须校验必填参数", "score": 1.0, "source": "默认规则"},
                        {"text": "所有接口必须校验参数类型和格式", "score": 1.0, "source": "默认规则"},
                        {"text": "所有接口必须处理异常和边界情况", "score": 1.0, "source": "默认规则"},
                        {"text": "所有写操作必须校验权限", "score": 1.0, "source": "默认规则"},
                    ],
                    "flows": [],
                },
                "raw_chunks": [],
                "total": 4,
                "error": str(e),
                "fallback": True,
            }

    def retrieve_for_l1(
        self,
        requirement_context: str,
        source_type: str = "",
        project_id: str = "",
    ) -> Dict[str, Any]:
        """为L1提供上下文（聚焦于业务规则和约束）"""
        query = f"业务规则 约束条件 测试设计 等价类 边界值 权限 {requirement_context[:500]}"
        result = self.retrieve(query_text=query, project_id=project_id, top_k=3)
        try:
            from app.knowledge.testing_expert import get_testing_expert
            expert = get_testing_expert().retrieve_for_task(requirement_context[:300], top_k=3)
            constraints = result.setdefault("context", {}).setdefault("constraints", [])
            for item in expert.get("cards", []):
                constraints.append({
                    "text": item["principle"],
                    "score": item.get("score", 1),
                    "source": f"测试专家/{item['title']}",
                    "source_type": "testing_expert",
                })
            result["expert_prompt"] = expert.get("prompt", "")
        except Exception:
            pass
        return result

    def retrieve_for_l2(
        self,
        features: List[Dict[str, Any]],
        project_id: str = "",
    ) -> Dict[str, Any]:
        """为L2提供上下文（聚焦于API定义和数据结构）"""
        query_parts = ["API接口定义 请求参数 响应结构"]
        for f in features[:5]:
            query_parts.append(f.get("title", ""))
        query = " ".join(query_parts)
        return self.retrieve(query_text=query, project_id=project_id, top_k=3)

    def _normalize_to_context(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """将 ContextRouter 检索结果标准化为统一上下文格式"""
        context = {
            "apis": [],
            "entities": [],
            "constraints": [],
            "flows": [],
        }

        for item in results:
            text = item.get("text", "")
            if not text:
                continue

            entry = {
                "text": text,
                "score": item.get("score", 0),
                "source": item.get("source", ""),
                "source_type": item.get("source_type", ""),
            }

            # 根据 source_type 和文本内容分类
            source_type = item.get("source_type", "").lower()
            text_lower = text.lower()

            if "api" in source_type or "api" in text_lower or "接口" in text:
                context["apis"].append(entry)
            elif "entity" in source_type or "实体" in text or "字段" in text:
                context["entities"].append(entry)
            elif "constraint" in source_type or "约束" in text or "规则" in text:
                context["constraints"].append(entry)
            elif "flow" in source_type or "流程" in text or "步骤" in text:
                context["flows"].append(entry)
            else:
                # 默认归入 constraints
                context["constraints"].append(entry)

        return context
