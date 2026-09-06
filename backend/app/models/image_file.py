"""
图片文件模型
"""
from sqlalchemy import Column, String, Integer, BigInteger, ForeignKey, Index
from sqlalchemy.orm import relationship
from app.models.base import OwnedModel


class ImageFile(OwnedModel):
    """
    图片文件表
    
    存储上传的UI原型图或页面截图信息
    一个任务可以有多张图片
    """
    __tablename__ = "image_file"

    project_id = Column(
        Integer,
        ForeignKey("project.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="所属项目",
    )
    
    task_id = Column(
        Integer,
        ForeignKey("task.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="任务ID"
    )
    
    original_filename = Column(
        String(255),
        nullable=False,
        comment="原始文件名"
    )
    
    file_path = Column(
        String(512),
        nullable=False,
        unique=True,
        comment="文件存储路径"
    )
    
    file_size = Column(
        BigInteger,
        nullable=False,
        comment="文件大小（字节）"
    )
    
    file_type = Column(
        String(50),
        nullable=False,
        comment="文件MIME类型"
    )
    
    width = Column(
        Integer,
        nullable=True,
        comment="图片宽度"
    )
    
    height = Column(
        Integer,
        nullable=True,
        comment="图片高度"
    )
    
    md5_hash = Column(
        String(32),
        nullable=True,
        index=True,
        comment="文件MD5哈希值"
    )
    
    # 关联关系
    task = relationship("Task", back_populates="images")
    
    def __repr__(self):
        return f"<ImageFile(id={self.id}, task_id={self.task_id}, filename={self.original_filename})>"


# 复合索引
Index('idx_image_task_created', ImageFile.task_id, ImageFile.created_at)
