"""
MySQL 存储模块

对接 MySQL，负责文档与 Chunk 的结构化元数据持久化，
作为向量库/图库的关系型补充，支持精确过滤与回溯。
"""
from app.rag.mysql_store.store import MySQLStore
from app.rag.mysql_store.factory import get_mysql_store, reset_mysql_store

__all__ = [
    "MySQLStore",
    "get_mysql_store",
    "reset_mysql_store",
]
