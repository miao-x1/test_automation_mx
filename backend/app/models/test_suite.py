"""
测试套件模型

用于编排多个接口测试用例，支持：
- 批量执行（回归/冒烟）
- 用例排序
- 环境配置覆盖
"""
import enum
from sqlalchemy import Column, String, Integer, Text, Boolean, ForeignKey, Index
from sqlalchemy.orm import relationship
from app.models.base import OwnedModel


class SuiteType(str, enum.Enum):
    """套件类型"""
    REGRESSION = "regression"    # 回归测试
    SMOKE = "smoke"              # 冒烟测试
    CUSTOM = "custom"            # 自定义


class SuiteStatus(str, enum.Enum):
    """套件状态"""
    DRAFT = "draft"       # 草稿
    READY = "ready"       # 就绪
    RUNNING = "running"   # 执行中
    COMPLETED = "completed"  # 已完成


class TestSuite(OwnedModel):
    """
    测试套件

    编排多个 ApiCase，支持批量执行
    """
    __tablename__ = "test_suite"

    name = Column(
        String(200), nullable=False, comment="套件名称"
    )
    description = Column(
        Text, nullable=True, comment="套件描述"
    )
    suite_type = Column(
        String(20), nullable=False, default=SuiteType.CUSTOM,
        comment="套件类型: regression/smoke/custom"
    )
    status = Column(
        String(20), nullable=False, default=SuiteStatus.DRAFT,
        comment="状态: draft/ready/running/completed"
    )

    # ===== 用例编排 =====
    case_ids = Column(
        Text, nullable=True,
        comment="用例ID列表（JSON数组，有序）: [1, 5, 3, 12]"
    )

    # ===== 环境配置 =====
    env = Column(
        String(20), nullable=False, default="test",
        comment="执行环境: test/staging/production"
    )
    base_url = Column(
        String(500), nullable=True,
        comment="Base URL（覆盖全局配置）"
    )
    headers = Column(
        Text, nullable=True,
        comment="请求头（JSON）: {Authorization: 'Bearer xxx'}"
    )
    variables = Column(
        Text, nullable=True,
        comment="变量池（JSON）: {token: 'xxx'}"
    )

    # ===== 执行配置 =====
    concurrency = Column(
        Integer, nullable=False, default=1,
        comment="并发数"
    )
    fail_strategy = Column(
        String(20), nullable=False, default="continue",
        comment="失败策略: continue（继续）/ stop（停止）"
    )
    retry_count = Column(
        Integer, nullable=False, default=0,
        comment="失败重试次数"
    )

    # ===== 统计 =====
    last_run_at = Column(
        String(30), nullable=True, comment="最近执行时间"
    )
    run_count = Column(
        Integer, nullable=False, default=0, comment="执行次数"
    )
    is_deleted = Column(
        Boolean, nullable=False, default=False, comment="是否删除"
    )

    # 关联
    executions = relationship("SuiteExecution", back_populates="suite", cascade="all, delete-orphan")


class SuiteExecution(OwnedModel):
    """套件执行记录"""
    __tablename__ = "suite_execution"

    suite_id = Column(
        Integer, ForeignKey("test_suite.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="套件ID"
    )
    execution_id = Column(
        Integer, ForeignKey("execution_record.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="关联的执行记录ID"
    )
    status = Column(
        String(20), nullable=False, default="waiting",
        comment="执行状态: waiting/running/success/failed"
    )
    total = Column(
        Integer, nullable=False, default=0, comment="总用例数"
    )
    passed = Column(
        Integer, nullable=False, default=0, comment="通过数"
    )
    failed = Column(
        Integer, nullable=False, default=0, comment="失败数"
    )
    duration = Column(
        Integer, nullable=True, comment="执行耗时(ms)"
    )
    result_detail = Column(
        Text, nullable=True, comment="执行结果详情（JSON）"
    )

    # 关联
    suite = relationship("TestSuite", back_populates="executions")


Index('idx_suite_execution_suite', SuiteExecution.suite_id, SuiteExecution.status)
Index('idx_test_suite_user', TestSuite.user_id, TestSuite.is_deleted)
