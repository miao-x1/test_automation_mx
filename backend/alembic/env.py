"""
Alembic环境配置

- 从环境变量构建数据库 URL（Docker 兼容）
- 自动导入所有模型以便 Alembic 检测变更
"""
import os
import importlib
import pkgutil
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import inspect
from sqlalchemy import pool
from alembic import context
from alembic.operations import Operations

# Alembic Config对象
config = context.config

# 日志配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------- 从统一配置构建数据库 URL ----------
# 使用项目的 Settings 类（已通过 load_dotenv() 加载 .env），
# 避免 os.getenv() 单独读取导致配置不一致
from app.core.config import settings

# 覆盖 alembic.ini 中的 sqlalchemy.url
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# ---------- 自动导入所有模型 ----------
from app.db.database import Base

# 动态导入 app.models 下的所有模块
import app.models as models_pkg
for importer, modname, ispkg in pkgutil.iter_modules(models_pkg.__path__):
    if not modname.startswith("_"):
        try:
            importlib.import_module(f"app.models.{modname}")
        except Exception as e:
            print(f"Warning: failed to import app.models.{modname}: {e}")

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式迁移"""
    _install_idempotent_ops()
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def _install_idempotent_ops() -> None:
    """Skip create/add when the object already exists.

    Historical revisions were written against empty databases. Production
    databases that reached 003 and then used create_all() already contain
    later tables/columns. Skipping duplicates is required so upgrade head
    can finish; 035 still reconciles remaining type/column drift.
    """
    if getattr(Operations, "_ui_auto_idempotent", False):
        return

    orig_create_table = Operations.create_table
    orig_add_column = Operations.add_column
    orig_create_index = Operations.create_index
    orig_create_fk = Operations.create_foreign_key

    def create_table(self, table_name, *args, **kwargs):
        insp = inspect(self.get_bind())
        if table_name in insp.get_table_names():
            return None
        return orig_create_table(self, table_name, *args, **kwargs)

    def add_column(self, table_name, column, *args, **kwargs):
        insp = inspect(self.get_bind())
        if table_name in insp.get_table_names():
            existing = {c["name"] for c in insp.get_columns(table_name)}
            if getattr(column, "name", None) in existing:
                return None
        return orig_add_column(self, table_name, column, *args, **kwargs)

    def create_index(self, name, table_name, *args, **kwargs):
        insp = inspect(self.get_bind())
        if table_name in insp.get_table_names():
            existing = {i["name"] for i in insp.get_indexes(table_name)}
            if name in existing:
                return None
        return orig_create_index(self, name, table_name, *args, **kwargs)

    def create_foreign_key(self, name, source, referent, *args, **kwargs):
        insp = inspect(self.get_bind())
        if source in insp.get_table_names():
            existing = {fk.get("name") for fk in insp.get_foreign_keys(source)}
            if name in existing:
                return None
        if referent not in inspect(self.get_bind()).get_table_names():
            return None
        return orig_create_fk(self, name, source, referent, *args, **kwargs)

    Operations.create_table = create_table
    Operations.add_column = add_column
    Operations.create_index = create_index
    Operations.create_foreign_key = create_foreign_key
    Operations._ui_auto_idempotent = True


def run_migrations_online() -> None:
    """在线模式迁移"""
    _install_idempotent_ops()
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
