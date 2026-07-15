"""add schedule_task and schedule_run_log tables

Revision ID: 015
Revises: 014
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa

revision = '015'
down_revision = '014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'schedule_task',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(100), nullable=False, comment='任务名称'),
        sa.Column('description', sa.Text(), nullable=True, comment='任务描述'),
        sa.Column('schedule_type', sa.String(20), nullable=False, server_default='daily', comment='调度类型'),
        sa.Column('cron_expression', sa.String(100), nullable=True, comment='Cron表达式'),
        sa.Column('execute_time', sa.String(10), nullable=True, comment='执行时间HH:MM'),
        sa.Column('execute_date', sa.String(20), nullable=True, comment='执行日期YYYY-MM-DD'),
        sa.Column('start_time', sa.DateTime(), nullable=True, comment='生效开始时间'),
        sa.Column('end_time', sa.DateTime(), nullable=True, comment='生效结束时间'),
        sa.Column('timeout', sa.Integer(), server_default='3600', comment='超时时间(秒)'),
        sa.Column('max_retries', sa.Integer(), server_default='3', comment='最大重试次数'),
        sa.Column('retry_interval', sa.Integer(), server_default='60', comment='重试间隔(秒)'),
        sa.Column('notify_on_success', sa.Boolean(), server_default='0', comment='成功时通知'),
        sa.Column('notify_on_failure', sa.Boolean(), server_default='1', comment='失败时通知'),
        sa.Column('notify_channels', sa.String(200), nullable=True, comment='通知渠道'),
        sa.Column('requirement_id', sa.Integer(), sa.ForeignKey('requirement_task.id', ondelete='SET NULL'), nullable=True),
        sa.Column('task_config', sa.Text(), nullable=True, comment='任务配置JSON'),
        sa.Column('status', sa.String(20), nullable=False, server_default='active', comment='状态'),
        sa.Column('last_run_at', sa.DateTime(), nullable=True),
        sa.Column('last_run_status', sa.String(20), nullable=True),
        sa.Column('next_run_at', sa.DateTime(), nullable=True),
        sa.Column('run_count', sa.Integer(), server_default='0'),
        sa.Column('fail_count', sa.Integer(), server_default='0'),
    )
    op.create_index('idx_schedule_task_status', 'schedule_task', ['status'])

    op.create_table(
        'schedule_run_log',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('schedule_task_id', sa.Integer(), sa.ForeignKey('schedule_task.id', ondelete='CASCADE'), nullable=False),
        sa.Column('run_number', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, comment='执行状态'),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('duration', sa.Integer(), nullable=True, comment='执行耗时(秒)'),
        sa.Column('retry_count', sa.Integer(), server_default='0'),
        sa.Column('result_summary', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('task_id', sa.Integer(), sa.ForeignKey('task.id', ondelete='SET NULL'), nullable=True),
    )
    op.create_index('idx_run_log_schedule', 'schedule_run_log', ['schedule_task_id'])
    op.create_index('idx_run_log_status', 'schedule_run_log', ['status'])


def downgrade() -> None:
    op.drop_index('idx_run_log_status', table_name='schedule_run_log')
    op.drop_index('idx_run_log_schedule', table_name='schedule_run_log')
    op.drop_table('schedule_run_log')
    op.drop_index('idx_schedule_task_status', table_name='schedule_task')
    op.drop_table('schedule_task')
