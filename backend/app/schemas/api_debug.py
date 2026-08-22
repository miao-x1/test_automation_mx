"""
API 执行记录 + AI 调试 Schema

定义:
  - ExecuteRequest:        执行接口请求
  - ExecutionRecordResponse: 执行记录响应
  - AnalyzeRequest:        AI 分析请求
  - AnalysisResult:        分析结果
"""
from typing import Any, Dict, List, Optional, Union
from datetime import datetime
from pydantic import BaseModel, Field


# ============================================================
# 执行接口
# ============================================================

class ExecuteRequest(BaseModel):
    """执行接口请求"""
    method: str = Field(..., description="HTTP 方法: GET/POST/PUT/DELETE/PATCH")
    url: str = Field(..., description="请求 URL")
    headers: Optional[Dict[str, str]] = Field(default=None, description="请求头")
    params: Optional[Dict[str, Any]] = Field(default=None, description="Query 参数")
    body: Optional[Any] = Field(default=None, description="请求体")
    auth: Optional[Dict[str, Any]] = Field(default=None, description="认证信息")
    timeout: int = Field(default=30000, ge=1000, le=120000, description="超时(ms)")
    api_id: Optional[int] = Field(default=None, description="关联接口 ID")
    case_id: Optional[int] = Field(default=None, description="关联用例 ID")
    env: str = Field(default="test", description="执行环境")
    auto_analyze: bool = Field(default=False, description="执行失败后自动调用 AI 分析")


class ExecuteResponse(BaseModel):
    """执行接口响应"""
    status: str = Field(..., description="success/failed/error/timeout")
    record_id: Optional[int] = Field(None, description="执行记录 ID")
    request: Dict[str, Any]
    response: Optional[Dict[str, Any]] = None
    status_code: Optional[int] = None
    duration: float = Field(0, description="耗时(ms)")
    error: Optional[str] = None
    analysis: Optional[Dict[str, Any]] = Field(None, description="AI 分析结果(仅 auto_analyze=True 且失败时)")


# ============================================================
# 执行记录
# ============================================================

class ExecutionRecordResponse(BaseModel):
    """执行记录响应"""
    id: int
    api_id: Optional[int] = None
    case_id: Optional[int] = None
    execution_id: Optional[int] = None
    method: str
    url: str
    headers: Optional[Any] = None
    params: Optional[Any] = None
    body: Optional[Any] = None
    auth: Optional[Any] = None
    status_code: Optional[int] = None
    response_headers: Optional[Any] = None
    response_body: Optional[Any] = None
    response_size: Optional[int] = None
    status: str
    duration: float
    error: Optional[str] = None
    analysis_status: str = "none"
    analysis_result: Optional[Any] = None
    analyzed_at: Optional[str] = None
    env: Optional[str] = None
    trigger_source: Optional[str] = None
    client_ip: Optional[str] = None
    created_at: Optional[str] = None


class ExecutionRecordListResponse(BaseModel):
    """执行记录列表"""
    total: int
    page: int
    page_size: int
    items: List[ExecutionRecordResponse]


# ============================================================
# AI 分析
# ============================================================

class AnalyzeRequest(BaseModel):
    """AI 分析请求"""
    record_id: Optional[int] = Field(None, description="执行记录 ID(二选一)")
    force: bool = Field(default=False, description="强制分析(即使请求成功)")
    request: Optional[Dict[str, Any]] = Field(None, description="直接传入请求(二选一)")
    response: Optional[Dict[str, Any]] = Field(None, description="直接传入响应")
    error: Optional[str] = Field(None, description="直接传入错误信息")
    status: Optional[str] = Field(None, description="执行状态")


class AnalysisResult(BaseModel):
    """AI 分析结果"""
    status: str
    record_id: Optional[int] = None
    problem_cause: str
    solution: str
    fix_suggestion: str
    confidence: float
    category: Optional[str] = None
    source: str = Field(..., description="llm / rule_engine")
    elapsed_ms: int = 0


class HealthResponse(BaseModel):
    """健康检查"""
    status: str
    agent: str
    capabilities: List[str]
    patterns_count: int
    llm_available: bool
    supported_actions: List[str]
