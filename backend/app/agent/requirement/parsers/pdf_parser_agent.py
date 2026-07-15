"""PDFParserAgent - PDF文档解析Agent

将PDF需求文档解析为统一的RequirementContext。
使用pdfplumber提取文本和表格，LLM分析提取测试要点。
"""
import json
import logging
import time
from typing import Any, Dict

from autogen_core import message_handler, MessageContext, default_subscription

from app.runtime.base_agent import BaseRoutedAgent
from app.runtime.messages import AgentRequest, AgentResponse
from app.agent.requirement.requirement_context import (
    RequirementContext, PageInfo, ElementInfo, BusinessFlow, TestPoint, Constraint,
)
from app.core.logger import log

logger = logging.getLogger(__name__)


@default_subscription
class PDFParserAgent(BaseRoutedAgent):
    """PDF文档解析Agent - 将PDF解析为RequirementContext"""

    def __init__(self) -> None:
        super().__init__(
            description="PDF文档解析Agent，提取PDF中的需求信息和测试要点",
            display_name="PDFParserAgent",
            capabilities=["pdf_parse", "requirement_parse"],
        )

    async def execute(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """解析PDF文档"""
        file_path = payload.get("file_path", "")
        requirement = payload.get("requirement", "")
        task_id = payload.get("task_id", "")
        session_key = payload.get("session_key", "default")

        log.info(f"[PDFParserAgent] 开始解析PDF: {file_path}")

        # Step 1: 提取PDF文本
        pdf_text = ""
        tables = []
        try:
            import pdfplumber
            with pdfplumber.open(file_path) as pdf:
                for i, page in enumerate(pdf.pages):
                    text = page.extract_text() or ""
                    if text:
                        pdf_text += f"\n## Page {i+1}\n{text}"
                    for table in page.extract_tables():
                        if table:
                            tables.append({"page": i+1, "data": table})
            log.info(f"[PDFParserAgent] PDF提取完成: {len(pdf_text)} chars, {len(tables)} tables")
        except ImportError:
            log.error("[PDFParserAgent] pdfplumber not installed")
            pdf_text = ""
        except Exception as e:
            log.error(f"[PDFParserAgent] PDF解析失败: {e}")
            pdf_text = ""

        if not pdf_text and not requirement:
            return {"status": "error", "error": "PDF内容为空且无附加需求文本"}

        # Step 2: LLM分析提取需求
        combined_text = f"{pdf_text}\n\n附加需求: {requirement}" if requirement else pdf_text
        # 截断防止超出token限制
        if len(combined_text) > 8000:
            combined_text = combined_text[:8000]

        system_prompt = (
            "你是测试需求分析专家。请分析以下PDF文档内容，提取测试相关信息。\n"
            "返回JSON格式，包含以下字段：\n"
            '{"pages": [{"url":"","title":"页面名称","page_type":"login/list/detail/form/dashboard","description":"页面描述","elements":[]}],\n'
            '"elements": [{"name":"元素名","element_type":"button/input/select/link/text","locator":"","text":"显示文本","action":"click/input/select","required":false}],\n'
            '"business_flow": [{"flow_name":"流程名","steps":[{"action":"","target":"","description":""}],"preconditions":[],"postconditions":[]}],\n'
            '"test_points": [{"name":"测试点名","description":"描述","category":"functional/boundary/error/security","priority":"high/medium/low","test_data":{}}],\n'
            '"constraints": [{"type":"business/technical/environmental","description":"约束描述","source":"pdf"}],\n'
            '"summary": "整体摘要","intent": "测试意图"}\n'
            "只返回JSON，不要其他内容。"
        )

        try:
            llm_response = await self.call_llm(
                system_prompt=system_prompt,
                user_prompt=combined_text,
                temperature=0.3,
                max_tokens=4096,
                task_id=task_id,
                step="pdf_llm_analyze",
                session_key=session_key,
            )
            parsed = self._parse_llm_json(llm_response)
        except Exception as e:
            log.error(f"[PDFParserAgent] LLM分析失败: {e}")
            parsed = {"summary": pdf_text[:500], "intent": "pdf_requirement"}

        # Step 3: 构建RequirementContext
        context = RequirementContext(
            task_id=task_id,
            session_key=session_key,
            source_types=["pdf"],
            source_files=[file_path],
            raw_requirement=pdf_text[:4000],
            summary=parsed.get("summary", ""),
            intent=parsed.get("intent", "pdf_requirement"),
            metadata={"page_count": len(pdf_text.split("## Page")) - 1, "table_count": len(tables)},
        )

        # 填充pages
        for p in parsed.get("pages", []):
            context.pages.append(PageInfo(
                url=p.get("url", ""),
                title=p.get("title", ""),
                page_type=p.get("page_type", ""),
                description=p.get("description", ""),
                elements=p.get("elements", []),
            ))

        # 填充elements
        for e in parsed.get("elements", []):
            context.elements.append(ElementInfo(
                name=e.get("name", ""),
                element_type=e.get("element_type", ""),
                locator=e.get("locator", ""),
                text=e.get("text", ""),
                action=e.get("action", ""),
                required=e.get("required", False),
            ))

        # 填充business_flow
        for f in parsed.get("business_flow", []):
            context.business_flow.append(BusinessFlow(
                flow_name=f.get("flow_name", ""),
                steps=f.get("steps", []),
                preconditions=f.get("preconditions", []),
                postconditions=f.get("postconditions", []),
            ))

        # 填充test_points
        for tp in parsed.get("test_points", []):
            context.test_points.append(TestPoint(
                name=tp.get("name", ""),
                description=tp.get("description", ""),
                category=tp.get("category", "functional"),
                priority=tp.get("priority", "medium"),
                test_data=tp.get("test_data", {}),
            ))

        # 填充constraints
        for c in parsed.get("constraints", []):
            context.constraints.append(Constraint(
                type=c.get("type", "business"),
                description=c.get("description", ""),
                source="pdf",
            ))

        log.info(f"[PDFParserAgent] 解析完成: {len(context.pages)} pages, {len(context.test_points)} test_points")
        return {"status": "success", "context": context.to_dict()}

    def _parse_llm_json(self, raw: str) -> dict:
        """解析LLM返回的JSON"""
        if isinstance(raw, dict):
            return raw
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        try:
            return json.loads(raw)
        except Exception:
            return {"summary": str(raw)[:500]}
