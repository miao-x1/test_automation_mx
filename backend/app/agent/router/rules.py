"""
Routing Rules - 路由规则定义

所有意图到 Agent 的映射规则集中管理。
新增意图路由只需在此添加规则，无需修改其它代码。
"""
from typing import List

from app.agent.router.intent_router import RoutingRule
from app.agent.core.types import IntentType


def get_default_rules() -> List[RoutingRule]:
    """
    获取默认路由规则。

    规则按优先级排序，先匹配的先执行。
    每条规则包含：意图类型、目标Agent、条件描述。
    """
    return [
        # ---- 输入类型路由 ----
        RoutingRule(
            intent=IntentType.IMAGE,
            agent_name="element_agent",
            description="图片输入 → 视觉元素识别Agent",
            keywords=["图片", "image", "screenshot", "截图", "png", "jpg", "jpeg"],
            file_extensions=[".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"],
        ),
        RoutingRule(
            intent=IntentType.URL,
            agent_name="page_crawler_agent",
            description="URL输入 → 页面抓取Agent",
            keywords=["url", "http", "https", "网页", "页面", "crawl"],
            url_patterns=["http://", "https://"],
        ),
        RoutingRule(
            intent=IntentType.SCRIPT,
            agent_name="script_parser",
            description="脚本输入 → 脚本解析Agent",
            keywords=["脚本", "script", "playwright", "python", "yaml"],
            file_extensions=[".py", ".yaml", ".yml", ".json"],
        ),
        RoutingRule(
            intent=IntentType.PDF,
            agent_name="requirement_agent",
            description="PDF文档 → 需求解析Agent",
            file_extensions=[".pdf"],
        ),
        RoutingRule(
            intent=IntentType.SWAGGER,
            agent_name="requirement_agent",
            description="Swagger文档 → 需求解析Agent",
            keywords=["swagger", "openapi", "api文档", "接口文档"],
            file_extensions=[".yaml", ".yml", ".json"],
        ),
        RoutingRule(
            intent=IntentType.VIDEO,
            agent_name="element_agent",
            description="视频输入 → 视觉元素识别Agent（预留VideoAgent）",
            file_extensions=[".mp4", ".avi", ".mov", ".mkv"],
        ),
        RoutingRule(
            intent=IntentType.SCHEMA,
            agent_name="requirement_agent",
            description="数据库Schema → 需求解析Agent（预留SchemaAgent）",
            keywords=["schema", "ddl", "create table", "数据库"],
        ),
        RoutingRule(
            intent=IntentType.DOCUMENT,
            agent_name="requirement_agent",
            description="文档输入 → 需求解析Agent（预留DocumentAgent）",
            file_extensions=[".doc", ".docx", ".txt", ".md"],
        ),
        RoutingRule(
            intent=IntentType.API_DOC,
            agent_name="requirement_agent",
            description="API文档 → 需求解析Agent（预留ApiAgent）",
            keywords=["api", "接口", "endpoint", "rest", "graphql"],
        ),

        # ---- 业务意图路由 ----
        RoutingRule(
            intent=IntentType.REQUIREMENT,
            agent_name="requirement_agent",
            description="自然语言需求 → 需求解析Agent",
            keywords=["需求", "requirement", "测试", "test", "功能", "feature"],
            is_default=True,
        ),
        RoutingRule(
            intent=IntentType.EXECUTION,
            agent_name="execution_agent",
            description="执行意图 → 执行Agent",
            keywords=["执行", "execute", "run", "运行", "playwright"],
        ),
        RoutingRule(
            intent=IntentType.RAG,
            agent_name="rag_agent",
            description="RAG检索 → RAGAgent",
            keywords=["检索", "rag", "retrieve", "召回", "search"],
        ),
        RoutingRule(
            intent=IntentType.GRAPH,
            agent_name="graph_agent",
            description="图推理 → GraphAgent",
            keywords=["图", "graph", "neo4j", "关系", "流程图"],
        ),
        RoutingRule(
            intent=IntentType.KNOWLEDGE,
            agent_name="knowledge_update_agent",
            description="知识更新 → KnowledgeUpdateAgent",
            keywords=["知识", "knowledge", "索引", "index", "入库"],
        ),
        RoutingRule(
            intent=IntentType.MINDMAP,
            agent_name="case_agent",
            description="思维导图 → CaseAgent",
            keywords=["思维导图", "mindmap", "脑图"],
        ),
        RoutingRule(
            intent=IntentType.REVIEW,
            agent_name="feedback_agent",
            description="审查/反馈 → FeedbackAgent",
            keywords=["审查", "review", "反馈", "feedback", "评分"],
        ),
        RoutingRule(
            intent=IntentType.MIXED,
            agent_name="input_router",
            description="多模态混合输入 → InputRouter",
            keywords=["混合", "mixed", "multimodal"],
        ),
    ]
