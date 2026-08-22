"""add api_execution_record

Revision ID: 021
Revises: 020
Create Date: 2026-07-20

新增 api_execution_record 表 — 单次 HTTP 请求级执行记录
供 AI 接口调试系统(ApiDebugAgent)使用
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_execution_record",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=True),

        # 关联
        sa.Column("api_id", sa.Integer(), nullable=True),
        sa.Column("case_id", sa.Integer(), nullable=True),
        sa.Column("execution_id", sa.Integer(), nullable=True),

        # 请求
        sa.Column("method", sa.String(10), nullable=False, comment="HTTP 方法: GET/POST/PUT/DELETE/PATCH"),
        sa.Column("url", sa.String(2048), nullable=False, comment="请求 URL"),
        sa.Column("headers_json", mysql.MEDIUMTEXT(), nullable=True, comment="请求头 JSON"),
        sa.Column("params_json", mysql.MEDIUMTEXT(), nullable=True, comment="Query 参数 JSON"),
        sa.Column("body_json", mysql.MEDIUMTEXT(), nullable=True, comment="请求体 JSON"),
        sa.Column("auth_json", sa.Text(), nullable=True, comment="认证信息 JSON"),

        # 响应
        sa.Column("status_code", sa.Integer(), nullable=True, comment="HTTP 状态码"),
        sa.Column("response_headers_json", mysql.MEDIUMTEXT(), nullable=True, comment="响应头 JSON"),
        sa.Column("response_body", mysql.MEDIUMTEXT(), nullable=True, comment="响应体"),
        sa.Column("response_size", sa.Integer(), nullable=True, comment="响应体大小(字节)"),

        # 结果
        sa.Column("status", sa.Enum("success", "failed", "error", "timeout", "pending", name="executionstatus", native_enum=False, length=20), nullable=False, server_default="pending", comment="执行状态"),
        sa.Column("duration", sa.Float(), nullable=False, server_default="0", comment="执行耗时(毫秒)"),
        sa.Column("error", sa.Text(), nullable=True, comment="错误信息"),

        # AI 分析
        sa.Column("analysis_status", sa.Enum("none", "analyzing", "done", "failed", name="analysisstatus", native_enum=False, length=20), nullable=False, server_default="none", comment="AI 分析状态"),
        sa.Column("analysis_result", mysql.MEDIUMTEXT(), nullable=True, comment="AI 分析结果 JSON"),
        sa.Column("analyzed_at", sa.String(30), nullable=True, comment="AI 分析完成时间"),

        # 环境
        sa.Column("env", sa.String(20), nullable=True, comment="执行环境"),
        sa.Column("trigger_source", sa.String(30), nullable=False, server_default="debug", comment="触发来源"),
        sa.Column("client_ip", sa.String(50), nullable=True, comment="客户端 IP"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="0", comment="是否删除"),

        sa.PrimaryKeyConstraint("id"),
    )

    # 索引
    op.create_index("ix_api_execution_record_api_id", "api_execution_record", ["api_id"])
    op.create_index("ix_api_execution_record_case_id", "api_execution_record", ["case_id"])
    op.create_index("ix_api_execution_record_execution_id", "api_execution_record", ["execution_id"])
    op.create_index("ix_api_execution_record_status_code", "api_execution_record", ["status_code"])
    op.create_index("idx_api_exec_user_created", "api_execution_record", ["user_id", "created_at"])
    op.create_index("idx_api_exec_status_code", "api_execution_record", ["status_code", "status"])
    op.create_index("idx_api_exec_case_status", "api_execution_record", ["case_id", "status"])


def downgrade() -> None:
    op.drop_index("idx_api_exec_case_status", table_name="api_execution_record")
    op.drop_index("idx_api_exec_status_code", table_name="api_execution_record")
    op.drop_index("idx_api_exec_user_created", table_name="api_execution_record")
    op.drop_index("ix_api_execution_record_status_code", table_name="api_execution_record")
    op.drop_index("ix_api_execution_record_execution_id", table_name="api_execution_record")
    op.drop_index("ix_api_execution_record_case_id", table_name="api_execution_record")
    op.drop_index("ix_api_execution_record_api_id", table_name="api_execution_record")
    op.drop_table("api_execution_record")
