"""add runtime_task

Revision ID: 022
Revises: 021
Create Date: 2026-07-20

新增 runtime_task 表 — 企业级 Agent Runtime 任务记录
持久化 TaskDispatcher 的任务状态,支持崩溃恢复与历史查询
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_task",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),

        # 任务标识
        sa.Column("task_id", sa.String(64), nullable=False, comment="任务 ID"),
        sa.Column("parent_task_id", sa.String(64), nullable=True, comment="父任务 ID"),

        # 任务内容
        sa.Column("task_type", sa.String(32), nullable=False, server_default="agent", comment="任务类型"),
        sa.Column("agent_name", sa.String(128), nullable=False, comment="Agent 名称"),
        sa.Column("action", sa.String(64), nullable=False, server_default="execute", comment="action"),
        sa.Column("payload_json", mysql.MEDIUMTEXT(), nullable=True, comment="任务参数 JSON"),

        # 状态
        sa.Column(
            "status",
            sa.Enum("pending", "running", "success", "failed", "timeout", "cancelled", name="runtimetaskstatus"),
            nullable=False,
            server_default="pending",
            comment="任务状态",
        ),
        sa.Column(
            "priority",
            sa.Enum("low", "normal", "high", "urgent", name="runtimetaskpriority"),
            nullable=False,
            server_default="normal",
            comment="优先级",
        ),

        # 重试
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0", comment="已重试次数"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3", comment="最大重试次数"),

        # 时间
        sa.Column("created_at_ts", sa.DateTime(), nullable=True, comment="任务创建时间"),
        sa.Column("started_at_ts", sa.DateTime(), nullable=True, comment="开始执行时间"),
        sa.Column("completed_at_ts", sa.DateTime(), nullable=True, comment="完成时间"),
        sa.Column("duration_ms", sa.Integer(), nullable=True, comment="执行耗时(毫秒)"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="300", comment="超时时间"),

        # 执行者
        sa.Column("worker_id", sa.String(64), nullable=True, comment="Worker ID"),
        sa.Column("user_id", sa.Integer(), nullable=True, comment="用户 ID"),
        sa.Column("session_id", sa.String(64), nullable=True, comment="会话 ID"),

        # 结果
        sa.Column("result_json", mysql.MEDIUMTEXT(), nullable=True, comment="任务结果 JSON"),
        sa.Column("error", sa.Text(), nullable=True, comment="错误信息"),
        sa.Column("events_count", sa.Integer(), nullable=False, server_default="0", comment="事件数量"),

        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uq_runtime_task_task_id"),
    )

    # 索引
    op.create_index("ix_runtime_task_task_id", "runtime_task", ["task_id"], unique=False)
    op.create_index("ix_runtime_task_parent_task_id", "runtime_task", ["parent_task_id"])
    op.create_index("ix_runtime_task_task_type", "runtime_task", ["task_type"])
    op.create_index("ix_runtime_task_agent_name", "runtime_task", ["agent_name"])
    op.create_index("ix_runtime_task_status", "runtime_task", ["status"])
    op.create_index("ix_runtime_task_priority", "runtime_task", ["priority"])
    op.create_index("ix_runtime_task_created_at_ts", "runtime_task", ["created_at_ts"])
    op.create_index("ix_runtime_task_completed_at_ts", "runtime_task", ["completed_at_ts"])
    op.create_index("ix_runtime_task_duration_ms", "runtime_task", ["duration_ms"])
    op.create_index("ix_runtime_task_worker_id", "runtime_task", ["worker_id"])
    op.create_index("ix_runtime_task_user_id", "runtime_task", ["user_id"])
    op.create_index("ix_runtime_task_session_id", "runtime_task", ["session_id"])

    # 复合索引
    op.create_index("idx_runtime_task_status_created", "runtime_task", ["status", "created_at_ts"])
    op.create_index("idx_runtime_task_user_status", "runtime_task", ["user_id", "status"])
    op.create_index("idx_runtime_task_agent_status", "runtime_task", ["agent_name", "status"])
    op.create_index("idx_runtime_task_completed_status", "runtime_task", ["completed_at_ts", "status"])


def downgrade() -> None:
    op.drop_index("idx_runtime_task_completed_status", table_name="runtime_task")
    op.drop_index("idx_runtime_task_agent_status", table_name="runtime_task")
    op.drop_index("idx_runtime_task_user_status", table_name="runtime_task")
    op.drop_index("idx_runtime_task_status_created", table_name="runtime_task")
    op.drop_index("ix_runtime_task_session_id", table_name="runtime_task")
    op.drop_index("ix_runtime_task_user_id", table_name="runtime_task")
    op.drop_index("ix_runtime_task_worker_id", table_name="runtime_task")
    op.drop_index("ix_runtime_task_duration_ms", table_name="runtime_task")
    op.drop_index("ix_runtime_task_completed_at_ts", table_name="runtime_task")
    op.drop_index("ix_runtime_task_created_at_ts", table_name="runtime_task")
    op.drop_index("ix_runtime_task_priority", table_name="runtime_task")
    op.drop_index("ix_runtime_task_status", table_name="runtime_task")
    op.drop_index("ix_runtime_task_agent_name", table_name="runtime_task")
    op.drop_index("ix_runtime_task_task_type", table_name="runtime_task")
    op.drop_index("ix_runtime_task_parent_task_id", table_name="runtime_task")
    op.drop_index("ix_runtime_task_task_id", table_name="runtime_task")
    op.drop_table("runtime_task")
