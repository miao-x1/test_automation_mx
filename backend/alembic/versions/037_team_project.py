"""Team workspace, projects, members, and project_id isolation.

Revision ID: 037
Revises: 036
"""
from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

from app.db.alembic_ops import (
    add_column_if_missing,
    create_fk_if_missing,
    create_index_if_missing,
    ensure_user_table,
    table_exists,
)

revision: str = "037"
down_revision: Union[str, None] = "036"
branch_labels = None
depends_on = None


def _ts_columns():
    return (
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="更新时间"),
    )


def upgrade() -> None:
    ensure_user_table()
    now = datetime.now()

    if not table_exists("organization"):
        op.create_table(
            "organization",
            *_ts_columns(),
            sa.Column("name", sa.String(100), nullable=False, comment="团队名称"),
            sa.Column("description", sa.String(512), nullable=True, comment="团队描述"),
            sa.Column("owner_id", sa.Integer(), nullable=False, comment="所有者"),
            sa.Column("avatar", sa.String(512), nullable=True),
            sa.Column("is_personal", sa.Boolean(), nullable=False, server_default="0", comment="是否个人空间"),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        )
        create_index_if_missing("ix_organization_owner_id", "organization", ["owner_id"])
        create_index_if_missing("idx_org_owner", "organization", ["owner_id"])

    if not table_exists("organization_member"):
        op.create_table(
            "organization_member",
            *_ts_columns(),
            sa.Column("organization_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(20), nullable=False, server_default="MEMBER"),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("organization_id", "user_id", name="uq_org_member"),
        )
        create_index_if_missing("ix_organization_member_organization_id", "organization_member", ["organization_id"])
        create_index_if_missing("ix_organization_member_user_id", "organization_member", ["user_id"])

    if not table_exists("project"):
        op.create_table(
            "project",
            *_ts_columns(),
            sa.Column("organization_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("description", sa.String(512), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default="0"),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        )
        create_index_if_missing("ix_project_organization_id", "project", ["organization_id"])
        create_index_if_missing("ix_project_created_by", "project", ["created_by"])
        create_index_if_missing("idx_project_org", "project", ["organization_id"])

    if not table_exists("project_member"):
        op.create_table(
            "project_member",
            *_ts_columns(),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(20), nullable=False, server_default="TESTER"),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("project_id", "user_id", name="uq_project_member"),
        )
        create_index_if_missing("ix_project_member_project_id", "project_member", ["project_id"])
        create_index_if_missing("ix_project_member_user_id", "project_member", ["user_id"])

    if not table_exists("organization_invite"):
        op.create_table(
            "organization_invite",
            *_ts_columns(),
            sa.Column("organization_id", sa.Integer(), nullable=False),
            sa.Column("email", sa.String(255), nullable=True),
            sa.Column("token", sa.String(64), nullable=False),
            sa.Column("role", sa.String(20), nullable=False, server_default="MEMBER"),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("project_role", sa.String(20), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("accepted_at", sa.DateTime(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
            sa.UniqueConstraint("token"),
        )
        create_index_if_missing("ix_organization_invite_organization_id", "organization_invite", ["organization_id"])
        create_index_if_missing("ix_organization_invite_email", "organization_invite", ["email"])
        create_index_if_missing("ix_organization_invite_token", "organization_invite", ["token"])

    for table in (
        "requirement_task",
        "task",
        "execution_record",
        "test_environment",
        "test_case",
        "image_file",
        "test_asset",
    ):
        add_column_if_missing(
            table,
            sa.Column("project_id", sa.Integer(), nullable=True, comment="所属项目"),
        )
        create_index_if_missing(f"ix_{table}_project_id", table, ["project_id"])
        create_fk_if_missing(
            f"fk_{table}_project_id",
            table,
            "project",
            ["project_id"],
            ["id"],
            ondelete="SET NULL",
        )

    _backfill_personal_workspaces(now)


def _backfill_personal_workspaces(now: datetime) -> None:
    if not table_exists("user") or not table_exists("organization"):
        return
    bind = op.get_bind()
    users = bind.execute(text("SELECT id, username, display_name FROM user")).fetchall()
    for row in users:
        user_id = row[0]
        display = row[2] or row[1] or f"user-{user_id}"
        existing = bind.execute(
            text(
                "SELECT o.id FROM organization o "
                "JOIN organization_member m ON m.organization_id = o.id "
                "WHERE o.is_personal = 1 AND m.user_id = :uid AND m.role = 'OWNER' LIMIT 1"
            ),
            {"uid": user_id},
        ).fetchone()
        if existing:
            org_id = existing[0]
        else:
            bind.execute(
                text(
                    "INSERT INTO organization (created_at, updated_at, name, description, owner_id, is_personal) "
                    "VALUES (:c, :u, :name, :desc, :owner, 1)"
                ),
                {
                    "c": now,
                    "u": now,
                    "name": f"{display} 的空间",
                    "desc": "个人测试空间",
                    "owner": user_id,
                },
            )
            org_id = bind.execute(text("SELECT last_insert_rowid()") if bind.dialect.name == "sqlite" else text("SELECT LAST_INSERT_ID()")).scalar()
            bind.execute(
                text(
                    "INSERT INTO organization_member (created_at, updated_at, organization_id, user_id, role) "
                    "VALUES (:c, :u, :oid, :uid, 'OWNER')"
                ),
                {"c": now, "u": now, "oid": org_id, "uid": user_id},
            )

        project = bind.execute(
            text("SELECT id FROM project WHERE organization_id = :oid AND is_default = 1 LIMIT 1"),
            {"oid": org_id},
        ).fetchone()
        if project:
            project_id = project[0]
        else:
            bind.execute(
                text(
                    "INSERT INTO project (created_at, updated_at, organization_id, name, description, created_by, is_default) "
                    "VALUES (:c, :u, :oid, :name, :desc, :uid, 1)"
                ),
                {
                    "c": now,
                    "u": now,
                    "oid": org_id,
                    "name": "默认项目",
                    "desc": "自动创建的个人项目",
                    "uid": user_id,
                },
            )
            project_id = bind.execute(text("SELECT last_insert_rowid()") if bind.dialect.name == "sqlite" else text("SELECT LAST_INSERT_ID()")).scalar()
            bind.execute(
                text(
                    "INSERT INTO project_member (created_at, updated_at, project_id, user_id, role) "
                    "VALUES (:c, :u, :pid, :uid, 'PROJECT_ADMIN')"
                ),
                {"c": now, "u": now, "pid": project_id, "uid": user_id},
            )

        for table in ("requirement_task", "task", "execution_record", "test_environment", "test_case", "image_file", "test_asset"):
            if table_exists(table):
                bind.execute(
                    text(f"UPDATE {table} SET project_id = :pid WHERE project_id IS NULL AND user_id = :uid"),
                    {"pid": project_id, "uid": user_id},
                )


def downgrade() -> None:
    pass
