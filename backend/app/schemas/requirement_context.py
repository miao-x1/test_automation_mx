"""
RequirementContext - 统一上下文模型

所有 ParserAgent 的标准输出格式，用于 RAG 索引和用例生成。

支持输入类型：pdf, doc, swagger, image, video, schema, url, text
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class PageInfo(BaseModel):
    """页面信息（来自 URL / 图片 / 视频）"""
    page_id: str = ""
    page_name: str = ""
    page_url: Optional[str] = None
    page_type: str = "web"  # web / mobile / api
    elements_count: int = 0
    description: str = ""


class FlowStep(BaseModel):
    """业务流程的一个步骤"""
    step_id: str = ""
    action: str = ""  # goto / fill / click / submit / verify / wait
    target: Optional[str] = None  # 目标元素或接口
    value: Optional[str] = None  # 输入值
    description: str = ""


class FlowInfo(BaseModel):
    """业务流（来自视频/流程图/文本描述）"""
    flow_id: str = ""
    flow_name: str = ""
    description: str = ""
    steps: List[FlowStep] = []
    preconditions: List[str] = []
    postconditions: List[str] = []


class ApiParameter(BaseModel):
    """API 参数"""
    name: str = ""
    param_in: str = "query"  # query / path / header / body
    type: str = "string"
    required: bool = False
    description: str = ""
    default: Optional[Any] = None
    enum: List[str] = []


class ApiEndpoint(BaseModel):
    """API 端点（来自 Swagger）"""
    path: str = ""
    method: str = "GET"  # GET / POST / PUT / DELETE / PATCH
    summary: str = ""
    description: str = ""
    tags: List[str] = []
    parameters: List[ApiParameter] = []
    request_schema: Optional[Dict[str, Any]] = None
    response_schema: Optional[Dict[str, Any]] = None
    error_responses: Dict[str, str] = {}  # {code: description}


class EntityField(BaseModel):
    """数据实体的字段"""
    name: str = ""
    type: str = "string"
    required: bool = False
    description: str = ""
    default: Optional[Any] = None
    constraints: Dict[str, Any] = {}  # minLength, maxLength, pattern, min, max, enum


class EntityInfo(BaseModel):
    """数据实体（来自 Schema）"""
    entity_name: str = ""
    description: str = ""
    fields: List[EntityField] = []
    primary_key: str = ""
    indexes: List[str] = []


class ConstraintInfo(BaseModel):
    """约束/规则（来自文本/规范文档）"""
    constraint_id: str = ""
    constraint_type: str = "business"  # business / security / performance / compatibility
    description: str = ""
    source: str = ""  # 来源文档/章节
    priority: str = "medium"  # high / medium / low
    scope: str = ""  # 适用范围


class RequirementContext(BaseModel):
    """
    统一上下文模型 - 所有 ParserAgent 的标准输出

    所有字段都可空（取决于 source_type），保证灵活性
    """
    # 基础标识
    project_id: str = ""
    task_id: str = ""
    knowledge_id: Optional[int] = None  # 关联 knowledge_source
    source_type: str = "text"  # pdf / doc / swagger / image / video / schema / url / text

    # 业务目标
    business_goal: str = ""  # 业务目标概述（一句话）
    summary: str = ""  # 需求摘要

    # 结构化内容
    pages: List[PageInfo] = []
    flows: List[FlowInfo] = []
    apis: List[ApiEndpoint] = []
    entities: List[EntityInfo] = []
    constraints: List[ConstraintInfo] = []

    # 原始内容（兜底）
    raw_text: str = ""

    # 元信息
    metadata: Dict[str, Any] = Field(default_factory=dict)
    parsed_at: Optional[datetime] = None
    parse_version: int = 1

    class Config:
        json_schema_extra = {
            "example": {
                "project_id": "proj_001",
                "task_id": "task_123",
                "source_type": "swagger",
                "business_goal": "用户登录功能",
                "apis": [
                    {
                        "path": "/api/login",
                        "method": "POST",
                        "summary": "用户登录",
                        "parameters": [
                            {"name": "username", "param_in": "body", "required": True}
                        ]
                    }
                ],
                "constraints": [
                    {"constraint_type": "security", "description": "密码必须加密传输"}
                ]
            }
        }

    def to_embedding_text(self) -> str:
        """生成用于 RAG embedding 的文本"""
        parts = []

        if self.business_goal:
            parts.append(f"业务目标: {self.business_goal}")

        if self.summary:
            parts.append(f"摘要: {self.summary}")

        # 页面信息
        for p in self.pages:
            page_info = f"页面: {p.page_name}"
            if p.page_url:
                page_info += f" ({p.page_url})"
            if p.description:
                page_info += f" - {p.description}"
            parts.append(page_info)

        # 流程信息
        for f in self.flows:
            steps_str = " -> ".join(s.action for s in f.steps[:5])
            parts.append(f"流程: {f.flow_name} ({steps_str})")

        # API 信息
        for api in self.apis:
            parts.append(f"API: {api.method} {api.path} - {api.summary}")

        # 实体信息
        for ent in self.entities:
            fields_str = ", ".join(fld.name for fld in ent.fields[:5])
            parts.append(f"实体: {ent.entity_name} ({fields_str})")

        # 约束信息
        for c in self.constraints:
            parts.append(f"约束[{c.constraint_type}]: {c.description}")

        # 原始文本（截断）
        if self.raw_text:
            parts.append(f"原始内容: {self.raw_text[:2000]}")

        return "\n".join(parts)

    def to_chunk_texts(self, max_chunk_size: int = 500) -> List[Dict[str, Any]]:
        """
        将上下文拆分为多个 chunk 文本，用于 RAG 索引

        Returns:
            List of {text, chunk_type, locator}
        """
        chunks = []

        # 1. 业务目标单独一个 chunk
        if self.business_goal or self.summary:
            chunks.append({
                "text": f"业务目标: {self.business_goal}\n摘要: {self.summary}",
                "chunk_type": "narrative",
                "locator": "business_goal"
            })

        # 2. 每个 API 端点一个 chunk
        for api in self.apis:
            api_text = f"API: {api.method} {api.path}\n"
            api_text += f"描述: {api.summary}\n"
            if api.description:
                api_text += f"详细: {api.description}\n"
            if api.parameters:
                params = [f"  - {p.name}({p.type}, {'必填' if p.required else '可选'})" for p in api.parameters]
                api_text += "参数:\n" + "\n".join(params) + "\n"
            if api.request_schema:
                api_text += f"请求体: {api.request_schema}\n"
            if api.error_responses:
                api_text += f"错误响应: {api.error_responses}\n"
            chunks.append({
                "text": api_text,
                "chunk_type": "api",
                "locator": f"{api.method} {api.path}"
            })

        # 3. 每个实体一个 chunk
        for ent in self.entities:
            ent_text = f"实体: {ent.entity_name}\n"
            if ent.description:
                ent_text += f"描述: {ent.description}\n"
            ent_text += "字段:\n"
            for fld in ent.fields:
                constraints_str = f" ({fld.constraints})" if fld.constraints else ""
                ent_text += f"  - {fld.name}: {fld.type}{'(必填)' if fld.required else ''}{constraints_str}\n"
            chunks.append({
                "text": ent_text,
                "chunk_type": "entity",
                "locator": ent.entity_name
            })

        # 4. 每个流程一个 chunk
        for flow in self.flows:
            flow_text = f"流程: {flow.flow_name}\n"
            if flow.description:
                flow_text += f"描述: {flow.description}\n"
            if flow.preconditions:
                flow_text += "前置条件:\n" + "\n".join(f"  - {p}" for p in flow.preconditions) + "\n"
            flow_text += "步骤:\n"
            for i, step in enumerate(flow.steps, 1):
                flow_text += f"  {i}. {step.action}"
                if step.target:
                    flow_text += f" -> {step.target}"
                if step.description:
                    flow_text += f" ({step.description})"
                flow_text += "\n"
            chunks.append({
                "text": flow_text,
                "chunk_type": "flow",
                "locator": flow.flow_id or flow.flow_name
            })

        # 5. 每个约束一个 chunk
        for c in self.constraints:
            c_text = f"约束[{c.constraint_type}]: {c.description}\n"
            if c.source:
                c_text += f"来源: {c.source}\n"
            if c.scope:
                c_text += f"适用范围: {c.scope}\n"
            chunks.append({
                "text": c_text,
                "chunk_type": "constraint",
                "locator": c.constraint_id or ""
            })

        # 6. 每个页面一个 chunk
        for p in self.pages:
            p_text = f"页面: {p.page_name}\n"
            if p.page_url:
                p_text += f"URL: {p.page_url}\n"
            p_text += f"类型: {p.page_type}\n"
            if p.description:
                p_text += f"描述: {p.description}\n"
            if p.elements_count:
                p_text += f"元素数: {p.elements_count}\n"
            chunks.append({
                "text": p_text,
                "chunk_type": "page",
                "locator": p.page_id or p.page_name
            })

        # 7. 原始文本按段落切分
        if self.raw_text:
            paragraphs = self._split_text_to_paragraphs(self.raw_text, max_chunk_size)
            for i, para in enumerate(paragraphs):
                chunks.append({
                    "text": para,
                    "chunk_type": "narrative",
                    "locator": f"paragraph_{i+1}"
                })

        return chunks

    def _split_text_to_paragraphs(self, text: str, max_size: int) -> List[str]:
        """将长文本按段落/句子切分"""
        if len(text) <= max_size:
            return [text]

        # 先按双换行分段落
        paragraphs = text.split("\n\n")
        result = []

        for para in paragraphs:
            if len(para) <= max_size:
                result.append(para)
            else:
                # 段落太长，按句子切分
                sentences = para.replace("。", "。\n").replace("！", "！\n").replace("？", "？\n").split("\n")
                current = ""
                for s in sentences:
                    if len(current) + len(s) <= max_size:
                        current += s
                    else:
                        if current:
                            result.append(current)
                        current = s
                if current:
                    result.append(current)

        return result

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（兼容旧接口）"""
        return self.model_dump()
