"""Performance assessment tables and invite cancel/decline columns.

Revision ID: 039
Revises: 038
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db.alembic_ops import add_column_if_missing, create_index_if_missing, table_exists

revision: str = "039"
down_revision: Union[str, None] = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing("organization_invite", sa.Column("cancelled_at", sa.DateTime(), nullable=True))
    add_column_if_missing("organization_invite", sa.Column("declined_at", sa.DateTime(), nullable=True))

    if not table_exists("performance_assessment"):
        op.create_table(
            "performance_assessment",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("creator_id", sa.Integer(), nullable=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("target_url", sa.String(1024), nullable=False),
            sa.Column("environment_id", sa.Integer(), nullable=True),
            sa.Column("rounds", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("scenario", sa.String(50), nullable=False, server_default="page"),
            sa.Column("status", sa.String(20), nullable=False, server_default="CREATED"),
            sa.Column("score_total", sa.Integer(), nullable=True),
            sa.Column("score_page", sa.Integer(), nullable=True),
            sa.Column("score_resource", sa.Integer(), nullable=True),
            sa.Column("score_network", sa.Integer(), nullable=True),
            sa.Column("score_job", sa.Integer(), nullable=True),
            sa.Column("score_regression", sa.Integer(), nullable=True),
            sa.Column("report_json", sa.Text(), nullable=True),
            sa.Column("issues_json", sa.Text(), nullable=True),
            sa.Column("advice_json", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["creator_id"], ["user.id"], ondelete="SET NULL"),
        )
        create_index_if_missing("ix_performance_assessment_project_id", "performance_assessment", ["project_id"])

    if not table_exists("performance_assessment_metric"):
        op.create_table(
            "performance_assessment_metric",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("assessment_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(80), nullable=False),
            sa.Column("value", sa.Float(), nullable=True),
            sa.Column("unit", sa.String(20), nullable=True),
            sa.Column("supported", sa.Integer(), nullable=False, server_default="1"),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["assessment_id"], ["performance_assessment.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        )
        create_index_if_missing("ix_performance_assessment_metric_assessment_id", "performance_assessment_metric", ["assessment_id"])


def downgrade() -> None:
    pass
