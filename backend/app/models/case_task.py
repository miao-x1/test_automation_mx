"""
用例生成任务模型

存储用例生成的任务信息，包括输入来源、解析结果、生成结果
"""
import enum
from sqlalchemy import Column, String, Integer, Text, Boolean
from app.db.types import MEDIUMTEXT
from app.models.base import OwnedModel


class CaseTaskStatus(str, enum.Enum):
    """用例任务状态"""
    WAITING = "waiting"         # 等待处理
    PARSING = "parsing"         # 解析中
    GENERATING = "generating"   # 用例生成中
    REVIEWING = "reviewing"     # 评审中
    COMPLETED = "completed"     # 已完成
    FAILED = "failed"           # 失败


class CaseTask(OwnedModel):
    """用例生成任务"""
    title = Column(String(200), nullable=False, comment="任务标题")
    source_type = Column(
        String(30), nullable=False, default="text",
        comment="输入来源: pdf/doc/image/video/schema/swagger/url/text"
    )
    source_file = Column(String(500), nullable=True, comment="源文件路径")
    source_url = Column(String(2000), nullable=True, comment="源URL")
    raw_input = Column(Text, nullable=True, comment="原始输入内容")
    status = Column(
        String(20), nullable=False, default=CaseTaskStatus.WAITING,
        index=True, comment="任务状态"
    )
    requirement_context = Column(MEDIUMTEXT, nullable=True, comment="解析后的RequirementContext(JSON)")
    case_set = Column(MEDIUMTEXT, nullable=True, comment="生成的CaseSet(JSON)")
    error_message = Column(Text, nullable=True, comment="错误信息")
    version = Column(Integer, nullable=False, default=1, comment="版本号")
