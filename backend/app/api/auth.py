"""
认证 API 路由

提供：
- POST /api/auth/register     - 用户注册
- POST /api/auth/login        - 用户登录
- POST /api/auth/refresh      - 刷新Token
- GET  /api/auth/me           - 获取当前用户信息
- POST /api/auth/logout       - 退出登录
- PUT  /api/auth/profile      - 更新用户资料
- PUT  /api/auth/password     - 修改密码
"""
import re

from fastapi import APIRouter, Depends, HTTPException, status, Request, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field, EmailStr
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.database import get_db
from app.models.user import User, UserRole, Workspace
from app.core.config import settings
from app.core.auth import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    get_current_user, require_auth, require_admin,
    set_auth_cookies, clear_auth_cookies,
)
from app.schemas.response import Response
from app.core.logger import log
from app.services.captcha_service import create_captcha, verify_captcha
from app.services.verification_service import VerifyError, consume_sms_code, issue_sms_code

_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _require_phone(phone: str) -> str:
    value = (phone or "").strip()
    if not _PHONE_RE.match(value):
        raise HTTPException(status_code=400, detail="请输入有效的中国大陆手机号")
    return value


def _require_captcha(captcha_id: str, captcha_code: str) -> None:
    if not settings.CAPTCHA_REQUIRED:
        return
    if not verify_captcha(captcha_id or "", captcha_code or ""):
        raise HTTPException(status_code=400, detail="图形验证码错误或已过期")

router = APIRouter()


# ==================== 请求模型 ====================

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=8, max_length=100, description="密码")
    phone: str = Field(..., description="手机号")
    sms_code: str = Field(..., min_length=4, max_length=8, description="短信验证码")
    captcha_id: str = Field(..., description="图形验证码ID")
    captcha_code: str = Field(..., description="图形验证码")
    email: Optional[str] = Field(None, description="邮箱")
    display_name: Optional[str] = Field(None, max_length=100, description="显示名称")


class LoginRequest(BaseModel):
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")
    captcha_id: str = Field(default="", description="图形验证码ID")
    captcha_code: str = Field(default="", description="图形验证码")


class SendSmsRequest(BaseModel):
    phone: str = Field(..., description="手机号")
    purpose: str = Field(..., description="register/reset")
    captcha_id: str = Field(..., description="图形验证码ID")
    captcha_code: str = Field(..., description="图形验证码")


class ResetPasswordRequest(BaseModel):
    phone: str = Field(..., description="手机号")
    sms_code: str = Field(..., min_length=4, max_length=8, description="短信验证码")
    new_password: str = Field(..., min_length=8, max_length=100, description="新密码")
    captcha_id: str = Field(..., description="图形验证码ID")
    captcha_code: str = Field(..., description="图形验证码")


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., description="刷新令牌")


class UpdateProfileRequest(BaseModel):
    display_name: Optional[str] = Field(None, max_length=100, description="显示名称")
    avatar: Optional[str] = Field(None, max_length=512, description="头像URL")
    email: Optional[str] = Field(None, description="邮箱")


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., description="旧密码")
    new_password: str = Field(..., min_length=6, max_length=100, description="新密码")


# ==================== 注册 ====================

@router.get("/public-config", summary="登录页公开配置")
async def public_config():
    """供登录页读取：注册、验证码、短信通道。无需登录。"""
    return Response(code=200, message="ok", data={
        "allow_register": settings.register_enabled,
        "register_require_approval": settings.REGISTER_REQUIRE_APPROVAL,
        "captcha_required": False,
        "sms_provider": (settings.SMS_PROVIDER or "console").lower(),
        "sms_echo": settings.sms_echo_enabled,
    })


@router.get("/captcha", summary="获取图形验证码")
async def get_captcha():
    payload = create_captcha()
    if not settings.sms_echo_enabled:
        payload.pop("debug_text", None)
    return Response(code=200, message="ok", data=payload)


