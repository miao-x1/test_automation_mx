"""
三库协同 - 数据库迁移脚本

创建 Tag / KnowledgeTag 表。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.database import sync_engine
from sqlalchemy import text
from app.models.tag import Tag, KnowledgeTag
from app.models.base import BaseModel


def migrate():
    """执行迁移"""
    print("=" * 60)
    print("三库协同 - 数据库迁移")
    print("=" * 60)

    # 创建 Tag 和 KnowledgeTag 表
    tables_to_create = [Tag.__table__, KnowledgeTag.__table__]
    for table in tables_to_create:
        try:
            table.create(bind=sync_engine, checkfirst=True)
            print(f"  [OK] 表已创建: {table.name}")
        except Exception as e:
            print(f"  [SKIP] 表已存在或创建失败: {table.name} - {e}")

    # 验证
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        # 检查 tag 表
        result = db.execute(text("SHOW TABLES LIKE 'tag'"))
        if result.fetchone():
            print("  [OK] tag 表存在")
        result = db.execute(text("SHOW TABLES LIKE 'knowledge_tag'"))
        if result.fetchone():
            print("  [OK] knowledge_tag 表存在")
    finally:
        db.close()

    print("\n迁移完成！")


if __name__ == "__main__":
    migrate()
