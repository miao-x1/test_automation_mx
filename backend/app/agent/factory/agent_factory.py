"""
AgentFactory - Agent 工厂

负责：
- 注册 Agent 类
- 注销 Agent 类
- 根据名称创建 Agent 实例
- 根据能力获取 Agent 列表
- 支持多个模型 Provider
- 管理默认配置

设计原则：
1. Agent 类注册后，可按需创建实例
2. 创建实例时注入 Runtime 和 Config
3. 支持按能力查询（如 vision, crawl, case_generate）
4. 新增 Agent 只需注册，无需修改调用方代码
"""
import importlib
import threading
from typing import Any, Dict, List, Optional, Type

from app.agent.core.base_agent import BaseAgent
from app.agent.core.config import AgentConfig, create_default_config
from app.agent.core.types import AgentCapability
from app.agent.core.exceptions import (
    AgentNotFoundError,
    AgentAlreadyExistsError,
    AgentConfigError,
)
from app.core.logger import log


class AgentFactory:
    """
    Agent 工厂（单例）。

    使用方式：
        # 注册
        AgentFactory.register("requirement_agent", RequirementAgent, config)

        # 创建实例
        agent = AgentFactory.create("requirement_agent", runtime=runtime)

        # 按能力查询
        agents = AgentFactory.get_by_capability(AgentCapability.VISION)

    新增 Agent 时只需：
        AgentFactory.register("new_agent", NewAgent)
    后续在 Intent Router 中引用即可。
    """

    # 类级注册表
    _registry: Dict[str, Type[BaseAgent]] = {}
    _configs: Dict[str, AgentConfig] = {}
    _instances: Dict[str, BaseAgent] = {}
    _lock = threading.Lock()

    # ---- 注册与注销 ----

    @classmethod
    def register(
        cls,
        agent_name: str,
        agent_class: Type[BaseAgent],
        config: Optional[AgentConfig] = None,
    ) -> None:
        """注册 Agent 类"""
        with cls._lock:
            if agent_name in cls._registry:
                log.debug(f"Agent '{agent_name}' already registered, updating")
                cls._registry[agent_name] = agent_class
                if config:
                    cls._configs[agent_name] = config
                return

            cls._registry[agent_name] = agent_class

            if config is None:
                config = create_default_config(
                    agent_name=agent_name,
                    description=getattr(agent_class, "description", ""),
                )
            cls._configs[agent_name] = config

            # 从类属性同步能力标签
            capabilities = getattr(agent_class, "capabilities", [])
            if capabilities and not config.capabilities:
                config.capabilities = [c.value if isinstance(c, AgentCapability) else c for c in capabilities]

            log.info(f"Agent '{agent_name}' registered (class={agent_class.__name__})")

    @classmethod
    def unregister(cls, agent_name: str) -> None:
        """注销 Agent"""
        with cls._lock:
            cls._registry.pop(agent_name, None)
            cls._configs.pop(agent_name, None)
            cls._instances.pop(agent_name, None)
            log.info(f"Agent '{agent_name}' unregistered")

    # ---- 创建实例 ----

    @classmethod
    def create(
        cls,
        agent_name: str,
        runtime: Optional[Any] = None,
        session_id: Optional[str] = None,
        config: Optional[AgentConfig] = None,
        **kwargs,
    ) -> BaseAgent:
        """
        创建 Agent 实例。

        参数：
        - agent_name: Agent 名称
        - runtime: Runtime 实例（可选）
        - session_id: Session ID（可选）
        - config: 覆盖默认配置（可选）
        - **kwargs: 传递给 Agent 构造函数的额外参数
        """
        with cls._lock:
            agent_class = cls._registry.get(agent_name)

        if agent_class is None:
            # 尝试懒加载
            agent_class = cls._lazy_load(agent_name)

        if agent_class is None:
            raise AgentNotFoundError(agent_name)

        # 获取配置
        if config is None:
            config = cls._configs.get(agent_name)
        if config is None:
            config = create_default_config(agent_name=agent_name)

        # 创建实例
        try:
            agent = agent_class(
                config=config,
                runtime=runtime,
                session_id=session_id,
                **kwargs,
            )
            return agent
        except Exception as e:
            raise AgentConfigError(
                f"Failed to create agent '{agent_name}': {e}",
                agent_name=agent_name,
            ) from e

    @classmethod
    def create_and_register(
        cls,
        agent_name: str,
        runtime: Any,
        session_id: str,
        **kwargs,
    ) -> BaseAgent:
        """
        创建 Agent 实例并注册到 Runtime。

        便捷方法：创建 + 注册一步完成。
        注册时使用 agent_name 作为键，确保与工厂注册名一致。
        """
        agent = cls.create(agent_name, runtime=runtime, session_id=session_id, **kwargs)
        runtime.register_agent(agent, name=agent_name)
        return agent

    # ---- 查询 ----

    @classmethod
    def get_config(cls, agent_name: str) -> Optional[AgentConfig]:
        """获取 Agent 配置"""
        with cls._lock:
            return cls._configs.get(agent_name)

    @classmethod
    def list_agents(cls) -> Dict[str, dict]:
        """列出所有已注册 Agent"""
        with cls._lock:
            result = {}
            for name, agent_class in cls._registry.items():
                config = cls._configs.get(name)
                result[name] = {
                    "agent_name": name,
                    "class_name": agent_class.__name__,
                    "display_name": getattr(agent_class, "display_name", name),
                    "description": getattr(agent_class, "description", ""),
                    "capabilities": [
                        c.value if isinstance(c, AgentCapability) else c
                        for c in getattr(agent_class, "capabilities", [])
                    ],
                    "model": config.model_name if config else "",
                    "provider": config.provider if config else "",
                }
            return result

    @classmethod
    def get_by_capability(cls, capability: AgentCapability) -> List[str]:
        """根据能力获取 Agent 列表"""
        cap_value = capability.value if isinstance(capability, AgentCapability) else str(capability)
        with cls._lock:
            result = []
            for name, agent_class in cls._registry.items():
                capabilities = getattr(agent_class, "capabilities", [])
                cap_values = [c.value if isinstance(c, AgentCapability) else c for c in capabilities]
                if cap_value in cap_values:
                    result.append(name)
            return result

    @classmethod
    def get_by_name(cls, agent_name: str) -> Optional[Type[BaseAgent]]:
        """根据名称获取 Agent 类"""
        with cls._lock:
            return cls._registry.get(agent_name)

    @classmethod
    def is_registered(cls, agent_name: str) -> bool:
        """检查 Agent 是否已注册"""
        with cls._lock:
            return agent_name in cls._registry

    @classmethod
    def count(cls) -> int:
        """获取已注册 Agent 数量"""
        with cls._lock:
            return len(cls._registry)

    # ---- 懒加载（兼容旧 AgentFactory） ----

    @classmethod
    def _lazy_load(cls, agent_name: str) -> Optional[Type[BaseAgent]]:
        """
        懒加载未注册的 Agent。

        通过名称映射动态导入 Agent 类，
        兼容旧的 AgentFactory.create_agent() 接口。
        所有路径已更新为重构后的正确位置。
        """
        lazy_map = {
            "requirement_agent": "app.agent.requirement.requirement_agent.RequirementAgent",
            "execution_agent": "app.agent.execution.execution_agent.ExecutionAgent",
            "rag_agent": "app.agent.rag.rag_agent.RAGAgent",
            "graph_agent": "app.agent.graph.graph_agent.GraphAgent",
            "element_agent": "app.agent.vision.element_agent.ElementAgent",
            "case_agent": "app.agent.case.case_agent.CaseAgent",
            "feedback_agent": "app.agent.feedback.feedback_agent.FeedbackAgent",
            "script_generation_agent": "app.agent.script.script_generation_agent.ScriptGenerationAgent",
            "script_executor": "app.agent.script.script_executor.ScriptExecutor",
            "page_crawler_agent": "app.agent.vision.page_crawler_agent.PageCrawlerAgent",
            "embedding_agent": "app.agent.rag.embedding_agent.EmbeddingAgent",
            "retrieval_agent": "app.agent.rag.retrieval_agent.RetrievalAgent",
            "knowledge_update_agent": "app.agent.requirement.knowledge_update_agent.KnowledgeUpdateAgent",
            "script_reuse_agent": "app.agent.script.script_reuse_agent.ScriptReuseAgent",
            "relation_agent": "app.agent.graph.relation_agent.RelationAgent",
            "playwright_agent": "app.agent.vision.playwright_agent.PlaywrightAgent",
            "element_merge_agent": "app.agent.vision.element_merge_agent.ElementMergeAgent",
            "fusion_agent": "app.agent.requirement.fusion_agent.FusionAgent",
            "input_router": "app.agent.requirement.input_router.InputRouter",
            "flow_parser": "app.agent.requirement.flow_parser.FlowParser",
            "flow_script_generator": "app.agent.requirement.flow_script_generator.FlowScriptGenerator",
            "page_state_manager": "app.agent.requirement.page_state_manager.PageStateManager",
            "strategy_agent": "app.agent.script.strategy_agent.StrategyAgent",
            "type_classifier": "app.agent.requirement.test_type_classifier_agent.TestTypeClassifierAgent",
            "script_parser": "app.agent.script.script_parser.ScriptParser",
            "script_validator": "app.agent.script.script_validator.ScriptValidator",
            "scheduler_agent": "app.agent.scheduling.scheduler_agent.SchedulerAgent",
            "task_executor": "app.agent.scheduling.task_executor.TaskExecutor",
            "review_agent": "app.agent.case.review_agent.ReviewAgent",
            "storage_agent": "app.agent.storage.storage_agent.StorageAgent",
        }

        dotted_path = lazy_map.get(agent_name)
        if not dotted_path:
            return None

        try:
            module_path, class_name = dotted_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            agent_class = getattr(module, class_name)

            # 自动注册
            config = create_default_config(
                agent_name=agent_name,
                description=getattr(agent_class, "description", ""),
            )
            cls.register(agent_name, agent_class, config)
            return agent_class
        except Exception as e:
            log.warning(f"Lazy load agent '{agent_name}' failed: {e}")
            return None

    # ---- 兼容旧接口 ----

    @classmethod
    def create_agent(cls, agent_type: Optional[str] = None, **kwargs) -> BaseAgent:
        """兼容旧 AgentFactory.create_agent() 接口"""
        if not agent_type:
            raise ValueError("create_agent 必须指定真实 agent_type，禁止回落到 mock")
        return cls.create(agent_type, **kwargs)

    @classmethod
    def get_agent_config(cls, agent_name: str) -> Optional[AgentConfig]:
        """兼容旧 AgentFactory.get_config() 接口"""
        return cls.get_config(agent_name)
