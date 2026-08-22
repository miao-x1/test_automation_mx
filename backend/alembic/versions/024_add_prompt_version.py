"""add prompt version table

Revision ID: 024
Revises: 023
Create Date: 2026-07-20

新增 prompt_version 表 — Agent Prompt 版本管理
支持版本管理、A/B 测试、回滚、版本比较
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_version",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=True),

        # 关联
        sa.Column("agent_name", sa.String(64), nullable=False, comment="Agent 名称"),
        sa.Column("prompt_key", sa.String(64), nullable=False, server_default="system_prompt", comment="Prompt 标识"),

        # 版本
        sa.Column("version", sa.String(32), nullable=False, comment="版本号"),
        sa.Column("content", mysql.MEDIUMTEXT(), nullable=False, comment="Prompt 内容"),
        sa.Column("description", sa.Text(), nullable=True, comment="版本描述"),

        # 状态
        sa.Column(
            "status",
            sa.Enum("draft", "active", "archived", "testing", name="promptstatus", native_enum=False, length=20),
            nullable=False, server_default="draft", comment="状态",
        ),

        # A/B 测试
        sa.Column("ab_test_group", sa.String(16), nullable=True, comment="A/B 测试分组"),
        sa.Column("ab_test_ratio", sa.Float(), nullable=True, server_default="0", comment="A/B 测试流量比例"),

        # 元数据
        sa.Column("change_type", sa.String(20), nullable=True, comment="变更类型: new/modify/rollback"),
        sa.Column("parent_version", sa.String(32), nullable=True, comment="父版本号"),
        sa.Column("tags", sa.Text(), nullable=True, comment="标签 JSON"),

        # 统计
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0", comment="使用次数"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0", comment="成功次数"),

        sa.PrimaryKeyConstraint("id"),
    )

    # 索引
    op.create_index("ix_prompt_version_agent_name", "prompt_version", ["agent_name"])
    op.create_index("idx_prompt_version_unique", "prompt_version", ["agent_name", "prompt_key", "version"], unique=True)
    op.create_index("idx_prompt_agent_key_status", "prompt_version", ["agent_name", "prompt_key", "status"])
    op.create_index("idx_prompt_status_created", "prompt_version", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_prompt_status_created", table_name="prompt_version")
    op.drop_index("idx_prompt_agent_key_status", table_name="prompt_version")
    op.drop_index("idx_prompt_version_unique", table_name="prompt_version")
    op.drop_index("ix_prompt_version_agent_name", table_name="prompt_version")
    op.drop_table("prompt_version")
