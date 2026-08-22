"""add llm call log table

Revision ID: 025
Revises: 024
Create Date: 2026-07-20

新增 llm_call_log 表,记录每次 LLM Gateway 调用,
用于 Token 用量与费用统计、失败切换追踪。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_call_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="更新时间"),
        sa.Column("agent_name", sa.String(length=64), nullable=False, comment="调用方 Agent 名称"),
        sa.Column("task_id", sa.String(length=64), nullable=True, comment="任务 ID"),
        sa.Column("step", sa.String(length=64), nullable=True, comment="执行步骤标识"),
        sa.Column("session_key", sa.String(length=128), nullable=True, comment="会话 key"),
        sa.Column("provider", sa.String(length=32), nullable=False, comment="供应商"),
        sa.Column("model", sa.String(length=64), nullable=False, comment="实际命中的模型名"),
        sa.Column("requested_model", sa.String(length=64), nullable=True, comment="原始请求的模型名"),
        sa.Column("prompt_tokens", sa.Integer(), server_default="0", nullable=False, comment="输入 token 数"),
        sa.Column("completion_tokens", sa.Integer(), server_default="0", nullable=False, comment="输出 token 数"),
        sa.Column("total_tokens", sa.Integer(), server_default="0", nullable=False, comment="总 token 数"),
        sa.Column("cost", sa.Float(), server_default="0", nullable=False, comment="本次调用费用(元)"),
        sa.Column("currency", sa.String(length=8), server_default="CNY", nullable=False, comment="币种"),
        sa.Column("duration", sa.Float(), server_default="0", nullable=False, comment="耗时(秒)"),
        sa.Column("status", sa.String(length=16), server_default="success", nullable=False, comment="状态"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="错误信息"),
        sa.Column("error_type", sa.String(length=32), nullable=True, comment="错误类型"),
        sa.Column("fallback_used", sa.Integer(), server_default="0", nullable=False, comment="是否触发失败切换"),
        sa.Column("fallback_chain", sa.Text(), nullable=True, comment="切换链(JSON)"),
        sa.Column("attempt_index", sa.Integer(), server_default="0", nullable=False, comment="第几次尝试"),
        sa.Column("prompt_preview", sa.Text(), nullable=True, comment="system prompt 摘要"),
        sa.PrimaryKeyConstraint("id"),
    )

    # 单列索引
    op.create_index("ix_llm_call_log_agent_name", "llm_call_log", ["agent_name"])
    op.create_index("ix_llm_call_log_provider", "llm_call_log", ["provider"])
    op.create_index("ix_llm_call_log_status", "llm_call_log", ["status"])

    # 复合索引(提升统计查询性能)
    op.create_index("idx_llm_log_agent_time", "llm_call_log", ["agent_name", "created_at"])
    op.create_index("idx_llm_log_provider_time", "llm_call_log", ["provider", "created_at"])
    op.create_index("idx_llm_log_task", "llm_call_log", ["task_id", "created_at"])
    op.create_index("idx_llm_log_status_time", "llm_call_log", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_llm_log_status_time", table_name="llm_call_log")
    op.drop_index("idx_llm_log_task", table_name="llm_call_log")
    op.drop_index("idx_llm_log_provider_time", table_name="llm_call_log")
    op.drop_index("idx_llm_log_agent_time", table_name="llm_call_log")
    op.drop_index("ix_llm_call_log_status", table_name="llm_call_log")
    op.drop_index("ix_llm_call_log_provider", table_name="llm_call_log")
    op.drop_index("ix_llm_call_log_agent_name", table_name="llm_call_log")
    op.drop_table("llm_call_log")
