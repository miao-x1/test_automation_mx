"""PageKnowledge 数据库迁移脚本"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.database import sync_engine
from app.models.page_knowledge import PageKnowledge, PageKnowledgeElement


def migrate():
    print("=" * 60)
    print("PageKnowledge 数据库迁移")
    print("=" * 60)

    tables = [PageKnowledge.__table__, PageKnowledgeElement.__table__]
    for table in tables:
        try:
            table.create(bind=sync_engine, checkfirst=True)
            print(f"  [OK] 表已创建: {table.name}")
        except Exception as e:
            print(f"  [SKIP] 表已存在或创建失败: {table.name} - {e}")

    # 验证
    from app.db.database import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    try:
        result = db.execute(text("SHOW TABLES LIKE 'page_knowledge'"))
        if result.fetchone():
            print("  [OK] page_knowledge 表存在")
        result = db.execute(text("SHOW TABLES LIKE 'page_knowledge_element'"))
        if result.fetchone():
            print("  [OK] page_knowledge_element 表存在")
    finally:
        db.close()
    print("\n迁移完成！")


if __name__ == "__main__":
    migrate()
