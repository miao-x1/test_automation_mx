"""项目效能测评。与旧 Locust/JMeter performance_task 分离。"""
from sqlalchemy import Column, String, Integer, Float, Text, DateTime, ForeignKey, Index
from app.models.base import BaseModel


class PerformanceAssessment(BaseModel):
    __tablename__ = "performance_assessment"

    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    creator_id = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String(200), nullable=False)
    target_url = Column(String(1024), nullable=False)
    environment_id = Column(Integer, nullable=True)
    rounds = Column(Integer, nullable=False, default=1)
    scenario = Column(String(50), nullable=False, default="page")
    status = Column(String(20), nullable=False, default="CREATED", index=True)
    score_total = Column(Integer, nullable=True)
    score_page = Column(Integer, nullable=True)
    score_resource = Column(Integer, nullable=True)
    score_network = Column(Integer, nullable=True)
    score_job = Column(Integer, nullable=True)
    score_regression = Column(Integer, nullable=True)
    report_json = Column(Text, nullable=True)
    issues_json = Column(Text, nullable=True)
    advice_json = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)


class PerformanceAssessmentMetric(BaseModel):
    __tablename__ = "performance_assessment_metric"

    assessment_id = Column(Integer, ForeignKey("performance_assessment.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(80), nullable=False)
    value = Column(Float, nullable=True)
    unit = Column(String(20), nullable=True)
    supported = Column(Integer, nullable=False, default=1)


Index("idx_assessment_project", PerformanceAssessment.project_id, PerformanceAssessment.created_at)
