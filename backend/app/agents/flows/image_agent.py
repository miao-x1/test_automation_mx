"""ImageAgent - 页面元素分析Agent（消息驱动）

接收 PageMessage，分析页面元素，输出 CaseMessage
"""
import json
import os
import time
import logging
import traceback
from typing import Any, Dict, List, Optional, Tuple

STATUS_SUCCESS = "SUCCESS"
STATUS_FAILED = "FAILED"
STATUS_INVALID_INPUT = "INVALID_INPUT"


def decide_image_source(urls: List[str], image_paths: List[str]) -> str:
    """upload | url | invalid。禁止无输入时回落到 mock 元素。"""
    images = [p for p in (image_paths or []) if str(p).strip()]
    targets = [u for u in (urls or []) if str(u).strip()]
    if images:
        return "upload"
    if targets:
        return "url"
    return "invalid"

from autogen_core import message_handler, MessageContext, DefaultTopicId, default_subscription

from app.runtime.base_agent import BaseRoutedAgent
from app.agents.messages import PageMessage, CaseMessage

logger = logging.getLogger(__name__)


@default_subscription
class ImageAgent(BaseRoutedAgent):
    """页面元素分析Agent - 接收页面消息，分析元素后发布用例消息"""

    def __init__(self) -> None:
        super().__init__(
            description="页面元素分析Agent，提取页面可交互元素",
            display_name="ImageAgent",
            capabilities=["page_element_analysis"],
        )

    async def execute(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """GraphFlow 入口：构造 PageMessage 并处理"""
        from app.agents.messages import PageMessage
        msg = PageMessage(
            task_id=payload.get("task_id", ""),
            session_key=payload.get("session_key", "default"),
            intent=payload.get("intent", ""),
            test_steps=payload.get("test_steps", []),
            target_urls=payload.get("target_urls", payload.get("urls", [])),
            image_paths=payload.get("image_paths", payload.get("images", [])),
            test_scope=payload.get("test_scope", ""),
            page_descriptions=payload.get("page_descriptions", {}),
        )
        status = await self.handle_page(msg, ctx)
        return {"status": status, "step": "image", "task_id": msg.task_id}

    @message_handler
    async def handle_page(self, message: PageMessage, ctx: MessageContext) -> str:
        """处理页面消息。返回 SUCCESS / FAILED / INVALID_INPUT。"""
        start = time.time()
        logger.info(f"[ImageAgent] 收到页面消息: task={message.task_id}")

        try:
            await self.emit_start(
                task_id=message.task_id,
                step="image",
                message=f"{self._display_name} 开始处理",
                session_key=message.session_key,
            )
            urls = [u for u in (message.target_urls or []) if str(u).strip()]
            image_paths = [p for p in (getattr(message, "image_paths", None) or []) if str(p).strip()]
            source = decide_image_source(urls, image_paths)

            if source == "invalid":
                err = "缺少页面截图和页面 URL，无法识别 UI 元素。请上传截图或提供可访问的 URL。"
                logger.warning(f"[ImageAgent] INVALID_INPUT: {err} task={message.task_id}")
                duration = time.time() - start
                output = {"status": STATUS_INVALID_INPUT, "page_elements": {}, "element_locators": {}, "error": err}
                self._save_result(message, output, duration, "error", err)
                await self.emit_error(
                    task_id=message.task_id,
                    step="image",
                    error=err,
                    traceback_str="",
                    session_key=message.session_key,
                )
                return STATUS_INVALID_INPUT

            if source == "upload":
                result, status, err = await self._analyze_uploaded_images(image_paths)
                if status != STATUS_SUCCESS:
                    duration = time.time() - start
                    output = {"status": status, "page_elements": {}, "element_locators": {}, "error": err}
                    self._save_result(message, output, duration, "error", err)
                    await self.emit_error(
                        task_id=message.task_id,
                        step="image",
                        error=err,
                        traceback_str="",
                        session_key=message.session_key,
                    )
                    return status
            else:
                page_descriptions = message.page_descriptions or {}
                system_prompt = (
                    "你是一个前端页面元素分析专家。请根据提供的页面URL和描述，"
                    "分析每个页面中的可交互元素（按钮、输入框、链接、下拉框等）。"
                    "返回JSON格式: "
                    '{"page_elements": {"<url>": [{"name": "", "type": "", "locator": ""}]}, '
                    '"element_locators": {"<元素名>": {"strategy": "", "value": ""}}}'
                )
                user_prompt = (
                    f"测试意图: {message.intent}\n"
                    f"测试步骤: {json.dumps(message.test_steps, ensure_ascii=False)}\n"
                    f"目标URL: {json.dumps(urls, ensure_ascii=False)}\n"
                    f"页面描述: {json.dumps(page_descriptions, ensure_ascii=False)}\n"
                    f"测试范围: {message.test_scope}"
                )
                result = await self.call_llm_json(
                    system_prompt,
                    user_prompt,
                    task_id=message.task_id,
                    step="image",
                    session_key=message.session_key,
                )
                if not result or not isinstance(result, dict):
                    raise RuntimeError("页面元素识别失败：模型未返回有效结果")

            page_elements = result.get("page_elements", {})
            element_locators = result.get("element_locators", {})
            output = {
                "status": STATUS_SUCCESS,
                "page_elements": page_elements,
                "element_locators": element_locators,
                "target_urls": urls,
                "image_paths": image_paths,
                "intent": message.intent,
            }
            duration = time.time() - start
            self._save_result(message, output, duration, "success")
            await self.emit_end(
                task_id=message.task_id,
                step="image",
                duration=duration,
                output=output,
                session_key=message.session_key,
            )
            case_msg = CaseMessage(
                task_id=message.task_id,
                session_key=message.session_key,
                user_id=message.user_id,
                page_elements=page_elements,
                element_locators=element_locators,
                requirement_summary=message.intent,
                intent=message.intent,
            )
            await self.publish_message(case_msg, DefaultTopicId())
            logger.info(f"[ImageAgent] 页面元素分析完成，发布CaseMessage: task={message.task_id}")
            return STATUS_SUCCESS

        except Exception as e:
            duration = time.time() - start
            logger.error(f"[ImageAgent] 分析失败: {e}", exc_info=True)
            await self.emit_error(
                task_id=message.task_id,
                step="image",
                error=str(e),
                traceback_str=traceback.format_exc(),
                session_key=message.session_key,
            )
            self._save_result(message, {"status": STATUS_FAILED, "error": str(e)}, duration, "error", str(e))
            return STATUS_FAILED

    async def _analyze_uploaded_images(
        self, image_paths: List[str]
    ) -> Tuple[Optional[Dict[str, Any]], str, str]:
        from app.agent.vision.element_agent import ElementAgent

        agent = ElementAgent()
        page_elements: Dict[str, List] = {}
        element_locators: Dict[str, Dict] = {}
        for path in image_paths:
            if not os.path.isfile(path):
                return None, STATUS_INVALID_INPUT, f"上传图片不存在或无法访问: {path}"
            collected = None
            try:
                async for step in agent.analyze_image(0, path):
                    if step.get("step") == "result":
                        collected = step.get("data")
                    if step.get("step") == "错误":
                        return None, STATUS_FAILED, step.get("message") or "图片识别失败"
            except Exception as e:
                return None, STATUS_FAILED, f"图片识别失败: {e}"
            if not collected:
                return None, STATUS_FAILED, "图片识别未返回结果"
            key = collected.get("page_url") or path
            els = collected.get("elements") or []
            page_elements[str(key)] = els
            for el in els:
                name = el.get("name")
                if name:
                    element_locators[name] = {"strategy": "name", "value": name}
        return {"page_elements": page_elements, "element_locators": element_locators}, STATUS_SUCCESS, ""

    def _save_result(self, message: PageMessage, output: Dict, duration: float,
                     status: str = "success", error: str = None) -> None:
        """保存结果到数据库"""
        from app.services.context_router.storage_router import get_storage_router

        storage = get_storage_router()
        try:
            storage.mysql_save("FlowResult", {
                "task_id": message.task_id,
                "session_key": message.session_key,
                "user_id": message.user_id,
                "step": "page",
                "agent_name": "ImageAgent",
                "status": status,
                "input_json": message.model_dump_json(),
                "output_json": json.dumps(output, ensure_ascii=False),
                "duration": duration,
                "error_message": error,
                "message_type": "PageMessage",
            })
        except Exception as e:
            logger.error(f"[ImageAgent] DB保存失败: {e}")
