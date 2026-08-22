"""add quality_report table

Revision ID: 028
Revises: 027
Create Date: 2026-07-21

新增测试质量分析报告表 quality_report
- 存储由 QualityAnalysisAgent 生成的质量分析结果
- 包含覆盖不足/高风险模块/重复测试/缺陷趋势四大维度分析
- 综合质量分数(0-100)与分项分数
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quality_report",
        # --- 通用基类字段 ---
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),

        # --- 基础信息 ---
        sa.Column("title", sa.String(length=200), nullable=False, comment="报告标题"),
        sa.Column("description", sa.Text(), nullable=True, comment="报告描述"),

        # --- 分析范围 ---
        sa.Column("analysis_scope", sa.Text(), nullable=True, comment="分析范围(JSON)"),

        # --- 状态 ---
        sa.Column("status", sa.String(length=20), server_default="pending",
                  nullable=False, comment="状态: pending/analyzing/completed/failed"),

        # --- 质量分数 ---
        sa.Column("quality_score", sa.Float(), nullable=True, comment="综合质量分数(0-100)"),
        sa.Column("coverage_score", sa.Float(), nullable=True, comment="覆盖率分数(0-100)"),
        sa.Column("risk_score", sa.Float(), nullable=True, comment="风险分数(0-100)"),
        sa.Column("duplication_score", sa.Float(), nullable=True, comment="重复度分数(0-100)"),
        sa.Column("defect_score", sa.Float(), nullable=True, comment="缺陷分数(0-100)"),

        # --- 分析结果 ---
        sa.Column("summary", sa.Text(), nullable=True, comment="总体摘要"),
        sa.Column("coverage_analysis", sa.Text(), nullable=True, comment="覆盖不足分析(JSON)"),
        sa.Column("risk_analysis", sa.Text(), nullable=True, comment="高风险模块分析(JSON)"),
        sa.Column("duplication_analysis", sa.Text(), nullable=True, comment="重复测试分析(JSON)"),
        sa.Column("defect_trend", sa.Text(), nullable=True, comment="缺陷趋势分析(JSON)"),
        sa.Column("recommendations", sa.Text(), nullable=True, comment="改进建议(JSON数组)"),

        # --- 输入数据统计 ---
        sa.Column("input_stats", sa.Text(), nullable=True, comment="输入数据统计(JSON)"),

        # --- 错误信息 ---
        sa.Column("error_message", sa.Text(), nullable=True, comment="分析失败时的错误信息"),

        # --- 时间戳 ---
        sa.Column("started_at", sa.DateTime(), nullable=True, comment="分析开始时间"),
        sa.Column("completed_at", sa.DateTime(), nullable=True, comment="分析完成时间"),

        # --- 软删除 ---
        sa.Column("is_deleted", sa.Boolean(), server_default="0",
                  nullable=False, comment="是否删除"),

        # --- 约束 ---
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
    )

    # 索引
    op.create_index("ix_quality_report_user_id", "quality_report", ["user_id"])
    op.create_index("ix_quality_report_is_deleted", "quality_report", ["is_deleted"])
    op.create_index("ix_quality_report_status", "quality_report", ["status"])
    op.create_index("idx_quality_report_user_status", "quality_report", ["user_id", "status"])
    op.create_index("idx_quality_report_status_created", "quality_report", ["status", "created_at"])
    op.create_index("idx_quality_report_user_created", "quality_report", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_quality_report_user_created", table_name="quality_report")
    op.drop_index("idx_quality_report_status_created", table_name="quality_report")
    op.drop_index("idx_quality_report_user_status", table_name="quality_report")
    op.drop_index("ix_quality_report_status", table_name="quality_report")
    op.drop_index("ix_quality_report_is_deleted", table_name="quality_report")
    op.drop_index("ix_quality_report_user_id", table_name="quality_report")
    op.drop_table("quality_report")
