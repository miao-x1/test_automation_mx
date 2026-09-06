"""Jenkins 风格的项目测试任务与回归管线。不替代现有分析/执行引擎。"""
import enum
from sqlalchemy import Column, String, Integer, Text, ForeignKey, Index
from app.models.base import BaseModel


class JobStatus(str, enum.Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TestJob(BaseModel):
    __tablename__ = "test_job"

    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    creator_id = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String(200), nullable=False)
    job_type = Column(String(30), nullable=False, default="web")
    requirement_id = Column(Integer, nullable=True, index=True)
    task_id = Column(Integer, nullable=True, index=True)
    status = Column(String(20), nullable=False, default=JobStatus.CREATED, index=True)
    result = Column(Text, nullable=True)
    last_execution_id = Column(Integer, nullable=True)


class RegressionPipeline(BaseModel):
    __tablename__ = "regression_pipeline"

    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(200), nullable=False)
    description = Column(String(512), nullable=True)


class RegressionPipelineItem(BaseModel):
    __tablename__ = "regression_pipeline_item"

    pipeline_id = Column(Integer, ForeignKey("regression_pipeline.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("test_job.id", ondelete="CASCADE"), nullable=False, index=True)
    sort_order = Column(Integer, nullable=False, default=0)


class RegressionRun(BaseModel):
    __tablename__ = "regression_run"

    pipeline_id = Column(Integer, ForeignKey("regression_pipeline.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(20), nullable=False, default=JobStatus.CREATED, index=True)
    passed_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    result_json = Column(Text, nullable=True)


Index("idx_test_job_project_status", TestJob.project_id, TestJob.status)
Index("idx_regression_run_project", RegressionRun.project_id, RegressionRun.created_at)
