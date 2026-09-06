"""Jenkins-style test jobs and regression pipelines.

Revision ID: 038
Revises: 037
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db.alembic_ops import create_index_if_missing, table_exists

revision: str = "038"
down_revision: Union[str, None] = "037"
branch_labels = None
depends_on = None


def _ts():
    return (
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="更新时间"),
    )


def upgrade() -> None:
    if not table_exists("test_job"):
        op.create_table(
            "test_job",
            *_ts(),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("creator_id", sa.Integer(), nullable=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("job_type", sa.String(30), nullable=False, server_default="web"),
            sa.Column("requirement_id", sa.Integer(), nullable=True),
            sa.Column("task_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="CREATED"),
            sa.Column("result", sa.Text(), nullable=True),
            sa.Column("last_execution_id", sa.Integer(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["creator_id"], ["user.id"], ondelete="SET NULL"),
        )
        create_index_if_missing("ix_test_job_project_id", "test_job", ["project_id"])
        create_index_if_missing("ix_test_job_status", "test_job", ["status"])
        create_index_if_missing("idx_test_job_project_status", "test_job", ["project_id", "status"])

    if not table_exists("regression_pipeline"):
        op.create_table(
            "regression_pipeline",
            *_ts(),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("description", sa.String(512), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        )
        create_index_if_missing("ix_regression_pipeline_project_id", "regression_pipeline", ["project_id"])

    if not table_exists("regression_pipeline_item"):
        op.create_table(
            "regression_pipeline_item",
            *_ts(),
            sa.Column("pipeline_id", sa.Integer(), nullable=False),
            sa.Column("job_id", sa.Integer(), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["pipeline_id"], ["regression_pipeline.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["job_id"], ["test_job.id"], ondelete="CASCADE"),
        )
        create_index_if_missing("ix_regression_pipeline_item_pipeline_id", "regression_pipeline_item", ["pipeline_id"])

    if not table_exists("regression_run"):
        op.create_table(
            "regression_run",
            *_ts(),
            sa.Column("pipeline_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="CREATED"),
            sa.Column("passed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("result_json", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["pipeline_id"], ["regression_pipeline.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        )
        create_index_if_missing("ix_regression_run_project_id", "regression_run", ["project_id"])


def downgrade() -> None:
    pass