@router.post("/sms/send", summary="发送短信验证码")
async def send_sms_code(req: SendSmsRequest, request: Request, db: Session = Depends(get_db)):
    phone = _require_phone(req.phone)
    _require_captcha(req.captcha_id, req.captcha_code)
    purpose = (req.purpose or "").strip().lower()
    if purpose == "register":
        if not settings.register_enabled:
            raise HTTPException(status_code=403, detail="当前环境已关闭开放注册")
        if db.query(User).filter(User.phone == phone).first():
            raise HTTPException(status_code=400, detail="该手机号已注册")
    elif purpose == "reset":
        if not db.query(User).filter(User.phone == phone).first():
            raise HTTPException(status_code=400, detail="该手机号未注册")
    else:
        raise HTTPException(status_code=400, detail="验证码用途无效")
    try:
        code = issue_sms_code(db, phone, purpose, ip=_client_ip(request))
    except VerifyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    data = {"sent": True, "ttl": settings.SMS_CODE_TTL_SECONDS}
    if settings.sms_echo_enabled:
        data["debug_code"] = code
    return Response(code=200, message="验证码已发送", data=data)


@router.post("/register", summary="用户注册")
async def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """
    用户注册

    - 创建用户账号
    - 自动创建个人工作空间
    - 返回 access_token + refresh_token
    """
    if not settings.register_enabled:
        raise HTTPException(status_code=403, detail="当前环境已关闭开放注册，请联系管理员创建账号")

    _require_captcha(req.captcha_id, req.captcha_code)
    phone = _require_phone(req.phone)
    try:
        consume_sms_code(db, phone, "register", req.sms_code)
    except VerifyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 检查用户名是否已存在
    existing = db.query(User).filter(User.username == req.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")

    if db.query(User).filter(User.phone == phone).first():
        raise HTTPException(status_code=400, detail="该手机号已注册")

    # 检查邮箱是否已存在
    if req.email:
        existing_email = db.query(User).filter(User.email == req.email).first()
        if existing_email:
            raise HTTPException(status_code=400, detail="邮箱已被注册")

    # 创建用户
    pending_approval = settings.REGISTER_REQUIRE_APPROVAL
    user = User(
        username=req.username,
        email=req.email,
        phone=phone,
        hashed_password=hash_password(req.password),
        display_name=req.display_name or req.username,
        role=UserRole.USER,
        is_active=not pending_approval,
    )
    db.add(user)
    db.flush()  # 获取 user.id

    # 自动创建个人工作空间
    workspace = Workspace(
        user_id=user.id,
        name=f"{user.display_name}的工作空间",
        description=f"{user.username} 的个人工作空间",
    )
    db.add(workspace)
    db.commit()
    db.refresh(user)
    from app.services.workspace_service import bootstrap_user_workspace
    bootstrap_user_workspace(db, user)

    if pending_approval:
        log.info(f"用户注册待审批 | username={user.username}")
        return JSONResponse(content=Response(
            code=200,
            message="注册成功，请等待管理员审批后再登录",
            data={"user": _user_to_dict(user), "pending_approval": True},
        ).model_dump())

    # 生成 Token
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})

    log.info(f"用户注册成功 | username={user.username}")

    response = JSONResponse(content=Response(code=200, message="注册成功", data={
        "user": _user_to_dict(user),
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }).model_dump())
    set_auth_cookies(response, access_token, refresh_token)
    return response


# ==================== 登录 ====================

def _login_response(user: User, message: str = "登录成功"):
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})
    log.info(f"用户登录成功 | username={user.username}")
    response = JSONResponse(content=Response(code=200, message=message, data={
        "user": _user_to_dict(user),
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }).model_dump())
    set_auth_cookies(response, access_token, refresh_token)
    return response


@router.post("/quick-enter", summary="跳过验证码直接进入")
async def quick_enter(db: Session = Depends(get_db)):
    username = (settings.ADMIN_USERNAME or "").strip()
    user = db.query(User).filter(User.username == username).first() if username else None
    if not user:
        user = db.query(User).filter(User.role == UserRole.ADMIN, User.is_active.is_(True)).order_by(User.id.asc()).first()
    if not user:
        user = db.query(User).filter(User.is_active.is_(True)).order_by(User.id.asc()).first()
    if not user:
        raise HTTPException(status_code=404, detail="没有可登录的账号")
    return _login_response(user)


