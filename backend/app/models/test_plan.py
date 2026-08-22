"""
测试计划数据模型

TestPlan:测试计划(包含多个 TestSuite,定义执行策略)
PlanSuite:Plan 与 Suite 的关联(带执行顺序)
PlanExecution:计划执行记录(每次执行 Plan 生成一条)

层次:
    TestPlan (1) → (N) PlanSuite → TestSuite
    TestPlan (1) → (N) PlanExecution (每次执行一条)
"""
from sqlalchemy import Column, String, Integer, Float, Text, Boolean, ForeignKey, Index
from sqlalchemy.orm import relationship

from app.models.base import OwnedModel


class TestPlan(OwnedModel):
    """
    测试计划

    一个测试计划包含多个 TestSuite,按指定策略(串行/并行)执行。
    支持失败停止(fail_stop)和失败继续(fail_continue)。

    示例:
        TestPlan(name="登录回归测试")
            → Suite1: 登录功能用例集
            → Suite2: 权限验证用例集
            → Suite3: 数据隔离用例集
    """
    __tablename__ = "test_plan"

    name = Column(String(200), nullable=False, comment="计划名称")
    description = Column(Text, nullable=True, comment="计划描述")

    # 执行策略
    strategy = Column(
        String(20),
        default="serial",
        nullable=False,
        comment="执行策略: serial(串行) / parallel(并行)",
    )
    fail_policy = Column(
        String(20),
        default="continue",
        nullable=False,
        comment="失败策略: stop(失败停止) / continue(失败继续)",
    )

    # 环境配置(所有 Suite 共享,可被 Suite 级配置覆盖)
    env = Column(String(20), default="test", comment="执行环境: dev/test/staging/prod")
    base_url = Column(String(500), nullable=True, comment="基础 URL")
    headers_json = Column(Text, nullable=True, comment="全局请求头(JSON)")
    variables_json = Column(Text, nullable=True, comment="全局变量(JSON)")

    # 并发控制(parallel 策略下生效)
    max_concurrency = Column(Integer, default=4, comment="最大并发数(parallel 模式)")

    # 重试配置
    retry_count = Column(Integer, default=0, comment="失败重试次数")
    retry_delay = Column(Integer, default=5, comment="重试间隔(秒)")

    # 超时(整个计划的最大执行时间)
    timeout_seconds = Column(Integer, default=3600, comment="计划超时(秒)")

    # 调度配置(可选,支持 cron 定时执行)
    schedule_cron = Column(String(64), nullable=True, comment="定时调度表达式(cron)")
    schedule_enabled = Column(Boolean, default=False, comment="是否启用定时调度")

    # 状态
    status = Column(
        String(20),
        default="draft",
        nullable=False,
        index=True,
        comment="状态: draft/ready/running/completed/failed/archived",
    )

    # 标签
    tags = Column(String(500), nullable=True, comment="标签(逗号分隔)")

    # 统计(冗余字段,便于列表展示)
    suite_count = Column(Integer, default=0, comment="包含的 Suite 数量")
    last_run_at = Column(String(30), nullable=True, comment="最近执行时间")
    last_run_status = Column(String(20), nullable=True, comment="最近执行状态")
    run_count = Column(Integer, default=0, comment="累计执行次数")

    # 软删除
    is_deleted = Column(Boolean, default=False, index=True, comment="是否删除")

    # 关联
    plan_suites = relationship(
        "PlanSuite",
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="PlanSuite.execution_order",
    )
    executions = relationship(
        "PlanExecution",
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="PlanExecution.created_at.desc()",
    )

    def to_dict(self, include_suites: bool = False) -> dict:
        result = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "strategy": self.strategy,
            "fail_policy": self.fail_policy,
            "env": self.env,
            "base_url": self.base_url,
            "max_concurrency": self.max_concurrency,
            "retry_count": self.retry_count,
            "retry_delay": self.retry_delay,
            "timeout_seconds": self.timeout_seconds,
            "schedule_cron": self.schedule_cron,
            "schedule_enabled": self.schedule_enabled,
            "status": self.status,
            "tags": self.tags,
            "suite_count": self.suite_count,
            "last_run_at": self.last_run_at,
            "last_run_status": self.last_run_status,
            "run_count": self.run_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_suites:
            result["suites"] = [ps.to_dict() for ps in self.plan_suites]
        return result

    def __repr__(self):
        return f"<TestPlan(id={self.id}, name={self.name}, strategy={self.strategy})>"


