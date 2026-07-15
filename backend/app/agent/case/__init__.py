"""
Case Agent 模块 - AI驱动测试用例生成

统一入口：CaseAgent
  - generate()            → Web UI 测试用例
  - generate_rag_cases()  → RAG增强用例（无RAG上下文时自动退化为纯文本生成）
  - compile_stream()      → API测试用例流式生成

Agent协作流程：
  ParserAgent → CaseAgent → ReviewAgent
"""
from app.agent.case.agent_selector import AgentSelector
from app.agent.case.document_parser import DocumentParserAgent
from app.agent.case.image_parser import ImageParserAgent
from app.agent.case.case_agent import CaseAgent
from app.agent.case.review_agent import ReviewAgent
from app.agent.case.mindmap_agent import MindMapAgent

__all__ = [
    "AgentSelector",
    "DocumentParserAgent",
    "ImageParserAgent",
    "CaseAgent",
    "ReviewAgent",
    "MindMapAgent",
]
