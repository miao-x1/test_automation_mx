"""
InputRouterAgent - 需求输入路由Agent

根据输入类型（文本/图片/PDF/Word/视频/Swagger/数据库Schema）选择对应的解析Agent。

使用 AutoGen Core 消息机制：
  - 接收 RequirementInputMessage（广播消息）
  - 通过 send_request() 调用对应的 ParserAgent
  - 合并所有解析结果为统一的 RequirementContext
  - 发布 RequirementContextMessage 给下游 TestCaseGeneratorAgent

路由规则：
  text          → 内置文本解析（LLM直接分析）
  image         → ImageAnalyzerAgent
  pdf           → PDFParserAgent
  word/doc/docx → PDFParserAgent（Word先转PDF或直接文本提取）
  video         → VideoAnalyzerAgent
  swagger       → SwaggerParserAgent
  schema        → DatabaseSchemaAgent
"""
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from autogen_core import message_handler, MessageContext, default_subscription
from pydantic import BaseModel, Field

from app.runtime.base_agent import BaseRoutedAgent
from app.core.logger import log
from app.agent.requirement.requirement_context import (
    RequirementContext, PageInfo, ElementInfo, BusinessFlow, TestPoint, Constraint,
)

logger = logging.getLogger(__name__)


# ================================================================== #
#  AutoGen 消息类型定义                                                #
# ================================================================== #

class RequirementInputMessage(BaseModel):
    """
    需求输入消息（广播给 InputRouterAgent）

    支持多种输入类型的混合：
      - text: 需求文本
      - image_paths: 图片文件路径列表
      - pdf_paths: PDF文件路径列表
      - word_paths: Word文件路径列表
      - video_paths: 视频文件路径列表
      - swagger_content: Swagger/OpenAPI JSON字符串
      - schema_content: 数据库DDL SQL字符串
      - urls: URL列表
      - context: 附加上下文（系统名称/业务背景等）
    """
    task_id: str = ""
    session_key: str = "default"
    user_id: Optional[int] = None

    # 多模态输入
    text: str = ""
    image_paths: List[str] = Field(default_factory=list)
    pdf_paths: List[str] = Field(default_factory=list)
    word_paths: List[str] = Field(default_factory=list)
    video_paths: List[str] = Field(default_factory=list)
    swagger_content: str = ""
    schema_content: str = ""
    urls: List[str] = Field(default_factory=list)

    # 附加上下文
    context: Dict[str, Any] = Field(default_factory=dict)


class RequirementContextMessage(BaseModel):
    """
    需求上下文消息（InputRouterAgent → TestCaseGeneratorAgent）

    携带统一的 RequirementContext，供下游用例生成使用。
    """
    task_id: str = ""
    session_key: str = "default"
    user_id: Optional[int] = None
    context: Dict[str, Any] = Field(default_factory=dict)


# ================================================================== #
#  InputRouterAgent                                                   #
# ================================================================== #

