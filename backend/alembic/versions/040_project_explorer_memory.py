"""Project explorer index and project memory tables.

Revision ID: 040
Revises: 039
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db.alembic_ops import table_exists

revision: str = "040"
down_revision: Union[str, None] = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not table_exists("project_source"):
        op.create_table(
            "project_source",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("organization_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("source_type", sa.String(20), nullable=False),
            sa.Column("repo_url", sa.String(512), nullable=True),
            sa.Column("repo_owner", sa.String(128), nullable=True),
            sa.Column("repo_name", sa.String(200), nullable=True),
            sa.Column("default_branch", sa.String(100), nullable=True),
            sa.Column("local_path", sa.String(512), nullable=True),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("file_count", sa.Integer(), nullable=True),
            sa.Column("symbol_count", sa.Integer(), nullable=True),
            sa.Column("overview_json", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    if not table_exists("project_code_index"):
        op.create_table(
            "project_code_index",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("organization_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("path", sa.String(512), nullable=False),
            sa.Column("language", sa.String(20), nullable=True),
            sa.Column("module", sa.String(255), nullable=True),
            sa.Column("line_start", sa.Integer(), nullable=True),
            sa.Column("line_end", sa.Integer(), nullable=True),
            sa.Column("signature", sa.String(512), nullable=True),
            sa.Column("snippet", sa.Text(), nullable=True),
            sa.Column("extra_json", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    if not table_exists("project_memory_item"):
        op.create_table(
            "project_memory_item",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("organization_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(32), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("content", sa.Text(), nullable=True),
            sa.Column("workspace", sa.String(20), nullable=True),
            sa.Column("role", sa.String(20), nullable=True),
            sa.Column("extra_json", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade() -> None:
    pass
