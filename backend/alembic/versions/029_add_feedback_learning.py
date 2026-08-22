"""add feedback learning tables

Revision ID: 029
Revises: 028
Create Date: 2026-07-21

新增 AI 测试反馈学习系统两张表:
1. feedback_learning_record  - 反馈学习记录(成功/失败/修改案例)
2. feedback_optimization      - 优化建议(RAG/Prompt/策略优化)

数据流:
  执行记录/审核记录/资产版本 → feedback_learning_record(收集)
                                        ↓
                              FeedbackAgent(LLM 分析)
                                        ↓
                              feedback_optimization(优化建议)
                                        ↓
                    应用到 RAG(检索参数) / PromptManager(新版本) / 生成策略(配置)
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ================================================================
    # 1. feedback_learning_record 表
    # ================================================================
    op.create_table(
        "feedback_learning_record",
        # --- 通用基类字段 ---
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),

        # --- 基础信息 ---
        sa.Column("record_type", sa.String(length=20), nullable=False,
                  comment="记录类型: success/failure/modification"),
        sa.Column("source", sa.String(length=30), nullable=False,
                  comment="数据来源: execution/review/asset_version/feedback/quality_report"),
        sa.Column("source_id", sa.Integer(), nullable=True,
                  comment="来源记录ID"),

        # --- 关联 Agent ---
        sa.Column("agent_name", sa.String(length=64), nullable=True,
                  comment="关联Agent名"),

        # --- 案例内容 ---
        sa.Column("content_json", sa.Text(), nullable=True, comment="案例内容(JSON)"),
        sa.Column("analysis_json", sa.Text(), nullable=True, comment="LLM分析结果(JSON)"),

        # --- 标签与分类 ---
        sa.Column("tags", sa.String(length=500), nullable=True, comment="标签(逗号分隔)"),
        sa.Column("module", sa.String(length=100), nullable=True, comment="模块名"),

        # --- 状态 ---
        sa.Column("status", sa.String(length=20), server_default="pending",
                  nullable=False, comment="状态: pending/analyzed/archived"),

        # --- 软删除 ---
        sa.Column("is_deleted", sa.Boolean(), server_default="0",
                  nullable=False, comment="是否删除"),

        # --- 约束 ---
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
    )

    op.create_index("ix_flr_record_type", "feedback_learning_record", ["record_type"])
    op.create_index("ix_flr_agent_name", "feedback_learning_record", ["agent_name"])
    op.create_index("ix_flr_module", "feedback_learning_record", ["module"])
    op.create_index("ix_flr_status", "feedback_learning_record", ["status"])
    op.create_index("ix_flr_is_deleted", "feedback_learning_record", ["is_deleted"])
    op.create_index("ix_flr_user_id", "feedback_learning_record", ["user_id"])
    op.create_index("idx_flr_type_status", "feedback_learning_record", ["record_type", "status"])
    op.create_index("idx_flr_agent_type", "feedback_learning_record", ["agent_name", "record_type"])
    op.create_index("idx_flr_user_created", "feedback_learning_record", ["user_id", "created_at"])

    # ================================================================
    # 2. feedback_optimization 表
    # ================================================================
    op.create_table(
        "feedback_optimization",
        # --- 通用基类字段 ---
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),

        # --- 基础信息 ---
        sa.Column("title", sa.String(length=200), nullable=False, comment="优化建议标题"),
        sa.Column("description", sa.Text(), nullable=True, comment="优化建议描述"),

        # --- 优化类型 ---
        sa.Column("optimization_type", sa.String(length=20), nullable=False,
                  comment="优化类型: rag/prompt/strategy"),

        # --- 关联 Agent ---
        sa.Column("agent_name", sa.String(length=64), nullable=True,
                  comment="目标Agent名"),

        # --- 优化内容 ---
        sa.Column("optimization_json", sa.Text(), nullable=True, comment="优化内容(JSON)"),
        sa.Column("source_record_ids", sa.Text(), nullable=True,
                  comment="来源学习记录ID列表(JSON)"),

        # --- 分析摘要 ---
        sa.Column("summary", sa.Text(), nullable=True, comment="优化分析摘要"),
        sa.Column("confidence", sa.Float(), nullable=True,
                  comment="置信度(0-1)"),

        # --- 应用状态 ---
        sa.Column("status", sa.String(length=20), server_default="pending",
                  nullable=False, comment="状态: pending/applied/rejected/archived"),

        # --- 应用结果 ---
        sa.Column("applied_at", sa.String(length=30), nullable=True, comment="应用时间(ISO)"),
        sa.Column("applied_result", sa.Text(), nullable=True, comment="应用结果(JSON)"),
        sa.Column("applied_by", sa.Integer(), nullable=True, comment="应用者用户ID"),

        # --- 软删除 ---
        sa.Column("is_deleted", sa.Boolean(), server_default="0",
                  nullable=False, comment="是否删除"),

        # --- 约束 ---
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
    )

    op.create_index("ix_fo_optimization_type", "feedback_optimization", ["optimization_type"])
    op.create_index("ix_fo_agent_name", "feedback_optimization", ["agent_name"])
    op.create_index("ix_fo_status", "feedback_optimization", ["status"])
    op.create_index("ix_fo_is_deleted", "feedback_optimization", ["is_deleted"])
    op.create_index("ix_fo_user_id", "feedback_optimization", ["user_id"])
    op.create_index("idx_fo_type_status", "feedback_optimization", ["optimization_type", "status"])
    op.create_index("idx_fo_agent_type", "feedback_optimization", ["agent_name", "optimization_type"])
    op.create_index("idx_fo_user_created", "feedback_optimization", ["user_id", "created_at"])


def downgrade() -> None:
    # feedback_optimization
    op.drop_index("idx_fo_user_created", table_name="feedback_optimization")
    op.drop_index("idx_fo_agent_type", table_name="feedback_optimization")
    op.drop_index("idx_fo_type_status", table_name="feedback_optimization")
    op.drop_index("ix_fo_user_id", table_name="feedback_optimization")
    op.drop_index("ix_fo_is_deleted", table_name="feedback_optimization")
    op.drop_index("ix_fo_status", table_name="feedback_optimization")
    op.drop_index("ix_fo_agent_name", table_name="feedback_optimization")
    op.drop_index("ix_fo_optimization_type", table_name="feedback_optimization")
    op.drop_table("feedback_optimization")

    # feedback_learning_record
    op.drop_index("idx_flr_user_created", table_name="feedback_learning_record")
    op.drop_index("idx_flr_agent_type", table_name="feedback_learning_record")
    op.drop_index("idx_flr_type_status", table_name="feedback_learning_record")
    op.drop_index("ix_flr_user_id", table_name="feedback_learning_record")
    op.drop_index("ix_flr_is_deleted", table_name="feedback_learning_record")
    op.drop_index("ix_flr_status", table_name="feedback_learning_record")
    op.drop_index("ix_flr_module", table_name="feedback_learning_record")
    op.drop_index("ix_flr_agent_name", table_name="feedback_learning_record")
    op.drop_index("ix_flr_record_type", table_name="feedback_learning_record")
    op.drop_table("feedback_learning_record")
