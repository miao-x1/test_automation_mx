"""
ContextRouter - 上下文智能路由器

职责：
    根据任务上下文（TaskContext），智能判断需要查询哪些数据库，
    生成检索计划（RetrievalPlan）。

路由规则：
    1. 脚本生成任务：
       - MySQL: 查询任务信息、测试用例
       - Milvus: 检索历史脚本、历史用例
       - Neo4j: 查询页面元素关系、API调用链

    2. 用例生成任务：
       - MySQL: 查询需求信息、已有用例
       - Milvus: 检索历史用例、测试规范
       - Neo4j: 查询页面元素关系

    3. 需求分析任务：
       - MySQL: 查询需求记录
       - Milvus: 检索需求文档、历史需求
       - Neo4j: 不查询（无关系数据）

    4. Web测试任务：
       - MySQL: 查询任务、页面元素
       - Milvus: 检索历史脚本
       - Neo4j: 查询页面导航关系

设计原则：
    - 不直接操作数据库，只生成计划
    - 计划可序列化，支持API传输
    - 支持LLM增强路由（可选）
"""
import re
import logging
from typing import Any, Dict, List, Optional

from app.context.models import (
    TaskContext,
    RetrievalPlan,
    MysqlQuery,
    MilvusQuery,
    Neo4jQuery,
    TaskType,
)

logger = logging.getLogger(__name__)


