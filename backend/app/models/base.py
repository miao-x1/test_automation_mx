"""
通用数据库模型基类

层次：
- BaseModel: 基础字段（id, created_at, updated_at）
- OwnedModel: 继承BaseModel，增加 user_id / created_by（数据隔离）
"""
from datetime import datetime
from sqlalchemy import Column, Integer, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declared_attr
from app.db.database import Base


class BaseModel(Base):
    """
    通用模型基类
    
    所有模型继承此类，自动添加：
    - id: 主键
    - created_at: 创建时间
    - updated_at: 更新时间
    """
    __abstract__ = True
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    created_at = Column(
        DateTime,
        default=datetime.now,
        nullable=False,
        comment="创建时间"
    )
    updated_at = Column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now,
        nullable=False,
        comment="更新时间"
    )
    
    @declared_attr
    def __tablename__(cls):
        """自动生成表名（类名转小写下划线）"""
        import re
        name = re.sub(r'(?<!^)(?=[A-Z])', '_', cls.__name__).lower()
        return name
    
    def to_dict(self):
        """转换为字典"""
        return {
            column.name: getattr(self, column.name)
            for column in self.__table__.columns
        }
    
    def __repr__(self):
        """字符串表示"""
        return f"<{self.__class__.__name__}(id={self.id})>"


class OwnedModel(BaseModel):
    """
    数据隔离模型基类
    
    继承BaseModel，增加用户归属字段：
    - user_id: 所属用户ID（数据隔离核心字段）
    - created_by: 创建者用户名（冗余字段，便于展示）
    
    所有需要数据隔离的业务模型必须继承此类。
    查询规则：SELECT * FROM xxx WHERE user_id=current_user
    """
    __abstract__ = True

    user_id = Column(
        Integer,
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="所属用户ID（数据隔离）"
    )

    created_by = Column(
        Integer,
        nullable=True,
        index=True,
        comment="创建者用户ID"
    )
