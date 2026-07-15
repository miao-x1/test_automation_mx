"""
Generation 模块

拆分Agent职责：
  RequirementAgent - 需求理解
  RagAgent - RAG检索
  CaseGenerateAgent - 用例生成
  ReviewAgent - 审查
  MindmapAgent - 思维导图

规则：
  - Agent输入：GenerationContext
  - Agent输出：DTO
  - Agent禁止：数据库/HTTP/文件
"""
from app.services.generation.context import (
    GenerationContext,
    CaseDTO,
    ReviewResultDTO,
    MindmapDTO,
    RAGResultDTO,
)
from app.services.generation.requirement_agent import RequirementAgent
from app.services.generation.rag_agent import RagAgent
from app.services.generation.case_generate_agent import CaseGenerateAgent
from app.services.generation.review_agent import ReviewAgent
from app.services.generation.mindmap_agent import MindmapAgent

__all__ = [
    "GenerationContext",
    "CaseDTO",
    "ReviewResultDTO",
    "MindmapDTO",
    "RAGResultDTO",
    "RequirementAgent",
    "RagAgent",
    "CaseGenerateAgent",
    "ReviewAgent",
    "MindmapAgent",
]
