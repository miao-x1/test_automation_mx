"""add api header/body/parameter sub-tables

Revision ID: 031
Revises: 030
Create Date: 2026-07-22

接口数据模型分离 — 将 headers/body/parameters 从 JSON 文本列拆分为独立子表:

  1. api_header    - 请求头子表 (api_id, key, value, required)
  2. api_body      - 请求体子表 (api_id, body_type, schema, example)
  3. api_parameter - 参数子表   (api_id, location, name, type, required)

设计:
  - 每个子表通过 api_id FK 关联 api_endpoint.id (CASCADE)
  - 保留原 api_endpoint 中的 *_json 列做兼容, 新数据优先写入子表
  - 迁移不搬运历史数据, 后续按需从 JSON 迁移
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ================================================================
    # 1. api_header 表
    # ================================================================
    op.create_table(
        "api_header",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("api_id", sa.Integer(), nullable=False, comment="关联的接口 ID"),
        sa.Column("key", sa.String(200), nullable=False, comment="Header 名, 如 Content-Type"),
        sa.Column("value", sa.Text(), nullable=True, comment="Header 值"),
        sa.Column("required", sa.Boolean(), nullable=False, default=True, comment="是否必填"),
        sa.Column("sort_order", sa.Integer(), nullable=False, default=0, comment="排序序号"),
        sa.ForeignKeyConstraint(["api_id"], ["api_endpoint.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="API 请求头子表",
    )
    op.create_index("ix_api_header_api_id", "api_header", ["api_id"])

    # ================================================================
    # 2. api_body 表
    # ================================================================
    op.create_table(
        "api_body",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("api_id", sa.Integer(), nullable=False, comment="关联的接口 ID"),
        sa.Column("body_type", sa.String(50), nullable=False, default="application/json",
                  comment="Body 类型: application/json/form-data/x-www-form-urlencoded/raw"),
        sa.Column("schema_json", sa.Text(), nullable=True, comment="JSON Schema 定义"),
        sa.Column("example_json", sa.Text(), nullable=True, comment="示例数据 JSON"),
        sa.Column("raw_text", sa.Text(), nullable=True, comment="原始文本(当 body_type=raw 时)"),
        sa.ForeignKeyConstraint(["api_id"], ["api_endpoint.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="API 请求体子表",
    )
    op.create_index("ix_api_body_api_id", "api_body", ["api_id"])

    # ================================================================
    # 3. api_parameter 表
    # ================================================================
    op.create_table(
        "api_parameter",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("api_id", sa.Integer(), nullable=False, comment="关联的接口 ID"),
        sa.Column("location", sa.String(20), nullable=False, default="query",
                  comment="参数位置: query/path/header/cookie"),
        sa.Column("name", sa.String(200), nullable=False, comment="参数名"),
        sa.Column("type", sa.String(50), nullable=False, default="string",
                  comment="参数类型: string/integer/number/boolean/array/object"),
        sa.Column("required", sa.Boolean(), nullable=False, default=False, comment="是否必填"),
        sa.Column("default_value", sa.String(500), nullable=True, comment="默认值"),
        sa.Column("description", sa.String(500), nullable=True, comment="参数说明"),
        sa.Column("example", sa.String(500), nullable=True, comment="示例值"),
        sa.Column("sort_order", sa.Integer(), nullable=False, default=0, comment="排序序号"),
        sa.ForeignKeyConstraint(["api_id"], ["api_endpoint.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="API 参数子表",
    )
    op.create_index("ix_api_parameter_api_id", "api_parameter", ["api_id"])


def downgrade() -> None:
    op.drop_index("ix_api_parameter_api_id", table_name="api_parameter")
    op.drop_table("api_parameter")
    op.drop_index("ix_api_body_api_id", table_name="api_body")
    op.drop_table("api_body")
    op.drop_index("ix_api_header_api_id", table_name="api_header")
    op.drop_table("api_header")
