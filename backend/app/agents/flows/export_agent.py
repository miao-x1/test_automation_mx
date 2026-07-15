"""ExportAgent - 测试结果导出Agent（消息驱动）

接收 ExportMessage，保存最终脚本结果到数据库，并向 CollectorAgent 投递结果。
这是业务流的最终步骤，不再发布下一阶段 FlowMessage。
"""
import json
import time
import logging
import traceback
from typing import Any, Dict

from autogen_core import message_handler, MessageContext, AgentId, default_subscription

from app.runtime.base_agent import BaseRoutedAgent
from app.runtime.messages import ResultMessage
from app.agents.messages import ExportMessage

logger = logging.getLogger(__name__)


@default_subscription
class ExportAgent(BaseRoutedAgent):
    """测试结果导出Agent - 接收导出消息，保存脚本并投递最终结果给CollectorAgent"""

    def __init__(self) -> None:
        super().__init__(
            description="测试结果导出Agent，保存最终脚本结果并投递给CollectorAgent",
            display_name="ExportAgent",
            capabilities=["result_export"],
        )

    async def execute(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """GraphFlow 入口：构造 ExportMessage 并处理"""
        from app.agents.messages import ExportMessage
        msg = ExportMessage(
            task_id=payload.get("task_id", ""),
            session_key=payload.get("session_key", "default"),
            scripts=payload.get("scripts", []),
            script_language=payload.get("script_language", "python"),
            framework=payload.get("framework", "playwright"),
        )
        await self.handle_export(msg, ctx)
        return {"status": "success", "step": "export", "task_id": msg.task_id}

    @message_handler
    async def handle_export(self, message: ExportMessage, ctx: MessageContext) -> None:
        """处理导出消息（业务流终点）"""
        start = time.time()
        logger.info(f"[ExportAgent] 收到导出消息: task={message.task_id}")

        try:
            # 发送开始事件给 CollectorAgent
            await self.emit_start(
                task_id=message.task_id,
                step="export",
                message=f"{self._display_name} 开始处理",
                session_key=message.session_key,
            )
            # 1. 汇总脚本数据
            scripts = message.scripts or []
            framework = message.framework or "playwright"
            script_language = message.script_language or "python"

            output = {
                "scripts": scripts,
                "script_language": script_language,
                "framework": framework,
                "total_scripts": len(scripts),
            }

            duration = time.time() - start

            # 2. 保存所有脚本到数据库
            self._save_result(message, output, duration, "success")

            # 发送结束事件给 CollectorAgent
            await self.emit_end(
                task_id=message.task_id,
                step="export",
                duration=duration,
                output=output,
                session_key=message.session_key,
            )

            # 3. 创建摘要
            summary = {
                "total_scripts": len(scripts),
                "framework": framework,
                "script_language": script_language,
                "status": "success",
                "task_id": message.task_id,
                "session_key": message.session_key,
            }

            # 4. 向 CollectorAgent 投递最终结果（最终步骤，不再发布 FlowMessage）
            result_msg = ResultMessage(
                task_id=message.task_id,
                agent_type="ExportAgent",
                agent_key=self.id.key,
                status="success",
                data=summary,
                duration=duration,
            )
            collector_id = AgentId("collector", self.id.key)
            await self.send_message(result_msg, collector_id)

            logger.info(
                f"[ExportAgent] 导出完成，已投递结果给CollectorAgent: "
                f"task={message.task_id}, 脚本数={len(scripts)}, 框架={framework}"
            )

        except Exception as e:
            duration = time.time() - start
            logger.error(f"[ExportAgent] 导出失败: {e}", exc_info=True)
            # 发送错误事件给 CollectorAgent
            await self.emit_error(
                task_id=message.task_id,
                step="export",
                error=str(e),
                traceback_str=traceback.format_exc(),
                session_key=message.session_key,
            )
            self._save_result(message, {"error": str(e)}, duration, "error", str(e))

    def _save_result(self, message: ExportMessage, output: Dict, duration: float,
                     status: str = "success", error: str = None) -> None:
        """保存结果到数据库"""
        from app.services.context_router.storage_router import get_storage_router

        storage = get_storage_router()
        try:
            storage.mysql_save("FlowResult", {
                "task_id": message.task_id,
                "session_key": message.session_key,
                "user_id": message.user_id,
                "step": "export",
                "agent_name": "ExportAgent",
                "status": status,
                "input_json": message.model_dump_json(),
                "output_json": json.dumps(output, ensure_ascii=False),
                "duration": duration,
                "error_message": error,
                "message_type": "ExportMessage",
            })
        except Exception as e:
            logger.error(f"[ExportAgent] DB保存失败: {e}")
