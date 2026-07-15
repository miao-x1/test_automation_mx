"""
AgentRegistry - Agent 自动注册

所有 Agent 在模块导入时自动注册到 AgentFactory，
后续新增 Agent 无需修改其它代码。

注册的 Agent 列表：
- RequirementAgent      - 需求解析
- ImageAgent            - 图片分析（ElementAgent）
- VideoAgent            - 视频分析（预留）
- ApiAgent              - API 文档解析（预留）
- DocumentAgent         - PDF/文档解析（预留）
- CaseAgent             - 用例生成
- ScriptAgent           - 脚本生成（ScriptGenerator）
- ExecutionAgent        - 脚本执行
- ReviewAgent           - 审查/反馈（FeedbackAgent）
- MindMapAgent          - 思维导图（预留）
- RAGAgent              - RAG 检索
- KnowledgeAgent        - 知识更新（KnowledgeUpdateAgent）
- ResultCollectorAgent  - 结果收集
- GraphAgent            - 图推理
- PageCrawlerAgent      - 页面抓取
- ElementMergeAgent     - 元素融合
- ScriptReuseAgent      - 脚本复用
- RelationAgent         - 页面关联
- EmbeddingAgent        - 向量化
- RetrievalAgent        - 元素检索
- GraphSearchAgent      - 图搜索
- StrategyAgent         - 策略选择
- TypeClassifier        - 类型分类
- FlowParser            - 流程解析
- FlowScriptGenerator   - 流程脚本
- SchedulerAgent        - 定时调度
- TaskExecutor          - 定时执行
- ScriptParser          - 脚本解析
- ScriptValidator       - 脚本校验
- MockAgent             - Mock
"""
import importlib
from typing import Dict, List, Tuple, Type

from app.agent.core.base_agent import BaseAgent
from app.agent.core.config import AgentConfig, create_default_config
from app.agent.factory.agent_factory import AgentFactory
from app.agent.core.types import AgentCapability
from app.core.config import settings
from app.core.logger import log


# Agent 注册定义表
# (agent_name, module_path, class_name, display_name, capabilities)
_AGENT_DEFINITIONS: List[Tuple[str, str, str, str, List[AgentCapability]]] = [
    # ---- 核心业务 Agent ----
    (
        "requirement_agent",
        "app.agent.requirement.requirement_agent",
        "RequirementAgent",
        "需求解析Agent",
        [AgentCapability.REQUIREMENT_PARSE],
    ),
    (
        "element_agent",
        "app.agent.vision.element_agent",
        "ElementAgent",
        "视觉元素识别Agent（ImageAgent）",
        [AgentCapability.VISION],
    ),
    (
        "case_agent",
        "app.agent.case.case_agent",
        "CaseAgent",
        "用例生成Agent",
        [AgentCapability.CASE_GENERATE],
    ),
    (
        "script_generation_agent",
        "app.agent.script.script_generation_agent",
        "ScriptGenerationAgent",
        "脚本生成Agent（含4级降级链）",
        [AgentCapability.SCRIPT_GENERATE],
    ),
    (
        "execution_agent",
        "app.agent.execution.execution_agent",
        "ExecutionAgent",
        "脚本执行Agent",
        [AgentCapability.SCRIPT_EXECUTE],
    ),
    (
        "feedback_agent",
        "app.agent.feedback.feedback_agent",
        "FeedbackAgent",
        "反馈分析Agent（ReviewAgent）",
        [AgentCapability.FEEDBACK],
    ),
    (
        "rag_agent",
        "app.agent.rag.rag_agent",
        "RAGAgent",
        "RAG检索Agent",
        [AgentCapability.RAG_RETRIEVE],
    ),
    (
        "knowledge_update_agent",
        "app.agent.requirement.knowledge_update_agent",
        "KnowledgeUpdateAgent",
        "知识更新Agent（KnowledgeAgent）",
        [AgentCapability.KNOWLEDGE_UPDATE],
    ),
    (
        "graph_agent",
        "app.agent.graph.graph_agent",
        "GraphAgent",
        "图推理Agent",
        [AgentCapability.GRAPH_INFER],
    ),
    (
        "page_crawler_agent",
        "app.agent.vision.page_crawler_agent",
        "PageCrawlerAgent",
        "页面抓取Agent",
        [AgentCapability.CRAWL],
    ),
    (
        "element_merge_agent",
        "app.agent.vision.element_merge_agent",
        "ElementMergeAgent",
        "元素融合Agent",
        [AgentCapability.MERGE],
    ),
    # ---- 检索与索引 ----
    (
        "embedding_agent",
        "app.agent.rag.embedding_agent",
        "EmbeddingAgent",
        "向量化Agent",
        [AgentCapability.EMBEDDING],
    ),
    (
        "retrieval_agent",
        "app.agent.rag.retrieval_agent",
        "RetrievalAgent",
        "元素检索Agent",
        [AgentCapability.RAG_RETRIEVE],
    ),
    (
        "script_reuse_agent",
        "app.agent.script.script_reuse_agent",
        "ScriptReuseAgent",
        "脚本复用Agent",
        [AgentCapability.REUSE_CHECK],
    ),
    (
        "graph_search_agent",
        "app.agent.graph_search_agent",
        "GraphSearchAgent",
        "图搜索Agent",
        [AgentCapability.GRAPH_SEARCH],
    ),
    # ---- 流程与策略 ----
    (
        "relation_agent",
        "app.agent.graph.relation_agent",
        "RelationAgent",
        "页面关联Agent",
        [AgentCapability.RELATION],
    ),
    (
        "flow_parser",
        "app.agent.requirement.flow_parser",
        "FlowParser",
        "流程解析Agent",
        [AgentCapability.FLOW_PARSE],
    ),
    (
        "flow_script_generator",
        "app.agent.requirement.flow_script_generator",
        "FlowScriptGenerator",
        "流程脚本Agent",
        [AgentCapability.FLOW_SCRIPT],
    ),
    (
        "strategy_agent",
        "app.agent.script.strategy_agent",
        "StrategyAgent",
        "策略选择Agent",
        [AgentCapability.STRATEGY],
    ),
    (
        "type_classifier",
        "app.agent.requirement.type_classifier",
        "TypeClassifier",
        "类型分类Agent",
        [AgentCapability.TYPE_CLASSIFY],
    ),
    # ---- 脚本工具 ----
    (
        "script_parser",
        "app.agent.script.script_parser",
        "ScriptParser",
        "脚本解析Agent",
        [AgentCapability.SCRIPT_PARSE],
    ),
    (
        "script_validator",
        "app.agent.script.script_validator",
        "ScriptValidator",
        "脚本校验Agent",
        [AgentCapability.SCRIPT_VALIDATE],
    ),
    (
        "script_executor",
        "app.agent.script.script_executor",
        "ScriptExecutor",
        "脚本执行器Agent",
        [AgentCapability.SCRIPT_EXECUTE],
    ),
    # ---- 调度 ----
    (
        "scheduler_agent",
        "app.agent.scheduling.scheduler_agent",
        "SchedulerAgent",
        "定时调度Agent",
        [AgentCapability.SCHEDULE],
    ),
    (
        "task_executor",
        "app.agent.scheduling.task_executor",
        "TaskExecutor",
        "定时执行Agent",
        [AgentCapability.SCHEDULE],
    ),
    # ---- 融合与路由 ----
    (
        "fusion_agent",
        "app.agent.requirement.fusion_agent",
        "FusionAgent",
        "多模态融合Agent",
        [AgentCapability.DATA_FUSION],
    ),
    (
        "input_router",
        "app.agent.requirement.input_router",
        "InputRouter",
        "输入路由Agent",
        [AgentCapability.INTENT_ROUTE],
    ),
    (
        "router_agent",
        "app.agent.router_agent",
        "RouterAgent",
        "三库路由Agent",
        [AgentCapability.INTENT_ROUTE],
    ),
    # ---- Mock ----
    (
        "mock_agent",
        "app.agent.mock_agent",
        "MockAgent",
        "Mock Agent",
        [AgentCapability.MOCK],
    ),
    (
        "playwright_agent",
        "app.agent.vision.playwright_agent",
        "PlaywrightAgent",
        "Playwright脚本生成Agent",
        [AgentCapability.SCRIPT_GENERATE],
    ),
]


