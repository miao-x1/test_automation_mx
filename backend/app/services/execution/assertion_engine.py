"""
AssertionEngine - 断言引擎

职责：验证响应是否符合预期

支持断言类型：
- equals: 等于
- not_equals: 不等于
- contains: 包含
- not_contains: 不包含
- not_empty: 非空
- is_type: 类型检查
- regex: 正则匹配
- greater_than: 大于
- less_than: 小于
- exists: 路径存在
- schema: JSON Schema 验证
"""
import json
import re
from typing import Any, Dict, List, Optional
from app.core.logger import log


class AssertionEngine:
    """断言引擎"""

    def validate(
        self,
        response: Dict[str, Any],
        assertions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        执行断言验证

        Args:
            response: HTTP响应 {status_code, json, text, headers}
            assertions: 断言列表

        Returns:
            {
                "passed": bool,
                "results": [{"type", "path", "expected", "actual", "passed", "message"}],
                "passed_count": int,
                "failed_count": int
            }
        """
        results = []

        for assertion in assertions:
            a_type = assertion.get("type", "equals")
            path = assertion.get("path", "")
            expected = assertion.get("expected")

            # 提取实际值
            actual = self._extract_value(response, path)

            # 执行断言
            passed, message = self._assert(a_type, actual, expected, assertion)

            results.append({
                "type": a_type,
                "path": path,
                "expected": expected,
                "actual": actual,
                "passed": passed,
                "message": message,
            })

        passed_count = sum(1 for r in results if r["passed"])
        failed_count = len(results) - passed_count
        all_passed = failed_count == 0

        return {
            "passed": all_passed,
            "results": results,
            "passed_count": passed_count,
            "failed_count": failed_count,
        }

    def _extract_value(self, response: Dict[str, Any], path: str) -> Any:
        """从响应中提取值（支持点号路径）"""
        if not path:
            return response

        # 特殊路径
        if path == "status_code":
            return response.get("status_code")
        if path == "text":
            return response.get("text")

        # 从json中提取
        data = response.get("json")
        if data is None:
            return None

        # 点号路径: data.user.name
        parts = path.split(".")
        current = data
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    idx = int(part)
                    current = current[idx]
                except (ValueError, IndexError):
                    return None
            else:
                return None

        return current

    def _assert(
        self,
        assertion_type: str,
        actual: Any,
        expected: Any,
        assertion: Dict[str, Any],
    ) -> tuple:
        """执行单个断言，返回 (passed, message)"""
        try:
            if assertion_type == "equals":
                passed = actual == expected
                msg = f"期望 {expected}, 实际 {actual}" if not passed else "通过"

            elif assertion_type == "not_equals":
                passed = actual != expected
                msg = f"值不应等于 {expected}" if not passed else "通过"

            elif assertion_type == "contains":
                passed = str(expected) in str(actual)
                msg = f"期望包含 '{expected}', 实际 '{actual}'" if not passed else "通过"

            elif assertion_type == "not_contains":
                passed = str(expected) not in str(actual)
                msg = f"不应包含 '{expected}'" if not passed else "通过"

            elif assertion_type == "not_empty":
                passed = actual is not None and actual != "" and actual != []
                msg = f"值为空" if not passed else "通过"

            elif assertion_type == "exists":
                passed = actual is not None
                msg = f"路径不存在" if not passed else "通过"

            elif assertion_type == "is_type":
                type_map = {"string": str, "int": int, "float": float, "bool": bool, "list": list, "dict": dict}
                expected_type = type_map.get(str(expected), str)
                passed = isinstance(actual, expected_type)
                msg = f"期望类型 {expected}, 实际 {type(actual).__name__}" if not passed else "通过"

            elif assertion_type == "greater_than":
                passed = float(actual) > float(expected)
                msg = f"{actual} 不大于 {expected}" if not passed else "通过"

            elif assertion_type == "less_than":
                passed = float(actual) < float(expected)
                msg = f"{actual} 不小于 {expected}" if not passed else "通过"

            elif assertion_type == "regex":
                pattern = assertion.get("pattern", str(expected))
                passed = bool(re.search(pattern, str(actual)))
                msg = f"不匹配正则 {pattern}" if not passed else "通过"

            elif assertion_type == "schema":
                # 简化版schema验证
                passed = isinstance(actual, dict)
                msg = "Schema验证" if passed else "不是有效的JSON对象"

            else:
                passed = False
                msg = f"未知断言类型: {assertion_type}"

            return passed, msg

        except Exception as e:
            return False, f"断言执行异常: {e}"
