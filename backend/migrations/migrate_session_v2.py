"""数据库迁移：创建 session_artifact 表并为 session 表添加新字段"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from app.db.database import sync_engine, Base
import app.models  # noqa

def migrate():
    print("=== 数据库迁移 ===")

    # 1. 创建所有新表（包括 session_artifact）
    print("\n--- 1. 创建新表 ---")
    Base.metadata.create_all(bind=sync_engine, checkfirst=True)
    print("[OK] 新表已创建")

    # 2. 为 session 表添加新字段（如果不存在）
    print("\n--- 2. 检查并添加 session 表新字段 ---")
    from sqlalchemy import inspect as sql_inspect
    inspector = sql_inspect(sync_engine)

    # 获取 session 表现有列
    existing_columns = [col["name"] for col in inspector.get_columns("session")]
    print(f"  session 表现有列: {existing_columns}")

    new_columns = {
        "session_key": "VARCHAR(128)",
        "graphflow_task_id": "VARCHAR(64)",
        "requirement_text": "TEXT",
        "input_mode": "VARCHAR(20) DEFAULT 'text'",
        "total_tokens": "INTEGER DEFAULT 0",
        "total_duration": "FLOAT DEFAULT 0.0",
        "artifact_count": "INTEGER DEFAULT 0",
        "error_count": "INTEGER DEFAULT 0",
    }

    with sync_engine.connect() as conn:
        for col_name, col_type in new_columns.items():
            if col_name not in existing_columns:
                sql = f"ALTER TABLE session ADD COLUMN {col_name} {col_type}"
                print(f"  添加列: {sql}")
                conn.execute(text(sql))
                conn.commit()
                print(f"  [OK] 已添加: {col_name}")
            else:
                print(f"  [SKIP] 已存在: {col_name}")

    # 3. 验证
    print("\n--- 3. 验证 ---")
    inspector2 = sql_inspect(sync_engine)
    tables = inspector2.get_table_names()
    print(f"  表数量: {len(tables)}")
    print(f"  session_artifact 存在: {'session_artifact' in tables}")
    session_cols = [col["name"] for col in inspector2.get_columns("session")]
    print(f"  session 列: {session_cols}")
    artifact_cols = [col["name"] for col in inspector2.get_columns("session_artifact")]
    print(f"  session_artifact 列: {artifact_cols}")

    print("\n=== 迁移完成 ===")


if __name__ == "__main__":
    migrate()
