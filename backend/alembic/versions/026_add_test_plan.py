"""add test plan tables

Revision ID: 026
Revises: 025
Create Date: 2026-07-21

新增测试编排系统三张表:
- test_plan: 测试计划(包含多个 TestSuite,定义串行/并行策略)
- plan_suite: 计划-套件关联(带执行顺序)
- plan_execution: 计划执行记录(每次执行 Plan 生成一条)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ===== test_plan =====
    op.create_table(
        "test_plan",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False, comment="计划名称"),
        sa.Column("description", sa.Text(), nullable=True, comment="计划描述"),
        sa.Column("strategy", sa.String(length=20), server_default="serial", nullable=False, comment="执行策略"),
        sa.Column("fail_policy", sa.String(length=20), server_default="continue", nullable=False, comment="失败策略"),
        sa.Column("env", sa.String(length=20), server_default="test", comment="执行环境"),
        sa.Column("base_url", sa.String(length=500), nullable=True, comment="基础 URL"),
        sa.Column("headers_json", sa.Text(), nullable=True, comment="全局请求头(JSON)"),
        sa.Column("variables_json", sa.Text(), nullable=True, comment="全局变量(JSON)"),
        sa.Column("max_concurrency", sa.Integer(), server_default="4", comment="最大并发数"),
        sa.Column("retry_count", sa.Integer(), server_default="0", comment="失败重试次数"),
        sa.Column("retry_delay", sa.Integer(), server_default="5", comment="重试间隔(秒)"),
        sa.Column("timeout_seconds", sa.Integer(), server_default="3600", comment="计划超时(秒)"),
        sa.Column("schedule_cron", sa.String(length=64), nullable=True, comment="定时调度表达式"),
        sa.Column("schedule_enabled", sa.Boolean(), server_default="0", comment="是否启用定时调度"),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False, comment="状态"),
        sa.Column("tags", sa.String(length=500), nullable=True, comment="标签"),
        sa.Column("suite_count", sa.Integer(), server_default="0", comment="Suite 数量"),
        sa.Column("last_run_at", sa.String(length=30), nullable=True, comment="最近执行时间"),
        sa.Column("last_run_status", sa.String(length=20), nullable=True, comment="最近执行状态"),
        sa.Column("run_count", sa.Integer(), server_default="0", comment="累计执行次数"),
        sa.Column("is_deleted", sa.Boolean(), server_default="0", comment="是否删除"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_test_plan_status", "test_plan", ["status"])
    op.create_index("ix_test_plan_is_deleted", "test_plan", ["is_deleted"])
    op.create_index("ix_test_plan_user_id", "test_plan", ["user_id"])

    # ===== plan_suite =====
    op.create_table(
        "plan_suite",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("plan_id", sa.Integer(), nullable=False, comment="所属计划 ID"),
        sa.Column("suite_id", sa.Integer(), nullable=False, comment="关联 TestSuite ID"),
        sa.Column("execution_order", sa.Integer(), server_default="0", nullable=False, comment="执行顺序"),
        sa.Column("env_override", sa.String(length=20), nullable=True, comment="环境覆盖"),
        sa.Column("base_url_override", sa.String(length=500), nullable=True, comment="URL 覆盖"),
        sa.Column("variables_override", sa.Text(), nullable=True, comment="变量覆盖(JSON)"),
        sa.Column("role", sa.String(length=20), server_default="main", comment="角色"),
        sa.Column("enabled", sa.Boolean(), server_default="1", comment="是否启用"),
        sa.ForeignKeyConstraint(["plan_id"], ["test_plan.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_plan_suite_plan_id", "plan_suite", ["plan_id"])
    op.create_index("ix_plan_suite_suite_id", "plan_suite", ["suite_id"])
    op.create_index("idx_plan_suite_plan_order", "plan_suite", ["plan_id", "execution_order"])

    # ===== plan_execution =====
    op.create_table(
        "plan_execution",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("plan_id", sa.Integer(), nullable=False, comment="关联 TestPlan ID"),
        sa.Column("plan_name", sa.String(length=200), nullable=True, comment="计划名称快照"),
        sa.Column("execution_id", sa.String(length=64), nullable=False, comment="执行唯一标识"),
        sa.Column("runtime_task_id", sa.String(length=64), nullable=True, comment="Runtime 任务 ID"),
        sa.Column("strategy", sa.String(length=20), nullable=False, comment="执行策略快照"),
        sa.Column("fail_policy", sa.String(length=20), nullable=False, comment="失败策略快照"),
        sa.Column("env", sa.String(length=20), nullable=True, comment="执行环境快照"),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False, comment="状态"),
        sa.Column("start_time", sa.String(length=30), nullable=True, comment="开始时间"),
        sa.Column("end_time", sa.String(length=30), nullable=True, comment="结束时间"),
        sa.Column("duration", sa.Float(), server_default="0", comment="耗时(秒)"),
        sa.Column("total_suites", sa.Integer(), server_default="0", comment="Suite 总数"),
        sa.Column("executed_suites", sa.Integer(), server_default="0", comment="已执行 Suite 数"),
        sa.Column("success_suites", sa.Integer(), server_default="0", comment="成功 Suite 数"),
        sa.Column("failed_suites", sa.Integer(), server_default="0", comment="失败 Suite 数"),
        sa.Column("skipped_suites", sa.Integer(), server_default="0", comment="跳过 Suite 数"),
        sa.Column("total_cases", sa.Integer(), server_default="0", comment="用例总数"),
        sa.Column("passed_cases", sa.Integer(), server_default="0", comment="通过用例数"),
        sa.Column("failed_cases", sa.Integer(), server_default="0", comment="失败用例数"),
        sa.Column("suite_executions_json", sa.Text(), nullable=True, comment="Suite 执行明细(JSON)"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="错误信息"),
        sa.Column("trigger_source", sa.String(length=30), server_default="manual", comment="触发来源"),
        sa.Column("report_path", sa.String(length=512), nullable=True, comment="报告路径"),
        sa.ForeignKeyConstraint(["plan_id"], ["test_plan.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_id"),
    )
    op.create_index("ix_plan_execution_plan_id", "plan_execution", ["plan_id"])
    op.create_index("ix_plan_execution_execution_id", "plan_execution", ["execution_id"])
    op.create_index("ix_plan_execution_runtime_task_id", "plan_execution", ["runtime_task_id"])
    op.create_index("ix_plan_execution_status", "plan_execution", ["status"])
    op.create_index("idx_plan_execution_plan_status", "plan_execution", ["plan_id", "status"])
    op.create_index("idx_plan_execution_status_time", "plan_execution", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_plan_execution_status_time", table_name="plan_execution")
    op.drop_index("idx_plan_execution_plan_status", table_name="plan_execution")
    op.drop_index("ix_plan_execution_status", table_name="plan_execution")
    op.drop_index("ix_plan_execution_runtime_task_id", table_name="plan_execution")
    op.drop_index("ix_plan_execution_execution_id", table_name="plan_execution")
    op.drop_index("ix_plan_execution_plan_id", table_name="plan_execution")
    op.drop_table("plan_execution")

    op.drop_index("idx_plan_suite_plan_order", table_name="plan_suite")
    op.drop_index("ix_plan_suite_suite_id", table_name="plan_suite")
    op.drop_index("ix_plan_suite_plan_id", table_name="plan_suite")
    op.drop_table("plan_suite")

    op.drop_index("ix_test_plan_user_id", table_name="test_plan")
    op.drop_index("ix_test_plan_is_deleted", table_name="test_plan")
    op.drop_index("ix_test_plan_status", table_name="test_plan")
    op.drop_table("test_plan")
