"""
LLM Provider 基类

所有供应商适配器继承 BaseProvider,实现统一的 chat() 接口。
LLMGateway 通过 BaseProvider 抽象调用任意供应商。
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.llm.types import LLMCallContext, LLMResponse


@dataclass
class ProviderConfig:
    """供应商配置(从 config.py / 环境变量加载)"""
    name: str  # qwen / deepseek / openai / ollama / mock
    display_name: str = ""
    api_key: str = ""
    api_url: str = ""
    timeout: int = 120
    # 该供应商支持的模型列表
    models: List[str] = field(default_factory=list)
    # 默认模型(未指定时使用)
    default_model: str = ""
    enabled: bool = True
    # 额外配置(如 ollama 无需 key)
    extra: Dict[str, Any] = field(default_factory=dict)


class BaseProvider(abc.ABC):
    """
    供应商适配器基类

    约定:所有 Provider 返回统一的 LLMResponse,
    内部完成 httpx 调用 + usage 解析 + 错误分类,
    不关心统计与切换(那是 Gateway 的事)。
    """

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config
        self._name = config.name

    @property
    def name(self) -> str:
        return self._name

    @property
    def display_name(self) -> str:
        return self.config.display_name or self._name

    @property
    def enabled(self) -> bool:
        return self.config.enabled and self._is_configured()

    def _is_configured(self) -> bool:
        """是否已正确配置(子类可重写,如 ollama 不需要 api_key)"""
        return True

    @abc.abstractmethod
    async def chat(self, ctx: LLMCallContext) -> LLMResponse:
        """执行一次聊天补全调用"""
        raise NotImplementedError

    async def health_check(self) -> bool:
        """
        健康检查(轻量探测)

        默认实现:发一条极小的测试请求,成功即健康。
        子类可重写为更轻量的方式(如 /models 端点)。
        """
        try:
            ctx = LLMCallContext(
                messages=[
                    {"role": "user", "content": "ping"},
                ],
                model=self.config.default_model,
                temperature=0,
                max_tokens=8,
                timeout=10,
            )
            resp = await self.chat(ctx)
            return resp.success
        except Exception:
            return False

    async def list_models(self) -> List[str]:
        """返回该供应商支持的模型列表"""
        return list(self.config.models)

    def _classify_error(self, e: Exception, status_code: int = 0) -> str:
        """根据异常/状态码分类错误,用于切换决策"""
        msg = str(e).lower()
        if "timeout" in msg or "timed out" in msg:
            return "timeout"
        if status_code == 401 or status_code == 403 or "unauthorized" in msg or "api key" in msg:
            return "auth"
        if status_code == 429 or "rate limit" in msg or "quota" in msg:
            return "rate_limit"
        if status_code >= 500 or "server" in msg or "internal" in msg:
            return "server_error"
        if "connection" in msg or "network" in msg or "dns" in msg or "refused" in msg:
            return "network"
        return "unknown"

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self._name} enabled={self.enabled}>"