@router.post("/login", summary="用户登录")
async def login(req: LoginRequest, db: Session = Depends(get_db)):
    """
    用户登录

    - 验证用户名和密码
    - 返回 access_token + refresh_token
    """
    user = db.query(User).filter(User.username == req.username).first()
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    if not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    return _login_response(user)


@router.post("/password/reset", summary="短信验证后重置密码")
async def reset_password(req: ResetPasswordRequest, db: Session = Depends(get_db)):
    _require_captcha(req.captcha_id, req.captcha_code)
    phone = _require_phone(req.phone)
    user = db.query(User).filter(User.phone == phone).first()
    if not user:
        raise HTTPException(status_code=400, detail="该手机号未注册")
    try:
        consume_sms_code(db, phone, "reset", req.sms_code)
    except VerifyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    user.hashed_password = hash_password(req.new_password)
    db.commit()
    log.info(f"用户重置密码 | username={user.username}")
    return Response(code=200, message="密码已重置，请使用新密码登录")


# ==================== 刷新Token ====================

@router.post("/refresh", summary="刷新Token")
async def refresh_token(request: Request, db: Session = Depends(get_db)):
    """
    使用 refresh_token 获取新的 access_token

    支持两种方式传递 refresh_token：
    1. 请求体 JSON: {"refresh_token": "..."}
    2. Cookie: refresh_token=...
    """
    # 优先从请求体获取，其次从Cookie获取
    refresh_tok = None
    try:
        body = await request.json()
        refresh_tok = body.get("refresh_token")
    except Exception:
        pass

    if not refresh_tok:
        refresh_tok = request.cookies.get("refresh_token")

    if not refresh_tok:
        raise HTTPException(status_code=401, detail="缺少刷新令牌")

    payload = decode_token(refresh_tok)
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="无效的刷新令牌")

    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == int(user_id), User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在或已禁用")

    new_access_token = create_access_token(data={"sub": str(user.id)})
    new_refresh_token = create_refresh_token(data={"sub": str(user.id)})

    response = JSONResponse(content=Response(code=200, message="刷新成功", data={
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
    }).model_dump())
    set_auth_cookies(response, new_access_token, new_refresh_token)
    return response


# ==================== 当前用户信息 ====================

@router.get("/me", summary="获取当前用户信息")
async def get_me(user: User = Depends(require_auth)):
    """获取当前登录用户信息"""
    return Response(code=200, data=_user_to_dict(user))


# ==================== 退出登录 ====================

@router.post("/logout", summary="退出登录")
async def logout(user: User = Depends(require_auth)):
    """
    退出登录

    - 清除 httpOnly Cookie
    - JWT 是无状态的，前端清除 token 即可
    """
    log.info(f"用户退出登录 | username={user.username}")
    response = JSONResponse(content=Response(code=200, message="退出成功").model_dump())
    clear_auth_cookies(response)
    return response


# ==================== 更新资料 ====================

