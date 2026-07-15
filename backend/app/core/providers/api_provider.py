"""
API Testing Provider

基于 requests/httpx 的 API 接口测试能力实现
"""
from typing import Any, Dict
from app.core.provider import (
    TestingProvider, ApiProviderConfig, ProviderConfig,
    PrepareResult, GenerateResult, ExecuteResult, AnalyzeResult, ReportResult,
)


class ApiProvider(TestingProvider):
    """API 接口测试 Provider"""

    def provider_type(self) -> str:
        return "api"

    def provider_name(self) -> str:
        return "API 接口测试"

    def default_config(self) -> ApiProviderConfig:
        return ApiProviderConfig()

    def config_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "base_url": {
                    "type": "string",
                    "title": "Base URL",
                    "description": "API基础地址",
                    "placeholder": "https://api.example.com",
                },
                "endpoint": {
                    "type": "string",
                    "title": "接口路径",
                    "description": "API接口路径",
                    "placeholder": "/api/v1/users",
                },
                "method": {
                    "type": "string",
                    "title": "请求方法",
                    "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"],
                    "default": "GET",
                },
                "headers": {
                    "type": "object",
                    "title": "请求头",
                    "description": "自定义请求头(JSON)",
                },
                "body": {
                    "type": "string",
                    "title": "请求体",
                    "description": "请求体内容(JSON)",
                },
                "timeout": {
                    "type": "integer",
                    "title": "超时时间(ms)",
                    "default": 30000,
                },
            },
            "required": ["base_url", "endpoint"],
        }

    def prepare(self, config: ProviderConfig, **kwargs) -> PrepareResult:
        if not isinstance(config, ApiProviderConfig):
            return PrepareResult(success=False, message="配置类型错误")
        if not config.base_url:
            return PrepareResult(success=False, message="Base URL不能为空")
        return PrepareResult(success=True, message="API测试环境准备就绪")

    def generate(self, config: ProviderConfig, requirement: str = "", **kwargs) -> GenerateResult:
        if not isinstance(config, ApiProviderConfig):
            return GenerateResult(success=False, message="配置类型错误")

        template = f'''"""
API 接口测试脚本 - 自动生成
Endpoint: {config.base_url}{config.endpoint}
Method: {config.method}
"""
import requests
import json

def run_test():
    base_url = "{config.base_url}"
    endpoint = "{config.endpoint}"
    url = f"{{base_url}}{{endpoint}}"

    headers = {repr(config.headers) if config.headers else "{}"}
    body = {repr(config.body) if config.body else "None"}

    try:
        response = requests.request(
            method="{config.method}",
            url=url,
            headers=headers,
            json=json.loads(body) if body else None,
            timeout={config.timeout // 1000 if config.timeout else 30},
        )

        # 断言状态码
        assert response.status_code < 400, f"请求失败: {{response.status_code}}"

        # TODO: 根据需求添加更多断言
        # {requirement if requirement else "自动生成断言"}

        print(f"测试通过 - Status: {{response.status_code}}")
        return response.json()
    except Exception as e:
        print(f"测试失败: {{e}}")
        raise

if __name__ == "__main__":
    run_test()
'''
        return GenerateResult(success=True, script=template, script_language="python")

    def execute(self, config: ProviderConfig, script: str, **kwargs) -> ExecuteResult:
        return ExecuteResult(success=True, message="API测试执行由执行服务处理")

    def analyze(self, config: ProviderConfig, execute_result: ExecuteResult, **kwargs) -> AnalyzeResult:
        if execute_result.success:
            return AnalyzeResult(success=True, root_cause="", suggestion="", confidence=1.0)
        return AnalyzeResult(
            success=True,
            root_cause=execute_result.error_message or "接口请求失败",
            suggestion="检查接口地址、参数和网络连通性",
            confidence=0.8,
        )

    def report(self, config: ProviderConfig, execute_result: ExecuteResult, analyze_result: AnalyzeResult, **kwargs) -> ReportResult:
        summary = f"API 测试: {'通过' if execute_result.success else '失败'}"
        return ReportResult(success=True, summary=summary)
