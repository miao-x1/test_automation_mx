"""
数据库连接模块
"""
from pathlib import Path
from typing import AsyncGenerator
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.core.config import settings
from app.core.logger import log


# 创建Base类
Base = declarative_base()


def _get_engine_kwargs():
    """获取引擎参数"""
    kwargs = {"echo": settings.DB_ECHO}
    if settings.USE_SQLITE:
        # SQLite需要特殊参数
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_pre_ping"] = True
        kwargs["pool_size"] = 10
        kwargs["max_overflow"] = 20
        kwargs["pool_recycle"] = 3600
    return kwargs


# 确保SQLite数据目录存在
if settings.USE_SQLITE:
    Path(settings.SQLITE_PATH).parent.mkdir(parents=True, exist_ok=True)


# 同步引擎
sync_engine = create_engine(settings.DATABASE_URL, **_get_engine_kwargs())

# 同步会话工厂
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=sync_engine
)


def get_db() -> Session:
    """获取数据库会话（同步）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """初始化数据库"""
    try:
        # 创建所有表
        Base.metadata.create_all(bind=sync_engine)
        log.info("数据库表初始化完成")
    except Exception as e:
        log.error(f"数据库初始化失败: {e}")
        raise


def close_db():
    """关闭数据库连接"""
    try:
        sync_engine.dispose()
        log.info("数据库连接已关闭")
    except Exception as e:
        log.error(f"关闭数据库连接失败: {e}")
