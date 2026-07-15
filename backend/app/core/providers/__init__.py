"""
Provider 初始化模块

注册所有内置 Provider
"""
from app.core.provider import ProviderRegistry
from app.core.providers.web_provider import WebProvider
from app.core.providers.api_provider import ApiProvider
from app.core.providers.performance_provider import PerformanceProvider
from app.core.providers.android_provider import AndroidProvider


def init_providers():
    """初始化并注册所有 Provider"""
    ProviderRegistry.register(WebProvider())
    ProviderRegistry.register(ApiProvider())
    ProviderRegistry.register(PerformanceProvider())
    ProviderRegistry.register(AndroidProvider())
