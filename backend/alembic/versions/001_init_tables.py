"""初始化数据库表结构

Revision ID: 001
Revises: 
Create Date: 2026-06-04 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级：创建所有表"""
    
    # 创建task表
    op.create_table(
        'task',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='主键ID'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新时间'),
        sa.Column('task_name', sa.String(length=255), nullable=False, comment='任务名称'),
        sa.Column('status', sa.Enum('PENDING', 'PROCESSING', 'SUCCESS', 'FAILED', name='taskstatus'), nullable=False, comment='任务状态'),
        sa.Column('error_message', sa.String(length=1024), nullable=True, comment='错误信息'),
        sa.PrimaryKeyConstraint('id'),
        comment='任务表'
    )
    op.create_index('ix_task_task_name', 'task', ['task_name'])
    op.create_index('ix_task_status', 'task', ['status'])
    op.create_index('idx_task_status_created', 'task', ['status', 'created_at'])
    
    # 创建image_file表
    op.create_table(
        'image_file',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='主键ID'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新时间'),
        sa.Column('task_id', sa.Integer(), nullable=False, comment='任务ID'),
        sa.Column('original_filename', sa.String(length=255), nullable=False, comment='原始文件名'),
        sa.Column('file_path', sa.String(length=512), nullable=False, comment='文件存储路径'),
        sa.Column('file_size', sa.BigInteger(), nullable=False, comment='文件大小（字节）'),
        sa.Column('file_type', sa.String(length=50), nullable=False, comment='文件MIME类型'),
        sa.Column('width', sa.Integer(), nullable=True, comment='图片宽度'),
        sa.Column('height', sa.Integer(), nullable=True, comment='图片高度'),
        sa.Column('md5_hash', sa.String(length=32), nullable=True, comment='文件MD5哈希值'),
        sa.ForeignKeyConstraint(['task_id'], ['task.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('file_path'),
        comment='图片文件表'
    )
    op.create_index('ix_image_file_task_id', 'image_file', ['task_id'])
    op.create_index('ix_image_file_md5_hash', 'image_file', ['md5_hash'])
    op.create_index('idx_image_task_created', 'image_file', ['task_id', 'created_at'])
    
    # 创建analysis_result表
    op.create_table(
        'analysis_result',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='主键ID'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新时间'),
        sa.Column('task_id', sa.Integer(), nullable=False, comment='任务ID'),
        sa.Column('agent_type', sa.String(length=50), nullable=False, comment='使用的Agent类型'),
        sa.Column('page_type', sa.String(length=100), nullable=True, comment='页面类型（如：登录页、列表页）'),
        sa.Column('elements_json', sa.Text(), nullable=True, comment='识别的UI元素JSON'),
        sa.Column('interactions_json', sa.Text(), nullable=True, comment='交互操作JSON'),
        sa.Column('layout_json', sa.Text(), nullable=True, comment='布局信息JSON'),
        sa.Column('analysis_summary', sa.Text(), nullable=True, comment='分析总结'),
        sa.Column('raw_output', sa.Text(), nullable=True, comment='Agent原始输出'),
        sa.ForeignKeyConstraint(['task_id'], ['task.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('task_id'),
        comment='分析结果表'
    )
    op.create_index('ix_analysis_result_task_id', 'analysis_result', ['task_id'])
    
    # 创建script表
    op.create_table(
        'script',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='主键ID'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新时间'),
        sa.Column('task_id', sa.Integer(), nullable=False, comment='任务ID'),
        sa.Column('script_type', sa.String(length=50), nullable=False, comment='脚本类型'),
        sa.Column('script_content', sa.Text(), nullable=False, comment='脚本内容'),
        sa.Column('script_language', sa.String(length=20), nullable=False, comment='脚本语言'),
        sa.Column('file_path', sa.String(length=512), nullable=True, comment='脚本文件保存路径'),
        sa.ForeignKeyConstraint(['task_id'], ['task.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('task_id'),
        comment='脚本表'
    )
    op.create_index('ix_script_task_id', 'script', ['task_id'])


def downgrade() -> None:
    """降级：删除所有表"""
    op.drop_table('script')
    op.drop_table('analysis_result')
    op.drop_table('image_file')
    op.drop_table('task')
