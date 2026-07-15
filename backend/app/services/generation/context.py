"""
GenerationContext - 生成上下文

统一所有生成流程的输入/输出，Agent禁止直接操作数据库/HTTP/文件。

字段：
  session: 会话信息
  requirement: 需求内容
  rag: RAG检索结果
  history: 历史生成记录

规则：
  - Agent输入：GenerationContext
  - Agent输出：dict（DTO）
  - Agent禁止：数据库/HTTP/文件
"""
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class GenerationContext:
    """生成上下文（Agent统一输入）"""

    # 会话信息
    session: Dict[str, Any] = field(default_factory=dict)
    # session_id
    session_id: int = 0
    # 需求内容
    requirement: str = ""
    # 需求摘要
    requirement_summary: str = ""
    # 需求分块
    chunks: List[str] = field(default_factory=list)
    # 测试点/特性
    features: List[Dict[str, Any]] = field(default_factory=list)
    # RAG检索结果
    rag: Optional[Dict[str, Any]] = None
    # 历史生成记录
    history: List[Dict[str, Any]] = field(default_factory=list)
    # 配置
    config: Dict[str, Any] = field(default_factory=dict)
    # 用户ID
    user_id: Optional[int] = None

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "session_id": self.session_id,
            "requirement": self.requirement[:200],
            "requirement_summary": self.requirement_summary[:200],
            "chunks_count": len(self.chunks),
            "features_count": len(self.features),
            "has_rag": self.rag is not None,
            "history_count": len(self.history),
            "config_keys": list(self.config.keys()),
        }


@dataclass
class CaseDTO:
    """用例生成输出DTO"""

    title: str = ""
    preconditions: List[str] = field(default_factory=list)
    steps: List[Dict[str, Any]] = field(default_factory=list)
    assertions: List[Dict[str, Any]] = field(default_factory=list)
    expected_result: str = ""
    priority: str = "P1"
    tags: List[str] = field(default_factory=list)
    env: str = "test"
    asset_type: str = "api"
    source_type: str = "ai"

    def to_content_json(self) -> str:
        """转换为content_json格式"""
        import json
        return json.dumps({
            "title": self.title,
            "preconditions": self.preconditions,
            "steps": self.steps,
            "assertions": self.assertions,
            "expected_result": self.expected_result,
            "priority": self.priority,
            "tags": self.tags,
            "env": self.env,
        }, ensure_ascii=False)

    def is_valid(self) -> bool:
        """校验是否可执行"""
        return bool(self.steps) and bool(self.assertions)


@dataclass
class ReviewResultDTO:
    """审查结果DTO"""

    passed: bool = False
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    quality_score: float = 0.0


@dataclass
class MindmapDTO:
    """思维导图DTO"""

    nodes: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    summary: str = ""


@dataclass
class RAGResultDTO:
    """RAG检索结果DTO"""

    context: str = ""
    elements: List[Dict[str, Any]] = field(default_factory=list)
    total: int = 0
    has_context: bool = False
