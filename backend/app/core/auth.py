"""
认证核心模块

提供：
- JWT Token 生成与验证
- 密码哈希与校验
- 当前用户依赖注入（支持 Bearer Token + Cookie 双模式）
"""
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request, Response as FastAPIResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.models.user import User
from app.core.logger import log

# 密码加密上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Bearer Token 提取器
security = HTTPBearer(auto_error=False)

# JWT 配置
SECRET_KEY = getattr(settings, 'SECRET_KEY', None) or "ui-automation-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24小时
REFRESH_TOKEN_EXPIRE_DAYS = 7

# Cookie 名称
ACCESS_TOKEN_COOKIE = "access_token"
REFRESH_TOKEN_COOKIE = "refresh_token"


def hash_password(password: str) -> str:
    """密码哈希"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """密码校验"""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """生成 access_token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict) -> str:
    """生成 refresh_token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """解码并验证 token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def set_auth_cookies(response: FastAPIResponse, access_token: str, refresh_token: str):
    """设置认证Cookie（httpOnly）"""
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE,
        value=access_token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE,
        value=refresh_token,
        httponly=True,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        samesite="lax",
        path="/",
    )


def clear_auth_cookies(response: FastAPIResponse):
    """清除认证Cookie"""
    response.delete_cookie(key=ACCESS_TOKEN_COOKIE, path="/")
    response.delete_cookie(key=REFRESH_TOKEN_COOKIE, path="/")


def _extract_token_from_request(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = None,
) -> Optional[str]:
    """
    从请求中提取 access_token

    优先级：
    1. Authorization: Bearer <token>
    2. Cookie: access_token=<token>
    """
    # 1. Bearer Token
    if credentials and credentials.credentials:
        return credentials.credentials

    # 2. Cookie
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if token:
        return token

    return None


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    获取当前用户（依赖注入）

    支持两种认证方式：
    1. Authorization: Bearer <token>
    2. Cookie: access_token=<token>

    如果无 token 或 token 无效，返回 None（不强制登录）
    """
    token = _extract_token_from_request(request, credentials)
    if token is None:
        return None

    payload = decode_token(token)
    if payload is None:
        return None

    # 验证 token 类型
    if payload.get("type") != "access":
        return None

    user_id = payload.get("sub")
    if user_id is None:
        return None

    try:
        uid = int(user_id)
    except (ValueError, TypeError):
        return None

    user = db.query(User).filter(User.id == uid, User.is_active == True).first()
    return user


def require_auth(
    user: Optional[User] = Depends(get_current_user),
) -> User:
    """
    强制登录依赖注入

    必须登录才能访问，否则返回 401
    """
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或登录已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
