"""add data_testid to ui_element

Revision ID: 004_add_data_testid
Revises: 003_unified_architecture
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa

revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('ui_element', sa.Column('data_testid', sa.String(255), nullable=True, comment='data-testid属性'))


def downgrade() -> None:
    op.drop_column('ui_element', 'data_testid')
