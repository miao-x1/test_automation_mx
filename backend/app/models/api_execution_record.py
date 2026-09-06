"""
API 执行记录模型 - 单次 HTTP 请求级

与 ExecutionRecord(批次级,一次执行多个用例)不同,
ApiExecutionRecord 记录每一次 HTTP 请求的完整信息:
  - 请求(method/url/headers/body)
  - 响应(status_code/headers/body/duration)
  - 错误信息
  - AI 分析结果(由 ApiDebugAgent 生成)

供 AI 调试系统(Postman + AI 分析)使用。
"""
import enum
from sqlalchemy import (
    Column, String, Integer, Text, Boolean, Float, Index,
)
from app.db.types import MEDIUMTEXT
from sqlalchemy import Enum as SAEnum

from app.models.base import OwnedModel


class ExecutionStatus(str, enum.Enum):
    """单次请求执行状态"""
    SUCCESS = "success"
    FAILED = "failed"
    ERROR = "error"          # 网络错误/超时/异常
    TIMEOUT = "timeout"
    PENDING = "pending"      # 待执行


class AnalysisStatus(str, enum.Enum):
    """AI 分析状态"""
    NONE = "none"            # 未分析
    ANALYZING = "analyzing"  # 分析中
    DONE = "done"            # 已完成
    FAILED = "failed"        # 分析失败


class ApiExecutionRecord(OwnedModel):
    """API 执行记录(单次 HTTP 请求级)

    使用场景:
      1. 接口调试页面执行单次请求 → 保存一条记录
      2. 测试用例执行时,每个 step 保存一条记录
      3. ApiDebugAgent 基于此记录做失败原因分析
    """
    __tablename__ = "api_execution_record"

    # ===== 关联 =====
    api_id = Column(
        Integer, nullable=True, index=True,
        comment="关联 ApiEndpoint ID(调试场景可为空)",
    )
    case_id = Column(
        Integer, nullable=True, index=True,
        comment="关联 ApiCase ID(测试执行场景)",
    )
    execution_id = Column(
        Integer, nullable=True, index=True,
        comment="关联 ExecutionRecord ID(批次执行场景)",
    )

    # ===== 请求信息 =====
    method = Column(
        String(10), nullable=False,
        comment="HTTP 方法: GET/POST/PUT/DELETE/PATCH",
    )
    url = Column(
        String(2048), nullable=False,
        comment="请求 URL(完整地址含 query)",
    )
    headers_json = Column(
        MEDIUMTEXT, nullable=True,
        comment="请求头 JSON",
    )
    params_json = Column(
        MEDIUMTEXT, nullable=True,
        comment="Query 参数 JSON",
    )
    body_json = Column(
        MEDIUMTEXT, nullable=True,
        comment="请求体 JSON",
    )
    auth_json = Column(
        Text, nullable=True,
        comment="认证信息 JSON",
    )

    # ===== 响应信息 =====
    status_code = Column(
        Integer, nullable=True, index=True,
        comment="HTTP 状态码",
    )
    response_headers_json = Column(
        MEDIUMTEXT, nullable=True,
        comment="响应头 JSON",
    )
    response_body = Column(
        MEDIUMTEXT, nullable=True,
        comment="响应体(原样保存,JSON 字符串或文本)",
    )
    response_size = Column(
        Integer, nullable=True,
        comment="响应体大小(字节)",
    )

    # ===== 执行结果 =====
    status = Column(
        SAEnum(ExecutionStatus, length=20, native_enum=False),
        nullable=False, default=ExecutionStatus.PENDING,
        comment="执行状态: success/failed/error/timeout/pending",
    )
    duration = Column(
        Float, nullable=False, default=0.0,
        comment="执行耗时(毫秒)",
    )
    error = Column(
        Text, nullable=True,
        comment="错误信息(异常堆栈/超时说明)",
    )

    # ===== AI 分析结果 =====
    analysis_status = Column(
        SAEnum(AnalysisStatus, length=20, native_enum=False),
        nullable=False, default=AnalysisStatus.NONE,
        comment="AI 分析状态: none/analyzing/done/failed",
    )
    analysis_result = Column(
        MEDIUMTEXT, nullable=True,
        comment="AI 分析结果 JSON: {problem_cause, solution, fix_suggestion, ...}",
    )
    analyzed_at = Column(
        String(30), nullable=True,
        comment="AI 分析完成时间",
    )

    # ===== 环境信息 =====
    env = Column(
        String(20), nullable=True, default="test",
        comment="执行环境: test/staging/prod",
    )
    trigger_source = Column(
        String(30), nullable=False, default="debug",
        comment="触发来源: debug(调试)/case(用例)/batch(批次)/api",
    )
    client_ip = Column(
        String(50), nullable=True,
        comment="客户端 IP",
    )

    # ===== 软删除 =====
    is_deleted = Column(
        Boolean, nullable=False, default=False,
        comment="是否删除",
    )

    __table_args__ = (
        Index("idx_api_exec_user_created", "user_id", "created_at"),
        Index("idx_api_exec_status_code", "status_code", "status"),
        Index("idx_api_exec_case_status", "case_id", "status"),
    )

    def to_dict(self) -> dict:
        """转换为字典(用于 API 响应)"""
        import json as _json
        def _safe_load(s):
            if not s:
                return None
            try:
                return _json.loads(s)
            except Exception:
                return s

        return {
            "id": self.id,
            "api_id": self.api_id,
            "case_id": self.case_id,
            "execution_id": self.execution_id,
            "method": self.method,
            "url": self.url,
            "headers": _safe_load(self.headers_json),
            "params": _safe_load(self.params_json),
            "body": _safe_load(self.body_json),
            "auth": _safe_load(self.auth_json),
            "status_code": self.status_code,
            "response_headers": _safe_load(self.response_headers_json),
            "response_body": _safe_load(self.response_body) if self.response_body else None,
            "response_size": self.response_size,
            "status": self.status.value if hasattr(self.status, "value") else self.status,
            "duration": self.duration,
            "error": self.error,
            "analysis_status": self.analysis_status.value if hasattr(self.analysis_status, "value") else self.analysis_status,
            "analysis_result": _safe_load(self.analysis_result),
            "analyzed_at": self.analyzed_at,
            "env": self.env,
            "trigger_source": self.trigger_source,
            "client_ip": self.client_ip,
            "user_id": self.user_id,
            "created_at": str(self.created_at) if self.created_at else None,
            "updated_at": str(self.updated_at) if self.updated_at else None,
        }
