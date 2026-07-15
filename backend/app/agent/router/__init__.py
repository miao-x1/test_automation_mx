"""
Router 模块 - Intent Router 意图路由

职责：
根据任务类型自动选择 Agent。
所有选择逻辑集中管理，禁止散落 if-else。

路由规则：
- 上传图片    → ImageAgent (element_agent)
- 上传PDF     → DocumentAgent (预留)
- 上传Swagger → ApiAgent (预留)
- 自然语言     → RequirementAgent
- 视频        → VideoAgent (预留)
- 接口文档     → ApiAgent (预留)
- 数据库Schema → SchemaAgent (预留)
- URL         → PageCrawlerAgent
- 脚本        → ScriptParser
- 执行        → ExecutionAgent
- RAG检索     → RAGAgent
- 图推理      → GraphAgent
- 知识更新     → KnowledgeUpdateAgent
"""
from app.agent.router.intent_router import IntentRouter, RoutingRule, get_intent_router
from app.agent.router.rules import get_default_rules

__all__ = [
    "IntentRouter",
    "RoutingRule",
    "get_intent_router",
    "get_default_rules",
]