class PlanSuite(OwnedModel):
    """
    计划-套件关联表

    定义 TestPlan 中 TestSuite 的执行顺序和覆盖配置。
    """
    __tablename__ = "plan_suite"

    plan_id = Column(
        Integer,
        ForeignKey("test_plan.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属计划 ID",
    )
    suite_id = Column(
        Integer,
        ForeignKey("test_suite.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联的 TestSuite ID",
    )
    execution_order = Column(
        Integer,
        default=0,
        nullable=False,
        comment="执行顺序(serial 模式下生效,0=最先)",
    )

    # Suite 级配置覆盖(为空则继承 Plan 级配置)
    env_override = Column(String(20), nullable=True, comment="环境覆盖")
    base_url_override = Column(String(500), nullable=True, comment="基础 URL 覆盖")
    variables_override = Column(Text, nullable=True, comment="变量覆盖(JSON)")

    # 该 Suite 在 Plan 中的角色
    role = Column(
        String(20),
        default="main",
        comment="角色: main(主)/setup(前置)/teardown(后置)",
    )
    enabled = Column(Boolean, default=True, comment="是否启用该 Suite")

    # 关联
    plan = relationship("TestPlan", back_populates="plan_suites")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "plan_id": self.plan_id,
            "suite_id": self.suite_id,
            "execution_order": self.execution_order,
            "env_override": self.env_override,
            "base_url_override": self.base_url_override,
            "role": self.role,
            "enabled": self.enabled,
        }

    def __repr__(self):
        return f"<PlanSuite(plan_id={self.plan_id}, suite_id={self.suite_id}, order={self.execution_order})>"


class PlanExecution(OwnedModel):
    """
    计划执行记录

    每次执行 TestPlan 生成一条记录,追踪整个计划的执行状态。
    包含每个 Suite 的执行明细(通过 suite_executions_json)。
    """
    __tablename__ = "plan_execution"

    plan_id = Column(
        Integer,
        ForeignKey("test_plan.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联的 TestPlan ID",
    )
    plan_name = Column(String(200), nullable=True, comment="计划名称快照")

    # 执行标识
    execution_id = Column(
        String(64),
        unique=True,
        index=True,
        comment="执行唯一标识(plan_exec_xxx)",
    )
    runtime_task_id = Column(
        String(64),
        nullable=True,
        index=True,
        comment="Runtime 任务 ID(关联 runtime_task)",
    )

    # 执行配置快照
    strategy = Column(String(20), nullable=False, comment="执行策略快照")
    fail_policy = Column(String(20), nullable=False, comment="失败策略快照")
    env = Column(String(20), nullable=True, comment="执行环境快照")

    # 状态
    status = Column(
        String(20),
        default="pending",
        nullable=False,
        index=True,
        comment="状态: pending/running/success/failed/cancelled/timeout",
    )

    # 时间
    start_time = Column(String(30), nullable=True, comment="开始时间")
    end_time = Column(String(30), nullable=True, comment="结束时间")
    duration = Column(Float, default=0.0, comment="耗时(秒)")

    # 统计
    total_suites = Column(Integer, default=0, comment="Suite 总数")
    executed_suites = Column(Integer, default=0, comment="已执行 Suite 数")
    success_suites = Column(Integer, default=0, comment="成功 Suite 数")
    failed_suites = Column(Integer, default=0, comment="失败 Suite 数")
    skipped_suites = Column(Integer, default=0, comment="跳过 Suite 数")

    # 用例级统计(所有 Suite 汇总)
    total_cases = Column(Integer, default=0, comment="用例总数")
    passed_cases = Column(Integer, default=0, comment="通过用例数")
    failed_cases = Column(Integer, default=0, comment="失败用例数")

    # 每个 Suite 的执行明细(JSON 数组)
    suite_executions_json = Column(
        Text,
        nullable=True,
        comment="Suite 执行明细(JSON): [{suite_id, suite_name, execution_id, status, passed, failed, duration}]",
    )

    # 错误与日志
    error_message = Column(Text, nullable=True, comment="错误信息")
    trigger_source = Column(
        String(30),
        default="manual",
        comment="触发来源: manual/schedule/api",
    )

    # 报告路径
    report_path = Column(String(512), nullable=True, comment="计划级报告路径")

    # 关联
    plan = relationship("TestPlan", back_populates="executions")

    def to_dict(self, include_details: bool = False) -> dict:
        import json as _json
        result = {
            "id": self.id,
            "plan_id": self.plan_id,
            "plan_name": self.plan_name,
            "execution_id": self.execution_id,
            "runtime_task_id": self.runtime_task_id,
            "strategy": self.strategy,
            "fail_policy": self.fail_policy,
            "env": self.env,
            "status": self.status,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "total_suites": self.total_suites,
            "executed_suites": self.executed_suites,
            "success_suites": self.success_suites,
            "failed_suites": self.failed_suites,
            "skipped_suites": self.skipped_suites,
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "failed_cases": self.failed_cases,
            "error_message": (self.error_message or "")[:200] if self.error_message else None,
            "trigger_source": self.trigger_source,
            "report_path": self.report_path,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_details and self.suite_executions_json:
            try:
                result["suite_executions"] = _json.loads(self.suite_executions_json)
            except Exception:
                result["suite_executions"] = []
        return result

    def __repr__(self):
        return f"<PlanExecution(id={self.id}, plan_id={self.plan_id}, status={self.status})>"


# 索引
Index("idx_plan_suite_plan_order", PlanSuite.plan_id, PlanSuite.execution_order)
Index("idx_plan_execution_plan_status", PlanExecution.plan_id, PlanExecution.status)
Index("idx_plan_execution_status_time", PlanExecution.status, PlanExecution.created_at)
