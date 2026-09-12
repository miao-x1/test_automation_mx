"""Professional test-task workspace and case table fields.

Revision ID: 041
Revises: 040
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db.alembic_ops import add_column_if_missing, create_index_if_missing, table_exists

revision: str = "041"
down_revision: Union[str, None] = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not table_exists("project_test_task"):
        op.create_table(
            "project_test_task",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("focus", sa.String(200), nullable=True),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("requirement_text", sa.Text(), nullable=True),
            sa.Column("analysis_json", sa.Text(), nullable=True),
            sa.Column("strategy_json", sa.Text(), nullable=True),
            sa.Column("test_requirement_id", sa.Integer(), nullable=True),
            sa.Column("last_execution_id", sa.Integer(), nullable=True),
            sa.Column("extra_json", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        create_index_if_missing("idx_ptt_project", "project_test_task", ["user_id", "project_id", "status"])

    add_column_if_missing("test_case", sa.Column("case_code", sa.String(40), nullable=True))
    add_column_if_missing("test_case", sa.Column("module", sa.String(100), nullable=True))
    add_column_if_missing("test_case", sa.Column("scenario", sa.String(500), nullable=True))
    add_column_if_missing("test_case", sa.Column("test_data", sa.Text(), nullable=True))
    add_column_if_missing("test_case", sa.Column("tags", sa.String(500), nullable=True))
    add_column_if_missing("test_case", sa.Column("test_task_id", sa.Integer(), nullable=True))
    create_index_if_missing("ix_test_case_case_code", "test_case", ["case_code"])
    create_index_if_missing("ix_test_case_test_task_id", "test_case", ["test_task_id"])

    add_column_if_missing("project_memory_item", sa.Column("test_task_id", sa.Integer(), nullable=True))
    create_index_if_missing("ix_memory_test_task_id", "project_memory_item", ["test_task_id"])


def downgrade() -> None:
    pass
