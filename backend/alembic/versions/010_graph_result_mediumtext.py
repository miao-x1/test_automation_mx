"""change graph_result from TEXT to MEDIUMTEXT

Revision ID: 010
Revises: 009
Create Date: 2026-06-10
"""
from alembic import op

from app.db.alembic_ops import column_exists

revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if column_exists('requirement_task', 'graph_result') and op.get_bind().dialect.name != "sqlite":
        op.execute("ALTER TABLE requirement_task MODIFY COLUMN graph_result MEDIUMTEXT NULL COMMENT 'Graph推理结果(JSON): 页面路径、元素、业务流'")


def downgrade() -> None:
    op.execute("ALTER TABLE requirement_task MODIFY COLUMN graph_result TEXT NULL COMMENT 'Graph推理结果(JSON): 页面路径、元素、业务流'")
