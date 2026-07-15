"""
思维导图模型

存储用例的思维导图数据
"""
from sqlalchemy import Column, String, Integer, Text, ForeignKey
from app.models.base import BaseModel


class CaseMindmap(BaseModel):
    """用例思维导图"""
    case_task_id = Column(
        Integer, ForeignKey("case_task.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="关联用例任务ID"
    )
    mindmap_data = Column(Text, nullable=True, comment="思维导图数据(JSON树形结构)")
    format = Column(
        String(20), nullable=False, default="json",
        comment="格式: json/markdown/xmind"
    )
    version = Column(Integer, nullable=False, default=1, comment="版本号")
