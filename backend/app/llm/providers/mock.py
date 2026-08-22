"""
Mock Provider - 测试用

不发送真实请求,直接返回固定内容。
用于:
- 单元测试 / 无网络的开发环境
- 验证 Gateway 路由与统计逻辑
- 作为最终兜底(可选)
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from app.llm.providers.base import BaseProvider, ProviderConfig
from app.llm.types import LLMCallContext, LLMResponse


class MockProvider(BaseProvider):
    """模拟供应商,不调用真实 API"""

    def _is_configured(self) -> bool:
        return True  # mock 始终可用

    async def chat(self, ctx: LLMCallContext) -> LLMResponse:
        start = time.time()
        model = ctx.model or self.config.default_model or "mock-model"
        # 模拟一点延迟
        # await asyncio.sleep(0.01)  # 实际不 sleep,保持测试快速
        content = self._generate_mock_content(ctx)
        # 模拟 token 用量(按字符粗估)
        prompt_chars = sum(len(m.get("content", "")) for m in ctx.messages)
        completion_chars = len(content)
        prompt_tokens = max(1, prompt_chars // 4)
        completion_tokens = max(1, completion_chars // 4)
        return LLMResponse(
            content=content,
            model=model,
            provider="mock",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            duration=time.time() - start,
            success=True,
            raw={"id": f"mock-{uuid.uuid4().hex[:8]}", "mock": True},
        )

    def _generate_mock_content(self, ctx: LLMCallContext) -> str:
        """根据请求内容生成有意义的 mock 响应"""
        # 尝试从 messages 提取最后一条用户消息
        user_msg = ""
        for m in reversed(ctx.messages):
            if m.get("role") == "user":
                user_msg = m.get("content", "")
                break
        if not user_msg:
            return '{"status": "mock", "message": "Mock LLM response"}'
        # 如果看起来像要 JSON,返回 JSON
        if "{" in user_msg or "json" in user_msg.lower():
            return '{"status": "mock", "message": "Mock JSON response", "echo": "' + user_msg[:50].replace('"', "'") + '"}'
        return f"[Mock] 已收到请求({len(user_msg)}字符),模拟回复内容。"

    async def health_check(self) -> bool:
        return True