@router.put("/profile", summary="更新用户资料")
async def update_profile(
    req: UpdateProfileRequest,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """更新用户资料（显示名称、头像、邮箱）"""
    if req.display_name is not None:
        user.display_name = req.display_name
    if req.avatar is not None:
        user.avatar = req.avatar
    if req.email is not None:
        # 检查邮箱是否已被其他用户使用
        existing = db.query(User).filter(User.email == req.email, User.id != user.id).first()
        if existing:
            raise HTTPException(status_code=400, detail="邮箱已被其他用户使用")
        user.email = req.email
    db.commit()
    db.refresh(user)
    return Response(code=200, message="更新成功", data=_user_to_dict(user))


# ==================== 修改密码 ====================

@router.put("/password", summary="修改密码")
async def change_password(
    req: ChangePasswordRequest,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """修改密码"""
    if not verify_password(req.old_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="旧密码错误")
    user.hashed_password = hash_password(req.new_password)
    db.commit()
    return Response(code=200, message="密码修改成功")


# ==================== 头像上传 ====================

@router.post("/avatar", summary="上传头像")
async def upload_avatar(
    file: UploadFile = File(..., description="头像图片"),
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """上传用户头像图片"""
    from pathlib import Path as FilePath
    from app.core.config import settings

    # 验证文件类型
    allowed_types = {"image/jpeg", "image/png", "image/gif", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {file.content_type}，仅支持 JPG/PNG/GIF/WebP")

    # 验证文件大小（最大 2MB）
    content = await file.read()
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="头像文件不能超过 2MB")

    # 保存文件
    upload_dir = FilePath(settings.UPLOAD_DIR) / "avatars"
    upload_dir.mkdir(parents=True, exist_ok=True)

    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "png"
    filename = f"user_{user.id}_{int(__import__('time').time())}.{ext}"
    file_path = upload_dir / filename

    with open(file_path, "wb") as f:
        f.write(content)

    # 更新用户头像URL
    avatar_url = f"/api/auth/avatar/{filename}"
    user.avatar = avatar_url
    db.commit()
    db.refresh(user)

    return Response(code=200, message="头像上传成功", data=_user_to_dict(user))


@router.get("/avatar/{filename}", summary="获取头像图片")
async def get_avatar(filename: str):
    """获取用户头像图片"""
    from pathlib import Path as FilePath
    from app.core.config import settings

    file_path = FilePath(settings.UPLOAD_DIR) / "avatars" / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="头像不存在")
    return FileResponse(str(file_path))


# ==================== 个人中心统计 ====================

@router.get("/profile/stats", summary="个人中心统计")
async def get_profile_stats(
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """获取当前用户的个人统计数据"""
    from app.models.task import Task, TaskStatus
    from app.models.requirement_task import RequirementTask, RequirementStatus
    from app.models.execution_record import ExecutionRecord, ExecutionStatus
    from app.models.script import Script
    from app.models.ui_element import UIElement
    from app.models.feedback import Feedback

    uid = user.id

    # 任务统计
    total_tasks = db.query(func.count(Task.id)).filter(Task.user_id == uid).scalar() or 0
    completed_tasks = db.query(func.count(Task.id)).filter(
        Task.user_id == uid, Task.status == TaskStatus.SUCCESS
    ).scalar() or 0
    failed_tasks = db.query(func.count(Task.id)).filter(
        Task.user_id == uid, Task.status == TaskStatus.FAILED
    ).scalar() or 0

    # 需求统计
    total_requirements = db.query(func.count(RequirementTask.id)).filter(
        RequirementTask.user_id == uid
    ).scalar() or 0

    # 执行统计
    total_executions = db.query(func.count(ExecutionRecord.id)).filter(
        ExecutionRecord.user_id == uid
    ).scalar() or 0
    success_executions = db.query(func.count(ExecutionRecord.id)).filter(
        ExecutionRecord.user_id == uid, ExecutionRecord.status == ExecutionStatus.SUCCESS
    ).scalar() or 0

    # 知识库统计
    total_elements = db.query(func.count(UIElement.id)).filter(
        UIElement.user_id == uid
    ).scalar() or 0
    total_scripts = db.query(func.count(Script.id)).filter(
        Script.user_id == uid
    ).scalar() or 0

    # 反馈统计
    avg_score = db.query(func.avg(Feedback.score)).filter(
        Feedback.user_id == uid
    ).scalar()
    avg_score = round(float(avg_score), 1) if avg_score else 0

    pass_rate = (success_executions / total_executions * 100) if total_executions > 0 else 0

    return Response(code=200, data={
        "tasks": {"total": total_tasks, "completed": completed_tasks, "failed": failed_tasks},
        "requirements": {"total": total_requirements},
        "executions": {"total": total_executions, "success": success_executions, "pass_rate": round(pass_rate, 1)},
        "knowledge": {"elements": total_elements, "scripts": total_scripts},
        "feedback": {"avg_score": avg_score},
    })


# ==================== 辅助函数 ====================

def _user_to_dict(user: User) -> dict:
    """用户对象转字典（去除敏感信息）"""
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "phone": user.phone,
        "display_name": user.display_name,
        "avatar": user.avatar,
        "role": user.role,
        "is_active": user.is_active,
        "workspace_id": user.workspace.id if user.workspace else None,
        "created_at": str(user.created_at) if user.created_at else None,
    }