class ContextRouter:
    """上下文智能路由器

    根据任务类型和关键词，智能判断需要查询哪些数据库。
    支持规则路由和LLM增强路由两种模式。
    """

    # 任务类型关键词映射
    TASK_KEYWORDS = {
        TaskType.SCRIPT_GENERATION: ["脚本", "script", "playwright", "pytest", "自动化脚本", "代码生成"],
        TaskType.CASE_GENERATION: ["测试用例", "用例生成", "生成用例", "testcase", "测试点", "用例设计"],
        TaskType.REQUIREMENT_ANALYSIS: ["需求分析", "需求解析", "理解需求", "requirement"],
        TaskType.WEB_TEST: ["web测试", "页面测试", "web自动化", "浏览器", "ui测试"],
        TaskType.API_TEST: ["api测试", "接口测试", "rest", "graphql", "swagger"],
    }

    # MySQL表与任务类型的映射
    MYSQL_TABLE_MAP = {
        TaskType.SCRIPT_GENERATION: ["task", "test_case", "script", "ui_element", "page_element"],
        TaskType.CASE_GENERATION: ["test_requirement", "test_case_point", "test_case", "requirement_task"],
        TaskType.REQUIREMENT_ANALYSIS: ["requirement_task", "requirement_input", "test_requirement"],
        TaskType.WEB_TEST: ["task", "ui_element", "page_element", "script"],
        TaskType.API_TEST: ["api_case", "api_metadata", "task"],
        TaskType.GENERAL: ["task"],
    }

    # Milvus集合与任务类型的映射
    MILVUS_COLLECTION_MAP = {
        TaskType.SCRIPT_GENERATION: ["script_vector", "test_case_vector", "ui_element_vector"],
        TaskType.CASE_GENERATION: ["test_case_vector", "rag_knowledge_vector", "requirement_vector"],
        TaskType.REQUIREMENT_ANALYSIS: ["requirement_vector", "rag_knowledge_vector"],
        TaskType.WEB_TEST: ["script_vector", "ui_element_vector", "page_vector"],
        TaskType.API_TEST: ["rag_knowledge_vector"],
        TaskType.GENERAL: ["rag_knowledge_vector"],
    }

    # Neo4j节点标签与任务类型的映射
    NEO4J_LABEL_MAP = {
        TaskType.SCRIPT_GENERATION: ["Page", "Element", "API", "TestCase", "Script"],
        TaskType.CASE_GENERATION: ["Page", "Element", "Requirement", "TestCase"],
        TaskType.REQUIREMENT_ANALYSIS: [],
        TaskType.WEB_TEST: ["Page", "Element", "Script"],
        TaskType.API_TEST: ["API", "TestCase"],
        TaskType.GENERAL: [],
    }

    def __init__(self):
        """初始化路由器"""
        logger.info("[ContextRouter] 初始化完成")

    def route(self, context: TaskContext) -> RetrievalPlan:
        """
        根据任务上下文生成检索计划

        Args:
            context: 任务上下文（包含任务类型、需求、关键词等）

        Returns:
            RetrievalPlan: 检索计划（包含mysql/milvus/neo4j三类查询）
        """
        # 1. 确定任务类型
        task_type = self._determine_task_type(context)
        logger.info(f"[ContextRouter] 任务类型: {task_type} | task_id={context.task_id}")

        # 2. 生成三类查询计划
        mysql_plan = self._build_mysql_plan(context, task_type)
        milvus_plan = self._build_milvus_plan(context, task_type)
        neo4j_plan = self._build_neo4j_plan(context, task_type)

        # 3. 生成路由理由
        reason = self._generate_reason(context, task_type, mysql_plan, milvus_plan, neo4j_plan)

        plan = RetrievalPlan(
            mysql=mysql_plan,
            milvus=milvus_plan,
            neo4j=neo4j_plan,
            reason=reason,
            task_type=task_type,
        )

        logger.info(
            f"[ContextRouter] 路由完成 | "
            f"MySQL表: {mysql_plan.tables} | "
            f"Milvus查询: {milvus_plan.queries} | "
            f"Neo4j标签: {neo4j_plan.node_labels}"
        )

        return plan

    def _determine_task_type(self, context: TaskContext) -> str:
        """确定任务类型"""
        # 如果已指定，直接使用
        if context.task_type and context.task_type != "general":
            return context.task_type

        # 根据关键词判断
        text = (context.requirement or "").lower()
        for task_type, keywords in self.TASK_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                return task_type.value

        return TaskType.GENERAL.value

    def _build_mysql_plan(self, context: TaskContext, task_type: str) -> MysqlQuery:
        """构建MySQL查询计划"""
        tables = self.MYSQL_TABLE_MAP.get(TaskType(task_type), ["task"])

        # 根据关键词过滤表
        if context.business_module:
            if "登录" in context.requirement or "login" in context.requirement.lower():
                if "ui_element" not in tables:
                    tables.append("ui_element")
                if "page_element" not in tables:
                    tables.append("page_element")

        filters = {}
        if context.task_id:
            filters["task_id"] = context.task_id
        if context.business_module:
            filters["business_module"] = context.business_module

        return MysqlQuery(
            tables=tables,
            filters=filters,
            limit=100,
        )

    def _build_milvus_plan(self, context: TaskContext, task_type: str) -> MilvusQuery:
        """构建Milvus查询计划"""
        collections = self.MILVUS_COLLECTION_MAP.get(TaskType(task_type), ["rag_knowledge_vector"])

        # 构建查询文本
        queries = []
        if context.requirement:
            queries.append(context.requirement[:200])  # 限制长度
        if context.business_module:
            queries.append(context.business_module)
        if context.keywords:
            queries.extend(context.keywords[:5])

        # 实体类型过滤
        entity_types = []
        if task_type == TaskType.SCRIPT_GENERATION.value:
            entity_types = ["script", "case"]
        elif task_type == TaskType.CASE_GENERATION.value:
            entity_types = ["case", "chunk"]
        elif task_type == TaskType.WEB_TEST.value:
            entity_types = ["script", "page"]

        return MilvusQuery(
            queries=queries,
            collections=collections,
            entity_types=entity_types,
            top_k=10,
            score_threshold=0.3,
        )

    def _build_neo4j_plan(self, context: TaskContext, task_type: str) -> Neo4jQuery:
        """构建Neo4j查询计划"""
        labels = self.NEO4J_LABEL_MAP.get(TaskType(task_type), [])

        # 构建节点名称
        node_names = []
        if context.page_names:
            node_names.extend(context.page_names)
        if context.api_names:
            node_names.extend(context.api_names)

        # 从需求中提取页面名称
        if context.requirement:
            extracted = self._extract_entities(context.requirement)
            node_names.extend(extracted)

        # 关系类型
        relation_types = []
        if task_type == TaskType.SCRIPT_GENERATION.value:
            relation_types = ["HAS_ELEMENT", "CALLS_API", "GENERATES_SCRIPT", "TEST_ON"]
        elif task_type == TaskType.CASE_GENERATION.value:
            relation_types = ["HAS_ELEMENT", "TEST_ON", "DERIVES_TEST"]
        elif task_type == TaskType.WEB_TEST.value:
            relation_types = ["HAS_ELEMENT", "NAVIGATE_TO", "GENERATES_SCRIPT"]

        # 起始节点
        start_nodes = []
        for name in node_names[:3]:
            start_nodes.append({"label": "Page", "name": name})

        return Neo4jQuery(
            node_labels=labels,
            node_names=node_names[:10],
            relation_types=relation_types,
            depth=2,
            start_nodes=start_nodes,
        )

    def _extract_entities(self, text: str) -> List[str]:
        """从需求文本中提取可能的实体名称（页面名/接口名）"""
        entities = []

        # 提取中文页面名（如"登录页面"、"首页"等）
        page_patterns = [
            r"([\u4e00-\u9fa5]{2,6})页面",
            r"([\u4e00-\u9fa5]{2,6})页",
            r"([\u4e00-\u9fa5]{2,6})页面",
        ]
        for pattern in page_patterns:
            matches = re.findall(pattern, text)
            entities.extend(matches)

        # 提取英文页面名
        en_matches = re.findall(r"\b(login|register|home|cart|order|payment|user|profile)\b", text, re.IGNORECASE)
        entities.extend(en_matches)

        return list(set(entities))[:5]

    def _generate_reason(
        self,
        context: TaskContext,
        task_type: str,
        mysql_plan: MysqlQuery,
        milvus_plan: MilvusQuery,
        neo4j_plan: Neo4jQuery,
    ) -> str:
        """生成路由理由说明"""
        parts = [f"任务类型: {task_type}"]

        if mysql_plan.tables:
            parts.append(f"MySQL查询表: {', '.join(mysql_plan.tables)}（获取业务数据）")

        if milvus_plan.queries:
            parts.append(f"Milvus检索: {len(milvus_plan.queries)}条查询（获取历史知识）")

        if neo4j_plan.node_labels:
            parts.append(f"Neo4j查询: 标签{neo4j_plan.node_labels}（获取业务关系）")
        else:
            parts.append("Neo4j: 跳过（当前任务类型无需图查询）")

        return " | ".join(parts)


# 单例
_router: Optional[ContextRouter] = None


def get_context_router() -> ContextRouter:
    """获取ContextRouter单例"""
    global _router
    if _router is None:
        _router = ContextRouter()
    return _router
