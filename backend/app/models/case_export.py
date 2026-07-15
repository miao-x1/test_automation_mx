"""
导出记录模型

存储用例导出的历史记录
"""
import enum
from sqlalchemy import Column, String, Integer, Text, ForeignKey
from app.models.base import BaseModel


class CaseExportStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class CaseExport(BaseModel):
    """用例导出记录"""
    case_task_id = Column(
        Integer, ForeignKey("case_task.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="关联用例任务ID"
    )
    export_type = Column(
        String(20), nullable=False,
        comment="导出类型: excel/markdown/xmind/jira/testrail"
    )
    file_path = Column(String(500), nullable=True, comment="导出文件路径")
    status = Column(
        String(20), nullable=False, default=CaseExportStatus.PENDING,
        comment="导出状态: pending/completed/failed"
    )
    config = Column(Text, nullable=True, comment="导出配置(JSON)")
    error_message = Column(Text, nullable=True, comment="错误信息")
