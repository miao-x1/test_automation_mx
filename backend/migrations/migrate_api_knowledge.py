"""
API Knowledge 数据库迁移脚本

创建 api_knowledge 和 api_dependency 表。
"""
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from app.db.database import sync_engine
from app.models.api_knowledge import APIKnowledge, APIDependency
from sqlalchemy import inspect, text


def run_migration():
    """执行数据库迁移"""
    inspector = inspect(sync_engine)
    conn = sync_engine.connect()

    try:
        # 1. 创建 api_knowledge 表
        if not inspector.has_table("api_knowledge"):
            print("[Migration] 创建 api_knowledge 表...")
            APIKnowledge.__table__.create(conn)
            conn.commit()
            print("[Migration] api_knowledge 表创建成功")
        else:
            print("[Migration] api_knowledge 表已存在，检查是否需要补充字段...")
            # 检查并补充可能缺失的字段
            existing_columns = {col["name"] for col in inspector.get_columns("api_knowledge")}
            model_columns = {c.name for c in APIKnowledge.__table__.columns}
            missing = model_columns - existing_columns
            if missing:
                print(f"[Migration] 补充缺失字段: {missing}")
                for col in APIKnowledge.__table__.columns:
                    if col.name in missing:
                        col_type = col.type.compile(sync_engine.dialect)
                        conn.execute(text(f"ALTER TABLE api_knowledge ADD COLUMN {col.name} {col_type}"))
                conn.commit()
                print("[Migration] 字段补充完成")
            else:
                print("[Migration] api_knowledge 字段完整，无需补充")

        # 2. 创建 api_dependency 表
        if not inspector.has_table("api_dependency"):
            print("[Migration] 创建 api_dependency 表...")
            APIDependency.__table__.create(conn)
            conn.commit()
            print("[Migration] api_dependency 表创建成功")
        else:
            print("[Migration] api_dependency 表已存在")

        # 3. 创建索引
        indexes_to_create = [
            ("idx_api_knowledge_method_path", "api_knowledge", "method, path"),
            ("idx_api_knowledge_module_tags", "api_knowledge", "module, tags"),
            ("idx_api_dep_api_depends", "api_dependency", "api_id, depends_on_api_id"),
        ]
        existing_indexes = set()
        for table in ["api_knowledge", "api_dependency"]:
            if inspector.has_table(table):
                for idx in inspector.get_indexes(table):
                    existing_indexes.add(idx["name"])

        for idx_name, table_name, columns in indexes_to_create:
            if idx_name not in existing_indexes:
                try:
                    conn.execute(text(f"CREATE INDEX {idx_name} ON {table_name} ({columns})"))
                    conn.commit()
                    print(f"[Migration] 创建索引: {idx_name}")
                except Exception as e:
                    print(f"[Migration] 索引 {idx_name} 创建跳过: {e}")
            else:
                print(f"[Migration] 索引 {idx_name} 已存在")

        print("\n[Migration] API Knowledge 迁移完成!")
        print(f"  - api_knowledge 表: {'OK' if inspector.has_table('api_knowledge') else 'FAIL'}")
        print(f"  - api_dependency 表: {'OK' if inspector.has_table('api_dependency') else 'FAIL'}")

    except Exception as e:
        conn.rollback()
        print(f"[Migration] 迁移失败: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    run_migration()
