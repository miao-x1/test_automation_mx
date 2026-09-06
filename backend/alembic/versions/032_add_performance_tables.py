"""add performance test tables

Revision ID: 032
Revises: 031
Create Date: 2026-07-22

性能测试模块 — 三张核心表:
  1. performance_task   - 性能测试任务 (名称、目标接口、配置、状态)
  2. performance_result - 执行结果 (TPS、RT、错误率、并发数等汇总)
  3. performance_metric - 实时指标 (按时间切片的 TPS/RT/CPU/Memory)
"""
from alembic import op
import sqlalchemy as sa


revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ================================================================
    # 1. performance_task 表
    # ================================================================
    op.create_table(
        "performance_task",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(200), nullable=False, comment="任务名称"),
        sa.Column("test_type", sa.String(20), nullable=False, server_default="api",
                  comment="测试类型: api/web"),
        sa.Column("target_url", sa.String(500), nullable=False, comment="目标接口 URL"),
        sa.Column("method", sa.String(10), nullable=False, server_default="GET",
                  comment="HTTP 方法"),
        sa.Column("headers_json", sa.Text(), nullable=True, comment="请求头 JSON"),
        sa.Column("body_json", sa.Text(), nullable=True, comment="请求体 JSON"),
        sa.Column("business_volume", sa.Integer(), nullable=True,
                  comment="预期日业务量 (次/天)"),
        sa.Column("concurrency", sa.Integer(), nullable=False, server_default="10",
                  comment="并发用户数"),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="60",
                  comment="持续时长 (秒)"),
        sa.Column("tps_target", sa.Float(), nullable=True, comment="目标 TPS"),
        sa.Column("ramp_up", sa.Integer(), nullable=False, server_default="10",
                  comment="预热时间 (秒)"),
        sa.Column("script_type", sa.String(20), nullable=False, server_default="locust",
                  comment="脚本类型: locust/jmeter"),
        sa.Column("script_content", sa.Text(), nullable=True, comment="生成的脚本内容"),
        sa.Column("jmeter_config", sa.Text(), nullable=True, comment="JMeter XML 配置"),
        sa.Column("plan_json", sa.Text(), nullable=True, comment="LLM 生成的测试方案 JSON"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending",
                  comment="状态: pending/planning/scripting/running/completed/failed"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="错误信息"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="0",
                  comment="软删除"),
        sa.PrimaryKeyConstraint("id"),
        comment="性能测试任务表",
    )
    op.create_index("ix_perf_task_user_status", "performance_task", ["user_id", "status"])
    op.create_index("ix_perf_task_type", "performance_task", ["test_type"])

    # ================================================================
    # 2. performance_result 表
    # ================================================================
    op.create_table(
        "performance_result",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=False, comment="关联任务 ID"),
        sa.Column("total_requests", sa.Integer(), nullable=False, server_default="0",
                  comment="总请求数"),
        sa.Column("total_errors", sa.Integer(), nullable=False, server_default="0",
                  comment="总错误数"),
        sa.Column("error_rate", sa.Float(), nullable=False, server_default="0.0",
                  comment="错误率 (%)"),
        sa.Column("avg_tps", sa.Float(), nullable=False, server_default="0.0",
                  comment="平均 TPS"),
        sa.Column("peak_tps", sa.Float(), nullable=False, server_default="0.0",
                  comment="峰值 TPS"),
        sa.Column("avg_rt", sa.Float(), nullable=False, server_default="0.0",
                  comment="平均响应时间 (ms)"),
        sa.Column("p50_rt", sa.Float(), nullable=True, comment="P50 响应时间 (ms)"),
        sa.Column("p90_rt", sa.Float(), nullable=True, comment="P90 响应时间 (ms)"),
        sa.Column("p95_rt", sa.Float(), nullable=True, comment="P95 响应时间 (ms)"),
        sa.Column("p99_rt", sa.Float(), nullable=True, comment="P99 响应时间 (ms)"),
        sa.Column("concurrency", sa.Integer(), nullable=False, server_default="0",
                  comment="实际并发数"),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="0",
                  comment="实际执行时长 (秒)"),
        sa.Column("analysis_json", sa.Text(), nullable=True,
                  comment="LLM 分析结果 JSON"),
        sa.Column("status", sa.String(20), nullable=False, server_default="running",
                  comment="结果状态: running/completed/failed"),
        sa.PrimaryKeyConstraint("id"),
        comment="性能测试结果汇总表",
    )
    op.create_index("ix_perf_result_task", "performance_result", ["task_id"])

    # ================================================================
    # 3. performance_metric 表 — 实时指标 (按时间切片)
    # ================================================================
    op.create_table(
        "performance_metric",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("result_id", sa.Integer(), nullable=False, comment="关联结果 ID"),
        sa.Column("timestamp", sa.Float(), nullable=False, comment="时间戳 (epoch)"),
        sa.Column("elapsed", sa.Float(), nullable=False, comment="已执行时间 (秒)"),
        sa.Column("tps", sa.Float(), nullable=False, server_default="0.0",
                  comment="当前 TPS"),
        sa.Column("avg_rt", sa.Float(), nullable=False, server_default="0.0",
                  comment="当前平均 RT (ms)"),
        sa.Column("concurrent_users", sa.Integer(), nullable=False, server_default="0",
                  comment="当前并发用户数"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0",
                  comment="累计错误数"),
        sa.Column("cpu_percent", sa.Float(), nullable=True, comment="CPU 使用率 (%)"),
        sa.Column("memory_mb", sa.Float(), nullable=True, comment="内存使用 (MB)"),
        sa.PrimaryKeyConstraint("id"),
        comment="性能测试实时指标表",
    )
    op.create_index("ix_perf_metric_result", "performance_metric", ["result_id"])


def downgrade() -> None:
    op.drop_index("ix_perf_metric_result", table_name="performance_metric")
    op.drop_table("performance_metric")
    op.drop_index("ix_perf_result_task", table_name="performance_result")
    op.drop_table("performance_result")
    op.drop_index("ix_perf_task_type", table_name="performance_task")
    op.drop_index("ix_perf_task_user_status", table_name="performance_task")
    op.drop_table("performance_task")
