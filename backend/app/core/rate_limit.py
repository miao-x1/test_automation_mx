"""
简单滑动窗口限流（进程内）。

单实例试点足够；多副本需改 Redis。纯 ASGI，不阻断 SSE 已建立的连接
（仅在请求进入时计数）。
"""
import json
import time
from collections import defaultdict, deque

from app.core.config import settings

_LLM_PREFIXES = (
    "/api/v1/",
    "/requirement",
    "/graphflow",
    "/runtime",
    "/api/llm-gateway",
    "/code",
    "/performance",
    "/api/v2/runtime",
    "/session/v2",
    "/executions",
    "/test-orchestration",
)


class RateLimitMiddleware:
    def __init__(self, app):
        self.app = app
        self._hits: dict[tuple[str, str], deque] = defaultdict(deque)

    def _client_ip(self, headers: dict, client) -> str:
        forwarded = headers.get(b"x-forwarded-for")
        if forwarded:
            return forwarded.decode("latin-1").split(",")[0].strip()
        if client:
            return client[0]
        return "unknown"

    def _allow(self, key: tuple[str, str], limit: int) -> bool:
        now = time.time()
        window = self._hits[key]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= limit:
            return False
        window.append(now)
        return True

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not settings.RATE_LIMIT_ENABLED:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET")
        if method == "OPTIONS":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        ip = self._client_ip(headers, scope.get("client"))

        limit = None
        bucket = None
        if path in (
            "/auth/login",
            "/auth/register",
            "/auth/captcha",
            "/auth/sms/send",
            "/auth/password/reset",
        ):
            limit = settings.RATE_LIMIT_LOGIN_PER_MINUTE
            bucket = "auth"
        elif any(path == p or path.startswith(p) for p in _LLM_PREFIXES):
            limit = settings.RATE_LIMIT_LLM_PER_MINUTE
            bucket = "llm"

        if limit is not None and not self._allow((ip, bucket), limit):
            body = json.dumps(
                {
                    "code": 429,
                    "message": "请求过于频繁，请稍后再试",
                    "data": {"error_code": "RATE_LIMITED"},
                },
                ensure_ascii=False,
            ).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json; charset=utf-8"),
                        (b"retry-after", b"60"),
                        (b"content-length", str(len(body)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        await self.app(scope, receive, send)
