"""
DefectAgent - 缺陷管理 Agent（消息驱动）

职责：
  收到 ReportMessage（含失败用例）
  ↓
  分析失败用例
  ↓
  提取缺陷信息（错误类型、堆栈、截图）
  ↓
  发送 StorageMessage 保存缺陷
  ↓
  可选：发送到外部缺陷系统（Jira/GitHub Issues）

通信方式：
  # ReportAgent → DefectAgent（自动通过消息订阅）
  # DefectAgent 处理后发送 StorageMessage
"""
import json
import logging
import re
import time
import traceback
from typing import Any, Dict, List

from autogen_core import message_handler, MessageContext, DefaultTopicId, default_subscription

from app.runtime.base_agent import BaseRoutedAgent
from app.runtime.messages import AgentRequest, AgentResponse

logger = logging.getLogger(__name__)


@default_subscription
class DefectAgent(BaseRoutedAgent):
    """缺陷管理 Agent

    分析失败的测试用例，提取缺陷信息并保存。
    """

    def __init__(self) -> None:
        super().__init__(
            description="缺陷管理Agent，分析失败用例，提取缺陷信息并保存",
            display_name="DefectAgent",
            capabilities=["defect_analysis", "defect_create", "defect_export"],
        )
        # 注册管道 action
        self.register_action("analyze_from_execution", self._pipeline_analyze_from_execution)

    async def execute(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """GraphFlow 入口"""
        return await self._do_analyze(payload)

    async def _pipeline_analyze_from_execution(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """管道适配：签名统一为 (payload, ctx)

        BaseRoutedAgent._invoke_handler 调用 handler(payload, ctx)，
        但 analyze_from_execution 的签名是 (execution_result, task_id)，
        此方法负责提取参数并转发。
        """
        execution_result = payload.get("execution_result", {})
        task_id = str(payload.get("task_id", ""))
        return await self.analyze_from_execution(execution_result=execution_result, task_id=task_id)

    async def analyze_from_execution(
        self, execution_result: Dict[str, Any], task_id: str = ""
    ) -> Dict[str, Any]:
        """
        管道适配方法 — 从执行结果分析缺陷

        将 execution_result 转换为 _do_analyze 需要的格式。
        """
        logs = ""
        failed_results = []

        if isinstance(execution_result, dict):
            logs = execution_result.get("log_content", "")
            failed_count = execution_result.get("failed_count", 0)

            # 如果有失败，从日志中提取失败用例
            if failed_count > 0 and logs:
                import re
                # 匹配 ##TEST_FAIL## 标记行
                fail_pattern = r"##TEST_FAIL##\s*(.+?)(?:\n|$)"
                fail_matches = re.findall(fail_pattern, logs)
                for match in fail_matches:
                    failed_results.append({
                        "test_name": match.strip(),
                        "error_message": execution_result.get("error_message", ""),
                        "traceback": "",
                        "screenshots": [execution_result.get("screenshot_path", "")] if execution_result.get("screenshot_path") else [],
                    })

        # 如果没有显式失败结果，也尝试从日志提取
        if not failed_results and logs:
            defects = self._extract_defects_from_logs(logs, task_id)
            if defects:
                return {
                    "status": "success",
                    "defects": defects,
                    "total_defects": len(defects),
                    "duration": 0,
                }

        payload = {
            "task_id": str(task_id) if task_id else "0",
            "failed_results": failed_results,
            "logs": logs[-5000:] if logs else "",
        }

        return await self._do_analyze(payload)

    @message_handler
    async def handle_request(self, message: AgentRequest, ctx: MessageContext) -> AgentResponse:
        """处理来自其他 Agent 的缺陷分析请求"""
        start = time.time()
        action = message.target_action or "analyze"
        logger.info(f"[DefectAgent] 收到请求 action={action}")

        try:
            if action == "analyze":
                result = await self._do_analyze(message.payload)
            elif action == "create":
                result = await self._do_create(message.payload)
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
            logger.error(f"[DefectAgent] 处理失败: {e}", exc_info=True)
            return AgentResponse(
                request_id=message.request_id,
                sender_type=self._agent_type,
                status="error",
                error=str(e),
                duration=duration,
            )

    async def _do_analyze(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """分析失败用例，提取缺陷信息"""
        start = time.time()
        task_id = payload.get("task_id", "")
        failed_results = payload.get("failed_results", [])
        logs = payload.get("logs", "")

        await self.emit_start(
            task_id=task_id,
            step="defect",
            message=f"开始分析失败用例: {len(failed_results)} 个",
            session_key=payload.get("session_key", "default"),
        )

        defects = []
        for i, result in enumerate(failed_results):
            defect = self._extract_defect(result, i + 1, logs)
            defects.append(defect)

        # 如果没有显式的失败结果列表，从日志中提取
        if not defects and logs:
            defects = self._extract_defects_from_logs(logs, task_id)

        # 保存缺陷到数据库
        if defects:
            from app.agents.messages import StorageMessage
            for defect in defects:
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
                        "step": "defect",
                        "agent_name": "DefectAgent",
                        "status": "error",
                        "input_json": json.dumps({"test_name": defect.get("test_name", "")}),
                        "output_json": json.dumps(defect),
                        "duration": 0,
                        "message_type": "DefectMessage",
                    },
                )
                try:
                    await self.publish_message(storage_msg, DefaultTopicId())
                except Exception as e:
                    logger.warning(f"[DefectAgent] 发布 StorageMessage 失败（非 Runtime 上下文）: {e}")

        duration = time.time() - start
        await self.emit_end(
            task_id=task_id,
            step="defect",
            duration=duration,
            output={"defects": defects, "total": len(defects)},
            session_key=payload.get("session_key", "default"),
        )

        return {
            "status": "success",
            "defects": defects,
            "total_defects": len(defects),
            "duration": duration,
        }

    async def _do_create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """创建缺陷记录"""
        defect_data = payload.get("defect", {})
        if not defect_data:
            return {"status": "error", "message": "defect不能为空"}

        # 发送 StorageMessage 保存
        from app.agents.messages import StorageMessage
        storage_msg = StorageMessage(
            task_id=payload.get("task_id", ""),
            session_key=payload.get("session_key", "default"),
            user_id=payload.get("user_id", 0),
            storage_type="mysql",
            operation="save",
            table="flow_result",
            data={
                "task_id": payload.get("task_id", ""),
                "session_key": payload.get("session_key", "default"),
                "step": "defect",
                "agent_name": "DefectAgent",
                "status": "error",
                "output_json": json.dumps(defect_data),
                "message_type": "DefectMessage",
            },
        )
        await self.publish_message(storage_msg, DefaultTopicId())

        return {
            "status": "success",
            "defect": defect_data,
            "message": "缺陷已创建",
        }

    def _extract_defect(self, result: Dict[str, Any], index: int, logs: str) -> Dict[str, Any]:
        """从失败结果中提取缺陷信息"""
        test_name = result.get("name", result.get("test", f"test_{index}"))
        error_message = result.get("error", result.get("message", ""))
        traceback_str = result.get("traceback", "")

        # 分析错误类型
        error_type = "unknown"
        if "AssertionError" in error_message or "assert" in error_message.lower():
            error_type = "assertion"
        elif "TimeoutError" in error_message or "timeout" in error_message.lower():
            error_type = "timeout"
        elif "ElementNotFound" in error_message or "not found" in error_message.lower():
            error_type = "element_not_found"
        elif "ConnectionError" in error_message:
            error_type = "connection"
        elif "SyntaxError" in error_message:
            error_type = "syntax"

        # 提取截图路径
        screenshots = result.get("screenshots", [])
        if not screenshots and "screenshot" in result:
            screenshots = [result["screenshot"]]

        return {
            "defect_id": f"DEFECT_{index:04d}",
            "test_name": test_name,
            "error_type": error_type,
            "error_message": error_message[:500],
            "traceback": traceback_str[:1000] if traceback_str else "",
            "screenshots": screenshots,
            "severity": self._determine_severity(error_type),
            "status": "open",
        }

    def _extract_defects_from_logs(self, logs: str, task_id: str) -> List[Dict[str, Any]]:
        """从日志中提取失败信息"""
        defects = []
        # 匹配 FAILED 行
        failed_pattern = re.compile(r"FAILED\s+(.+?)(?:\s*-\s*(.+))?$", re.MULTILINE)
        for i, match in enumerate(failed_pattern.finditer(logs)):
            test_name = match.group(1).strip()
            error_msg = match.group(2).strip() if match.group(2) else ""
            defects.append({
                "defect_id": f"DEFECT_{i+1:04d}",
                "test_name": test_name,
                "error_type": "unknown",
                "error_message": error_msg[:500],
                "traceback": "",
                "screenshots": [],
                "severity": "medium",
                "status": "open",
            })
        return defects

    def _determine_severity(self, error_type: str) -> str:
        """根据错误类型确定严重程度"""
        severity_map = {
            "assertion": "high",
            "timeout": "medium",
            "element_not_found": "high",
            "connection": "critical",
            "syntax": "critical",
            "unknown": "medium",
        }
        return severity_map.get(error_type, "medium")
