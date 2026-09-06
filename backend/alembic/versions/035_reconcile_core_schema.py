"""Reconcile core production tables with SQLAlchemy models.

Revision ID: 035
Revises: 034
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import inspect, text

from alembic import op

from app.db.alembic_ops import (
    add_column_if_missing,
    create_index_if_missing,
    ensure_test_asset_table,
    ensure_ui_element_table,
    ensure_user_table,
    ensure_workspace_table,
    table_exists,
)

revision: str = "035"
down_revision: Union[str, None] = "034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _modify_varchar(table: str, column: str, length: int, nullable: bool, default: str | None = None) -> None:
    insp = inspect(op.get_bind())
    if table not in insp.get_table_names():
        return
    existing = {c["name"]: c for c in insp.get_columns(table)}
    if column not in existing:
        return
    null_sql = "NULL" if nullable else "NOT NULL"
    default_sql = f" DEFAULT '{default}'" if default is not None else ""
    op.execute(text(
        f"ALTER TABLE {table} MODIFY COLUMN {column} VARCHAR({length}) {null_sql}{default_sql}"
    ))


def upgrade() -> None:
    ensure_user_table()
    ensure_workspace_table()
    ensure_ui_element_table()
    ensure_test_asset_table()
    add_column_if_missing("task", sa.Column("task_type", sa.String(20), nullable=False, server_default="web", comment="测试类型: web/api/performance/android"))
    add_column_if_missing("task", sa.Column("type_config", sa.String(4096), nullable=True, comment="测试类型配置(JSON)"))
    add_column_if_missing("task", sa.Column("framework", sa.String(64), nullable=True, comment="测试框架"))
    add_column_if_missing("task", sa.Column("platform", sa.String(64), nullable=True, comment="测试平台"))
    add_column_if_missing("task", sa.Column("confidence", sa.Float(), nullable=True, comment="AI识别置信度"))
    add_column_if_missing("task", sa.Column("user_id", sa.Integer(), nullable=True, comment="所属用户ID"))
    add_column_if_missing("task", sa.Column("created_by", sa.Integer(), nullable=True, comment="创建者用户ID"))
    _modify_varchar("task", "input_mode", 32, nullable=False, default="image")
    _modify_varchar("task", "status", 32, nullable=False, default="pending")
    if table_exists("task"):
        op.execute(text("UPDATE task SET status = LOWER(status) WHERE status IS NOT NULL"))

    add_column_if_missing("image_file", sa.Column("user_id", sa.Integer(), nullable=True, comment="所属用户ID"))
    add_column_if_missing("image_file", sa.Column("created_by", sa.Integer(), nullable=True, comment="创建者用户ID"))

    add_column_if_missing("script", sa.Column("kb_status", sa.String(20), nullable=False, server_default="approved", comment="知识库审核状态"))
    add_column_if_missing("script", sa.Column("script_source", sa.String(20), nullable=False, server_default="generated", comment="脚本来源"))
    add_column_if_missing("script", sa.Column("reuse_count", sa.Integer(), nullable=False, server_default="0", comment="被其他需求复用的次数"))
    add_column_if_missing("script", sa.Column("user_id", sa.Integer(), nullable=True, comment="所属用户ID"))
    add_column_if_missing("script", sa.Column("created_by", sa.Integer(), nullable=True, comment="创建者用户ID"))

    add_column_if_missing("requirement_task", sa.Column("user_id", sa.Integer(), nullable=True, comment="所属用户ID"))
    add_column_if_missing("requirement_task", sa.Column("created_by", sa.Integer(), nullable=True, comment="创建者用户ID"))
    add_column_if_missing("requirement_task", sa.Column("task_id", sa.Integer(), nullable=True, comment="关联的任务ID"))

    add_column_if_missing("execution_record", sa.Column("user_id", sa.Integer(), nullable=True, comment="所属用户ID"))
    add_column_if_missing("execution_record", sa.Column("created_by", sa.Integer(), nullable=True, comment="创建者用户ID"))
    add_column_if_missing("execution_record", sa.Column("trigger_source", sa.String(30), nullable=True, comment="触发来源"))
    add_column_if_missing("execution_record", sa.Column("asset_id", sa.Integer(), nullable=True, comment="关联 TestAsset ID"))
    add_column_if_missing("execution_record", sa.Column("execution_type", sa.String(20), nullable=True, comment="执行类型"))
    add_column_if_missing("execution_record", sa.Column("suite_id", sa.Integer(), nullable=True, comment="关联 TestSuite ID"))
    add_column_if_missing("execution_record", sa.Column("session_id", sa.Integer(), nullable=True, comment="关联 Session ID"))

    add_column_if_missing("ui_element", sa.Column("user_id", sa.Integer(), nullable=True, comment="所属用户ID"))
    add_column_if_missing("ui_element", sa.Column("created_by", sa.Integer(), nullable=True, comment="创建者用户ID"))
    add_column_if_missing("ui_element", sa.Column("data_testid", sa.String(255), nullable=True, comment="data-testid属性"))

    add_column_if_missing("analysis_result", sa.Column("user_id", sa.Integer(), nullable=True, comment="所属用户ID"))
    add_column_if_missing("analysis_result", sa.Column("created_by", sa.Integer(), nullable=True, comment="创建者用户ID"))
    add_column_if_missing("page_element", sa.Column("user_id", sa.Integer(), nullable=True, comment="所属用户ID"))
    add_column_if_missing("page_element", sa.Column("created_by", sa.Integer(), nullable=True, comment="创建者用户ID"))

    create_index_if_missing("ix_task_task_type", "task", ["task_type"])
    create_index_if_missing("ix_script_kb_status", "script", ["kb_status"])
    create_index_if_missing("ix_requirement_task_status", "requirement_task", ["status"])


def downgrade() -> None:
    return
