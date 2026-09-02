"""
数据库连接模块
"""
from pathlib import Path
from typing import AsyncGenerator
from sqlalchemy import create_engine, inspect, text
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
        # 确保所有模型已导入，否则 create_all 无法创建未注册的表
        import importlib
        import pkgutil
        import app.models as models_pkg
        for _, modname, _ in pkgutil.iter_modules(models_pkg.__path__):
            if not modname.startswith("_"):
                try:
                    importlib.import_module(f"app.models.{modname}")
                except Exception:
                    pass
        # 创建所有表（Alembic 已迁移，此处仅作安全兜底）
        Base.metadata.create_all(bind=sync_engine)
        # 检查是否存在旧的 schema 差异（例如缺失的列），尝试修复常见缺失列
        try:
            inspector = inspect(sync_engine)
            # 如果 script 表存在但缺少 script_source 列，则补齐该列（避免运行时大量 SQL 异常）
            if 'script' in inspector.get_table_names():
                cols = [c['name'] for c in inspector.get_columns('script')]
                if 'script_source' not in cols:
                    try:
                        with sync_engine.connect() as conn:
                            conn.execute(text("ALTER TABLE script ADD COLUMN script_source VARCHAR(20) NOT NULL DEFAULT 'generated'"))
                            log.info("数据库: 为 'script' 表添加缺失列 'script_source'")
                    except Exception as e:
                        log.warning(f"尝试添加 script_source 列失败: {e}")
        except Exception:
            # inspector 可能在部分 DB 后端不可用，忽略并继续
            log.debug("数据库结构检查失败，跳过列修复", exc_info=True)

        log.info("数据库表初始化完成")
    except Exception as e:
        # 不阻断启动 — Alembic 已处理表结构
        log.warning(f"数据库 create_all 跳过（Alembic 已迁移）: {e}")


def close_db():
    """关闭数据库连接"""
    try:
        sync_engine.dispose()
        log.info("数据库连接已关闭")
    except Exception as e:
        log.error(f"关闭数据库连接失败: {e}")
