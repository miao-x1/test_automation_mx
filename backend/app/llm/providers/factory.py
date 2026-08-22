"""
Provider 工厂

从 app.core.config.settings 加载所有供应商配置,创建并缓存 Provider 实例。
支持:
- 运行时切换启用/禁用
- 动态注册自定义 Provider
- 按名称获取
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.llm.providers.base import BaseProvider, ProviderConfig
from app.llm.providers.openai_compatible import (
    QwenProvider,
    DeepSeekProvider,
    OpenAIProvider,
    OllamaProvider,
)
from app.llm.providers.mock import MockProvider

logger = logging.getLogger(__name__)


class ProviderFactory:
    """供应商工厂(单例)"""

    def __init__(self) -> None:
        self._providers: Dict[str, BaseProvider] = {}
        self._initialized = False

    def initialize(self, settings: Any = None, force: bool = False) -> None:
        """
        从 settings 初始化所有内置 Provider

        首次调用会创建实例并缓存;force=True 强制重建。
        """
        if self._initialized and not force:
            return
        if settings is None:
            try:
                from app.core.config import settings as _settings
                settings = _settings
            except Exception as e:
                logger.warning(f"ProviderFactory: 无法加载 settings: {e}")
                settings = None

        self._providers.clear()

        # 注册内置 Provider(顺序即优先级参考)
        providers_to_register: List[BaseProvider] = []
        if settings is not None:
            providers_to_register.append(QwenProvider.from_config(settings))
            providers_to_register.append(DeepSeekProvider.from_config(settings))
            providers_to_register.append(OpenAIProvider.from_config(settings))
            providers_to_register.append(OllamaProvider.from_config(settings))
        providers_to_register.append(MockProvider(ProviderConfig(
            name="mock",
            display_name="Mock (测试用)",
            default_model="mock-model",
            models=["mock-model"],
        )))

        for p in providers_to_register:
            self._providers[p.name] = p

        self._initialized = True
        enabled = [n for n, p in self._providers.items() if p.enabled]
        logger.info(
            f"ProviderFactory initialized: {len(self._providers)} providers "
            f"({enabled} enabled)"
        )

    def get(self, name: str) -> Optional[BaseProvider]:
        if not self._initialized:
            self.initialize()
        return self._providers.get(name)

    def list_providers(self, include_disabled: bool = False) -> List[BaseProvider]:
        if not self._initialized:
            self.initialize()
        result = []
        for p in self._providers.values():
            if include_disabled or p.enabled:
                result.append(p)
        return result

    def list_enabled(self) -> List[BaseProvider]:
        return self.list_providers(include_disabled=False)

    def register(self, provider: BaseProvider) -> None:
        """动态注册自定义 Provider"""
        self._providers[provider.name] = provider
        logger.info(f"ProviderFactory: registered provider '{provider.name}'")

    def unregister(self, name: str) -> bool:
        return self._providers.pop(name, None) is not None

    def is_available(self, name: str) -> bool:
        p = self.get(name)
        return p is not None and p.enabled

    def clear_cache(self) -> None:
        """清空缓存,下次访问时重建"""
        self._providers.clear()
        self._initialized = False


# 单例
_factory: Optional[ProviderFactory] = None


def get_provider_factory() -> ProviderFactory:
    global _factory
    if _factory is None:
        _factory = ProviderFactory()
    return _factory
