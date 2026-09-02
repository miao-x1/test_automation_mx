"""
操作日志中间件

自动记录所有 API 请求到 OperationLog 表。

功能:
  1. 记录请求方法、路径、用户、IP、User-Agent
  2. 记录响应状态码和耗时
  3. 请求体自动脱敏后存储
  4. 排除健康检查和文档路径
  5. 异步写入,不阻塞请求

注册方式:
  在 app/main.py 中:
    from app.core.operation_log_middleware import OperationLogMiddleware
    app.add_middleware(OperationLogMiddleware)

注意:
  使用纯 ASGI middleware 而非 BaseHTTPMiddleware，
  避免 StreamingResponse (SSE) 连接泄漏和事件循环阻塞。
"""
import json
import logging
import time
from typing import Callable

from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# 不记录日志的路径前缀
_EXCLUDE_PREFIXES = (
    "/docs", "/redoc", "/openapi.json", "/favicon.ico",
    "/api/health",
)


class OperationLogMiddleware:
    """操作日志中间件 (纯 ASGI 实现)

    自动记录 API 请求到操作日志。
    使用纯 ASGI middleware，不继承 BaseHTTPMiddleware，
    确保 SSE/StreamingResponse 连接能正确处理客户端断开。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET")

        # 排除路径
        if path.startswith(_EXCLUDE_PREFIXES):
            await self.app(scope, receive, send)
            return

        start_time = time.time()

        # 读取请求体(用于日志)
        request_body = None
        original_receive = receive
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            body_parts = []
            more_body = True
            while more_body:
                message = await receive()
                if message["type"] == "http.request":
                    body_parts.append(message.get("body", b""))
                    more_body = message.get("more_body", False)
                else:
                    # http.disconnect 或其他
                    break

            body_bytes = b"".join(body_parts)
            if body_bytes:
                request_body = body_bytes.decode("utf-8", errors="replace")

            # 重新构造 receive 供后续处理
            # 注意：body 只能投递一次，之后必须委托给 original_receive，
            # 否则 SSE/Streaming 端点的 disconnect 监听器会一直收到 http.request
            # 而永远收不到 http.disconnect，导致 97%CPU 死循环并饿死事件循环。
            sent = {"body": body_bytes, "more_body": False}
            replay_state = {"delivered": False}

            async def replayed_receive():
                if not replay_state["delivered"]:
                    replay_state["delivered"] = True
                    return {"type": "http.request", "body": sent["body"], "more_body": False}
                # body 已投递，委托回原始 receive 以正确感知 http.disconnect
                return await original_receive()

            receive = replayed_receive

        # 包装 send 以捕获状态码
        response_status_code = 200
        response_started = False

        async def send_wrapper(message):
            nonlocal response_status_code, response_started
            if message["type"] == "http.response.start":
                response_status_code = message.get("status", 200)
                response_started = True
            await send(message)

        # 执行请求
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as e:
            duration = time.time() - start_time
            self._log_operation(
                scope, method, path, request_body,
                response_status=500,
                duration=duration,
                error_message=str(e),
            )
            raise

        duration = time.time() - start_time

        # 异步记录日志
        self._log_operation(
            scope, method, path, request_body,
            response_status=response_status_code,
            duration=duration,
        )

    def _log_operation(
        self,
        scope: dict,
        method: str,
        path: str,
        request_body: str,
        *,
        response_status: int,
        duration: float,
        error_message: str = None,
    ) -> None:
        """异步记录操作日志"""
        try:
            from app.services.audit_service import get_audit_service

            # 推断动作
            action = self._infer_action(method, path)

            # 推断资源类型
            resource_type, resource_id = self._infer_resource(path)

            # 从 scope 中提取 headers
            headers = dict(
                (k.decode("latin-1").lower(), v.decode("latin-1"))
                for k, v in scope.get("headers", [])
            )

            # 获取用户信息(从 scope state)
            state = scope.get("state", {})
            user_id = state.get("user_id")
            username = state.get("username")

            # 获取客户端IP
            ip_address = self._get_client_ip(scope, headers)
            user_agent = headers.get("user-agent", "")

            audit_service = get_audit_service()
            audit_service.log_operation(
                user_id=user_id,
                username=username,
                action=action,
                method=method,
                path=path,
                resource_type=resource_type,
                resource_id=resource_id,
                ip_address=ip_address,
                user_agent=user_agent,
                request_body=request_body,
                response_status=response_status,
                duration=duration,
                error_message=error_message,
                async_write=True,
            )
        except Exception as e:
            logger.debug(f"[OperationLogMiddleware] 记录操作日志失败: {e}")

    @staticmethod
    def _infer_action(method: str, path: str) -> str:
        """从HTTP方法和路径推断动作"""
        method_upper = method.upper()
        if method_upper == "GET":
            return "read"
        elif method_upper == "POST":
            if "login" in path:
                return "login"
            if "logout" in path:
                return "logout"
            if "register" in path:
                return "register"
            if "execute" in path or "run" in path:
                return "execute"
            if "delete" in path:
                return "delete"
            return "create"
        elif method_upper == "PUT" or method_upper == "PATCH":
            return "update"
        elif method_upper == "DELETE":
            return "delete"
        return method_upper.lower()

    @staticmethod
    def _infer_resource(path: str):
        """从路径推断资源类型和ID

        Returns:
            (resource_type, resource_id)
        """
        parts = [p for p in path.split("/") if p]
        if len(parts) < 2:
            return None, None

        # /api/{resource_type}/...
        if parts[0] == "api":
            if len(parts) >= 2:
                resource_type = parts[1]
                # 尝试从路径中提取ID
                resource_id = None
                if len(parts) >= 3:
                    try:
                        resource_id = int(parts[2])
                    except ValueError:
                        pass
                return resource_type, resource_id
        return None, None

    @staticmethod
    def _get_client_ip(scope: dict, headers: dict) -> str:
        """获取客户端真实IP(支持代理)"""
        # 检查代理头
        forwarded_for = headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = headers.get("x-real-ip")
        if real_ip:
            return real_ip

        client = scope.get("client")
        return client[0] if client else "unknown"