@default_subscription
class InputRouterAgent(BaseRoutedAgent):
    """
    需求输入路由Agent

    职责：
    1. 接收多种类型的输入
    2. 根据输入类型路由到对应的 ParserAgent
    3. 合并所有解析结果为统一的 RequirementContext
    4. 发布 RequirementContextMessage 给下游 Agent

    使用 AutoGen 消息机制：
    - 接收 RequirementInputMessage（通过 publish_message 广播）
    - 通过 send_request() 调用 ParserAgent（请求-响应模式）
    - 发布 RequirementContextMessage（通过 publish_message 广播）
    """

    def __init__(self) -> None:
        super().__init__(
            description="需求输入路由Agent，根据输入类型选择解析Agent并合并结果",
            display_name="InputRouterAgent",
            capabilities=["input_route", "requirement_parse"],
        )

    async def execute(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """
        执行需求输入路由

        payload 可以包含：
          - text, image_paths, pdf_paths, word_paths, video_paths
          - swagger_content, schema_content, urls, context
          - task_id, session_key, user_id
        """
        task_id = payload.get("task_id", "")
        session_key = payload.get("session_key", "default")
        user_id = payload.get("user_id")

        log.info(f"[InputRouterAgent] 开始路由需求输入 | task_id={task_id}")

        # 构建 RequirementInputMessage
        input_msg = RequirementInputMessage(
            task_id=task_id,
            session_key=session_key,
            user_id=user_id,
            text=payload.get("text", ""),
            image_paths=payload.get("image_paths", []),
            pdf_paths=payload.get("pdf_paths", []),
            word_paths=payload.get("word_paths", []),
            video_paths=payload.get("video_paths", []),
            swagger_content=payload.get("swagger_content", ""),
            schema_content=payload.get("schema_content", ""),
            urls=payload.get("urls", []),
            context=payload.get("context", {}),
        )

        # 路由并收集结果
        contexts = await self._route_and_collect(input_msg, ctx)

        if not contexts:
            log.warning("[InputRouterAgent] 无解析结果，返回空上下文")
            empty_ctx = RequirementContext(
                task_id=task_id,
                session_key=session_key,
                summary="无法解析输入内容",
                intent="unknown",
            )
            return {"status": "success", "context": empty_ctx.to_dict()}

        # 合并所有 RequirementContext
        merged = contexts[0]
        for ctx_item in contexts[1:]:
            merged.merge(ctx_item)

        # 如果有文本输入但未被独立处理，补充到 raw_requirement
        if input_msg.text and input_msg.text not in merged.raw_requirement:
            merged.raw_requirement = f"{input_msg.text}\n{merged.raw_requirement}".strip()

        # 补充附加上下文到 constraints
        if input_msg.context:
            for key, value in input_msg.context.items():
                if value and isinstance(value, str):
                    merged.constraints.append(Constraint(
                        type="business",
                        description=f"{key}: {value}",
                        source="context",
                    ))

        log.info(
            f"[InputRouterAgent] 路由完成 | "
            f"sources={merged.source_types}, "
            f"pages={len(merged.pages)}, "
            f"elements={len(merged.elements)}, "
            f"flows={len(merged.business_flow)}, "
            f"test_points={len(merged.test_points)}, "
            f"constraints={len(merged.constraints)}"
        )

        return {"status": "success", "context": merged.to_dict()}

    async def _route_and_collect(
        self, input_msg: RequirementInputMessage, ctx: MessageContext
    ) -> List[RequirementContext]:
        """根据输入类型路由到对应的ParserAgent，收集所有结果"""
        contexts: List[RequirementContext] = []
        session_key = input_msg.session_key

        # 1. 文本输入 → 内置文本解析
        if input_msg.text.strip():
            log.info("[InputRouterAgent] 路由: text → 内置文本解析")
            ctx_text = await self._parse_text(input_msg)
            if ctx_text:
                contexts.append(ctx_text)

        # 2. 图片输入 → ImageAnalyzerAgent
        if input_msg.image_paths:
            log.info(f"[InputRouterAgent] 路由: {len(input_msg.image_paths)} images → ImageAnalyzerAgent")
            ctx_img = await self._dispatch_parser(
                "image_analyzer_agent", "analyze", {
                    "image_paths": input_msg.image_paths,
                    "requirement": input_msg.text,
                    "task_id": input_msg.task_id,
                    "session_key": session_key,
                }, session_key
            )
            if ctx_img:
                contexts.append(ctx_img)

        # 3. PDF输入 → PDFParserAgent
        for pdf_path in input_msg.pdf_paths:
            log.info(f"[InputRouterAgent] 路由: pdf → PDFParserAgent | {pdf_path}")
            ctx_pdf = await self._dispatch_parser(
                "pdf_parser_agent", "analyze", {
                    "file_path": pdf_path,
                    "requirement": input_msg.text,
                    "task_id": input_msg.task_id,
                    "session_key": session_key,
                }, session_key
            )
            if ctx_pdf:
                contexts.append(ctx_pdf)

        # 4. Word输入 → PDFParserAgent（Word文档也走PDFParser，内部兼容docx）
        for word_path in input_msg.word_paths:
            log.info(f"[InputRouterAgent] 路由: word → PDFParserAgent | {word_path}")
            ctx_word = await self._dispatch_parser(
                "pdf_parser_agent", "analyze", {
                    "file_path": word_path,
                    "requirement": input_msg.text,
                    "task_id": input_msg.task_id,
                    "session_key": session_key,
                }, session_key
            )
            if ctx_word:
                contexts.append(ctx_word)

        # 5. 视频输入 → VideoAnalyzerAgent
        for video_path in input_msg.video_paths:
            log.info(f"[InputRouterAgent] 路由: video → VideoAnalyzerAgent | {video_path}")
            ctx_video = await self._dispatch_parser(
                "video_analyzer_agent", "analyze", {
                    "video_path": video_path,
                    "requirement": input_msg.text,
                    "task_id": input_msg.task_id,
                    "session_key": session_key,
                }, session_key
            )
            if ctx_video:
                contexts.append(ctx_video)

        # 6. Swagger输入 → SwaggerParserAgent
        if input_msg.swagger_content:
            log.info("[InputRouterAgent] 路由: swagger → SwaggerParserAgent")
            ctx_swagger = await self._dispatch_parser(
                "swagger_parser_agent", "analyze", {
                    "swagger_content": input_msg.swagger_content,
                    "requirement": input_msg.text,
                    "task_id": input_msg.task_id,
                    "session_key": session_key,
                }, session_key
            )
            if ctx_swagger:
                contexts.append(ctx_swagger)

        # 7. 数据库Schema → DatabaseSchemaAgent
        if input_msg.schema_content:
            log.info("[InputRouterAgent] 路由: schema → DatabaseSchemaAgent")
            ctx_schema = await self._dispatch_parser(
                "database_schema_agent", "analyze", {
                    "schema_content": input_msg.schema_content,
                    "requirement": input_msg.text,
                    "task_id": input_msg.task_id,
                    "session_key": session_key,
                }, session_key
            )
            if ctx_schema:
                contexts.append(ctx_schema)

        return contexts

    async def _dispatch_parser(
        self, agent_type: str, action: str, payload: Dict[str, Any], session_key: str
    ) -> Optional[RequirementContext]:
        """
        通过 AutoGen send_request 调用 ParserAgent

        使用请求-响应模式：send_message(AgentRequest, AgentId) → AgentResponse
        """
        try:
            response = await self.send_request(
                target_agent_type=agent_type,
                action=action,
                payload=payload,
                target_key=session_key,
            )
            if response and response.status == "success":
                ctx_data = response.data.get("context", {})
                if ctx_data:
                    return RequirementContext(**ctx_data)
            else:
                log.warning(
                    f"[InputRouterAgent] {agent_type} 返回失败 | "
                    f"status={response.status if response else 'None'}, "
                    f"error={response.error if response else 'No response'}"
                )
        except Exception as e:
            log.error(f"[InputRouterAgent] 调用 {agent_type} 失败: {e}")
        return None

    async def _parse_text(self, input_msg: RequirementInputMessage) -> Optional[RequirementContext]:
        """
        内置文本解析 - 直接调用LLM分析需求文本

        不需要路由到其他Agent，直接在InputRouterAgent内处理。
        """
        text = input_msg.text.strip()
        if not text:
            return None

        try:
            system_prompt = (
                "你是测试需求分析专家。请分析以下需求文本，提取测试相关信息。\n"
                "返回JSON格式，包含以下字段：\n"
                '{"pages": [{"url":"","title":"页面名称","page_type":"login/list/detail/form/dashboard","description":"页面描述","elements":[]}],\n'
                '"elements": [{"name":"元素名","element_type":"button/input/select/link/text","locator":"","text":"显示文本","action":"click/input/select","required":false}],\n'
                '"business_flow": [{"flow_name":"流程名","steps":[{"action":"","target":"","description":""}],"preconditions":[],"postconditions":[]}],\n'
                '"test_points": [{"name":"测试点名","description":"描述","category":"functional/boundary/error/security","priority":"high/medium/low","test_data":{}}],\n'
                '"constraints": [{"type":"business/technical/environmental","description":"约束描述","source":"text"}],\n'
                '"summary": "整体摘要","intent": "测试意图"}\n'
                "只返回JSON，不要其他内容。"
            )

            parsed = await self.call_llm_json(
                system_prompt=system_prompt,
                user_prompt=text[:8000],
                temperature=0.3,
                task_id=input_msg.task_id,
                step="text_parse",
                session_key=input_msg.session_key,
            )

            context = RequirementContext(
                task_id=input_msg.task_id,
                session_key=input_msg.session_key,
                source_types=["text"],
                source_files=[],
                raw_requirement=text[:4000],
                summary=parsed.get("summary", ""),
                intent=parsed.get("intent", "text_requirement"),
            )

            # 填充 pages
            for p in parsed.get("pages", []):
                context.pages.append(PageInfo(
                    url=p.get("url", ""),
                    title=p.get("title", ""),
                    page_type=p.get("page_type", ""),
                    description=p.get("description", ""),
                    elements=p.get("elements", []),
                ))

            # 填充 elements
            for e in parsed.get("elements", []):
                context.elements.append(ElementInfo(
                    name=e.get("name", ""),
                    element_type=e.get("element_type", ""),
                    locator=e.get("locator", ""),
                    text=e.get("text", ""),
                    action=e.get("action", ""),
                    required=e.get("required", False),
                ))

            # 填充 business_flow
            for f in parsed.get("business_flow", []):
                context.business_flow.append(BusinessFlow(
                    flow_name=f.get("flow_name", ""),
                    steps=f.get("steps", []),
                    preconditions=f.get("preconditions", []),
                    postconditions=f.get("postconditions", []),
                ))

            # 填充 test_points
            for tp in parsed.get("test_points", []):
                context.test_points.append(TestPoint(
                    name=tp.get("name", ""),
                    description=tp.get("description", ""),
                    category=tp.get("category", "functional"),
                    priority=tp.get("priority", "medium"),
                    test_data=tp.get("test_data", {}),
                ))

            # 填充 constraints
            for c in parsed.get("constraints", []):
                context.constraints.append(Constraint(
                    type=c.get("type", "business"),
                    description=c.get("description", ""),
                    source="text",
                ))

            log.info(f"[InputRouterAgent] 文本解析完成 | {len(context.test_points)} test_points")
            return context

        except Exception as e:
            log.error(f"[InputRouterAgent] 文本解析失败: {e}")
            # 降级：返回基础上下文
            return RequirementContext(
                task_id=input_msg.task_id,
                session_key=input_msg.session_key,
                source_types=["text"],
                raw_requirement=text[:4000],
                summary="文本解析降级",
                intent="text_requirement",
            )
