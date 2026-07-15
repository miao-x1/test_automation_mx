"""
统一上下文路由模块

职责：
    根据任务类型智能判断数据来源（MySQL/Milvus/Neo4j），
    并生成检索计划供RetrievalManager执行。

核心组件：
    - ContextRouter: 智能路由器，判断查什么库
    - RetrievalPlan: 检索计划（mysql/milvus/neo4j三类查询）
    - ContextFusion: 上下文融合器，合并三库结果

调用链路：
    任务上下文 → ContextRouter.route() → RetrievalPlan
    → RetrievalManager.retrieve(plan) → 三库结果
    → ContextFusion.fuse() → 统一上下文
"""
from app.context.models import (
    TaskContext,
    RetrievalPlan,
    MysqlQuery,
    MilvusQuery,
    Neo4jQuery,
    FusedContext,
    DataSource,
)
from app.context.router import ContextRouter, get_context_router
from app.context.fusion import ContextFusion, get_context_fusion

__all__ = [
    "TaskContext",
    "RetrievalPlan",
    "MysqlQuery",
    "MilvusQuery",
    "Neo4jQuery",
    "FusedContext",
    "DataSource",
    "ContextRouter",
    "get_context_router",
    "ContextFusion",
    "get_context_fusion",
]
