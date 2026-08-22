"""
OpenAI 兼容端点通用基类

Qwen / DeepSeek / OpenAI / Ollama 都走 /v1/chat/completions 兼容接口,
请求体与响应体结构一致,统一抽取到这里。
子类只需提供 api_url / api_key / default_model / models 列表。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import httpx

from app.llm.providers.base import BaseProvider, ProviderConfig
from app.llm.types import LLMCallContext, LLMResponse


class _OpenAICompatibleProvider(BaseProvider):
    """OpenAI 兼容端点通用实现(Qwen/DeepSeek/OpenAI/Ollama 共用)"""

    def _is_configured(self) -> bool:
        # ollama 不需要 key,其它需要 key
        if self.config.name == "ollama":
            return bool(self.config.api_url)
        return bool(self.config.api_key) and bool(self.config.api_url)

    def _build_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _build_body(self, ctx: LLMCallContext) -> Dict[str, Any]:
        model = ctx.model or self.config.default_model
        body: Dict[str, Any] = {
            "model": model,
            "messages": ctx.messages,
            "temperature": ctx.temperature,
            "max_tokens": ctx.max_tokens,
        }
        # 合并扩展参数
        body.update(ctx.extra_params)
        return body

    def _resolve_model(self, ctx: LLMCallContext) -> str:
        return ctx.model or self.config.default_model

    async def chat(self, ctx: LLMCallContext) -> LLMResponse:
        model = self._resolve_model(ctx)
        url = self.config.api_url
        headers = self._build_headers()
        body = self._build_body(ctx)
        timeout = ctx.timeout or self.config.timeout

        start = time.time()
        status_code = 0
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=body, headers=headers)
                status_code = resp.status_code
                resp.raise_for_status()
                result = resp.json()

            duration = time.time() - start

            # 解析 OpenAI 兼容响应
            usage = result.get("usage", {}) or {}
            prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
            completion_tokens = int(usage.get("completion_tokens", 0) or 0)
            total_tokens = int(
                usage.get("total_tokens", prompt_tokens + completion_tokens) or 0
            )
            content = ""
            choices = result.get("choices") or []
            if choices:
                content = choices[0].get("message", {}).get("content", "") or ""

            return LLMResponse(
                content=content,
                model=model,
                provider=self.name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                duration=duration,
                success=True,
                raw=result,
            )

        except httpx.TimeoutException as e:
            return LLMResponse(
                content="",
                model=model,
                provider=self.name,
                duration=time.time() - start,
                success=False,
                error=str(e),
                error_type="timeout",
            )
        except httpx.HTTPStatusError as e:
            err_body = ""
            try:
                err_body = e.response.text[:500]
            except Exception:
                pass
            return LLMResponse(
                content="",
                model=model,
                provider=self.name,
                duration=time.time() - start,
                success=False,
                error=f"HTTP {status_code}: {err_body}",
                error_type=self._classify_error(e, status_code),
            )
        except httpx.HTTPError as e:
            return LLMResponse(
                content="",
                model=model,
                provider=self.name,
                duration=time.time() - start,
                success=False,
                error=str(e),
                error_type=self._classify_error(e),
            )
        except Exception as e:
            return LLMResponse(
                content="",
                model=model,
                provider=self.name,
                duration=time.time() - start,
                success=False,
                error=str(e),
                error_type=self._classify_error(e),
            )

    async def health_check(self) -> bool:
        """轻量健康检查:尝试 GET /v1/models(OpenAI 兼容端点通用)"""
        if not self._is_configured():
            return False
        try:
            # 从 chat 端点推导 models 端点
            base = self.config.api_url.replace("/chat/completions", "/models")
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(base, headers=self._build_headers())
            return resp.status_code == 200
        except Exception:
            # 降级为最小 chat 探测
            return await super().health_check()


class QwenProvider(_OpenAICompatibleProvider):
    """通义千问(DashScope OpenAI 兼容模式)"""

    @classmethod
    def from_config(cls, settings: Any) -> "QwenProvider":
        api_key = settings.QWEN_API_KEY or ""
        return cls(
            ProviderConfig(
                name="qwen",
                display_name="通义千问 (DashScope)",
                api_key=api_key,
                api_url=settings.QWEN_API_URL,
                default_model="qwen-plus",
                models=[
                    "qwen-plus",
                    "qwen-max",
                    "qwen-turbo",
                    "qwen-vl-plus",
                    "qwen-vl-max",
                    "qwen-coder-plus",
                ],
            )
        )


class DeepSeekProvider(_OpenAICompatibleProvider):
    """DeepSeek"""

    @classmethod
    def from_config(cls, settings: Any) -> "DeepSeekProvider":
        api_key = settings.DEEPSEEK_API_KEY or ""
        url = settings.DEEPSEEK_API_URL or "https://api.deepseek.com/v1/chat/completions"
        return cls(
            ProviderConfig(
                name="deepseek",
                display_name="DeepSeek",
                api_key=api_key,
                api_url=url,
                default_model="deepseek-chat",
                models=["deepseek-chat", "deepseek-coder", "deepseek-reasoner"],
            )
        )


class OpenAIProvider(_OpenAICompatibleProvider):
    """OpenAI GPT 系列"""

    @classmethod
    def from_config(cls, settings: Any) -> "OpenAIProvider":
        import os
        api_key = os.getenv("OPENAI_API_KEY", "") or getattr(settings, "OPENAI_API_KEY", "") or ""
        url = os.getenv(
            "OPENAI_API_URL",
            "https://api.openai.com/v1/chat/completions",
        )
        return cls(
            ProviderConfig(
                name="openai",
                display_name="OpenAI",
                api_key=api_key,
                api_url=url,
                default_model="gpt-4o",
                models=["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
            )
        )


class OllamaProvider(_OpenAICompatibleProvider):
    """本地模型(Ollama OpenAI 兼容端点)"""

    def _is_configured(self) -> bool:
        # ollama 无需 api_key,只要有 url 即可
        return bool(self.config.api_url)

    def _build_headers(self) -> Dict[str, str]:
        # ollama 不需要 Authorization
        return {"Content-Type": "application/json"}

    @classmethod
    def from_config(cls, settings: Any) -> "OllamaProvider":
        host = settings.OLLAMA_HOST or "http://localhost:11434"
        url = host.rstrip("/") + "/v1/chat/completions"
        return cls(
            ProviderConfig(
                name="ollama",
                display_name="本地模型 (Ollama)",
                api_key="",
                api_url=url,
                default_model="qwen2.5:7b",
                models=["qwen2.5:7b", "qwen2.5:14b", "llama3.1:8b", "deepseek-r1:7b"],
            )
        )
