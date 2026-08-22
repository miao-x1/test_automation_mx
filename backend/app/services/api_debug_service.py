"""
ApiDebugService - AI 接口调试服务

职责:
  1. 执行 HTTP 请求 (httpx)
  2. 保存执行记录到 api_execution_record
  3. 调用 ApiDebugAgent 分析失败原因
  4. 执行记录 CRUD

不做:
  - HTTP 层逻辑 (由 router 负责)
  - SQL 拼接 (由 repository 负责)

调用关系:
  Router → Service → Repository
                  → Agent (ApiDebugAgent)
                  → httpx (HTTP 请求)
"""
import json
import logging
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterator, Optional

import httpx
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.api_execution_record import (
    ApiExecutionRecord,
    ExecutionStatus,
    AnalysisStatus,
)
from app.repositories.api_execution_record_repository import ApiExecutionRecordRepository
from app.core.exceptions import BusinessError, ValidationError

logger = logging.getLogger(__name__)


class RecordNotFoundError(BusinessError):
    def __init__(self, record_id: int):
        super().__init__(
            code="RECORD_NOT_FOUND",
            message=f"执行记录不存在: id={record_id}",
            details={"record_id": record_id},
        )


class ApiDebugService:
    """AI 接口调试服务"""

    def __init__(self):
        self._repo = ApiExecutionRecordRepository()

    @contextmanager
    def _session(self) -> Iterator[Session]:
        db = SessionLocal()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ============================================================
    # 执行 HTTP 请求 (核心)
    # ============================================================

    async def execute_request(
        self,
        *,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Any] = None,
        auth: Optional[Dict[str, Any]] = None,
        timeout: int = 30000,
        api_id: Optional[int] = None,
        case_id: Optional[int] = None,
        env: str = "test",
        auto_analyze: bool = False,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """执行 HTTP 请求并保存记录

        步骤:
          1. 创建 PENDING 记录
          2. 执行 httpx 请求
          3. 更新记录为 SUCCESS/FAILED/ERROR/TIMEOUT
          4. auto_analyze=True 且失败时,调用 ApiDebugAgent

        返回:
          {
            "status": "success/failed/error/timeout",
            "record_id": int,
            "request": {...},
            "response": {...},
            "status_code": int,
            "duration": float (ms),
            "error": str,
            "analysis": {...} (仅 auto_analyze=True 且失败时)
          }
        """
        start = time.time()
        method = method.upper()

        # 1. 创建 PENDING 记录
        with self._session() as db:
            record = self._repo.create(
                db,
                method=method,
                url=url,
                headers=headers,
                params=params,
                body=body,
                auth=auth,
                api_id=api_id,
                case_id=case_id,
                status=ExecutionStatus.PENDING,
                env=env,
                trigger_source="debug",
                user_id=user_id,
                created_by=user_id,
            )
            record_id = record.id
        logger.info(f"[ApiDebugSvc] 开始执行 record_id={record_id} {method} {url[:80]}")

        # 2. 执行 HTTP 请求
        request_data = {
            "method": method,
            "url": url,
            "headers": headers or {},
            "params": params or {},
            "body": body,
            "auth": auth,
        }
        response_data: Dict[str, Any] = {}
        status = ExecutionStatus.FAILED
        error_msg: Optional[str] = None

        try:
            # 准备请求参数
            req_headers = dict(headers or {})
            req_json = None
            req_content = None

            if body is not None:
                if isinstance(body, (dict, list)):
                    req_json = body
                else:
                    req_content = str(body)

            # 处理 auth
            if auth and isinstance(auth, dict):
                auth_type = auth.get("type", "")
                if auth_type == "bearer":
                    req_headers["Authorization"] = f"Bearer {auth.get('token', '')}"
                elif auth_type == "basic":
                    import base64
                    user_pass = f"{auth.get('username', '')}:{auth.get('password', '')}"
                    req_headers["Authorization"] = f"Basic {base64.b64encode(user_pass.encode()).decode()}"
                elif auth_type == "api_key":
                    key_name = auth.get("key_name", "X-API-Key")
                    req_headers[key_name] = auth.get("key_value", "")

            # 执行请求 (httpx async)
            timeout_s = min(timeout / 1000.0, 120.0)
            async with httpx.AsyncClient(timeout=timeout_s, verify=False) as client:
                resp = await client.request(
                    method=method,
                    url=url,
                    headers=req_headers,
                    params=params or None,
                    json=req_json,
                    content=req_content,
                )

            response_data = {
                "status_code": resp.status_code,
                "headers": dict(resp.headers),
                "body": self._parse_response_body(resp),
                "size": len(resp.content),
            }

            # 判断成功失败
            if 200 <= resp.status_code < 400:
                status = ExecutionStatus.SUCCESS
            else:
                status = ExecutionStatus.FAILED

        except httpx.TimeoutException as e:
            status = ExecutionStatus.TIMEOUT
            error_msg = f"请求超时: {e}"
            logger.warning(f"[ApiDebugSvc] 请求超时 record_id={record_id}: {e}")
        except httpx.ConnectError as e:
            status = ExecutionStatus.ERROR
            error_msg = f"连接失败: {e}"
            logger.warning(f"[ApiDebugSvc] 连接失败 record_id={record_id}: {e}")
        except Exception as e:
            status = ExecutionStatus.ERROR
            error_msg = f"请求异常: {type(e).__name__}: {e}"
            logger.error(f"[ApiDebugSvc] 请求异常 record_id={record_id}: {e}", exc_info=True)

        duration_ms = (time.time() - start) * 1000

        # 3. 更新记录
        with self._session() as db:
            record = self._repo.get_by_id(db, record_id)
            if record:
                self._repo.update_result(
                    db,
                    record,
                    status_code=response_data.get("status_code"),
                    response_headers=response_data.get("headers"),
                    response_body=response_data.get("body"),
                    response_size=response_data.get("size"),
                    status=status,
                    duration=duration_ms,
                    error=error_msg,
                )

        logger.info(
            f"[ApiDebugSvc] 执行完成 record_id={record_id} status={status.value} "
            f"code={response_data.get('status_code')} duration={duration_ms:.0f}ms"
        )

        result: Dict[str, Any] = {
            "status": status.value,
            "record_id": record_id,
            "request": request_data,
            "response": response_data,
            "status_code": response_data.get("status_code"),
            "duration": duration_ms,
            "error": error_msg,
        }

        # 4. auto_analyze 且失败时,调用 ApiDebugAgent
        if auto_analyze and status != ExecutionStatus.SUCCESS:
            try:
                analysis = await self.analyze_record(record_id, force=True)
                result["analysis"] = analysis
            except Exception as e:
                logger.error(f"[ApiDebugSvc] 自动分析失败 record_id={record_id}: {e}")
                result["analysis"] = {"status": "error", "message": str(e)}

        return result

    def _parse_response_body(self, resp) -> Any:
        """解析响应体"""
        content_type = resp.headers.get("content-type", "")
        try:
            if "application/json" in content_type:
                return resp.json()
            elif "text/" in content_type or "html" in content_type:
                return resp.text
            else:
                # 尝试 JSON,失败返回文本
                try:
                    return resp.json()
                except Exception:
                    return resp.text[:5000]
        except Exception:
            return resp.text[:5000]

    # ============================================================
    # AI 分析
    # ============================================================

    async def analyze_record(
        self,
        record_id: int,
        *,
        force: bool = False,
    ) -> Dict[str, Any]:
        """调用 ApiDebugAgent 分析执行记录"""
        from app.agents.flows.api_debug_agent import ApiDebugAgent

        agent = ApiDebugAgent()
        payload = {
            "action": "analyze",
            "record_id": record_id,
            "force": force,
        }
        try:
            result = await agent.execute(payload, ctx=None)
            logger.info(
                f"[ApiDebugSvc] 分析完成 record_id={record_id} "
                f"source={result.get('source')} confidence={result.get('confidence')}"
            )
            return result
        except Exception as e:
            logger.error(f"[ApiDebugSvc] 分析失败 record_id={record_id}: {e}", exc_info=True)
            return {
                "status": "error",
                "message": str(e),
                "record_id": record_id,
            }

    async def analyze_inline(
        self,
        request: Dict[str, Any],
        response: Dict[str, Any],
        error: Optional[str] = None,
        status: str = "failed",
    ) -> Dict[str, Any]:
        """直接传入数据做分析(不落库)"""
        from app.agents.flows.api_debug_agent import ApiDebugAgent

        agent = ApiDebugAgent()
        payload = {
            "action": "analyze",
            "request": request,
            "response": response,
            "error": error,
            "status": status,
            "force": True,
        }
        return await agent.execute(payload, ctx=None)

    # ============================================================
    # 健康检查
    # ============================================================

    async def health_check(self) -> Dict[str, Any]:
        from app.agents.flows.api_debug_agent import ApiDebugAgent
        agent = ApiDebugAgent()
        return await agent._do_health()

    # ============================================================
    # 执行记录 CRUD
    # ============================================================

    def get_record(self, record_id: int) -> Dict[str, Any]:
        with self._session() as db:
            record = self._repo.get_by_id(db, record_id)
            if not record:
                raise RecordNotFoundError(record_id)
            return self._repo.to_dict(record)

    def list_records(
        self,
        *,
        api_id: Optional[int] = None,
        case_id: Optional[int] = None,
        status: Optional[str] = None,
        status_code: Optional[int] = None,
        method: Optional[str] = None,
        keyword: Optional[str] = None,
        user_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        with self._session() as db:
            items, total = self._repo.list(
                db,
                api_id=api_id,
                case_id=case_id,
                status=status,
                status_code=status_code,
                method=method,
                keyword=keyword,
                user_id=user_id,
                page=page,
                page_size=page_size,
            )
            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "items": [self._repo.to_dict(r) for r in items],
            }

    def delete_record(self, record_id: int) -> Dict[str, Any]:
        with self._session() as db:
            record = self._repo.get_by_id(db, record_id)
            if not record:
                raise RecordNotFoundError(record_id)
            self._repo.soft_delete(db, record)
            return {"id": record_id, "is_deleted": True}
