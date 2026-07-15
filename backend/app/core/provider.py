"""
Testing Provider 接口定义

能力插件化：所有测试类型共享统一接口
以后新增测试类型无需新增页面，只需实现 Provider 接口

统一接口：
- prepare()    准备测试环境
- generate()   生成测试脚本
- execute()    执行测试
- analyze()    分析结果
- report()     生成报告
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from dataclasses import dataclass


@dataclass
class ProviderConfig:
    """Provider 配置基类"""
    pass


@dataclass
class WebProviderConfig(ProviderConfig):
    """Web UI 测试配置"""
    url: str = ""
    browser: str = "chromium"    # chromium/firefox/webkit
    viewport: str = "1280x720"
    headless: bool = True
    timeout: int = 30000


@dataclass
class ApiProviderConfig(ProviderConfig):
    """API 接口测试配置"""
    base_url: str = ""
    endpoint: str = ""
    method: str = "GET"
    headers: Dict[str, str] = None
    body: str = ""
    timeout: int = 30000

    def __post_init__(self):
        if self.headers is None:
            self.headers = {}


@dataclass
class PerformanceProviderConfig(ProviderConfig):
    """性能测试配置"""
    target_url: str = ""
    concurrency: int = 10
    duration: int = 60
    tps_target: int = 100
    ramp_up: int = 10


@dataclass
class AndroidProviderConfig(ProviderConfig):
    """Android 测试配置"""
    device: str = ""
    app_package: str = ""
    app_activity: str = ""
    app_path: str = ""
    timeout: int = 30000


@dataclass
class PrepareResult:
    """准备结果"""
    success: bool
    message: str = ""
    data: Dict[str, Any] = None

    def __post_init__(self):
        if self.data is None:
            self.data = {}


@dataclass
class GenerateResult:
    """生成结果"""
    success: bool
    script: str = ""
    script_language: str = "python"
    message: str = ""


@dataclass
class ExecuteResult:
    """执行结果"""
    success: bool
    duration: float = 0
    pass_count: int = 0
    fail_count: int = 0
    error_message: str = ""
    log_content: str = ""
    report_path: str = ""


@dataclass
class AnalyzeResult:
    """分析结果"""
    success: bool
    root_cause: str = ""
    suggestion: str = ""
    fail_step: str = ""
    confidence: float = 0.0


@dataclass
class ReportResult:
    """报告结果"""
    success: bool
    report_path: str = ""
    summary: str = ""
    data: Dict[str, Any] = None

    def __post_init__(self):
        if self.data is None:
            self.data = {}


class TestingProvider(ABC):
    """
    测试能力 Provider 基类

    所有测试类型必须实现此接口
    新增测试类型只需：
    1. 创建 XxxProvider(TestingProvider) 子类
    2. 注册到 ProviderRegistry
    3. 无需新增页面或路由
    """

    @abstractmethod
    def provider_type(self) -> str:
        """返回 Provider 类型标识"""
        pass

    @abstractmethod
    def provider_name(self) -> str:
        """返回 Provider 显示名称"""
        pass

    @abstractmethod
    def default_config(self) -> ProviderConfig:
        """返回默认配置"""
        pass

    @abstractmethod
    def config_schema(self) -> Dict[str, Any]:
        """返回配置的 JSON Schema（用于前端动态渲染配置表单）"""
        pass

    @abstractmethod
    def prepare(self, config: ProviderConfig, **kwargs) -> PrepareResult:
        """
        准备测试环境

        - Web: 启动浏览器、检查URL可达性
        - API: 检查接口可用性
        - Performance: 准备压测环境
        - Android: 连接设备、安装应用
        """
        pass

    @abstractmethod
    def generate(self, config: ProviderConfig, requirement: str = "", **kwargs) -> GenerateResult:
        """
        生成测试脚本

        - Web: 生成 Playwright 脚本
        - API: 生成 requests 脚本
        - Performance: 生成 Locust/k6 脚本
        - Android: 生成 Appium 脚本
        """
        pass

    @abstractmethod
    def execute(self, config: ProviderConfig, script: str, **kwargs) -> ExecuteResult:
        """
        执行测试

        - Web: 运行 Playwright
        - API: 运行 requests
        - Performance: 运行压测
        - Android: 运行 Appium
        """
        pass

    @abstractmethod
    def analyze(self, config: ProviderConfig, execute_result: ExecuteResult, **kwargs) -> AnalyzeResult:
        """
        分析执行结果

        - 通用: LLM 分析失败原因
        - Performance: 分析 TPS/延迟/错误率
        """
        pass

    @abstractmethod
    def report(self, config: ProviderConfig, execute_result: ExecuteResult, analyze_result: AnalyzeResult, **kwargs) -> ReportResult:
        """
        生成测试报告
        """
        pass


class ProviderRegistry:
    """
    Provider 注册表

    管理所有已注册的 TestingProvider
    """

    _providers: Dict[str, TestingProvider] = {}

    @classmethod
    def register(cls, provider: TestingProvider):
        """注册 Provider"""
        cls._providers[provider.provider_type()] = provider

    @classmethod
    def get(cls, provider_type: str) -> Optional[TestingProvider]:
        """获取 Provider"""
        return cls._providers.get(provider_type)

    @classmethod
    def list_providers(cls) -> Dict[str, TestingProvider]:
        """列出所有 Provider"""
        return cls._providers.copy()

    @classmethod
    def list_types(cls) -> list[str]:
        """列出所有已注册的测试类型"""
        return list(cls._providers.keys())
