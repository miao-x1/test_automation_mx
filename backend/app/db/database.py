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
        if settings.is_production:
            log.info("生产环境跳过 create_all：Schema 由 Alembic upgrade head 负责")
            return
        # 确保所有模型已导入，否则 create_all 无法创建未注册的表
        import importlib
        import pkgutil
        import app.models as models_pkg
        for _, modname, _ in pkgutil.iter_modules(models_pkg.__path__):
            if not modname.startswith("_"):
                try:
                    importlib.import_module(f"app.models.{modname}")
                except Exception as exc:
                    log.error(f"导入模型失败: app.models.{modname} | {exc}", exc_info=True)
                    raise
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
            if 'task' in inspector.get_table_names():
                cols = [c['name'] for c in inspector.get_columns('task')]
                task_alters = {
                    'task_type': "ALTER TABLE task ADD COLUMN task_type ENUM('web','api','performance','android') NOT NULL DEFAULT 'web'",
                    'type_config': "ALTER TABLE task ADD COLUMN type_config VARCHAR(4096) NULL",
                    'framework': "ALTER TABLE task ADD COLUMN framework VARCHAR(64) NULL",
                    'platform': "ALTER TABLE task ADD COLUMN platform VARCHAR(64) NULL",
                    'confidence': "ALTER TABLE task ADD COLUMN confidence FLOAT NULL",
                    'user_id': "ALTER TABLE task ADD COLUMN user_id INTEGER NULL",
                    'created_by': "ALTER TABLE task ADD COLUMN created_by INTEGER NULL",
                }
                input_mode_col = next((c for c in inspector.get_columns('task') if c['name'] == 'input_mode'), None)
                if input_mode_col is not None:
                    type_str = str(input_mode_col.get('type') or '')
                    if 'VARCHAR(10)' in type_str.upper() or 'VARCHAR(10)' in type_str:
                        try:
                            with sync_engine.begin() as conn:
                                conn.execute(text("ALTER TABLE task MODIFY COLUMN input_mode VARCHAR(32) NOT NULL"))
                            log.info("数据库: 扩展 'task.input_mode' 以容纳 requirement")
                        except Exception as e:
                            log.warning(f"尝试扩展 task.input_mode 失败: {e}")
                status_col = next((c for c in inspector.get_columns('task') if c['name'] == 'status'), None)
                if status_col is not None:
                    try:
                        with sync_engine.begin() as conn:
                            conn.execute(text("ALTER TABLE task MODIFY COLUMN status VARCHAR(32) NOT NULL DEFAULT 'pending'"))
                            conn.execute(text("UPDATE task SET status = LOWER(status)"))
                        log.info("数据库: 将 'task.status' 调整为 VARCHAR 并规范化小写值")
                    except Exception as e:
                        log.warning(f"尝试调整 task.status 失败: {e}")
                for col_name, ddl in task_alters.items():
                    if col_name in cols:
                        continue
                    try:
                        with sync_engine.begin() as conn:
                            conn.execute(text(ddl))
                        log.info(f"数据库: 为 'task' 表添加缺失列 '{col_name}'")
                    except Exception as e:
                        log.warning(f"尝试添加 task.{col_name} 列失败: {e}")
        except Exception:
            # inspector 可能在部分 DB 后端不可用，忽略并继续
            log.debug("数据库结构检查失败，跳过列修复", exc_info=True)

            owned_missing = {
                "image_file": {"user_id": "INTEGER NULL", "created_by": "INTEGER NULL"},
                "script": {
                    "user_id": "INTEGER NULL",
                    "created_by": "INTEGER NULL",
                    "kb_status": "VARCHAR(20) NULL",
                },
                "execution_record": {"user_id": "INTEGER NULL", "created_by": "INTEGER NULL"},
            }
            for table_name, col_ddl in owned_missing.items():
                if table_name not in inspector.get_table_names():
                    continue
                existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
                for col_name, ddl_type in col_ddl.items():
                    if col_name in existing_cols:
                        continue
                    try:
                        with sync_engine.begin() as conn:
                            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {ddl_type}"))
                        log.info(f"数据库: 为 '{table_name}' 表添加缺失列 '{col_name}'")
                    except Exception as e:
                        log.warning(f"尝试添加 {table_name}.{col_name} 列失败: {e}")
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
