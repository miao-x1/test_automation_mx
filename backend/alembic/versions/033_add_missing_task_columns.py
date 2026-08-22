"""add missing task columns: task_type/type_config/framework/platform/confidence + user_id/created_by

Revision ID: 033
Revises: 032
Create Date: 2026-08-09 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = '033'
down_revision: Union[str, None] = '032'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing = {c["name"] for c in inspector.get_columns("task")}

    if "task_type" not in existing:
        op.add_column("task", sa.Column(
            "task_type",
            sa.Enum("web", "api", "performance", "android", name="tasktype"),
            nullable=False,
            server_default="web",
            comment="测试类型: web/api/performance/android",
        ))
    if "type_config" not in existing:
        op.add_column("task", sa.Column(
            "type_config",
            sa.String(4096),
            nullable=True,
            comment="测试类型配置(JSON)",
        ))
    if "framework" not in existing:
        op.add_column("task", sa.Column(
            "framework",
            sa.String(64),
            nullable=True,
            comment="测试框架: playwright/appium/pytest/jmeter",
        ))
    if "platform" not in existing:
        op.add_column("task", sa.Column(
            "platform",
            sa.String(64),
            nullable=True,
            comment="测试平台: browser/mobile/server",
        ))
    if "confidence" not in existing:
        op.add_column("task", sa.Column(
            "confidence",
            sa.Float(),
            nullable=True,
            comment="AI识别置信度(0-1)",
        ))
    if "user_id" not in existing:
        op.add_column("task", sa.Column(
            "user_id",
            sa.Integer(),
            nullable=True,
            comment="所属用户ID（数据隔离）",
        ))
        op.create_foreign_key(
            "fk_task_user_id", "task", "user", ["user_id"], ["id"], ondelete="CASCADE"
        )
    if "created_by" not in existing:
        op.add_column("task", sa.Column(
            "created_by",
            sa.Integer(),
            nullable=True,
            comment="创建者用户ID",
        ))

    # 索引（幂等）
    existing_idx = {i["name"] for i in inspector.get_indexes("task")}
    for col_name in ["task_type", "framework", "platform"]:
        idx_name = f"ix_task_{col_name}"
        if idx_name not in existing_idx:
            op.create_index(idx_name, "task", [col_name])


def downgrade() -> None:
    for col in ["confidence", "platform", "framework", "type_config", "task_type"]:
        try:
            op.drop_column("task", col)
        except Exception:
            pass
