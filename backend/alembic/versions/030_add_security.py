"""add enterprise security tables

Revision ID: 030
Revises: 029
Create Date: 2026-07-21

企业级安全模块,新增四张表:
  1. api_key        - API Key 管理(哈希存储,支持过期/范围/使用统计)
  2. operation_log  - 操作日志(记录所有 API 调用,含请求体脱敏)
  3. audit_event    - 审计事件(权限变更/密钥操作/数据访问/安全告警)
  4. masking_rule   - 脱敏规则(字段级配置,支持多种脱敏策略)

安全设计:
  - API Key 仅存 SHA-256 哈希,明文只返回一次
  - 敏感字段加密使用 Fernet (app.core.crypto)
  - 操作日志 request_body 入库前自动脱敏
  - 审计事件分级(info/warning/critical)支持告警
  - masking_rule 不含用户数据,继承 BaseModel 而非 OwnedModel
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ================================================================
    # 1. api_key 表
    # ================================================================
    op.create_table(
        "api_key",
        # --- 通用基类字段 ---
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),

        # --- 基本信息 ---
        sa.Column("name", sa.String(length=100), nullable=False, comment="API Key 名称"),
        sa.Column("description", sa.String(length=500), nullable=True, comment="描述"),

        # --- 密钥存储(安全) ---
        sa.Column("key_prefix", sa.String(length=16), nullable=False,
                  comment="Key前12位(展示用)"),
        sa.Column("key_hash", sa.String(length=128), nullable=False,
                  comment="SHA-256 哈希值(不可逆)"),

        # --- 权限范围 ---
        sa.Column("scopes", sa.Text(), nullable=True,
                  comment="权限范围(JSON数组)"),

        # --- 生命周期 ---
        sa.Column("expires_at", sa.DateTime(), nullable=True, comment="过期时间"),
        sa.Column("is_active", sa.Boolean(), server_default="1",
                  nullable=False, comment="是否激活"),
        sa.Column("is_deleted", sa.Boolean(), server_default="0",
                  nullable=False, comment="是否删除"),

        # --- 使用统计 ---
        sa.Column("last_used_at", sa.DateTime(), nullable=True, comment="最后使用时间"),
        sa.Column("last_used_ip", sa.String(length=50), nullable=True,
                  comment="最后使用IP"),
        sa.Column("usage_count", sa.Integer(), server_default="0",
                  comment="使用次数"),

        # --- 约束 ---
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("key_hash", name="uq_apikey_hash"),
    )
    op.create_index("ix_apikey_id", "api_key", ["id"])
    op.create_index("ix_apikey_user_id", "api_key", ["user_id"])
    op.create_index("ix_apikey_name", "api_key", ["name"])
    op.create_index("ix_apikey_is_active", "api_key", ["is_active"])
    op.create_index("idx_apikey_user_active", "api_key", ["user_id", "is_active"])
    op.create_index("idx_apikey_prefix", "api_key", ["key_prefix"])
    op.create_index("idx_apikey_expires", "api_key", ["expires_at"])

    # ================================================================
    # 2. operation_log 表
    # ================================================================
    op.create_table(
        "operation_log",
        # --- 通用基类字段 ---
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),

        # --- 用户信息 ---
        sa.Column("username", sa.String(length=50), nullable=True,
                  comment="操作用户名(冗余)"),

        # --- 操作信息 ---
        sa.Column("action", sa.String(length=50), nullable=False,
                  comment="操作动作"),
        sa.Column("method", sa.String(length=10), nullable=False,
                  comment="HTTP方法"),
        sa.Column("path", sa.String(length=500), nullable=False,
                  comment="API路径"),

        # --- 资源信息 ---
        sa.Column("resource_type", sa.String(length=50), nullable=True,
                  comment="资源类型"),
        sa.Column("resource_id", sa.Integer(), nullable=True,
                  comment="资源ID"),

        # --- 请求信息 ---
        sa.Column("ip_address", sa.String(length=50), nullable=True,
                  comment="客户端IP"),
        sa.Column("user_agent", sa.String(length=500), nullable=True,
                  comment="User-Agent"),
        sa.Column("request_body", sa.Text(), nullable=True,
                  comment="请求体(已脱敏)"),

        # --- 响应信息 ---
        sa.Column("response_status", sa.Integer(), nullable=True,
                  comment="响应状态码"),
        sa.Column("duration", sa.Float(), nullable=True, comment="耗时(秒)"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="错误信息"),

        # --- 约束 ---
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_oplog_id", "operation_log", ["id"])
    op.create_index("ix_oplog_user_id", "operation_log", ["user_id"])
    op.create_index("ix_oplog_username", "operation_log", ["username"])
    op.create_index("ix_oplog_action", "operation_log", ["action"])
    op.create_index("ix_oplog_resource_type", "operation_log", ["resource_type"])
    op.create_index("ix_oplog_ip", "operation_log", ["ip_address"])
    op.create_index("idx_oplog_user_created", "operation_log", ["user_id", "created_at"])
    op.create_index("idx_oplog_action_created", "operation_log", ["action", "created_at"])
    op.create_index("idx_oplog_resource", "operation_log", ["resource_type", "resource_id"])
    op.create_index("idx_oplog_ip_created", "operation_log", ["ip_address", "created_at"])

    # ================================================================
    # 3. audit_event 表
    # ================================================================
    op.create_table(
        "audit_event",
        # --- 通用基类字段 ---
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),

        # --- 事件类型 ---
        sa.Column("event_type", sa.String(length=30), nullable=False,
                  comment="事件类型"),
        sa.Column("severity", sa.String(length=20), server_default="info",
                  nullable=False, comment="严重级别: info/warning/critical"),

        # --- 用户信息 ---
        sa.Column("username", sa.String(length=50), nullable=True,
                  comment="操作用户名(冗余)"),

        # --- 操作信息 ---
        sa.Column("action", sa.String(length=100), nullable=False,
                  comment="具体动作描述"),

        # --- 目标资源 ---
        sa.Column("target_type", sa.String(length=50), nullable=True,
                  comment="目标资源类型"),
        sa.Column("target_id", sa.String(length=100), nullable=True,
                  comment="目标资源ID"),

        # --- 详细信息 ---
        sa.Column("details", sa.Text(), nullable=True, comment="详细信息(JSON)"),

        # --- 环境信息 ---
        sa.Column("ip_address", sa.String(length=50), nullable=True,
                  comment="客户端IP"),

        # --- 约束 ---
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_auditevent_id", "audit_event", ["id"])
    op.create_index("ix_auditevent_user_id", "audit_event", ["user_id"])
    op.create_index("ix_auditevent_event_type", "audit_event", ["event_type"])
    op.create_index("ix_auditevent_severity", "audit_event", ["severity"])
    op.create_index("ix_auditevent_username", "audit_event", ["username"])
    op.create_index("ix_auditevent_target_type", "audit_event", ["target_type"])
    op.create_index("ix_auditevent_ip", "audit_event", ["ip_address"])
    op.create_index("idx_auditevent_type_severity", "audit_event", ["event_type", "severity"])
    op.create_index("idx_auditevent_user_created", "audit_event", ["user_id", "created_at"])
    op.create_index("idx_auditevent_target", "audit_event", ["target_type", "target_id"])
    op.create_index("idx_auditevent_critical", "audit_event", ["severity", "created_at"])

    # ================================================================
    # 4. masking_rule 表(继承 BaseModel,不含 user_id)
    # ================================================================
    op.create_table(
        "masking_rule",
        # --- BaseModel 基类字段 ---
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),

        # --- 规则信息 ---
        sa.Column("name", sa.String(length=100), nullable=False, comment="规则名称"),
        sa.Column("description", sa.String(length=500), nullable=True, comment="规则描述"),

        # --- 匹配条件 ---
        sa.Column("field_name", sa.String(length=100), nullable=True,
                  comment="字段名(精确匹配)"),
        sa.Column("field_pattern", sa.String(length=200), nullable=True,
                  comment="字段名正则匹配"),

        # --- 脱敏策略 ---
        sa.Column("mask_type", sa.String(length=20), nullable=False,
                  comment="脱敏类型"),
        sa.Column("visible_chars", sa.Integer(), server_default="4",
                  comment="可见字符数(尾部)"),
        sa.Column("custom_mask", sa.String(length=50), nullable=True,
                  comment="自定义脱敏格式"),

        # --- 状态 ---
        sa.Column("is_active", sa.Boolean(), server_default="1",
                  nullable=False, comment="是否激活"),
        sa.Column("is_deleted", sa.Boolean(), server_default="0",
                  nullable=False, comment="是否删除"),

        # --- 约束 ---
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_maskrule_id", "masking_rule", ["id"])
    op.create_index("ix_maskrule_name", "masking_rule", ["name"])
    op.create_index("ix_maskrule_field_name", "masking_rule", ["field_name"])
    op.create_index("ix_maskrule_is_active", "masking_rule", ["is_active"])
    op.create_index("idx_maskrule_field_active", "masking_rule", ["field_name", "is_active"])
    op.create_index("idx_maskrule_active", "masking_rule", ["is_active"])


def downgrade() -> None:
    # masking_rule
    op.drop_index("idx_maskrule_active", table_name="masking_rule")
    op.drop_index("idx_maskrule_field_active", table_name="masking_rule")
    op.drop_index("ix_maskrule_is_active", table_name="masking_rule")
    op.drop_index("ix_maskrule_field_name", table_name="masking_rule")
    op.drop_index("ix_maskrule_name", table_name="masking_rule")
    op.drop_index("ix_maskrule_id", table_name="masking_rule")
    op.drop_table("masking_rule")

    # audit_event
    op.drop_index("idx_auditevent_critical", table_name="audit_event")
    op.drop_index("idx_auditevent_target", table_name="audit_event")
    op.drop_index("idx_auditevent_user_created", table_name="audit_event")
    op.drop_index("idx_auditevent_type_severity", table_name="audit_event")
    op.drop_index("ix_auditevent_ip", table_name="audit_event")
    op.drop_index("ix_auditevent_target_type", table_name="audit_event")
    op.drop_index("ix_auditevent_username", table_name="audit_event")
    op.drop_index("ix_auditevent_severity", table_name="audit_event")
    op.drop_index("ix_auditevent_event_type", table_name="audit_event")
    op.drop_index("ix_auditevent_user_id", table_name="audit_event")
    op.drop_index("ix_auditevent_id", table_name="audit_event")
    op.drop_table("audit_event")

    # operation_log
    op.drop_index("idx_oplog_ip_created", table_name="operation_log")
    op.drop_index("idx_oplog_resource", table_name="operation_log")
    op.drop_index("idx_oplog_action_created", table_name="operation_log")
    op.drop_index("idx_oplog_user_created", table_name="operation_log")
    op.drop_index("ix_oplog_ip", table_name="operation_log")
    op.drop_index("ix_oplog_resource_type", table_name="operation_log")
    op.drop_index("ix_oplog_action", table_name="operation_log")
    op.drop_index("ix_oplog_username", table_name="operation_log")
    op.drop_index("ix_oplog_user_id", table_name="operation_log")
    op.drop_index("ix_oplog_id", table_name="operation_log")
    op.drop_table("operation_log")

    # api_key
    op.drop_index("idx_apikey_expires", table_name="api_key")
    op.drop_index("idx_apikey_prefix", table_name="api_key")
    op.drop_index("idx_apikey_user_active", table_name="api_key")
    op.drop_index("ix_apikey_is_active", table_name="api_key")
    op.drop_index("ix_apikey_name", table_name="api_key")
    op.drop_index("ix_apikey_user_id", table_name="api_key")
    op.drop_index("ix_apikey_id", table_name="api_key")
    op.drop_table("api_key")
