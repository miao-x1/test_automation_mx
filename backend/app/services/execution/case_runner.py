"""
CaseRunner - 用例执行器

职责：执行单个测试用例的所有步骤，收集结果

流程：
1. 初始化上下文
2. 按顺序执行步骤
3. 每步执行断言
4. 提取变量（用于后续步骤）
5. 汇总结果
"""
import time as _time
from typing import Any, Dict, Optional
from app.core.logger import log
from app.services.execution.context import ExecutionContext
from app.services.execution.http_runner import HttpRunner
from app.services.execution.assertion_engine import AssertionEngine


class CaseRunner:
    """用例执行器"""

    def __init__(self):
        self.http_runner = HttpRunner()
        self.assertion_engine = AssertionEngine()

    def run(
        self,
        case: Dict[str, Any],
        context: ExecutionContext,
    ) -> Dict[str, Any]:
        """
        执行单个测试用例

        Args:
            case: 测试用例
                {
                    "case_id": "C001",
                    "title": "xxx",
                    "type": "api",
                    "precondition": [...],
                    "steps": [...],
                    "assertions": [...],
                    "extract": [{"key": "token", "path": "data.token"}]
                }
            context: 执行上下文

        Returns:
            {
                "case_id": str,
                "title": str,
                "status": "PASS"|"FAIL"|"ERROR",
                "duration_ms": int,
                "step_results": [...],
                "assertion_result": {...},
                "error": str or None
            }
        """
        start = _time.time()
        case_id = case.get("case_id", "unknown")
        title = case.get("title", "")

        log.info(f"CaseRunner | 开始执行 | {case_id}: {title}")

        step_results = []
        case_error = None

        try:
            # 执行步骤
            steps = case.get("steps", [])
            for i, step in enumerate(steps):
                step_result = self._execute_step(step, context)
                step_results.append(step_result)

                # 提取变量
                extracts = step.get("extract", [])
                for ext in extracts:
                    key = ext.get("key", "")
                    path = ext.get("path", "")
                    if key and path:
                        value = self._extract_from_response(step_result, path)
                        if value is not None:
                            context.set_variable(key, value)
                            log.debug(f"CaseRunner | 提取变量 | {key} = {value}")

                # 步骤失败时决定是否继续
                if not step_result.get("success") and not step.get("continue_on_fail", False):
                    log.warning(f"CaseRunner | 步骤{i+1}失败，终止执行 | {case_id}")
                    break

            # 执行断言
            last_response = step_results[-1] if step_results else {}
            assertions = case.get("assertions", [])
            assertion_result = self.assertion_engine.validate(last_response, assertions)

            # 判定结果
            if case_error:
                status = "ERROR"
            elif assertion_result.get("passed", False):
                status = "PASS"
            else:
                status = "FAIL"

        except Exception as e:
            case_error = str(e)
            status = "ERROR"
            assertion_result = {"passed": False, "results": [], "passed_count": 0, "failed_count": 0}

        duration_ms = int((_time.time() - start) * 1000)

        result = {
            "case_id": case_id,
            "title": title,
            "status": status,
            "duration_ms": duration_ms,
            "step_results": step_results,
            "assertion_result": assertion_result,
            "error": case_error,
        }

        log.info(f"CaseRunner | 执行完成 | {case_id}: {status} ({duration_ms}ms)")
        return result

    def _execute_step(self, step: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
        """执行单个步骤"""
        action = step.get("action", "").upper()

        # HTTP 请求步骤
        if action in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
            return self.http_runner.execute(step, context)

        # 设置变量步骤
        elif action == "SET_VARIABLE":
            key = step.get("key", "")
            value = step.get("value", "")
            if key:
                context.set_variable(key, context.resolve_template(str(value)))
            return {"success": True, "action": "SET_VARIABLE", "key": key}

        # 等待步骤
        elif action == "WAIT":
            import time
            seconds = step.get("seconds", 1)
            time.sleep(seconds)
            return {"success": True, "action": "WAIT", "seconds": seconds}

        # 断言步骤（步骤内断言）
        elif action == "ASSERT":
            # 使用上一步的响应
            last_result = context.step_results[-1] if context.step_results else {}
            assertion_result = self.assertion_engine.validate(last_result, step.get("assertions", []))
            return {
                "success": assertion_result.get("passed", False),
                "action": "ASSERT",
                "assertion_result": assertion_result,
            }

        else:
            log.warning(f"CaseRunner | 未知action: {action}")
            return {"success": False, "action": action, "error": f"未知操作: {action}"}

    def _extract_from_response(self, response: Dict[str, Any], path: str) -> Any:
        """从响应中提取值"""
        if not path:
            return None

        data = response.get("json")
        if data is None:
            return None

        parts = path.split(".")
        current = data
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    current = current[int(part)]
                except (ValueError, IndexError):
                    return None
            else:
                return None
        return current
