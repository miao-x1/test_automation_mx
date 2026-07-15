"""
脚本模型
"""
from sqlalchemy import Column, String, Integer, Text, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import OwnedModel


class Script(OwnedModel):
    """
    脚本表
    
    存储生成的Playwright测试脚本
    一个任务对应一个脚本
    """
    __tablename__ = "script"
    
    task_id = Column(
        Integer,
        ForeignKey("task.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
        comment="任务ID"
    )
    
    script_type = Column(
        String(50),
        nullable=False,
        default="playwright",
        comment="脚本类型"
    )
    
    script_content = Column(
        Text,
        nullable=False,
        comment="脚本内容"
    )
    
    script_language = Column(
        String(20),
        nullable=False,
        default="python",
        comment="脚本语言"
    )
    
    file_path = Column(
        String(512),
        nullable=True,
        comment="脚本文件保存路径"
    )

    # 知识库审核状态
    kb_status = Column(
        String(20),
        default="approved",
        nullable=False,
        index=True,
        comment="知识库审核状态: draft/approved/rejected"
    )

    # 脚本来源
    script_source = Column(
        String(20),
        default="generated",
        nullable=False,
        comment="脚本来源: generated(新生成)/reused(复用历史)"
    )

    # 复用次数
    reuse_count = Column(
        Integer,
        default=0,
        nullable=False,
        comment="被其他需求复用的次数"
    )

    # 关联关系
    task = relationship("Task", back_populates="script")
    
    def __repr__(self):
        return f"<Script(id={self.id}, task_id={self.task_id}, type={self.script_type})>"
