"""
HttpRunner - HTTP 请求执行器

职责：执行单个 HTTP 请求步骤，返回响应
"""
import time as _time
from typing import Any, Dict, Optional
from app.core.logger import log


class HttpRunner:
    """HTTP 请求执行器"""

    def execute(
        self,
        step: Dict[str, Any],
        context: Any,
    ) -> Dict[str, Any]:
        """
        执行 HTTP 请求

        Args:
            step: 步骤定义
                {
                    "action": "POST",
                    "url": "/api/open_account",
                    "headers": {},
                    "body": {},
                    "params": {},
                    "timeout": 30
                }
            context: ExecutionContext

        Returns:
            {
                "status_code": int,
                "headers": dict,
                "json": dict or None,
                "text": str,
                "elapsed_ms": int,
                "success": bool,
                "error": str or None
            }
        """
        import httpx

        method = step.get("action", "GET").upper()
        url_path = step.get("url", "")
        step_headers = step.get("headers", {})
        body = step.get("body")
        params = step.get("params")
        timeout = step.get("timeout", 30)

        # 解析模板变量
        url_path = context.resolve_template(url_path)
        step_headers = context.resolve_dict(step_headers) if step_headers else {}
        if body:
            body = context.resolve_dict(body)
        if params:
            params = context.resolve_dict(params)

        # 合并URL
        if url_path.startswith("http"):
            url = url_path
        else:
            url = f"{context.base_url}{url_path}"

        # 合并headers
        merged_headers = {**context.headers, **step_headers}

        start = _time.time()
        try:
            with httpx.Client(timeout=timeout, verify=False) as client:
                kwargs: Dict[str, Any] = {
                    "method": method,
                    "url": url,
                    "headers": merged_headers,
                }
                if body is not None and method in ("POST", "PUT", "PATCH"):
                    kwargs["json"] = body
                if params:
                    kwargs["params"] = params

                response = client.request(**kwargs)

            elapsed_ms = int((_time.time() - start) * 1000)

            # 解析响应
            resp_json = None
            try:
                resp_json = response.json()
            except Exception:
                pass

            result = {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "json": resp_json,
                "text": response.text[:5000],
                "elapsed_ms": elapsed_ms,
                "success": 200 <= response.status_code < 300,
                "error": None,
            }

            log.info(f"HttpRunner | {method} {url} → {response.status_code} ({elapsed_ms}ms)")
            return result

        except httpx.TimeoutException:
            elapsed_ms = int((_time.time() - start) * 1000)
            log.warning(f"HttpRunner | {method} {url} → TIMEOUT ({elapsed_ms}ms)")
            return {
                "status_code": 0,
                "headers": {},
                "json": None,
                "text": "",
                "elapsed_ms": elapsed_ms,
                "success": False,
                "error": f"请求超时 ({timeout}s)",
            }
        except Exception as e:
            elapsed_ms = int((_time.time() - start) * 1000)
            log.error(f"HttpRunner | {method} {url} → ERROR: {e}")
            return {
                "status_code": 0,
                "headers": {},
                "json": None,
                "text": "",
                "elapsed_ms": elapsed_ms,
                "success": False,
                "error": str(e),
            }
