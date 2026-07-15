"""
ReportAgent - 测试报告 Agent（消息驱动）

职责：
  收到 ReportMessage
  ↓
  汇总执行结果
  ↓
  生成 HTML/JSON 报告
  ↓
  保存报告到数据库
  ↓
  发送 StorageMessage 给 MysqlStorageAgent

通信方式：
  # ExecutionFlowAgent → ReportAgent
  # ReportMessage 自动通过消息总线投递
  # ReportAgent 处理后发送 StorageMessage
"""
import json
import logging
import os
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List

from autogen_core import message_handler, MessageContext, DefaultTopicId, default_subscription

from app.runtime.base_agent import BaseRoutedAgent
from app.runtime.messages import AgentRequest, AgentResponse
from app.agents.messages import ReportMessage as FlowReportMessage

logger = logging.getLogger(__name__)


@default_subscription
class ReportAgent(BaseRoutedAgent):
    """测试报告 Agent

    汇总执行结果，生成测试报告。
    """

    def __init__(self) -> None:
        super().__init__(
            description="测试报告Agent，汇总执行结果，生成HTML/JSON报告并保存",
            display_name="ReportAgent",
            capabilities=["report_generate", "report_export"],
        )
        self._report_dir = os.path.join(os.getcwd(), "reports")
        # 注册管道 action
        self.register_action("generate", self._pipeline_generate)

    async def execute(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """GraphFlow 入口"""
        return await self._do_generate(payload)

    async def _pipeline_generate(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """管道适配：从 execution_result 生成报告

        管道传入 payload 包含 execution_result 和 task_id，
        需要转换为 _do_generate 期望的格式。
        """
        execution_result = payload.get("execution_result", payload)
        task_id = str(payload.get("task_id", ""))

        # 从 execution_result 提取报告所需字段
        if isinstance(execution_result, dict):
            total = execution_result.get("total", 0)
            passed = execution_result.get("passed", 0)
            failed = execution_result.get("failed_count", execution_result.get("failed", 0))
            skipped = execution_result.get("skipped", 0)
            logs = execution_result.get("log_content", "")
            duration = execution_result.get("duration", 0)
            results = execution_result.get("results", [])
        else:
            total = passed = failed = skipped = 0
            logs = ""
            duration = 0
            results = []

        report_payload = {
            "task_id": task_id,
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "duration": duration,
            "results": results,
            "logs": logs,
        }
        return await self._do_generate(report_payload)

    @message_handler
    async def handle_request(self, message: AgentRequest, ctx: MessageContext) -> AgentResponse:
        """处理来自其他 Agent 的报告请求"""
        start = time.time()
        action = message.target_action or "generate"
        logger.info(f"[ReportAgent] 收到请求 action={action}")

        try:
            if action == "generate":
                result = await self._do_generate(message.payload)
            elif action == "export":
                result = await self._do_export(message.payload)
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
            logger.error(f"[ReportAgent] 处理失败: {e}", exc_info=True)
            return AgentResponse(
                request_id=message.request_id,
                sender_type=self._agent_type,
                status="error",
                error=str(e),
                duration=duration,
            )

    @message_handler
    async def handle_report(self, message: FlowReportMessage, ctx: MessageContext) -> None:
        """处理 ReportMessage（来自 ExecutionFlowAgent）

        自动汇总执行结果，生成报告。
        """
        await self._do_generate({
            "task_id": message.task_id,
            "session_key": message.session_key,
            "user_id": message.user_id,
            "execution_id": message.execution_id,
            "total": message.total,
            "passed": message.passed,
            "failed": message.failed,
            "skipped": message.skipped,
            "duration": message.duration,
            "results": message.results,
            "logs": message.logs,
        })

    async def _do_generate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """生成测试报告"""
        start = time.time()
        task_id = payload.get("task_id", "")
        total = payload.get("total", 0)
        passed = payload.get("passed", 0)
        failed = payload.get("failed", 0)
        skipped = payload.get("skipped", 0)

        await self.emit_start(
            task_id=task_id,
            step="report",
            message=f"开始生成测试报告: {passed}/{total} 通过",
            session_key=payload.get("session_key", "default"),
        )

        # 生成报告数据
        report_data = {
            "task_id": task_id,
            "execution_id": payload.get("execution_id", ""),
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total": total,
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "pass_rate": round(passed / total * 100, 1) if total > 0 else 0,
            },
            "duration": payload.get("duration", 0),
            "results": payload.get("results", []),
            "logs": (payload.get("logs", "") or "")[-5000:],  # 截断日志
        }

        # 保存 HTML 报告
        os.makedirs(self._report_dir, exist_ok=True)
        report_file = os.path.join(self._report_dir, f"report_{task_id}.html")
        html = self._generate_html(report_data)
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(html)

        # 保存 JSON 报告
        json_file = os.path.join(self._report_dir, f"report_{task_id}.json")
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)

        # 发送 StorageMessage 保存到数据库
        from app.agents.messages import StorageMessage
        storage_msg = StorageMessage(
            task_id=task_id,
            session_key=payload.get("session_key", "default"),
            user_id=payload.get("user_id", 0),
            storage_type="mysql",
            operation="save",
            table="flow_result",
            data={
                "task_id": task_id,
                "session_key": payload.get("session_key", "default"),
                "step": "report",
                "agent_name": "ReportAgent",
                "status": "success" if failed == 0 else "partial",
                "input_json": json.dumps({"total": total}),
                "output_json": json.dumps(report_data["summary"]),
                "duration": payload.get("duration", 0),
                "message_type": "ReportMessage",
            },
        )
        # 尝试发布消息（如果不在 Runtime 上下文中则跳过）
        try:
            await self.publish_message(storage_msg, DefaultTopicId())
        except Exception as e:
            logger.warning(f"[ReportAgent] 发布 StorageMessage 失败（非 Runtime 上下文）: {e}")

        duration = time.time() - start
        await self.emit_end(
            task_id=task_id,
            step="report",
            duration=duration,
            output=report_data["summary"],
            session_key=payload.get("session_key", "default"),
        )

        return {
            "status": "success",
            "report_path": report_file,
            "json_path": json_file,
            "summary": report_data["summary"],
            "duration": duration,
        }

    async def _do_export(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """导出报告"""
        task_id = payload.get("task_id", "")
        format_type = payload.get("format", "html")

        report_file = os.path.join(self._report_dir, f"report_{task_id}.{format_type}")
        if not os.path.exists(report_file):
            return {"status": "not_found", "message": f"报告不存在: {report_file}"}

        return {
            "status": "success",
            "file_path": report_file,
            "format": format_type,
        }

    def _generate_html(self, data: Dict[str, Any]) -> str:
        """生成 HTML 报告"""
        summary = data.get("summary", {})
        pass_rate = summary.get("pass_rate", 0)
        status_color = "#52c41a" if pass_rate == 100 else "#faad14" if pass_rate >= 80 else "#ff4d4f"

        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>测试报告 - {data.get('task_id', '')}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .header {{ background: #f0f2f5; padding: 20px; border-radius: 8px; }}
        .summary {{ display: flex; gap: 20px; margin: 20px 0; }}
        .stat {{ flex: 1; padding: 15px; border-radius: 8px; text-align: center; }}
        .stat-total {{ background: #e6f7ff; }}
        .stat-passed {{ background: #f6ffed; }}
        .stat-failed {{ background: #fff2f0; }}
        .stat-skipped {{ background: #fffbe6; }}
        .stat-number {{ font-size: 28px; font-weight: bold; }}
        .stat-label {{ color: #666; }}
        .pass-rate {{ font-size: 48px; font-weight: bold; color: {status_color}; }}
        .logs {{ background: #f5f5f5; padding: 15px; border-radius: 8px;
                 max-height: 400px; overflow-y: auto; font-family: monospace;
                 white-space: pre-wrap; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>测试报告</h1>
        <p>Task ID: {data.get('task_id', '')}</p>
        <p>Execution ID: {data.get('execution_id', '')}</p>
        <p>时间: {data.get('timestamp', '')}</p>
        <p>耗时: {data.get('duration', 0):.2f}s</p>
    </div>

    <div style="text-align: center; margin: 30px 0;">
        <div class="pass-rate">{pass_rate}%</div>
        <div style="color: #999;">通过率</div>
    </div>

    <div class="summary">
        <div class="stat stat-total">
            <div class="stat-number">{summary.get('total', 0)}</div>
            <div class="stat-label">总计</div>
        </div>
        <div class="stat stat-passed">
            <div class="stat-number">{summary.get('passed', 0)}</div>
            <div class="stat-label">通过</div>
        </div>
        <div class="stat stat-failed">
            <div class="stat-number">{summary.get('failed', 0)}</div>
            <div class="stat-label">失败</div>
        </div>
        <div class="stat stat-skipped">
            <div class="stat-number">{summary.get('skipped', 0)}</div>
            <div class="stat-label">跳过</div>
        </div>
    </div>

    <h2>执行日志</h2>
    <div class="logs">{data.get('logs', '')}</div>
</body>
</html>"""
