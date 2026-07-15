"""图存储模块

对接 Neo4j，构建知识图谱（文档→分片→实体），
支持图检索与图扩展，增强 RAG 的关联发现能力。

主要组件：
  - Neo4jGraphStore: 知识图谱存储实现（文档/分片/实体）
  - ExtendedGraphStore: 扩展知识图谱（完整业务关系链）
  - get_graph_store: 知识图谱单例
  - get_extended_graph_store: 扩展图谱单例

ExtendedGraphStore 节点标签：
  Page / Element / API / DBTable / BusinessFlow /
  TestCase / Script / Requirement / Module

ExtendedGraphStore 关系链：
  页面 → 元素 → 接口 → 数据库表
                   ↗
  业务流程 → 测试用例 → 脚本
"""
from app.rag.graph_store.store import Neo4jGraphStore
from app.rag.graph_store.factory import get_graph_store, reset_graph_store
from app.rag.graph_store.extended_store import (
    ExtendedGraphStore,
    get_extended_graph_store,
    ALL_NODE_LABELS,
    ALL_REL_TYPES,
)

__all__ = [
    "Neo4jGraphStore",
    "get_graph_store",
    "reset_graph_store",
    "ExtendedGraphStore",
    "get_extended_graph_store",
    "ALL_NODE_LABELS",
    "ALL_REL_TYPES",
]
