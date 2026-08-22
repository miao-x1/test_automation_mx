"""add user_id and created_by to task table

Revision ID: 034
Revises: 033
Create Date: 2026-08-09 15:05:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = '034'
down_revision: Union[str, None] = '033'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing = {c["name"] for c in inspector.get_columns("task")}

    if "user_id" not in existing:
        op.add_column("task", sa.Column(
            "user_id", sa.Integer(), nullable=True,
            comment="所属用户ID（数据隔离）",
        ))
        op.create_foreign_key(
            "fk_task_user_id", "task", "user", ["user_id"], ["id"],
            ondelete="CASCADE"
        )
        op.create_index("ix_task_user_id", "task", ["user_id"])

    if "created_by" not in existing:
        op.add_column("task", sa.Column(
            "created_by", sa.Integer(), nullable=True,
            comment="创建者用户ID",
        ))
        op.create_index("ix_task_created_by", "task", ["created_by"])


def downgrade() -> None:
    for col, idx in [("created_by", "ix_task_created_by"), ("user_id", "ix_task_user_id")]:
        try:
            op.drop_index(idx, table_name="task")
        except Exception:
            pass
    try:
        op.drop_constraint("fk_task_user_id", "task", type_="foreignkey")
    except Exception:
        pass
    for col in ["created_by", "user_id"]:
        try:
            op.drop_column("task", col)
        except Exception:
            pass
