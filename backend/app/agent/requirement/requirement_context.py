"""
RequirementContext - 需求解析统一上下文模型

所有 ParserAgent 的标准输出格式，供下游用例生成与 RAG 索引使用。

包含：
- RequirementContext: 顶层上下文
- PageInfo: 页面信息（来自 URL / 图片 / 视频 / PDF）
- ElementInfo: UI 元素信息
- BusinessFlow: 业务流程
- TestPoint: 测试要点
- Constraint: 约束/规则
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PageInfo(BaseModel):
    """页面信息"""
    url: str = ""
    title: str = ""
    page_type: str = ""  # login/list/detail/form/dashboard/...
    description: str = ""
    elements: List[Dict[str, Any]] = Field(default_factory=list)


class ElementInfo(BaseModel):
    """UI 元素信息"""
    name: str = ""
    element_type: str = ""  # button/input/select/link/text/...
    locator: str = ""
    text: str = ""
    action: str = ""  # click/input/select/...
    required: bool = False


class BusinessFlow(BaseModel):
    """业务流程"""
    flow_name: str = ""
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    preconditions: List[str] = Field(default_factory=list)
    postconditions: List[str] = Field(default_factory=list)


class TestPoint(BaseModel):
    """测试要点"""
    name: str = ""
    description: str = ""
    category: str = "functional"  # functional/boundary/error/security
    priority: str = "medium"  # high/medium/low
    test_data: Dict[str, Any] = Field(default_factory=dict)


class Constraint(BaseModel):
    """约束/规则"""
    type: str = "business"  # business/technical/environmental/security
    description: str = ""
    source: str = ""  # pdf/image/video/swagger/schema


class RequirementContext(BaseModel):
    """
    统一需求上下文 - 所有 ParserAgent 的标准输出

    所有字段都可空（取决于输入来源），保证灵活性。
    """
    # 基础标识
    task_id: str = ""
    session_key: str = "default"
    source_types: List[str] = Field(default_factory=list)
    source_files: List[str] = Field(default_factory=list)

    # 业务目标
    summary: str = ""
    intent: str = ""

    # 原始内容（兜底）
    raw_requirement: str = ""

    # 结构化内容
    pages: List[PageInfo] = Field(default_factory=list)
    elements: List[ElementInfo] = Field(default_factory=list)
    business_flow: List[BusinessFlow] = Field(default_factory=list)
    test_points: List[TestPoint] = Field(default_factory=list)
    constraints: List[Constraint] = Field(default_factory=list)

    # 元信息
    metadata: Dict[str, Any] = Field(default_factory=dict)
    parsed_at: Optional[datetime] = None
    parse_version: int = 1
    user_id: Optional[int] = None

    def merge(self, other: "RequirementContext") -> "RequirementContext":
        """合并另一个 RequirementContext"""
        self.pages.extend(other.pages)
        self.elements.extend(other.elements)
        self.business_flow.extend(other.business_flow)
        self.test_points.extend(other.test_points)
        self.constraints.extend(other.constraints)
        for st in other.source_types:
            if st not in self.source_types:
                self.source_types.append(st)
        self.source_files.extend(other.source_files)
        if other.raw_requirement:
            self.raw_requirement = f"{self.raw_requirement}\n{other.raw_requirement}".strip()
        if other.summary:
            self.summary = f"{self.summary}\n{other.summary}".strip()
        if other.metadata:
            self.metadata.update(other.metadata)
        return self

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（兼容旧接口与序列化）"""
        return self.model_dump()

    def to_embedding_text(self) -> str:
        """生成用于 RAG embedding 的文本"""
        parts: List[str] = []

        if self.summary:
            parts.append(f"摘要: {self.summary}")
        if self.intent:
            parts.append(f"意图: {self.intent}")

        for p in self.pages:
            page_info = f"页面: {p.title}"
            if p.url:
                page_info += f" ({p.url})"
            if p.description:
                page_info += f" - {p.description}"
            parts.append(page_info)

        for e in self.elements:
            parts.append(f"元素: {e.name}({e.element_type}) action={e.action}")

        for f in self.business_flow:
            steps_str = " -> ".join(s.get("action", "") for s in f.steps[:5])
            parts.append(f"流程: {f.flow_name} ({steps_str})")

        for tp in self.test_points:
            parts.append(f"测试点[{tp.category}/{tp.priority}]: {tp.name} - {tp.description}")

        for c in self.constraints:
            parts.append(f"约束[{c.type}]: {c.description}")

        if self.raw_requirement:
            parts.append(f"原始内容: {self.raw_requirement[:2000]}")

        return "\n".join(parts)

    def to_compact_dict(self) -> Dict[str, Any]:
        """紧凑格式，用于LLM prompt"""
        return {
            "summary": self.summary,
            "intent": self.intent,
            "pages": [p.model_dump() for p in self.pages],
            "elements": [e.model_dump() for e in self.elements],
            "business_flow": [f.model_dump() for f in self.business_flow],
            "test_points": [t.model_dump() for t in self.test_points],
            "constraints": [c.model_dump() for c in self.constraints],
        }
