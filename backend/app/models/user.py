"""
用户模型

核心对象：User（用户） + Workspace（个人空间）

关系：
User 1:1 Workspace
User ├── Requirement
     ├── Task
     ├── Execution
     ├── Knowledge
     ├── Settings
     └── Feedback

所有数据通过 user_id 实现隔离，禁止跨用户访问。
"""
import enum
from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from app.models.base import BaseModel


class UserRole(str, enum.Enum):
    """用户角色"""
    ADMIN = "admin"
    USER = "user"


class User(BaseModel):
    """
    用户表

    存储用户账号信息，支持注册/登录
    """
    __tablename__ = "user"

    username = Column(
        String(50),
        nullable=False,
        unique=True,
        index=True,
        comment="用户名（唯一）"
    )

    email = Column(
        String(255),
        nullable=True,
        unique=True,
        index=True,
        comment="邮箱（可选，唯一）"
    )

    phone = Column(
        String(20),
        nullable=True,
        unique=True,
        index=True,
        comment="手机号（唯一）"
    )

    hashed_password = Column(
        String(255),
        nullable=False,
        comment="加密密码"
    )

    display_name = Column(
        String(100),
        nullable=True,
        comment="显示名称"
    )

    avatar = Column(
        String(512),
        nullable=True,
        comment="头像URL"
    )

    role = Column(
        String(20),
        default=UserRole.USER,
        nullable=False,
        index=True,
        comment="角色: admin/user"
    )

    is_active = Column(
        Boolean,
        default=True,
        nullable=False,
        comment="是否激活"
    )

    # 关联工作空间
    workspace = relationship(
        "Workspace",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    def __repr__(self):
        return f"<User(id={self.id}, username={self.username}, role={self.role})>"


class Workspace(BaseModel):
    """
    工作空间表

    每个用户拥有独立工作空间，知识库隔离通过 workspace_id 实现
    """
    __tablename__ = "workspace"

    user_id = Column(
        Integer,
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
        comment="所属用户ID"
    )

    name = Column(
        String(100),
        nullable=False,
        comment="工作空间名称"
    )

    description = Column(
        String(512),
        nullable=True,
        comment="工作空间描述"
    )

    # 关联用户
    user = relationship("User", back_populates="workspace")

    def __repr__(self):
        return f"<Workspace(id={self.id}, user_id={self.user_id}, name={self.name})>"


# 索引
Index('idx_workspace_user', Workspace.user_id)
Index('idx_user_username', User.username)
Index('idx_user_email', User.email)
