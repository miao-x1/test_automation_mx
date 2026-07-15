"""
RetrievedContext - RAG 检索结果模型

RetrieverAgent 的输出格式，包含从知识库检索到的相关内容。
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RetrievedChunk(BaseModel):
    """检索到的单个 chunk"""
    chunk_id: int = 0
    text: str = ""
    score: float = 0.0
    source_type: str = ""
    locator: str = ""
    knowledge_id: int = 0
    document_id: int = 0
    chunk_type: str = "narrative"  # narrative / api / entity / flow / constraint / page
    page: str = ""
    section: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_reference_str(self) -> str:
        """生成引用字符串"""
        if self.locator:
            return f"[{self.chunk_type}:{self.locator}]"
        return f"[doc:{self.knowledge_id}]"


class RetrievedContext(BaseModel):
    """
    RAG 检索结果

    包含从知识库检索到的相关内容，按类型分组
    """
    # 检索元信息
    query_text: str = ""
    project_id: str = ""
    task_id: str = ""
    top_k: int = 10
    score_threshold: float = 0.6

    # 检索结果（按类型分组）
    relevant_docs: List[RetrievedChunk] = []  # 通用文档
    flows: List[RetrievedChunk] = []          # 流程类
    constraints: List[RetrievedChunk] = []    # 约束类
    apis: List[RetrievedChunk] = []           # API 类
    entities: List[RetrievedChunk] = []       # 实体类
    pages: List[RetrievedChunk] = []          # 页面类

    # 统计信息
    total_results: int = 0
    avg_score: float = 0.0
    latency_ms: int = 0

    # 所有 chunks（扁平化）
    all_chunks: List[RetrievedChunk] = []

    class Config:
        json_schema_extra = {
            "example": {
                "query_text": "用户登录流程",
                "project_id": "proj_001",
                "relevant_docs": [
                    {
                        "text": "用户通过用户名密码登录系统...",
                        "score": 0.85,
                        "source_type": "doc",
                        "chunk_type": "narrative"
                    }
                ],
                "flows": [
                    {
                        "text": "流程: 登录\n步骤: 1. goto -> 登录页...",
                        "score": 0.92,
                        "chunk_type": "flow"
                    }
                ],
                "total_results": 5,
                "avg_score": 0.78
            }
        }

    def get_top_chunks(self, n: int = 10) -> List[RetrievedChunk]:
        """获取得分最高的 n 个 chunks"""
        all_items = (
            self.relevant_docs +
            self.flows +
            self.constraints +
            self.apis +
            self.entities +
            self.pages
        )
        sorted_items = sorted(all_items, key=lambda x: x.score, reverse=True)
        return sorted_items[:n]

    def to_prompt_section(self, max_chunks: int = 10) -> str:
        """
        生成用于 LLM Prompt 的 RAG 参考部分

        Args:
            max_chunks: 每类最多包含的 chunk 数

        Returns:
            格式化的参考文本
        """
        sections = []

        # 业务流程
        if self.flows:
            flow_texts = []
            for chunk in self.flows[:max_chunks]:
                flow_texts.append(f"- {chunk.text[:500]}")
                if chunk.score > 0.8:
                    flow_texts.append(f"  (相关度: {chunk.score:.2f})")
            sections.append("## 相关业务流程\n" + "\n".join(flow_texts))

        # API 接口
        if self.apis:
            api_texts = []
            for chunk in self.apis[:max_chunks]:
                api_texts.append(f"- {chunk.text[:500]}")
            sections.append("## 相关 API 接口\n" + "\n".join(api_texts))

        # 数据实体
        if self.entities:
            entity_texts = []
            for chunk in self.entities[:max_chunks]:
                entity_texts.append(f"- {chunk.text[:500]}")
            sections.append("## 相关数据实体\n" + "\n".join(entity_texts))

        # 业务约束
        if self.constraints:
            constraint_texts = []
            for chunk in self.constraints[:max_chunks]:
                constraint_texts.append(f"- [{chunk.metadata.get('constraint_type', 'business')}] {chunk.text[:300]}")
            sections.append("## 业务约束\n" + "\n".join(constraint_texts))

        # 页面信息
        if self.pages:
            page_texts = []
            for chunk in self.pages[:max_chunks]:
                page_texts.append(f"- {chunk.text[:300]}")
            sections.append("## 相关页面\n" + "\n".join(page_texts))

        # 其他相关文档
        if self.relevant_docs:
            doc_texts = []
            for chunk in self.relevant_docs[:max_chunks]:
                doc_texts.append(f"- {chunk.text[:500]}")
            sections.append("## 其他相关文档\n" + "\n".join(doc_texts))

        if not sections:
            return ""

        header = "# 知识库参考（来自项目历史资料）\n\n以下是从项目知识库中检索到的相关内容，生成的测试用例应与这些参考保持一致：\n"
        return header + "\n\n".join(sections)

    def get_references(self) -> List[str]:
        """获取所有引用字符串"""
        refs = []
        for chunk in self.get_top_chunks(20):
            ref = chunk.to_reference_str()
            if ref and ref not in refs:
                refs.append(ref)
        return refs

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return self.model_dump()
