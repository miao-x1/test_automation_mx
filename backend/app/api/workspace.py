"""工作空间 / 团队 / 项目 / 邀请。"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import require_auth
from app.db.database import get_db
from app.models.team import (
    Organization,
    OrganizationInvite,
    OrganizationMember,
    OrgRole,
    Project,
    ProjectMember,
    ProjectRole,
)
from app.models.user import User
from app.schemas.response import Response
from app.services.workspace_service import (
    ADMIN,
    LIMITED,
    RUN,
    VIEW,
    accept_invite,
    bootstrap_user_workspace,
    cancel_invite,
    create_invite,
    decline_invite,
    invite_status,
    org_role,
    require_org,
    require_project,
    visible_project_ids,
)
from app.services.test_job_service import (
    create_pipeline,
    dashboard_activity,
    job_out,
    pipeline_out,
    project_overview,
    refresh_run,
    run_out,
    run_pipeline,
    sync_project_jobs,
)
from app.models.test_job import RegressionPipeline, RegressionRun
from app.models.test_environment import TestEnvironment

router = APIRouter()


class OrgCreate(BaseModel):
    name: str
    description: Optional[str] = None
    avatar: Optional[str] = None


class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None
    organization_id: int


class MemberRoleBody(BaseModel):
    role: str


class AddMemberBody(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    user_id: Optional[int] = None
    role: str = ProjectRole.TESTER


class InviteBody(BaseModel):
    email: Optional[str] = None
    role: str = OrgRole.MEMBER
    project_id: Optional[int] = None
    project_role: Optional[str] = ProjectRole.TESTER


class AcceptInviteBody(BaseModel):
    token: str


class PipelineCreate(BaseModel):
    name: str
    description: Optional[str] = None
    job_ids: list[int] = []


class ProjectEnvCreate(BaseModel):
    name: str
    base_url: Optional[str] = None
    account: Optional[str] = None
    password: Optional[str] = None
    description: Optional[str] = None


def _user_brief(db: Session, user_id: int) -> dict:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {"id": user_id, "username": "", "display_name": ""}
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name or user.username,
        "email": user.email,
        "avatar": user.avatar,
    }


def _org_out(org: Organization, db: Session | None = None, user_id: int | None = None) -> dict:
    data = {
        "id": org.id,
        "name": org.name,
        "description": org.description,
        "owner_id": org.owner_id,
        "avatar": org.avatar,
        "is_personal": org.is_personal,
        "created_at": str(org.created_at) if org.created_at else None,
    }
    if db is not None:
        data["member_count"] = db.query(OrganizationMember).filter(OrganizationMember.organization_id == org.id).count()
        data["project_count"] = db.query(Project).filter(Project.organization_id == org.id).count()
        if user_id is not None:
            data["my_role"] = org_role(db, user_id, org.id)
    return data


def _project_out(db: Session, project: Project) -> dict:
    member_count = db.query(ProjectMember).filter(ProjectMember.project_id == project.id).count()
    org = db.query(Organization).filter(Organization.id == project.organization_id).first()
    stats = project_overview(db, project.id)
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "organization_id": project.organization_id,
        "organization_name": org.name if org else "",
        "is_default": project.is_default,
        "member_count": member_count,
        "last_test_at": stats.get("last_test_at"),
        "status": stats.get("status") or "IDLE",
        "success_rate": stats.get("success_rate"),
        "job_count": stats.get("job_count"),
        "created_at": str(project.created_at) if project.created_at else None,
    }


@router.get("/workspace", summary="我的工作空间")
def get_workspace(user: User = Depends(require_auth), db: Session = Depends(get_db)):
    boot = bootstrap_user_workspace(db, user)
    org_ids = [
        m.organization_id
        for m in db.query(OrganizationMember).filter(OrganizationMember.user_id == user.id).all()
    ]
    orgs = db.query(Organization).filter(Organization.id.in_(org_ids or [0])).all()
    project_ids = visible_project_ids(db, user)
    projects = db.query(Project).filter(Project.id.in_(project_ids or [0])).all()
    activity = dashboard_activity(db, project_ids)
    recent_activity = [
        {
            "type": "job",
            "title": job.get("name"),
            "status": job.get("status"),
            "project_id": job.get("project_id"),
            "at": job.get("updated_at") or job.get("created_at"),
        }
        for job in activity["recent_jobs"]
    ]
    return Response(code=200, message="ok", data={
        "default_project_id": boot["project"].id,
        "organizations": [_org_out(o, db, user.id) for o in orgs],
        "projects": [_project_out(db, p) for p in projects],
        "recent_activity": recent_activity,
        "recent_jobs": activity["recent_jobs"],
        "recent_failures": activity["recent_failures"],
    })


@router.post("/organizations", summary="创建团队")
def create_organization(body: OrgCreate, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="请填写团队名称")
    org = Organization(name=body.name.strip(), description=body.description, avatar=body.avatar, owner_id=user.id, is_personal=False)
    db.add(org)
    db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=OrgRole.OWNER))
    project = Project(organization_id=org.id, name="默认项目", created_by=user.id, is_default=True)
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=ProjectRole.PROJECT_ADMIN))
    db.commit()
    db.refresh(org)
    db.refresh(project)
    return Response(code=200, message="团队已创建", data={"organization": _org_out(org, db, user.id), "project": _project_out(db, project)})


@router.patch("/organizations/{organization_id}", summary="修改团队信息")
def patch_organization(organization_id: int, body: OrgCreate, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    org = require_org(db, user, organization_id, admin=True)
    if body.name and body.name.strip():
        org.name = body.name.strip()
    if body.description is not None:
        org.description = body.description
    if body.avatar is not None:
        org.avatar = body.avatar
    db.commit()
    db.refresh(org)
    return Response(code=200, message="团队已更新", data=_org_out(org, db, user.id))


@router.get("/organizations/{organization_id}", summary="团队详情")
def get_organization(organization_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    org = require_org(db, user, organization_id)
    members = db.query(OrganizationMember).filter(OrganizationMember.organization_id == organization_id).all()
    role = org_role(db, user.id, organization_id)
    projects = db.query(Project).filter(Project.organization_id == organization_id).all()
    if role not in {OrgRole.OWNER, OrgRole.ADMIN, OrgRole.OWNER.value, OrgRole.ADMIN.value}:
        allowed = set(visible_project_ids(db, user))
        projects = [p for p in projects if p.id in allowed]
    return Response(code=200, message="ok", data={
        "organization": _org_out(org, db, user.id),
        "my_role": role,
        "members": [{**_user_brief(db, m.user_id), "role": m.role, "joined_at": str(m.created_at) if m.created_at else None} for m in members],
        "projects": [_project_out(db, p) for p in projects],
    })


@router.post("/organizations/{organization_id}/members", summary="添加团队成员")
def add_org_member(organization_id: int, body: AddMemberBody, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    require_org(db, user, organization_id, admin=True)
    target = _find_user(db, body)
    existing = db.query(OrganizationMember).filter(
        OrganizationMember.organization_id == organization_id,
        OrganizationMember.user_id == target.id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="该用户已在团队中")
    role = body.role if body.role in {r.value for r in OrgRole} else OrgRole.MEMBER
    if role == OrgRole.OWNER:
        raise HTTPException(status_code=400, detail="不能直接指定所有者")
    db.add(OrganizationMember(organization_id=organization_id, user_id=target.id, role=role))
    db.commit()
    return Response(code=200, message="已加入团队")


@router.patch("/organizations/{organization_id}/members/{member_id}", summary="修改团队角色")
def patch_org_member(organization_id: int, member_id: int, body: MemberRoleBody, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    require_org(db, user, organization_id, admin=True)
    row = db.query(OrganizationMember).filter(
        OrganizationMember.organization_id == organization_id,
        OrganizationMember.user_id == member_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="成员不存在")
    if row.role == OrgRole.OWNER:
        raise HTTPException(status_code=400, detail="不能修改所有者角色")
    if body.role == OrgRole.OWNER:
        raise HTTPException(status_code=400, detail="不能转让所有者")
    row.role = body.role
    db.commit()
    return Response(code=200, message="角色已更新")


@router.delete("/organizations/{organization_id}/members/{member_id}", summary="移除团队成员")
def remove_org_member(organization_id: int, member_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    require_org(db, user, organization_id, admin=True)
    row = db.query(OrganizationMember).filter(
        OrganizationMember.organization_id == organization_id,
        OrganizationMember.user_id == member_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="成员不存在")
    if row.role == OrgRole.OWNER:
        raise HTTPException(status_code=400, detail="不能移除所有者")
    db.query(ProjectMember).filter(
        ProjectMember.user_id == member_id,
        ProjectMember.project_id.in_(
            db.query(Project.id).filter(Project.organization_id == organization_id)
        ),
    ).delete(synchronize_session=False)
    db.delete(row)
    db.commit()
    return Response(code=200, message="已移除")


@router.post("/organizations/{organization_id}/invites", summary="邀请成员")
def invite_member(organization_id: int, body: InviteBody, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    require_org(db, user, organization_id, admin=True)
    invite = create_invite(
        db,
        organization_id,
        user.id,
        email=body.email,
        role=body.role,
        project_id=body.project_id,
        project_role=body.project_role,
    )
    return Response(code=200, message="邀请已创建", data={
        "token": invite.token,
        "email": invite.email,
        "expires_at": str(invite.expires_at),
        "invite_path": f"/workspace/invite/{invite.token}",
    })


@router.get("/organizations/{organization_id}/invites", summary="邀请列表")
def list_invites(organization_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    require_org(db, user, organization_id, admin=True)
    rows = db.query(OrganizationInvite).filter(OrganizationInvite.organization_id == organization_id).order_by(OrganizationInvite.created_at.desc()).all()
    return Response(code=200, message="ok", data={"items": [{
        "id": row.id,
        "email": row.email,
        "role": row.role,
        "project_id": row.project_id,
        "project_role": row.project_role,
        "status": invite_status(row),
        "token": row.token if invite_status(row) == "pending" else None,
        "invite_path": f"/workspace/invite/{row.token}" if invite_status(row) == "pending" else None,
        "expires_at": str(row.expires_at) if row.expires_at else None,
        "created_at": str(row.created_at) if row.created_at else None,
    } for row in rows]})


@router.delete("/organizations/{organization_id}/invites/{invite_id}", summary="取消邀请")
def cancel_invite_api(organization_id: int, invite_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    require_org(db, user, organization_id, admin=True)
    cancel_invite(db, invite_id, organization_id)
    return Response(code=200, message="邀请已取消")


@router.get("/invites/{token}", summary="查看邀请")
def peek_invite(token: str, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    invite = db.query(OrganizationInvite).filter(OrganizationInvite.token == token).first()
    if not invite:
        raise HTTPException(status_code=404, detail="邀请不存在")
    org = db.query(Organization).filter(Organization.id == invite.organization_id).first()
    return Response(code=200, message="ok", data={
        "status": invite_status(invite),
        "organization_id": invite.organization_id,
        "organization_name": org.name if org else "",
        "email": invite.email,
        "role": invite.role,
        "project_id": invite.project_id,
        "expires_at": str(invite.expires_at) if invite.expires_at else None,
        "email_mismatch": bool(invite.email and user.email and invite.email.lower() != user.email.lower()),
    })


@router.post("/invites/accept", summary="接受邀请")
def accept_invite_api(body: AcceptInviteBody, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    data = accept_invite(db, user, body.token)
    return Response(code=200, message="已加入团队", data=data)


@router.post("/invites/decline", summary="拒绝邀请")
def decline_invite_api(body: AcceptInviteBody, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    decline_invite(db, user, body.token)
    return Response(code=200, message="已拒绝邀请")


@router.get("/projects", summary="我的项目")
def list_projects(user: User = Depends(require_auth), db: Session = Depends(get_db)):
    ids = visible_project_ids(db, user)
    projects = db.query(Project).filter(Project.id.in_(ids or [0])).all()
    return Response(code=200, message="ok", data={"items": [_project_out(db, p) for p in projects]})


@router.post("/projects", summary="创建项目")
def create_project(body: ProjectCreate, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    require_org(db, user, body.organization_id, admin=True)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="请填写项目名称")
    project = Project(
        organization_id=body.organization_id,
        name=body.name.strip(),
        description=body.description,
        created_by=user.id,
    )
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=ProjectRole.PROJECT_ADMIN))
    db.commit()
    db.refresh(project)
    return Response(code=200, message="项目已创建", data=_project_out(db, project))


@router.get("/projects/{project_id}", summary="项目详情")
def get_project(project_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    info = require_project(db, user, project_id, LIMITED)
    members = db.query(ProjectMember).filter(ProjectMember.project_id == project_id).all()
    overview = project_overview(db, project_id) if info["can_view"] else {
        "job_count": None,
        "success_rate": None,
        "status": "RESTRICTED",
        "recent_runs": [],
    }
    return Response(code=200, message="ok", data={
        "project": {**_project_out(db, info["project"]), **overview},
        "overview": overview,
        "my_role": info["project_role"] or info["org_role"],
        "can_limited": info["can_limited"],
        "can_view": info["can_view"],
        "can_run": info["can_run"],
        "can_admin": info["can_admin"],
        "members": [{**_user_brief(db, m.user_id), "role": m.role} for m in members],
    })


@router.patch("/projects/{project_id}", summary="修改项目")
def patch_project(project_id: int, body: OrgCreate, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    info = require_project(db, user, project_id, ADMIN)
    if body.name.strip():
        info["project"].name = body.name.strip()
    info["project"].description = body.description
    db.commit()
    return Response(code=200, message="已更新", data=_project_out(db, info["project"]))


@router.delete("/projects/{project_id}", summary="删除项目")
def delete_project(project_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    info = require_project(db, user, project_id, ADMIN)
    if info["project"].is_default:
        raise HTTPException(status_code=400, detail="默认项目不能删除")
    db.query(ProjectMember).filter(ProjectMember.project_id == project_id).delete()
    db.delete(info["project"])
    db.commit()
    return Response(code=200, message="已删除")


@router.post("/projects/{project_id}/members", summary="添加项目成员")
def add_project_member(project_id: int, body: AddMemberBody, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    require_project(db, user, project_id, ADMIN)
    target = _find_user(db, body)
    existing = db.query(ProjectMember).filter(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == target.id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="该用户已在项目中")
    role = body.role if body.role in {r.value for r in ProjectRole} else ProjectRole.TESTER
    db.add(ProjectMember(project_id=project_id, user_id=target.id, role=role))
    db.commit()
    return Response(code=200, message="已加入项目")


@router.patch("/projects/{project_id}/members/{member_id}", summary="修改项目角色")
def patch_project_member(project_id: int, member_id: int, body: MemberRoleBody, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    require_project(db, user, project_id, ADMIN)
    row = db.query(ProjectMember).filter(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == member_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="成员不存在")
    if body.role not in {r.value for r in ProjectRole}:
        raise HTTPException(status_code=400, detail="无效角色")
    row.role = body.role
    db.commit()
    return Response(code=200, message="角色已更新")


@router.delete("/projects/{project_id}/members/{member_id}", summary="移除项目成员")
def remove_project_member(project_id: int, member_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    require_project(db, user, project_id, ADMIN)
    row = db.query(ProjectMember).filter(
        ProjectMember.project_id == project_id,
        ProjectMember.user_id == member_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="成员不存在")
    db.delete(row)
    db.commit()
    return Response(code=200, message="已移除")


@router.get("/projects/{project_id}/jobs", summary="项目测试任务")
def list_project_jobs(project_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    require_project(db, user, project_id, VIEW)
    jobs = sync_project_jobs(db, project_id)
    return Response(code=200, message="ok", data={"items": [job_out(job) for job in jobs]})


@router.get("/projects/{project_id}/pipelines", summary="项目回归流程")
def list_pipelines(project_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    require_project(db, user, project_id, VIEW)
    rows = db.query(RegressionPipeline).filter(RegressionPipeline.project_id == project_id).all()
    return Response(code=200, message="ok", data={"items": [pipeline_out(db, row) for row in rows]})


@router.post("/projects/{project_id}/pipelines", summary="创建回归流程")
def create_project_pipeline(project_id: int, body: PipelineCreate, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    require_project(db, user, project_id, RUN)
    pipeline = create_pipeline(db, project_id, user, body.name, body.job_ids, body.description)
    return Response(code=200, message="回归流程已创建", data=pipeline_out(db, pipeline))


@router.post("/projects/{project_id}/pipelines/{pipeline_id}/run", summary="运行回归测试")
def run_project_pipeline(project_id: int, pipeline_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    require_project(db, user, project_id, RUN)
    pipeline = db.query(RegressionPipeline).filter(
        RegressionPipeline.id == pipeline_id,
        RegressionPipeline.project_id == project_id,
    ).first()
    if not pipeline:
        raise HTTPException(status_code=404, detail="回归流程不存在")
    run = run_pipeline(db, pipeline, user)
    return Response(code=200, message="回归已完成", data=run_out(run))


@router.get("/projects/{project_id}/pipelines/{pipeline_id}/runs", summary="回归执行历史")
def list_pipeline_runs(project_id: int, pipeline_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    require_project(db, user, project_id, VIEW)
    rows = (
        db.query(RegressionRun)
        .filter(RegressionRun.project_id == project_id, RegressionRun.pipeline_id == pipeline_id)
        .order_by(RegressionRun.created_at.desc())
        .limit(20)
        .all()
    )
    items = []
    for row in rows:
        if row.status == "RUNNING":
            row = refresh_run(db, row)
        items.append(run_out(row))
    return Response(code=200, message="ok", data={"items": items})


@router.get("/projects/{project_id}/environments", summary="项目测试环境")
def list_project_envs(project_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    require_project(db, user, project_id, VIEW)
    rows = db.query(TestEnvironment).filter(
        TestEnvironment.project_id == project_id,
        TestEnvironment.is_deleted.is_(False),
    ).all()
    return Response(code=200, message="ok", data={"items": [row.to_dict() for row in rows]})


@router.post("/projects/{project_id}/environments", summary="保存项目测试环境")
def create_project_env(project_id: int, body: ProjectEnvCreate, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    require_project(db, user, project_id, ADMIN)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="请填写环境名称")
    variables = None
    if body.account or body.password:
        variables = json.dumps({"account": body.account or "", "has_password": bool(body.password)}, ensure_ascii=False)
    env = TestEnvironment(
        project_id=project_id,
        user_id=user.id,
        created_by=user.id,
        name=body.name.strip(),
        display_name=body.name.strip(),
        description=body.description,
        env_type="test",
        base_url=body.base_url,
        variables_json=variables,
    )
    db.add(env)
    db.commit()
    db.refresh(env)
    return Response(code=200, message="环境已保存", data=env.to_dict())


def _find_user(db: Session, body: AddMemberBody) -> User:
    q = db.query(User)
    if body.user_id:
        user = q.filter(User.id == body.user_id).first()
    elif body.username:
        user = q.filter(User.username == body.username.strip()).first()
    elif body.email:
        user = q.filter(User.email == body.email.strip()).first()
    else:
        raise HTTPException(status_code=400, detail="请提供用户名或邮箱")
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user
