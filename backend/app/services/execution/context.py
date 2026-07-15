"""
ExecutionContext - 执行上下文

统一管理执行过程中的环境变量、请求头、变量池等
"""
import re
from typing import Any, Dict, Optional
from app.core.logger import log


class ExecutionContext:
    """
    执行上下文

    管理执行过程中的：
    - base_url: 基础URL
    - headers: 请求头（含token）
    - variables: 变量池（步骤间传递数据）
    - env: 环境标识
    - config: 额外配置
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        headers: Optional[Dict[str, str]] = None,
        variables: Optional[Dict[str, Any]] = None,
        env: str = "test",
        config: Optional[Dict[str, Any]] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.headers = headers or {
            "Content-Type": "application/json",
        }
        self.variables = variables or {}
        self.env = env
        self.config = config or {}
        self.step_results: list = []

    def set_variable(self, key: str, value: Any) -> None:
        """设置变量"""
        self.variables[key] = value

    def get_variable(self, key: str, default: Any = None) -> Any:
        """获取变量"""
        return self.variables.get(key, default)

    def resolve_template(self, text: str) -> str:
        """
        解析模板变量

        支持 ${variable_name} 语法
        例如: "${token}" → 变量池中的 token 值
        """
        if not isinstance(text, str):
            return text

        def replacer(match):
            var_name = match.group(1)
            value = self.variables.get(var_name)
            if value is not None:
                return str(value)
            return match.group(0)  # 未找到变量，保留原样

        return re.sub(r"\$\{(\w+)\}", replacer, text)

    def resolve_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """递归解析字典中的模板变量"""
        if not data:
            return data

        resolved = {}
        for key, value in data.items():
            if isinstance(value, str):
                resolved[key] = self.resolve_template(value)
            elif isinstance(value, dict):
                resolved[key] = self.resolve_dict(value)
            elif isinstance(value, list):
                resolved[key] = [
                    self.resolve_template(item) if isinstance(item, str)
                    else self.resolve_dict(item) if isinstance(item, dict)
                    else item
                    for item in value
                ]
            else:
                resolved[key] = value
        return resolved

    def add_step_result(self, result: Dict[str, Any]) -> None:
        """记录步骤执行结果"""
        self.step_results.append(result)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "base_url": self.base_url,
            "headers": self.headers,
            "variables": {k: v for k, v in self.variables.items() if k != "password"},
            "env": self.env,
        }
