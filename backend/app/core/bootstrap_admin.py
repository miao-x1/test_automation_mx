"""启动时按环境变量创建种子管理员。"""
from app.core.config import settings
from app.core.logger import log

_WEAK_PASSWORDS = {"admin", "admin123", "password", "123456", "magic1212"}


def ensure_seed_admin() -> None:
    username = (settings.ADMIN_USERNAME or "").strip()
    password = settings.ADMIN_PASSWORD or ""
    if not username or not password:
        return
    if password in _WEAK_PASSWORDS or len(password) < 8:
        log.warning("种子管理员密码过弱，已跳过创建。请设置至少 8 位且非常见口令的 ADMIN_PASSWORD")
        return

    from app.core.auth import hash_password
    from app.db.database import SessionLocal
    from app.models.user import User, UserRole, Workspace

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            return
        user = User(
            username=username,
            hashed_password=hash_password(password),
            display_name=username,
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(user)
        db.flush()
        db.add(Workspace(
            user_id=user.id,
            name=f"{username}的工作空间",
            description="种子管理员工作空间",
        ))
        db.commit()
        log.info(f"已创建种子管理员 | username={username}")
    except Exception as exc:
        db.rollback()
        log.warning(f"创建种子管理员失败: {exc}")
    finally:
        db.close()
