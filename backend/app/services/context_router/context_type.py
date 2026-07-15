"""
ContextType - 上下文类型枚举

定义 Agent 查询时必须指定的上下文类型，
ContextRouter 据此决定查询哪些数据源。

核心原则：
  1. Agent 禁止直接访问 Milvus / Neo4j / MySQL SessionLocal
  2. 所有上下文获取必须经过 ContextRouter
  3. R2R 只是知识入库工具（解析→分块→向量化→存入Milvus），不参与运行时查询
  4. 所有运行时检索都走 MySQL / Milvus / Neo4j，由 ContextRouter 统一路由
"""
from enum import Enum


class ContextType(str, Enum):
    """上下文查询类型

    每种类型对应一组数据源组合：
      PAGE_ELEMENT       → MySQL + Milvus + Neo4j
      DOCUMENT           → Milvus + MySQL
      TEST_CASE          → Milvus
      BUSINESS_FLOW      → Neo4j + MySQL
      SCRIPT             → Milvus + MySQL
      EXECUTION_HISTORY  → MySQL
      REQUIREMENT_TASK   → MySQL
      TASK               → MySQL
      SCHEDULE_TASK      → MySQL
      FEEDBACK           → MySQL
      SESSION_EVENT      → MySQL
      FLOW_RESULT        → MySQL
    """

    PAGE_ELEMENT = "page_element"
    """页面元素：MySQL（UIElement表）+ Milvus（ui_element_vector）+ Neo4j（Page→Element关系）"""

    DOCUMENT = "document"
    """知识文档：Milvus（rag_knowledge_vector集合）+ MySQL（knowledge_source/knowledge_chunk元数据）"""

    TEST_CASE = "test_case"
    """测试用例：Milvus（test_case_vector集合）"""

    BUSINESS_FLOW = "business_flow"
    """业务流程：Neo4j（页面导航路径）+ MySQL（PageElement表）"""

    SCRIPT = "script"
    """测试脚本：Milvus（script_vector集合）+ MySQL（Script表）"""

    EXECUTION_HISTORY = "execution_history"
    """执行历史：MySQL（ExecutionRecord表）"""

    REQUIREMENT_TASK = "requirement_task"
    """需求任务：MySQL（RequirementTask表）"""

    TASK = "task"
    """测试任务：MySQL（Task表）"""

    SCHEDULE_TASK = "schedule_task"
    """定时任务：MySQL（ScheduleTask表）"""

    FEEDBACK = "feedback"
    """用户反馈：MySQL（Feedback表）"""

    SESSION_EVENT = "session_event"
    """会话事件：MySQL（SessionEvent表）"""

    FLOW_RESULT = "flow_result"
    """流程结果：MySQL（FlowResult表）"""


# 路由配置：每种 ContextType 对应的数据源
# R2R 不在路由表中 — R2R 只是知识入库工具，不参与运行时查询
ROUTING_TABLE = {
    ContextType.PAGE_ELEMENT: ["mysql", "milvus", "neo4j"],
    ContextType.DOCUMENT: ["milvus", "mysql"],
    ContextType.TEST_CASE: ["milvus"],
    ContextType.BUSINESS_FLOW: ["neo4j", "mysql"],
    ContextType.SCRIPT: ["milvus", "mysql"],
    ContextType.EXECUTION_HISTORY: ["mysql"],
    ContextType.REQUIREMENT_TASK: ["mysql"],
    ContextType.TASK: ["mysql"],
    ContextType.SCHEDULE_TASK: ["mysql"],
    ContextType.FEEDBACK: ["mysql"],
    ContextType.SESSION_EVENT: ["mysql"],
    ContextType.FLOW_RESULT: ["mysql"],
}
