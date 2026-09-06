"""P0-2: 全新空 SQLite 必须能 create_all 全部模型表。"""
import os
import sys
import tempfile
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))
os.environ.setdefault("USE_SQLITE", "True")
os.environ.setdefault("APP_ENV", "development")


def test_fresh_sqlite_create_all():
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.orm import sessionmaker
    import importlib
    import pkgutil
    import app.models as models_pkg
    from app.db.database import Base

    for _, modname, _ in pkgutil.iter_modules(models_pkg.__path__):
        if not modname.startswith("_"):
            importlib.import_module(f"app.models.{modname}")

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = None
    try:
        engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        tables = inspect(engine).get_table_names()
        assert "user" in tables
        assert "knowledge_source" in tables
        assert "case_task" in tables or any("case" in t for t in tables)
        assert len(tables) >= 20
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            from app.models.user import User
            assert db.query(User).count() == 0
        finally:
            db.close()
    finally:
        if engine is not None:
            engine.dispose()
        try:
            os.remove(path)
        except OSError:
            pass
