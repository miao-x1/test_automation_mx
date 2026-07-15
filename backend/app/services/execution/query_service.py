"""
执行服务 - 查询服务

提供执行记录的查询功能：
- 查询单条执行记录
- 查询任务的所有执行记录
- 获取执行日志
- 获取报告文件路径
- 获取截图文件路径
"""
from typing import Optional
from sqlalchemy.orm import Session
from app.models.execution_record import ExecutionRecord


class ExecutionQueryService:
    """执行记录查询服务"""

    @staticmethod
    def get_execution(db: Session, execution_id: int) -> Optional[ExecutionRecord]:
        """查询执行记录"""
        return db.query(ExecutionRecord).filter(ExecutionRecord.id == execution_id).first()

    @staticmethod
    def get_executions_by_task(db: Session, task_id: int) -> list:
        """查询任务的所有执行记录"""
        return db.query(ExecutionRecord).filter(
            ExecutionRecord.task_id == task_id
        ).order_by(ExecutionRecord.created_at.desc()).all()

    @staticmethod
    def get_execution_log(db: Session, execution_id: int) -> Optional[str]:
        """获取执行日志"""
        record = db.query(ExecutionRecord).filter(ExecutionRecord.id == execution_id).first()
        return record.log_content if record else None

    @staticmethod
    def get_execution_report(db: Session, execution_id: int) -> Optional[str]:
        """获取报告文件路径"""
        record = db.query(ExecutionRecord).filter(ExecutionRecord.id == execution_id).first()
        return record.report_path if record else None

    @staticmethod
    def get_execution_screenshot(db: Session, execution_id: int) -> Optional[str]:
        """获取截图文件路径"""
        record = db.query(ExecutionRecord).filter(ExecutionRecord.id == execution_id).first()
        return record.screenshot_path if record else None
