"""
上下文路由数据模型

定义任务上下文、检索计划、融合结果等核心数据结构。
所有结构均可序列化为JSON，支持API传输。
"""
from enum import Enum
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
import json


class DataSource(str, Enum):
    """数据来源类型"""
    MYSQL = "mysql"
    MILVUS = "milvus"
    NEO4J = "neo4j"


class TaskType(str, Enum):
    """任务类型"""
    CASE_GENERATION = "testcase_generation"
    SCRIPT_GENERATION = "script_generation"
    REQUIREMENT_ANALYSIS = "requirement_analysis"
    WEB_TEST = "web_test"
    API_TEST = "api_test"
    GENERAL = "general"


@dataclass
class TaskContext:
    """任务上下文

    包含任务的基本信息，供Router判断数据来源。
    """
    task_id: str = ""
    task_type: str = "general"
    requirement: str = ""
    business_module: str = ""
    keywords: List[str] = field(default_factory=list)
    page_names: List[str] = field(default_factory=list)
    api_names: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "requirement": self.requirement,
            "business_module": self.business_module,
            "keywords": self.keywords,
            "page_names": self.page_names,
            "api_names": self.api_names,
            "metadata": self.metadata,
        }


@dataclass
class MysqlQuery:
    """MySQL查询计划"""
    tables: List[str] = field(default_factory=list)        # 要查询的表名
    filters: Dict[str, Any] = field(default_factory=dict)  # 过滤条件
    fields: List[str] = field(default_factory=list)        # 返回字段（空=全部）
    limit: int = 100

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tables": self.tables,
            "filters": self.filters,
            "fields": self.fields,
            "limit": self.limit,
        }


@dataclass
class MilvusQuery:
    """Milvus向量查询计划"""
    queries: List[str] = field(default_factory=list)           # 查询文本列表
    collections: List[str] = field(default_factory=list)       # 集合名
    entity_types: List[str] = field(default_factory=list)     # 实体类型过滤
    top_k: int = 10
    score_threshold: float = 0.3

    def to_dict(self) -> Dict[str, Any]:
        return {
            "queries": self.queries,
            "collections": self.collections,
            "entity_types": self.entity_types,
            "top_k": self.top_k,
            "score_threshold": self.score_threshold,
        }


@dataclass
class Neo4jQuery:
    """Neo4j图查询计划"""
    node_labels: List[str] = field(default_factory=list)       # 节点标签
    node_names: List[str] = field(default_factory=list)       # 节点名称/属性值
    relation_types: List[str] = field(default_factory=list)    # 关系类型
    depth: int = 2                                             # 遍历深度
    start_nodes: List[Dict[str, str]] = field(default_factory=list)  # 起始节点

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_labels": self.node_labels,
            "node_names": self.node_names,
            "relation_types": self.relation_types,
            "depth": self.depth,
            "start_nodes": self.start_nodes,
        }


@dataclass
class RetrievalPlan:
    """检索计划

    由ContextRouter生成，包含三类数据库的查询计划。
    """
    mysql: MysqlQuery = field(default_factory=MysqlQuery)
    milvus: MilvusQuery = field(default_factory=MilvusQuery)
    neo4j: Neo4jQuery = field(default_factory=Neo4jQuery)
    reason: str = ""        # 路由理由说明
    task_type: str = "general"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mysql": self.mysql.to_dict(),
            "milvus": self.milvus.to_dict(),
            "neo4j": self.neo4j.to_dict(),
            "reason": self.reason,
            "task_type": self.task_type,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class FusedContext:
    """融合后的统一上下文

    合并三库检索结果，供Agent使用。
    """
    business_context: Dict[str, Any] = field(default_factory=dict)    # MySQL业务数据
    knowledge_context: Dict[str, Any] = field(default_factory=dict)  # Milvus知识参考
    graph_context: Dict[str, Any] = field(default_factory=dict)      # Neo4j业务关系
    sources: List[str] = field(default_factory=list)                 # 使用的数据源列表
    summary: str = ""                                                 # 上下文摘要

    def to_dict(self) -> Dict[str, Any]:
        return {
            "business_context": self.business_context,
            "knowledge_context": self.knowledge_context,
            "graph_context": self.graph_context,
            "sources": self.sources,
            "summary": self.summary,
        }
