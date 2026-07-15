"""ImageAgent - 页面元素分析Agent（消息驱动）

接收 PageMessage，分析页面元素，输出 CaseMessage
"""
import json
import time
import logging
import traceback
from typing import Any, Dict

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
            test_scope=payload.get("test_scope", ""),
            page_descriptions=payload.get("page_descriptions", {}),
        )
        await self.handle_page(msg, ctx)
        return {"status": "success", "step": "image", "task_id": msg.task_id}

    @message_handler
    async def handle_page(self, message: PageMessage, ctx: MessageContext) -> None:
        """处理页面消息"""
        start = time.time()
        logger.info(f"[ImageAgent] 收到页面消息: task={message.task_id}")

        try:
            # 发送开始事件给 CollectorAgent
            await self.emit_start(
                task_id=message.task_id,
                step="image",
                message=f"{self._display_name} 开始处理",
                session_key=message.session_key,
            )
            # 1. 构造 LLM 输入
            urls = message.target_urls or []
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

            # 2. 调用 LLM 分析页面元素（无真实URL时使用mock数据）
            if urls:
                result = await self.call_llm_json(
                    system_prompt,
                    user_prompt,
                    task_id=message.task_id,
                    step="image",
                    session_key=message.session_key,
                )
            else:
                logger.warning(f"[ImageAgent] 无目标URL，使用mock元素数据: task={message.task_id}")
                result = {
                    "page_elements": {
                        "default_page": [
                            {"name": "登录按钮", "type": "button", "locator": "button[type='submit']"},
                            {"name": "用户名输入框", "type": "input", "locator": "input[name='username']"},
                            {"name": "密码输入框", "type": "input", "locator": "input[name='password']"},
                        ]
                    },
                    "element_locators": {
                        "登录按钮": {"strategy": "css", "value": "button[type='submit']"},
                        "用户名输入框": {"strategy": "css", "value": "input[name='username']"},
                        "密码输入框": {"strategy": "css", "value": "input[name='password']"},
                    },
                }

            # 3. 构造输出
            page_elements = result.get("page_elements", {})
            element_locators = result.get("element_locators", {})

            output = {
                "page_elements": page_elements,
                "element_locators": element_locators,
                "target_urls": urls,
                "intent": message.intent,
            }

            duration = time.time() - start

            # 4. 保存到数据库
            self._save_result(message, output, duration, "success")

            # 发送结束事件给 CollectorAgent
            await self.emit_end(
                task_id=message.task_id,
                step="image",
                duration=duration,
                output=output,
                session_key=message.session_key,
            )

            # 5. 发布 CaseMessage 给 CaseAgent
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

        except Exception as e:
            duration = time.time() - start
            logger.error(f"[ImageAgent] 分析失败: {e}", exc_info=True)
            # 发送错误事件给 CollectorAgent
            await self.emit_error(
                task_id=message.task_id,
                step="image",
                error=str(e),
                traceback_str=traceback.format_exc(),
                session_key=message.session_key,
            )
            self._save_result(message, {"error": str(e)}, duration, "error", str(e))

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
