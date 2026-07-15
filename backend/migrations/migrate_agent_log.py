"""
AgentLog 数据库迁移脚本

创建 agent_log 表。
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from app.db.database import sync_engine
from app.models.agent_log import AgentLog
from sqlalchemy import inspect


def run_migration():
    """执行数据库迁移"""
    inspector = inspect(sync_engine)
    conn = sync_engine.connect()

    try:
        if not inspector.has_table("agent_log"):
            print("[Migration] 创建 agent_log 表...")
            AgentLog.__table__.create(conn)
            conn.commit()
            print("[Migration] agent_log 表创建成功")
        else:
            print("[Migration] agent_log 表已存在")

        print("\n[Migration] AgentLog 迁移完成!")

    except Exception as e:
        conn.rollback()
        print(f"[Migration] 迁移失败: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    run_migration()
