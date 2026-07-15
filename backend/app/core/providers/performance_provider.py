"""
Performance Testing Provider

基于 Locust/k6 的性能测试能力实现
"""
from typing import Any, Dict
from app.core.provider import (
    TestingProvider, PerformanceProviderConfig, ProviderConfig,
    PrepareResult, GenerateResult, ExecuteResult, AnalyzeResult, ReportResult,
)


class PerformanceProvider(TestingProvider):
    """性能测试 Provider"""

    def provider_type(self) -> str:
        return "performance"

    def provider_name(self) -> str:
        return "性能测试"

    def default_config(self) -> PerformanceProviderConfig:
        return PerformanceProviderConfig()

    def config_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target_url": {
                    "type": "string",
                    "title": "目标URL",
                    "description": "压测目标地址",
                    "placeholder": "https://api.example.com/load",
                },
                "concurrency": {
                    "type": "integer",
                    "title": "并发数",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 10000,
                },
                "duration": {
                    "type": "integer",
                    "title": "持续时间(秒)",
                    "default": 60,
                    "minimum": 10,
                    "maximum": 3600,
                },
                "tps_target": {
                    "type": "integer",
                    "title": "目标TPS",
                    "default": 100,
                    "minimum": 1,
                },
                "ramp_up": {
                    "type": "integer",
                    "title": "预热时间(秒)",
                    "default": 10,
                    "minimum": 0,
                    "maximum": 300,
                },
            },
            "required": ["target_url"],
        }

    def prepare(self, config: ProviderConfig, **kwargs) -> PrepareResult:
        if not isinstance(config, PerformanceProviderConfig):
            return PrepareResult(success=False, message="配置类型错误")
        if not config.target_url:
            return PrepareResult(success=False, message="目标URL不能为空")
        return PrepareResult(success=True, message="性能测试环境准备就绪")

    def generate(self, config: ProviderConfig, requirement: str = "", **kwargs) -> GenerateResult:
        if not isinstance(config, PerformanceProviderConfig):
            return GenerateResult(success=False, message="配置类型错误")

        template = f'''"""
性能测试脚本 - 自动生成
Target: {config.target_url}
Concurrency: {config.concurrency}
Duration: {config.duration}s
"""
from locust import HttpUser, task, between

class PerformanceTestUser(HttpUser):
    wait_time = between(1, 3)
    host = "{config.target_url.rsplit('/', 1)[0] if '/' in config.target_url[8:] else config.target_url}"

    @task
    def test_endpoint(self):
        self.client.get("{config.target_url}")

    def on_start(self):
        """预热"""
        pass

# 运行: locust -f this_script.py --host={config.target_url} --users={config.concurrency} --run-time={config.duration}s
'''
        return GenerateResult(success=True, script=template, script_language="python")

    def execute(self, config: ProviderConfig, script: str, **kwargs) -> ExecuteResult:
        return ExecuteResult(success=True, message="性能测试执行由执行服务处理")

    def analyze(self, config: ProviderConfig, execute_result: ExecuteResult, **kwargs) -> AnalyzeResult:
        if execute_result.success:
            return AnalyzeResult(success=True, root_cause="", suggestion="", confidence=1.0)
        return AnalyzeResult(
            success=True,
            root_cause=execute_result.error_message or "性能测试未达标",
            suggestion="检查服务端性能瓶颈和网络延迟",
            confidence=0.7,
        )

    def report(self, config: ProviderConfig, execute_result: ExecuteResult, analyze_result: AnalyzeResult, **kwargs) -> ReportResult:
        summary = f"性能测试: {'通过' if execute_result.success else '未达标'}"
        return ReportResult(success=True, summary=summary)
