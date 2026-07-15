"""
RetrieverAgent - RAG 检索 Agent

架构变更：
  原：Agent → Milvus（直接查询，集合名 case_kb_{project_id} 不存在，API 过时）
  新：Agent → ContextRouter → Milvus + MySQL + Neo4j

  所有查询通过 ContextRouter 路由，禁止直接操作 Milvus。
  所有 Embedding 通过 EmbeddingFactory 统一获取，禁止重复实现。

职责：从知识库检索与需求相关的知识内容
输入：query_text + project_id
输出：RetrievedContext 字典
"""
import time as _time
from typing import Any, Dict, List, Optional

from app.core.logger import log
from app.agent.core.base import BaseAgent


class RetrieverAgent(BaseAgent):
    """RAG 检索 Agent

    通过 ContextRouter 检索知识内容，不直接操作 Milvus。
    """

    agent_name = "retriever"

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
        """统一执行入口"""
        return self.retrieve(**kwargs)

    def retrieve(
        self,
        project_id: str,
        query_text: str,
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        score_threshold: float = 0.6,
        task_id: str = "",
    ) -> Dict[str, Any]:
        """
        执行 RAG 检索

        通过 ContextRouter 路由到 Milvus + MySQL 检索 DOCUMENT 类型。

        Args:
            project_id: 项目ID
            query_text: 查询文本
            top_k: 返回数量
            filters: 过滤条件 {source_type, chunk_type, ...}
            score_threshold: 最小相似度阈值
            task_id: 关联的任务ID

        Returns:
            RetrievedContext 字典
        """
        start = _time.time()
        log.info(
            f"RetrieverAgent | 开始检索 | project={project_id}, "
            f"top_k={top_k}, query={query_text[:50]}"
        )

        try:
            # 通过 ContextRouter 检索
            from app.services.context_router import ContextType

            result = self.router.retrieve_sync(
                query=query_text,
                context_type=ContextType.DOCUMENT,
                top_k=top_k,
                filters=filters,
                project_id=project_id,
            )

            # 解析结果并分组
            raw_results = result.get("results", [])
            grouped = self._group_and_rerank(raw_results, filters)

            latency = int((_time.time() - start) * 1000)
            all_chunks = grouped["all_chunks"]
            avg_score = (
                sum(r.get("score", 0) for r in all_chunks) / len(all_chunks)
                if all_chunks
                else 0
            )

            result_dict = {
                **grouped,
                "query_text": query_text,
                "project_id": project_id,
                "task_id": task_id,
                "top_k": top_k,
                "score_threshold": score_threshold,
                "total_results": len(all_chunks),
                "avg_score": round(avg_score, 4),
                "latency_ms": latency,
            }

            self.emit("retrieved", {"total": result_dict["total_results"], "avg_score": avg_score})
            log.info(
                f"RetrieverAgent | 检索完成 | results={result_dict['total_results']}, "
                f"avg_score={avg_score:.3f}, latency={latency}ms"
            )

            return result_dict

        except Exception as e:
            log.error(f"RetrieverAgent | 检索失败: {e}")
            self.emit("error", {"error": str(e)})
            return self._empty_result(project_id, query_text, task_id)

    def _group_and_rerank(
        self,
        results: List[Dict[str, Any]],
        filters: Optional[Dict],
    ) -> Dict[str, List]:
        """按类型分组并重排"""
        groups: Dict[str, List] = {
            "relevant_docs": [],
            "flows": [],
            "constraints": [],
            "apis": [],
            "entities": [],
            "pages": [],
        }

        type_map = {
            "flow": "flows",
            "constraint": "constraints",
            "api": "apis",
            "entity": "entities",
            "page": "pages",
            "narrative": "relevant_docs",
            "content": "relevant_docs",
        }

        for r in results:
            metadata = r.get("metadata", {}) or {}
            chunk_type = metadata.get("chunk_type", r.get("chunk_type", "narrative"))
            target_group = type_map.get(chunk_type, "relevant_docs")
            groups[target_group].append(r)

        # 按 score 排序各组
        for key in groups:
            groups[key].sort(key=lambda x: x.get("score", 0), reverse=True)

        flat = sorted(results, key=lambda x: x.get("score", 0), reverse=True)
        groups["all_chunks"] = flat

        return groups

    def _empty_result(self, project_id: str, query_text: str, task_id: str) -> Dict[str, Any]:
        """返回空结果"""
        return {
            "relevant_docs": [], "flows": [], "constraints": [],
            "apis": [], "entities": [], "pages": [], "all_chunks": [],
            "query_text": query_text, "project_id": project_id, "task_id": task_id,
            "top_k": 10, "score_threshold": 0.6,
            "total_results": 0, "avg_score": 0.0, "latency_ms": 0,
        }
