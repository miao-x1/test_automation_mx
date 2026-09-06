"""Add user.phone and verification_code for open-source account basics.

Revision ID: 036
Revises: 035
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

from app.db.alembic_ops import add_column_if_missing, create_index_if_missing, table_exists

revision: str = "036"
down_revision: Union[str, None] = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "user",
        sa.Column("phone", sa.String(20), nullable=True, comment="手机号（唯一）"),
    )
    create_index_if_missing("ix_user_phone", "user", ["phone"])

    if not table_exists("verification_code"):
        op.create_table(
            "verification_code",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
            sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间"),
            sa.Column("updated_at", sa.DateTime(), nullable=False, comment="更新时间"),
            sa.Column("phone", sa.String(20), nullable=False, comment="手机号"),
            sa.Column("purpose", sa.String(20), nullable=False, comment="用途: register/reset"),
            sa.Column("code_hash", sa.String(64), nullable=False, comment="验证码哈希"),
            sa.Column("expires_at", sa.DateTime(), nullable=False, comment="过期时间"),
            sa.Column("consumed", sa.Boolean(), nullable=False, server_default="0", comment="是否已使用"),
            sa.Column("request_ip", sa.String(64), nullable=True, comment="请求 IP"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_verification_code_phone", "verification_code", ["phone"])
        op.create_index("idx_verify_phone_purpose", "verification_code", ["phone", "purpose"])


def downgrade() -> None:
    if table_exists("verification_code"):
        op.drop_table("verification_code")
