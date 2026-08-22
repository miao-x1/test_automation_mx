"""
性能测试模块数据模型

三张表:
  - PerformanceTask:   性能测试任务 (名称、目标接口、配置、状态)
  - PerformanceResult: 执行结果汇总 (TPS、RT、错误率)
  - PerformanceMetric: 实时指标 (按时间切片的 TPS/RT/CPU/Memory)
"""
from datetime import datetime
from enum import Enum
from sqlalchemy import Column, String, Text, Integer, Float, Boolean, Index
from app.models.base import OwnedModel


class PerformanceTestType(str, Enum):
    API = "api"
    WEB = "web"


class TaskStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    SCRIPTING = "scripting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class ResultStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class PerformanceTask(OwnedModel):
    """性能测试任务"""
    __tablename__ = "performance_task"

    name = Column(String(200), nullable=False, comment="任务名称")
    test_type = Column(String(20), nullable=False, default="api", comment="测试类型: api/web")
    target_url = Column(String(500), nullable=False, comment="目标接口 URL")
    method = Column(String(10), nullable=False, default="GET", comment="HTTP 方法")
    headers_json = Column(Text, nullable=True, comment="请求头 JSON")
    body_json = Column(Text, nullable=True, comment="请求体 JSON")
    business_volume = Column(Integer, nullable=True, comment="预期日业务量 (次/天)")
    concurrency = Column(Integer, nullable=False, default=10, comment="并发用户数")
    duration_seconds = Column(Integer, nullable=False, default=60, comment="持续时长 (秒)")
    tps_target = Column(Float, nullable=True, comment="目标 TPS")
    ramp_up = Column(Integer, nullable=False, default=10, comment="预热时间 (秒)")
    script_type = Column(String(20), nullable=False, default="locust", comment="脚本类型: locust/jmeter")
    script_content = Column(Text, nullable=True, comment="生成的脚本内容")
    jmeter_config = Column(Text, nullable=True, comment="JMeter XML 配置")
    plan_json = Column(Text, nullable=True, comment="LLM 生成的测试方案 JSON")
    status = Column(String(20), nullable=False, default="pending", comment="任务状态: pending/planning/scripting/running/completed/failed/stopped")
    error_message = Column(Text, nullable=True, comment="错误信息")
    is_deleted = Column(Boolean, nullable=False, default=False, comment="软删除")

    __table_args__ = (
        Index("ix_perf_task_user_status", "user_id", "status"),
        Index("ix_perf_task_type", "test_type"),
        {"comment": "性能测试任务表"},
    )

    def __repr__(self):
        return f"<PerformanceTask(id={self.id}, name={self.name}, status={self.status})>"


class PerformanceResult(OwnedModel):
    """性能测试执行结果汇总"""
    __tablename__ = "performance_result"

    task_id = Column(Integer, nullable=False, index=True, comment="关联任务 ID")
    total_requests = Column(Integer, nullable=False, default=0, comment="总请求数")
    total_errors = Column(Integer, nullable=False, default=0, comment="总错误数")
    error_rate = Column(Float, nullable=False, default=0.0, comment="错误率 (%)")
    avg_tps = Column(Float, nullable=False, default=0.0, comment="平均 TPS")
    peak_tps = Column(Float, nullable=False, default=0.0, comment="峰值 TPS")
    avg_rt = Column(Float, nullable=False, default=0.0, comment="平均响应时间 (ms)")
    p50_rt = Column(Float, nullable=True, comment="P50 响应时间 (ms)")
    p90_rt = Column(Float, nullable=True, comment="P90 响应时间 (ms)")
    p95_rt = Column(Float, nullable=True, comment="P95 响应时间 (ms)")
    p99_rt = Column(Float, nullable=True, comment="P99 响应时间 (ms)")
    concurrency = Column(Integer, nullable=False, default=0, comment="实际并发数")
    duration_seconds = Column(Integer, nullable=False, default=0, comment="实际执行时长 (秒)")
    analysis_json = Column(Text, nullable=True, comment="LLM 分析结果 JSON")
    status = Column(String(20), nullable=False, default="running", comment="结果状态: running/completed/failed/stopped")

    def __repr__(self):
        return f"<PerformanceResult(id={self.id}, task_id={self.task_id}, avg_tps={self.avg_tps})>"


class PerformanceMetric(OwnedModel):
    """性能测试实时指标 — 按时间切片记录"""
    __tablename__ = "performance_metric"

    result_id = Column(Integer, nullable=False, index=True, comment="关联结果 ID")
    timestamp = Column(Float, nullable=False, comment="时间戳 (epoch)")
    elapsed = Column(Float, nullable=False, comment="已执行时间 (秒)")
    tps = Column(Float, nullable=False, default=0.0, comment="当前 TPS")
    avg_rt = Column(Float, nullable=False, default=0.0, comment="当前平均 RT (ms)")
    concurrent_users = Column(Integer, nullable=False, default=0, comment="当前并发用户数")
    error_count = Column(Integer, nullable=False, default=0, comment="累计错误数")
    cpu_percent = Column(Float, nullable=True, comment="CPU 使用率 (%)")
    memory_mb = Column(Float, nullable=True, comment="内存使用 (MB)")

    def __repr__(self):
        return f"<PerformanceMetric(id={self.id}, result_id={self.result_id}, tps={self.tps})>"
