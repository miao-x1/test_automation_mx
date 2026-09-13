"""
全局鉴权门禁（纯 ASGI，不阻断 SSE）。

公开路径以外的请求必须带有效 JWT（Authorization Bearer 或 access_token Cookie）。
生产环境默认关闭 MCP；开发环境可按 ENABLE_MCP 打开。
"""
import json

from app.core.auth import decode_token
from app.core.config import settings

_PUBLIC_EXACT = {
    "/health",
    "/health/",
    "/api/health",
    "/api/health/",
    "/ready",
    "/ready/",
    "/api/ready",
    "/api/ready/",
    "/auth/login",
    "/auth/quick-enter",
    "/api/auth/login",
    "/api/auth/quick-enter",
    "/auth/register",
    "/auth/refresh",
    "/auth/public-config",
    "/auth/captcha",
    "/auth/sms/send",
    "/auth/password/reset",
}

_PUBLIC_PREFIXES = (
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
    "/fixtures",
)


def _json_response(status: int, message: str, error_code: str) -> list:
    body = json.dumps(
        {"code": status, "message": message, "data": {"error_code": error_code}},
        ensure_ascii=False,
    ).encode("utf-8")
    return [
        status,
        [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"content-length", str(len(body)).encode("ascii")),
        ],
        body,
    ]


def _extract_token(headers: dict) -> str | None:
    auth = headers.get(b"authorization")
    if auth:
        value = auth.decode("latin-1")
        if value.lower().startswith("bearer "):
            token = value[7:].strip()
            if token:
                return token
    cookie = headers.get(b"cookie")
    if not cookie:
        return None
    for part in cookie.decode("latin-1").split(";"):
        name, _, value = part.strip().partition("=")
        if name == "access_token" and value:
            return value
    return None


def _is_public(path: str, method: str) -> bool:
    if method == "OPTIONS":
        return True
    if path in _PUBLIC_EXACT:
        return True
    return any(path == prefix or path.startswith(prefix + "/") for prefix in _PUBLIC_PREFIXES)


class AuthGateMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET")

        if path.startswith("/mcp"):
            if not settings.mcp_enabled:
                status, headers, body = _json_response(404, "MCP 未启用", "MCP_DISABLED")
                await send({"type": "http.response.start", "status": status, "headers": headers})
                await send({"type": "http.response.body", "body": body})
                return
            if not settings.AUTH_REQUIRED:
                await self.app(scope, receive, send)
                return
            token = _extract_token(dict(scope.get("headers") or []))
            payload = decode_token(token) if token else None
            if payload is None or payload.get("type") != "access":
                status, headers, body = _json_response(401, "未登录或登录已过期", "UNAUTHORIZED")
                await send({"type": "http.response.start", "status": status, "headers": headers})
                await send({"type": "http.response.body", "body": body})
                return
            await self.app(scope, receive, send)
            return

        if not settings.AUTH_REQUIRED or _is_public(path, method):
            await self.app(scope, receive, send)
            return

        token = _extract_token(dict(scope.get("headers") or []))
        payload = decode_token(token) if token else None
        if payload is None or payload.get("type") != "access":
            status, headers, body = _json_response(401, "未登录或登录已过期", "UNAUTHORIZED")
            await send({"type": "http.response.start", "status": status, "headers": headers})
            await send({"type": "http.response.body", "body": body})
            return

        await self.app(scope, receive, send)
