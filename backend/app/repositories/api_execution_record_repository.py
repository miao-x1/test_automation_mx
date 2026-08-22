"""
ApiExecutionRecordRepository - 执行记录数据访问层

职责:
  1. 封装 api_execution_record 的 CRUD
  2. JSON 字段序列化
  3. 软删除过滤
  4. 按 api_id/case_id/status/status_code 过滤
"""
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, desc, or_
from sqlalchemy.orm import Session

from app.models.api_execution_record import (
    ApiExecutionRecord,
    ExecutionStatus,
    AnalysisStatus,
)

logger = logging.getLogger(__name__)


def _dump_json(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as e:
        logger.warning(f"JSON 序列化失败: {e}")
        return None


class ApiExecutionRecordRepository:
    """执行记录 Repository"""

    # ------------------------------------------------------------------
    # 创建
    # ------------------------------------------------------------------

    def create(
        self,
        db: Session,
        *,
        method: str,
        url: str,
        headers: Optional[Dict] = None,
        params: Optional[Dict] = None,
        body: Optional[Any] = None,
        auth: Optional[Dict] = None,
        api_id: Optional[int] = None,
        case_id: Optional[int] = None,
        execution_id: Optional[int] = None,
        status: ExecutionStatus = ExecutionStatus.PENDING,
        env: str = "test",
        trigger_source: str = "debug",
        client_ip: Optional[str] = None,
        user_id: Optional[int] = None,
        created_by: Optional[int] = None,
    ) -> ApiExecutionRecord:
        """创建执行记录"""
        record = ApiExecutionRecord(
            api_id=api_id,
            case_id=case_id,
            execution_id=execution_id,
            method=method.upper(),
            url=url,
            headers_json=_dump_json(headers),
            params_json=_dump_json(params),
            body_json=_dump_json(body) if not isinstance(body, str) else body,
            auth_json=_dump_json(auth),
            status=status,
            env=env,
            trigger_source=trigger_source,
            client_ip=client_ip,
            user_id=user_id,
            created_by=created_by,
        )
        db.add(record)
        db.flush()
        logger.info(f"[ApiExecRepo] 创建执行记录 id={record.id} {method} {url[:80]}")
        return record

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_by_id(
        self, db: Session, record_id: int, *, include_deleted: bool = False
    ) -> Optional[ApiExecutionRecord]:
        """按 ID 查询"""
        q = db.query(ApiExecutionRecord).filter(ApiExecutionRecord.id == record_id)
        if not include_deleted:
            q = q.filter(ApiExecutionRecord.is_deleted == False)
        return q.first()

    def list(
        self,
        db: Session,
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
    ) -> Tuple[List[ApiExecutionRecord], int]:
        """分页查询"""
        q = db.query(ApiExecutionRecord).filter(ApiExecutionRecord.is_deleted == False)

        if api_id is not None:
            q = q.filter(ApiExecutionRecord.api_id == api_id)
        if case_id is not None:
            q = q.filter(ApiExecutionRecord.case_id == case_id)
        if status:
            q = q.filter(ApiExecutionRecord.status == status)
        if status_code is not None:
            q = q.filter(ApiExecutionRecord.status_code == status_code)
        if method:
            q = q.filter(ApiExecutionRecord.method == method.upper())
        if user_id is not None:
            q = q.filter(ApiExecutionRecord.user_id == user_id)
        if keyword:
            kw = f"%{keyword}%"
            q = q.filter(or_(
                ApiExecutionRecord.url.like(kw),
                ApiExecutionRecord.error.like(kw),
            ))

        total = q.count()
        items = (
            q.order_by(desc(ApiExecutionRecord.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    # ------------------------------------------------------------------
    # 更新 (执行结果回填)
    # ------------------------------------------------------------------

    def update_result(
        self,
        db: Session,
        record: ApiExecutionRecord,
        *,
        status_code: Optional[int] = None,
        response_headers: Optional[Dict] = None,
        response_body: Optional[Any] = None,
        response_size: Optional[int] = None,
        status: ExecutionStatus = ExecutionStatus.SUCCESS,
        duration: float = 0.0,
        error: Optional[str] = None,
    ) -> ApiExecutionRecord:
        """更新执行结果"""
        if status_code is not None:
            record.status_code = status_code
        record.response_headers_json = _dump_json(response_headers)
        if response_body is not None:
            if isinstance(response_body, (dict, list)):
                record.response_body = _dump_json(response_body)
            else:
                record.response_body = str(response_body)
        if response_size is not None:
            record.response_size = response_size
        record.status = status
        record.duration = duration
        if error:
            record.error = error[:65535] if isinstance(error, str) else str(error)[:65535]
        db.flush()
        logger.info(f"[ApiExecRepo] 更新结果 id={record.id} status={status} code={status_code}")
        return record

    def update_analysis(
        self,
        db: Session,
        record: ApiExecutionRecord,
        *,
        analysis_status: AnalysisStatus,
        analysis_result: Optional[Dict] = None,
    ) -> ApiExecutionRecord:
        """更新 AI 分析结果"""
        record.analysis_status = analysis_status
        if analysis_result is not None:
            record.analysis_result = _dump_json(analysis_result)
        if analysis_status == AnalysisStatus.DONE:
            from datetime import datetime
            record.analyzed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.flush()
        return record

    # ------------------------------------------------------------------
    # 软删除
    # ------------------------------------------------------------------

    def soft_delete(self, db: Session, record: ApiExecutionRecord) -> None:
        record.is_deleted = True
        db.flush()

    # ------------------------------------------------------------------
    # 转换为 dict (用于响应)
    # ------------------------------------------------------------------

    def to_dict(self, record: ApiExecutionRecord) -> Dict[str, Any]:
        """转换为字典"""
        def _safe_load(s):
            if not s:
                return None
            try:
                return json.loads(s)
            except Exception:
                return s

        return {
            "id": record.id,
            "api_id": record.api_id,
            "case_id": record.case_id,
            "execution_id": record.execution_id,
            "method": record.method,
            "url": record.url,
            "headers": _safe_load(record.headers_json),
            "params": _safe_load(record.params_json),
            "body": _safe_load(record.body_json),
            "auth": _safe_load(record.auth_json),
            "status_code": record.status_code,
            "response_headers": _safe_load(record.response_headers_json),
            "response_body": _safe_load(record.response_body),
            "response_size": record.response_size,
            "status": record.status.value if hasattr(record.status, "value") else record.status,
            "duration": record.duration,
            "error": record.error,
            "analysis_status": record.analysis_status.value if hasattr(record.analysis_status, "value") else record.analysis_status,
            "analysis_result": _safe_load(record.analysis_result),
            "analyzed_at": record.analyzed_at,
            "env": record.env,
            "trigger_source": record.trigger_source,
            "client_ip": record.client_ip,
            "user_id": record.user_id,
            "created_at": str(record.created_at) if record.created_at else None,
            "updated_at": str(record.updated_at) if record.updated_at else None,
        }
