"""add agent config column

Revision ID: 023
Revises: 022
Create Date: 2026-07-20

为 agent_registry 表新增 config 字段(JSON)
支持 Agent 管理中心的配置热更新功能
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_registry",
        sa.Column(
            "config",
            mysql.MEDIUMTEXT(),
            nullable=True,
            comment="Agent 配置(JSON): 模型参数/超时/重试/自定义参数",
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_registry", "config")
