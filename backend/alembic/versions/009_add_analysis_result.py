"""add analysis_result to execution_record

Revision ID: 009
Revises: 008
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa

from app.db.alembic_ops import add_column_if_missing, table_exists

revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not table_exists('execution_record'):
        op.create_table(
            'execution_record',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='主键ID'),
            sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
            sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新时间'),
            sa.Column('task_id', sa.Integer(), nullable=True, comment='任务ID'),
            sa.Column('status', sa.String(length=20), nullable=False, comment='执行状态'),
            sa.Column('start_time', sa.String(length=30), nullable=True, comment='执行开始时间'),
            sa.Column('end_time', sa.String(length=30), nullable=True, comment='执行结束时间'),
            sa.Column('duration', sa.Float(), nullable=True, comment='执行耗时(秒)'),
            sa.Column('success_count', sa.Integer(), nullable=True, comment='通过的测试用例数'),
            sa.Column('failed_count', sa.Integer(), nullable=True, comment='失败的测试用例数'),
            sa.Column('error_message', sa.Text(), nullable=True, comment='错误信息'),
            sa.Column('log_content', sa.Text(), nullable=True, comment='执行日志'),
            sa.Column('report_path', sa.String(length=512), nullable=True, comment='测试报告路径'),
            sa.Column('screenshot_path', sa.String(length=512), nullable=True, comment='截图保存路径'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_execution_record_task_id', 'execution_record', ['task_id'])
        op.create_index('ix_execution_record_status', 'execution_record', ['status'])

    add_column_if_missing(
        'execution_record',
        sa.Column('analysis_result', sa.Text, nullable=True, comment='LLM失败分析结果(JSON): success, fail_step, root_cause, suggestion'),
    )


def downgrade() -> None:
    op.drop_column('execution_record', 'analysis_result')
