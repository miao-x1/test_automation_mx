"""团队 / 项目 / 权限。不改测试引擎，只决定谁能看和跑。"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.team import (
    Organization,
    OrganizationMember,
    OrganizationInvite,
    OrgRole,
    Project,
    ProjectMember,
    ProjectRole,
)
from app.models.user import User


LIMITED = "limited"
VIEW = "view"
RUN = "run"
ADMIN = "admin"

REPORTER_ROLES = {
    ProjectRole.REPORTER,
    ProjectRole.REPORTER.value,
}
VIEWER_ROLES = {
    ProjectRole.VIEWER,
    ProjectRole.VIEWER.value,
    ProjectRole.GUEST,
    ProjectRole.GUEST.value,
}


def bootstrap_user_workspace(db: Session, user: User) -> dict:
    """保证每个用户至少有一个个人空间和默认项目。"""
    personal = (
        db.query(Organization)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .filter(
            Organization.is_personal.is_(True),
            OrganizationMember.user_id == user.id,
            OrganizationMember.role == OrgRole.OWNER,
        )
        .first()
    )
    if not personal:
        personal = Organization(
            name=f"{user.display_name or user.username} 的空间",
            description="个人测试空间",
            owner_id=user.id,
            is_personal=True,
        )
        db.add(personal)
        db.flush()
        db.add(OrganizationMember(organization_id=personal.id, user_id=user.id, role=OrgRole.OWNER))

    default = (
        db.query(Project)
        .filter(Project.organization_id == personal.id, Project.is_default.is_(True))
        .first()
    )
    if not default:
        default = Project(
            organization_id=personal.id,
            name="默认项目",
            description="自动创建的个人项目",
            created_by=user.id,
            is_default=True,
        )
        db.add(default)
        db.flush()
        db.add(ProjectMember(project_id=default.id, user_id=user.id, role=ProjectRole.PROJECT_ADMIN))
    db.commit()
    db.refresh(personal)
    db.refresh(default)
    return {"organization": personal, "project": default}


def org_role(db: Session, user_id: int, organization_id: int) -> Optional[str]:
    row = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
        )
        .first()
    )
    return row.role if row else None


def project_role(db: Session, user_id: int, project_id: int) -> Optional[str]:
    row = (
        db.query(ProjectMember)
        .filter(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
        .first()
    )
    return row.role if row else None


def get_project_or_404(db: Session, project_id: int) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def access_for(db: Session, user: User, project_id: int) -> dict:
    project = get_project_or_404(db, project_id)
    o_role = org_role(db, user.id, project.organization_id)
    p_role = project_role(db, user.id, project.id)
    org_admin = o_role in {OrgRole.OWNER, OrgRole.ADMIN, OrgRole.OWNER.value, OrgRole.ADMIN.value}
    can_admin = org_admin or p_role in {ProjectRole.PROJECT_ADMIN, ProjectRole.PROJECT_ADMIN.value}
    can_run = can_admin or p_role in {ProjectRole.TESTER, ProjectRole.TESTER.value}
    can_view = can_run or p_role in REPORTER_ROLES or org_admin
    can_limited = can_view or p_role in VIEWER_ROLES
    return {
        "project": project,
        "org_role": o_role,
        "project_role": p_role,
        "can_limited": can_limited,
        "can_view": can_view,
        "can_run": can_run,
        "can_admin": can_admin,
    }


def require_owned_project(
    db: Session,
    user: User,
    project_id: Optional[int],
    need: str = VIEW,
    fallback_user_id: Optional[int] = None,
) -> dict:
    """有 project_id 则按项目权限；旧数据按创建者兜底。"""
    if project_id:
        return require_project(db, user, project_id, need)
    if fallback_user_id is not None and fallback_user_id != user.id:
        raise HTTPException(status_code=403, detail="没有该项目的权限")
    return require_project(db, user, None, need)


def require_project(db: Session, user: User, project_id: Optional[int], need: str = VIEW) -> dict:
    if not project_id:
        boot = bootstrap_user_workspace(db, user)
        project_id = boot["project"].id
    info = access_for(db, user, project_id)
    allowed = {
        LIMITED: info["can_limited"],
        VIEW: info["can_view"],
        RUN: info["can_run"],
        ADMIN: info["can_admin"],
    }.get(need, info["can_view"])
    if not allowed:
        raise HTTPException(status_code=403, detail="没有该项目的权限")
    return info


def require_org(db: Session, user: User, organization_id: int, admin: bool = False) -> Organization:
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="团队不存在")
    role = org_role(db, user.id, organization_id)
    if not role:
        raise HTTPException(status_code=403, detail="不是该团队成员")
    if admin and role not in {OrgRole.OWNER, OrgRole.ADMIN, OrgRole.OWNER.value, OrgRole.ADMIN.value}:
        raise HTTPException(status_code=403, detail="需要团队管理员权限")
    return org


def visible_project_ids(db: Session, user: User) -> list[int]:
    bootstrap_user_workspace(db, user)
    direct = [
        r.project_id
        for r in db.query(ProjectMember).filter(ProjectMember.user_id == user.id).all()
    ]
    org_ids = [
        r.organization_id
        for r in db.query(OrganizationMember)
        .filter(
            OrganizationMember.user_id == user.id,
            OrganizationMember.role.in_([OrgRole.OWNER, OrgRole.ADMIN, OrgRole.OWNER.value, OrgRole.ADMIN.value]),
        )
        .all()
    ]
    extra = []
    if org_ids:
        extra = [p.id for p in db.query(Project).filter(Project.organization_id.in_(org_ids)).all()]
    return sorted(set(direct + extra))


def create_invite(
    db: Session,
    organization_id: int,
    created_by: int,
    email: Optional[str] = None,
    role: str = OrgRole.MEMBER,
    project_id: Optional[int] = None,
    project_role: Optional[str] = None,
) -> OrganizationInvite:
    email_norm = (email or "").strip().lower() or None
    if email_norm:
        existing_user = db.query(User).filter(User.email == email_norm).first()
        if existing_user:
            member = (
                db.query(OrganizationMember)
                .filter(
                    OrganizationMember.organization_id == organization_id,
                    OrganizationMember.user_id == existing_user.id,
                )
                .first()
            )
            if member:
                raise HTTPException(status_code=400, detail="该用户已在团队中")
        pending = (
            db.query(OrganizationInvite)
            .filter(
                OrganizationInvite.organization_id == organization_id,
                OrganizationInvite.email == email_norm,
                OrganizationInvite.accepted_at.is_(None),
                OrganizationInvite.cancelled_at.is_(None),
                OrganizationInvite.declined_at.is_(None),
            )
            .first()
        )
        if pending and (not pending.expires_at or pending.expires_at > datetime.now()):
            raise HTTPException(status_code=400, detail="该邮箱已有未使用的邀请")
    invite = OrganizationInvite(
        organization_id=organization_id,
        email=email_norm,
        token=secrets.token_urlsafe(24),
        role=role or OrgRole.MEMBER,
        project_id=project_id,
        project_role=project_role or ProjectRole.TESTER,
        expires_at=datetime.now() + timedelta(days=7),
        created_by=created_by,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite


def accept_invite(db: Session, user: User, token: str) -> dict:
    invite = db.query(OrganizationInvite).filter(OrganizationInvite.token == token).first()
    if not invite or invite.accepted_at or invite.cancelled_at or invite.declined_at:
        raise HTTPException(status_code=400, detail="邀请无效或已使用")
    if invite.expires_at and invite.expires_at < datetime.now():
        raise HTTPException(status_code=400, detail="邀请已过期")
    if invite.email and user.email and invite.email.lower() != user.email.lower():
        raise HTTPException(status_code=403, detail="邀请邮箱与当前账号不一致")

    existing = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == invite.organization_id,
            OrganizationMember.user_id == user.id,
        )
        .first()
    )
    if not existing:
        db.add(OrganizationMember(
            organization_id=invite.organization_id,
            user_id=user.id,
            role=invite.role or OrgRole.MEMBER,
        ))
    if invite.project_id:
        pm = (
            db.query(ProjectMember)
            .filter(ProjectMember.project_id == invite.project_id, ProjectMember.user_id == user.id)
            .first()
        )
        if not pm:
            db.add(ProjectMember(
                project_id=invite.project_id,
                user_id=user.id,
                role=invite.project_role or ProjectRole.TESTER,
            ))
    invite.accepted_at = datetime.now()
    db.commit()
    return {"organization_id": invite.organization_id, "project_id": invite.project_id}


def cancel_invite(db: Session, invite_id: int, organization_id: int) -> None:
    invite = db.query(OrganizationInvite).filter(
        OrganizationInvite.id == invite_id,
        OrganizationInvite.organization_id == organization_id,
    ).first()
    if not invite:
        raise HTTPException(status_code=404, detail="邀请不存在")
    if invite.accepted_at:
        raise HTTPException(status_code=400, detail="邀请已被接受")
    invite.cancelled_at = datetime.now()
    db.commit()


def decline_invite(db: Session, user: User, token: str) -> None:
    invite = db.query(OrganizationInvite).filter(OrganizationInvite.token == token).first()
    if not invite or invite.accepted_at or invite.cancelled_at or invite.declined_at:
        raise HTTPException(status_code=400, detail="邀请无效或已使用")
    if invite.expires_at and invite.expires_at < datetime.now():
        raise HTTPException(status_code=400, detail="邀请已过期")
    if invite.email and user.email and invite.email.lower() != user.email.lower():
        raise HTTPException(status_code=403, detail="邀请邮箱与当前账号不一致")
    invite.declined_at = datetime.now()
    db.commit()


def invite_status(invite: OrganizationInvite) -> str:
    if invite.accepted_at:
        return "accepted"
    if invite.cancelled_at:
        return "cancelled"
    if invite.declined_at:
        return "declined"
    if invite.expires_at and invite.expires_at < datetime.now():
        return "expired"
    return "pending"