class AgentRegistry:
    """
    Agent 自动注册器。

    在应用启动时调用 auto_register_agents()，
    自动将所有 Agent 注册到 AgentFactory。

    新增 Agent 时：
    1. 在 _AGENT_DEFINITIONS 中添加一行
    2. 或在 Agent 类上使用 @register_agent 装饰器
    3. 无需修改其它代码
    """

    _registered: bool = False

    @classmethod
    def auto_register(cls) -> Dict[str, bool]:
        """
        自动注册所有 Agent。

        返回 {agent_name: success} 字典。
        失败的 Agent 会被跳过，不影响其它 Agent 注册。
        """
        if cls._registered:
            log.debug("Agents already auto-registered, skipping")
            return {}

        results: Dict[str, bool] = {}

        for agent_name, module_path, class_name, display_name, capabilities in _AGENT_DEFINITIONS:
            try:
                # 动态导入
                module = importlib.import_module(module_path)
                agent_class = getattr(module, class_name)

                # 始终设置类属性，确保与注册名一致
                agent_class.agent_name = agent_name
                if not getattr(agent_class, "display_name", "") or agent_class.display_name == "Base Agent":
                    agent_class.display_name = display_name
                if not getattr(agent_class, "capabilities", []):
                    agent_class.capabilities = capabilities

                # 创建配置
                config = create_default_config(
                    agent_name=agent_name,
                    display_name=display_name,
                    description=display_name,
                )
                config.capabilities = [c.value for c in capabilities]

                # 注册
                AgentFactory.register(agent_name, agent_class, config)
                results[agent_name] = True

            except ImportError as e:
                log.warning(f"Skip agent '{agent_name}' (import error): {e}")
                results[agent_name] = False
            except Exception as e:
                log.warning(f"Skip agent '{agent_name}' (register error): {e}")
                results[agent_name] = False

        cls._registered = True
        success_count = sum(1 for v in results.values() if v)
        log.info(f"AgentRegistry: {success_count}/{len(results)} agents registered")

        return results

    @classmethod
    def register_custom(
        cls,
        agent_name: str,
        agent_class: Type[BaseAgent],
        config: AgentConfig = None,
    ) -> None:
        """
        手动注册自定义 Agent。

        用于运行时动态注册新 Agent。
        """
        AgentFactory.register(agent_name, agent_class, config)

    @classmethod
    def reset(cls) -> None:
        """重置注册状态（测试用）"""
        cls._registered = False


def auto_register_agents() -> Dict[str, bool]:
    """便捷函数：自动注册所有 Agent"""
    return AgentRegistry.auto_register()
