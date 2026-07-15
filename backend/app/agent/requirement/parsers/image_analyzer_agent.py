"""ImageAnalyzerAgent - 图片/UI截图分析Agent

将UI截图/设计图解析为统一的RequirementContext。
使用VisionParser（qwen-vl-max）识别UI元素，LLM生成测试要点。
"""
import json
import logging
from typing import Any, Dict, List

from autogen_core import message_handler, MessageContext, default_subscription

from app.runtime.base_agent import BaseRoutedAgent
from app.runtime.messages import AgentRequest, AgentResponse
from app.agent.requirement.requirement_context import (
    RequirementContext, PageInfo, ElementInfo, BusinessFlow, TestPoint, Constraint,
)
from app.core.logger import log

logger = logging.getLogger(__name__)


@default_subscription
class ImageAnalyzerAgent(BaseRoutedAgent):
    """图片/UI截图分析Agent - 将图片解析为RequirementContext"""

    def __init__(self) -> None:
        super().__init__(
            description="图片/UI截图分析Agent，识别UI元素并提取测试要点",
            display_name="ImageAnalyzerAgent",
            capabilities=["image_parse", "vision_analyze", "requirement_parse"],
        )

    async def execute(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """分析图片/UI截图"""
        image_paths: List[str] = payload.get("image_paths", []) or []
        requirement = payload.get("requirement", "")
        task_id = payload.get("task_id", "")
        session_key = payload.get("session_key", "default")

        log.info(f"[ImageAnalyzerAgent] 开始分析图片: {len(image_paths)} 张")

        if not image_paths:
            return {"status": "error", "error": "未提供图片路径(image_paths)"}

        # Step 1: 使用VisionParser分析图片
        image_analysis: Dict[str, Any] = {}
        try:
            from app.agent.requirement.input_router import VisionParser
            parser = VisionParser()
            result = parser.parse(image_paths)
            image_analysis = result.to_dict()
            log.info(
                f"[ImageAnalyzerAgent] VisionParser完成: "
                f"success={image_analysis.get('success')}, "
                f"elements={len(image_analysis.get('elements', []))}"
            )
        except Exception as e:
            log.warning(f"[ImageAnalyzerAgent] VisionParser失败: {e}")
            image_analysis = {"summary": "图片分析失败", "elements": [], "success": False}

        # Step 2: LLM分析生成测试要点
        analysis_text = json.dumps(image_analysis, ensure_ascii=False, default=str)
        if len(analysis_text) > 8000:
            analysis_text = analysis_text[:8000]

        system_prompt = (
            "你是UI测试需求分析专家。请分析以下UI截图识别结果，提取测试相关信息。\n"
            "返回JSON格式，包含以下字段：\n"
            '{"pages": [{"url":"","title":"页面名称","page_type":"login/list/detail/form/dashboard","description":"页面描述","elements":[]}],\n'
            '"elements": [{"name":"元素名","element_type":"button/input/select/link/text","locator":"","text":"显示文本","action":"click/input/select","required":false}],\n'
            '"business_flow": [{"flow_name":"流程名","steps":[{"action":"","target":"","description":""}],"preconditions":[],"postconditions":[]}],\n'
            '"test_points": [{"name":"测试点名","description":"描述","category":"functional/boundary/error/security","priority":"high/medium/low","test_data":{}}],\n'
            '"constraints": [{"type":"business/technical/environmental","description":"约束描述","source":"image"}],\n'
            '"summary": "整体摘要","intent": "测试意图"}\n'
            "只返回JSON，不要其他内容。"
        )

        user_prompt = analysis_text
        if requirement:
            user_prompt = f"附加需求: {requirement}\n\n识别结果:\n{analysis_text}"

        try:
            llm_response = await self.call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=4096,
                task_id=task_id,
                step="image_llm_analyze",
                session_key=session_key,
            )
            parsed = self._parse_llm_json(llm_response)
        except Exception as e:
            log.error(f"[ImageAnalyzerAgent] LLM分析失败: {e}")
            parsed = {
                "summary": image_analysis.get("summary", "图片需求"),
                "intent": image_analysis.get("intent", "image_requirement"),
            }

        # Step 3: 构建RequirementContext
        context = RequirementContext(
            task_id=task_id,
            session_key=session_key,
            source_types=["image"],
            source_files=image_paths,
            raw_requirement=image_analysis.get("summary", ""),
            summary=parsed.get("summary", image_analysis.get("summary", "")),
            intent=parsed.get("intent", image_analysis.get("intent", "image_requirement")),
            metadata={
                "image_count": len(image_paths),
                "vision_success": image_analysis.get("success", False),
                "page_type": image_analysis.get("extra", {}).get("page_type", ""),
                "keywords": image_analysis.get("keywords", []),
            },
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

        # 若LLM未给出pages，用VisionParser结果兜底
        if not context.pages and image_analysis.get("extra", {}).get("page_type"):
            context.pages.append(PageInfo(
                url="",
                title=image_analysis.get("summary", "UI截图"),
                page_type=image_analysis.get("extra", {}).get("page_type", ""),
                description=image_analysis.get("summary", ""),
                elements=image_analysis.get("elements", []),
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

        # 若LLM未给出elements，用VisionParser结果兜底
        if not context.elements:
            for e in image_analysis.get("elements", []):
                context.elements.append(ElementInfo(
                    name=e.get("name", ""),
                    element_type=e.get("type", ""),
                    locator="",
                    text=e.get("action", ""),
                    action=e.get("action", ""),
                    required=False,
                ))

        # 填充business_flow
        for f in parsed.get("business_flow", []):
            context.business_flow.append(BusinessFlow(
                flow_name=f.get("flow_name", ""),
                steps=f.get("steps", []),
                preconditions=f.get("preconditions", []),
                postconditions=f.get("postconditions", []),
            ))

        # 若LLM未给出business_flow，用VisionParser的steps兜底
        if not context.business_flow and image_analysis.get("steps"):
            context.business_flow.append(BusinessFlow(
                flow_name="UI操作流程",
                steps=[{"action": s, "target": "", "description": s} for s in image_analysis.get("steps", [])],
                preconditions=[],
                postconditions=[],
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
                source="image",
            ))

        log.info(
            f"[ImageAnalyzerAgent] 分析完成: "
            f"{len(context.pages)} pages, {len(context.elements)} elements, "
            f"{len(context.test_points)} test_points"
        )
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
