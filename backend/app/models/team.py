"""团队 / 项目 / 成员 / 邀请。"""
import enum
from datetime import datetime
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Index, UniqueConstraint, Text
from app.models.base import BaseModel


class OrgRole(str, enum.Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"


class ProjectRole(str, enum.Enum):
    PROJECT_ADMIN = "PROJECT_ADMIN"
    TESTER = "TESTER"
    REPORTER = "REPORTER"
    VIEWER = "VIEWER"
    GUEST = "GUEST"  # 兼容旧数据，等同 VIEWER


class Organization(BaseModel):
    __tablename__ = "organization"

    name = Column(String(100), nullable=False, comment="团队名称")
    description = Column(String(512), nullable=True, comment="团队描述")
    owner_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    avatar = Column(String(512), nullable=True)
    is_personal = Column(Boolean, default=False, nullable=False, comment="是否个人空间")


class OrganizationMember(BaseModel):
    __tablename__ = "organization_member"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", name="uq_org_member"),)

    organization_id = Column(Integer, ForeignKey("organization.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False, default=OrgRole.MEMBER, comment="OWNER/ADMIN/MEMBER")


class Project(BaseModel):
    __tablename__ = "project"

    organization_id = Column(Integer, ForeignKey("organization.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(String(512), nullable=True)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True)
    is_default = Column(Boolean, default=False, nullable=False)


class ProjectMember(BaseModel):
    __tablename__ = "project_member"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member"),)

    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False, default=ProjectRole.TESTER, comment="PROJECT_ADMIN/TESTER/VIEWER")


class OrganizationInvite(BaseModel):
    __tablename__ = "organization_invite"

    organization_id = Column(Integer, ForeignKey("organization.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String(255), nullable=True, index=True)
    token = Column(String(64), nullable=False, unique=True, index=True)
    role = Column(String(20), nullable=False, default=OrgRole.MEMBER)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="SET NULL"), nullable=True)
    project_role = Column(String(20), nullable=True)
    expires_at = Column(DateTime, nullable=False)
    accepted_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    declined_at = Column(DateTime, nullable=True)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)


Index("idx_org_owner", Organization.owner_id)
Index("idx_project_org", Project.organization_id)
