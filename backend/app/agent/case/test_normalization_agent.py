"""
TestNormalizationAgent - L3 用例编译 Agent

职责：将L2结构化用例编译为Execution Engine可执行模型（Case Compiler / Execution Adapter）

核心能力：
1. 变量解析标记：标记 {{token}} 等变量引用（运行时解析）
2. URL补全：/api/xxx → http://host/api/xxx（根据base_url）
3. HTTP标准化：确保每个case有method/url/headers/body
4. assertion标准化：path统一为JSONPath格式（$.code），type校验
5. retry/timeout补全：为每个case添加默认retry=0, timeout=5000
6. pre_steps展开：将pre_steps编译为独立的execution steps

L3输出格式（Execution Ready Case）：
{
    "execution_case_id": "EX_TC001",
    "request": {"method": "POST", "url": "http://...", "headers": {...}, "body": {...}, "timeout": 5000},
    "pre_steps": [...],
    "assertions": [{"type": "equals", "jsonpath": "$.code", "expected": 200}],
    "variables": {"token": "{{token}}"},
    "runtime": {"retry": 0, "env": "test"}
}
"""
import json
from typing import Any, Dict, List
from app.core.logger import log
from app.agent.core.base import BaseAgent


class TestNormalizationAgent(BaseAgent):
    """L3 用例编译 Agent - 将L2结构化用例编译为Execution Engine可执行模型"""

    agent_name = "test_normalization"

    VALID_ASSERTION_TYPES = {"equals", "not_equals", "contains", "not_contains", "not_empty", "exists", "is_type", "regex", "greater_than", "less_than"}
    VALID_PRIORITIES = {"high", "medium", "low"}

    def __init__(self):
        super().__init__()
        self.model = None

    def execute(self, **kwargs) -> Any:
        return self.normalize(**kwargs)

    def normalize(self, cases: List[Dict[str, Any]], base_url: str = "http://localhost:8080", env: str = "test") -> Dict[str, Any]:
        """编译L2用例为Execution Ready格式"""
        log.info(f"TestNormalizationAgent | 开始编译 | cases={len(cases)}, base_url={base_url}, env={env}")

        compiled = []
        for i, case in enumerate(cases):
            compiled_case = self._compile_case(case, i + 1, base_url, env)
            compiled.append(compiled_case)

        self.emit("compiled", {"total": len(compiled)})
        log.info(f"TestNormalizationAgent | 编译完成 | total={len(compiled)}")

        return {
            "cases": compiled,
            "total": len(compiled),
        }

    def _compile_case(self, case: Dict, index: int, base_url: str, env: str) -> Dict:
        """编译单个用例"""
        # 1. 提取HTTP请求信息（兼容新旧格式）
        method = case.get("method", "").upper()
        url = case.get("url", "")
        headers = case.get("headers", {})
        body = case.get("body", {})

        # 兼容旧格式：从steps中提取
        if not method:
            steps = case.get("steps", [])
            for step in steps:
                action = step.get("action", "")
                if action.upper() in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                    method = action.upper()
                    url = step.get("url", "")
                    headers = step.get("headers", {})
                    body = step.get("body", {})
                    break

        if not method:
            method = "POST"

        # 2. URL补全
        if url and not url.startswith("http"):
            url = base_url.rstrip("/") + "/" + url.lstrip("/")

        # 3. Headers标准化
        if not headers:
            headers = {"Content-Type": "application/json"}
        if "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"

        # 4. Assertions标准化
        assertions = case.get("assertions", [])
        normalized_assertions = []
        for a in assertions:
            norm_a = {
                "type": a.get("type", "equals"),
                "jsonpath": a.get("jsonpath", a.get("path", "")),
                "expected": a.get("expected", ""),
            }
            # 确保jsonpath以$.开头
            if norm_a["jsonpath"] and not norm_a["jsonpath"].startswith("$"):
                norm_a["jsonpath"] = "$." + norm_a["jsonpath"]
            normalized_assertions.append(norm_a)

        # 5. Pre-steps编译
        pre_steps = case.get("pre_steps", [])
        compiled_pre_steps = []
        for ps in pre_steps:
            ps_request = ps.get("request", {})
            ps_url = ps_request.get("url", "")
            if ps_url and not ps_url.startswith("http"):
                ps_url = base_url.rstrip("/") + "/" + ps_url.lstrip("/")
            compiled_pre_steps.append({
                "name": ps.get("name", ""),
                "request": {
                    "method": ps_request.get("method", "POST").upper(),
                    "url": ps_url,
                    "headers": ps_request.get("headers", {"Content-Type": "application/json"}),
                    "body": ps_request.get("body", {}),
                },
                "extract": ps.get("extract", {}),
            })

        # 6. Variables
        variables = case.get("variables", {})

        # 7. 构建Execution Ready Case
        execution_case = {
            "execution_case_id": f"EX_{case.get('case_id', f'TC{index:03d}')}",
            "title": case.get("title", f"测试用例-{index}"),
            "case_id": case.get("case_id", f"TC{index:03d}"),
            "request": {
                "method": method,
                "url": url,
                "headers": headers,
                "body": body,
                "timeout": 5000,
            },
            "pre_steps": compiled_pre_steps,
            "assertions": normalized_assertions,
            "variables": variables,
            "runtime": {
                "retry": 0,
                "env": env,
            },
            "priority": case.get("priority", "P1"),
            "tags": case.get("tags", []),
        }

        return execution_case
