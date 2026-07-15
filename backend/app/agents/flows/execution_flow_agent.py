"""
ExecutionFlowAgent - 脚本执行 Agent（消息驱动）

职责：
  收到 ExecutionMessage
  ↓
  使用 PlaywrightTool 执行脚本
  ↓
  收集执行结果（通过/失败/跳过）
  ↓
  发送 ReportMessage 给 ReportAgent

通信方式：
  # ScriptAgent → ExecutionFlowAgent
  response = await self.send_request(
      "execution_flow_agent", "execute",
      {"script_path": "/path/to/test.py", "framework": "playwright"}
  )
  # response.data = {"total": 10, "passed": 8, "failed": 2, "results": [...]}
"""
import json
import logging
import time
import traceback
from typing import Any, Dict

from autogen_core import message_handler, MessageContext, DefaultTopicId, default_subscription

from app.runtime.base_agent import BaseRoutedAgent
from app.runtime.messages import AgentRequest, AgentResponse
from app.tools.base import ToolContext
from app.tools.playwright_tool import PlaywrightTool

logger = logging.getLogger(__name__)


@default_subscription
class ExecutionFlowAgent(BaseRoutedAgent):
    """脚本执行 Agent

    使用 PlaywrightTool 执行测试脚本。
    执行完成后发送 ReportMessage 给 ReportAgent。
    """

    def __init__(self) -> None:
        super().__init__(
            description="脚本执行Agent，使用Playwright执行测试脚本并收集结果",
            display_name="ExecutionFlowAgent",
            capabilities=["script_execute", "playwright"],
        )
        self._playwright_tool = None

    @property
    def playwright_tool(self) -> PlaywrightTool:
        """懒加载 Playwright 工具"""
        if self._playwright_tool is None:
            self._playwright_tool = PlaywrightTool()
        return self._playwright_tool

    async def execute(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """GraphFlow 入口"""
        return await self._do_execute(payload)

    @message_handler
    async def handle_request(self, message: AgentRequest, ctx: MessageContext) -> AgentResponse:
        """处理来自其他 Agent 的执行请求"""
        start = time.time()
        action = message.target_action or "execute"
        logger.info(f"[ExecutionFlowAgent] 收到请求 action={action}")

        try:
            if action == "execute":
                result = await self._do_execute(message.payload)
            elif action == "validate":
                result = await self._do_validate(message.payload)
            else:
                result = {"status": "error", "message": f"Unknown action: {action}"}

            duration = time.time() - start
            return AgentResponse(
                request_id=message.request_id,
                sender_type=self._agent_type,
                status="success" if result.get("status") != "error" else "error",
                data=result,
                duration=duration,
            )
        except Exception as e:
            duration = time.time() - start
            logger.error(f"[ExecutionFlowAgent] 处理失败: {e}", exc_info=True)
            return AgentResponse(
                request_id=message.request_id,
                sender_type=self._agent_type,
                status="error",
                error=str(e),
                duration=duration,
            )

    async def _do_execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """执行脚本

        使用 PlaywrightTool 执行脚本，收集结果，发送 ReportMessage。
        """
        # 发送开始事件
        await self.emit_start(
            task_id=payload.get("task_id", ""),
            step="execution",
            message="开始执行测试脚本",
            session_key=payload.get("session_key", "default"),
        )

        # 构建工具上下文
        tool_ctx = ToolContext(
            session_key=payload.get("session_key", "default"),
            task_id=payload.get("task_id", ""),
            user_id=payload.get("user_id", 0),
            agent_name=self._display_name,
        )

        # 执行脚本
        result = await self.playwright_tool.safe_execute(
            tool_ctx,
            script_content=payload.get("script_content", ""),
            script_path=payload.get("script_path", ""),
            browser=payload.get("browser", "chromium"),
            headless=payload.get("headless", True),
            timeout=payload.get("timeout", 300),
        )

        # 解析执行结果
        if result.success:
            # 从 stdout 解析 pytest 结果
            stdout = result.data.get("stdout", "")
            passed = stdout.count("PASSED")
            failed = stdout.count("FAILED")
            errors = stdout.count("ERROR")
            skipped = stdout.count("SKIPPED")
            total = passed + failed + errors + skipped

            exec_result = {
                "status": "success",
                "total": total,
                "passed": passed,
                "failed": failed + errors,
                "skipped": skipped,
                "stdout": stdout,
                "stderr": result.data.get("stderr", ""),
                "script_path": result.data.get("script_path", ""),
                "duration": result.duration,
            }

            # 发送结束事件
            await self.emit_end(
                task_id=payload.get("task_id", ""),
                step="execution",
                duration=result.duration,
                output=exec_result,
                session_key=payload.get("session_key", "default"),
            )

            # 发布 ReportMessage
            from app.agents.messages import ReportMessage
            report_msg = ReportMessage(
                task_id=payload.get("task_id", ""),
                session_key=payload.get("session_key", "default"),
                user_id=payload.get("user_id", 0),
                execution_id=payload.get("execution_id", ""),
                total=total,
                passed=passed,
                failed=failed + errors,
                skipped=skipped,
                duration=result.duration,
                results=[],
                logs=stdout,
            )
            await self.publish_message(report_msg, DefaultTopicId())

            return exec_result
        else:
            error_msg = result.error or "执行失败"
            await self.emit_error(
                task_id=payload.get("task_id", ""),
                step="execution",
                error=error_msg,
                session_key=payload.get("session_key", "default"),
            )
            return {
                "status": "error",
                "error": error_msg,
                "duration": result.duration,
            }

    async def _do_validate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """验证脚本语法"""
        tool_ctx = ToolContext(
            session_key=payload.get("session_key", "default"),
            task_id=payload.get("task_id", ""),
        )
        result = await self.playwright_tool.safe_execute(
            tool_ctx,
            action="validate",
            script_content=payload.get("script_content", ""),
        )
        return {
            "status": "success" if result.success else "error",
            "valid": result.data.get("valid", False) if result.data else False,
            "error": result.error,
        }
