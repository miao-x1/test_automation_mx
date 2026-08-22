"""add test environment tables

Revision ID: 027
Revises: 026
Create Date: 2026-07-21

新增测试环境管理两张表:
- test_environment: 测试环境(dev/test/staging/prod),管理 URL/数据库/账号/密钥
- environment_secret: 环境密钥(通用 Key-Value,加密存储)

敏感字段(db_password, api_key, api_secret, value)由应用层加密后存入。
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ===== test_environment =====
    op.create_table(
        "test_environment",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        # 基本信息
        sa.Column("name", sa.String(50), nullable=False, comment="环境名称"),
        sa.Column("display_name", sa.String(100), nullable=True, comment="显示名称"),
        sa.Column("description", sa.Text(), nullable=True, comment="环境描述"),
        sa.Column("env_type", sa.String(20), nullable=False, comment="环境类型: dev/test/staging/prod"),
        # URL
        sa.Column("base_url", sa.String(500), nullable=True, comment="基础 URL"),
        sa.Column("api_url", sa.String(500), nullable=True, comment="API 基础 URL"),
        sa.Column("web_url", sa.String(500), nullable=True, comment="Web 基础 URL"),
        # 数据库
        sa.Column("db_host", sa.String(200), nullable=True, comment="数据库地址"),
        sa.Column("db_port", sa.Integer(), nullable=True, comment="数据库端口"),
        sa.Column("db_name", sa.String(100), nullable=True, comment="数据库名称"),
        sa.Column("db_user", sa.String(100), nullable=True, comment="数据库用户名"),
        sa.Column("db_password", sa.Text(), nullable=True, comment="数据库密码(加密)"),
        # API 凭证
        sa.Column("api_key", sa.Text(), nullable=True, comment="API Key(加密)"),
        sa.Column("api_secret", sa.Text(), nullable=True, comment="API Secret(加密)"),
        # 额外配置
        sa.Column("headers_json", sa.Text(), nullable=True, comment="全局请求头(JSON)"),
        sa.Column("variables_json", sa.Text(), nullable=True, comment="全局变量(JSON)"),
        sa.Column("tags", sa.String(500), nullable=True, comment="标签"),
        # 状态
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_test_environment_user_id", "test_environment", ["user_id"])
    op.create_index("ix_test_environment_created_by", "test_environment", ["created_by"])
    op.create_index("ix_test_environment_is_active", "test_environment", ["is_active"])
    op.create_index("ix_test_environment_is_default", "test_environment", ["is_default"])
    op.create_index("ix_test_environment_is_deleted", "test_environment", ["is_deleted"])
    op.create_index("idx_env_user_name", "test_environment", ["user_id", "name"])
    op.create_index("idx_env_type", "test_environment", ["env_type", "is_active"])

    # ===== environment_secret =====
    op.create_table(
        "environment_secret",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("environment_id", sa.Integer(), nullable=False, comment="所属环境 ID"),
        sa.Column("key_name", sa.String(100), nullable=False, comment="密钥名称"),
        sa.Column("value", sa.Text(), nullable=True, comment="密钥值(加密)"),
        sa.Column("value_type", sa.String(20), nullable=False, server_default="string", comment="值类型"),
        sa.Column("description", sa.Text(), nullable=True, comment="描述"),
        sa.Column("is_sensitive", sa.Boolean(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["environment_id"], ["test_environment.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_environment_secret_environment_id", "environment_secret", ["environment_id"])
    op.create_index("ix_environment_secret_user_id", "environment_secret", ["user_id"])
    op.create_index("ix_environment_secret_created_by", "environment_secret", ["created_by"])
    op.create_index("idx_secret_env_key", "environment_secret", ["environment_id", "key_name"])


def downgrade() -> None:
    op.drop_index("idx_secret_env_key", table_name="environment_secret")
    op.drop_index("ix_environment_secret_created_by", table_name="environment_secret")
    op.drop_index("ix_environment_secret_user_id", table_name="environment_secret")
    op.drop_index("ix_environment_secret_environment_id", table_name="environment_secret")
    op.drop_table("environment_secret")

    op.drop_index("idx_env_type", table_name="test_environment")
    op.drop_index("idx_env_user_name", table_name="test_environment")
    op.drop_index("ix_test_environment_is_deleted", table_name="test_environment")
    op.drop_index("ix_test_environment_is_default", table_name="test_environment")
    op.drop_index("ix_test_environment_is_active", table_name="test_environment")
    op.drop_index("ix_test_environment_created_by", table_name="test_environment")
    op.drop_index("ix_test_environment_user_id", table_name="test_environment")
    op.drop_table("test_environment")
