"""
统一 Agent 工厂

封装 AgentRegistry 的创建逻辑，提供简洁的工厂接口。

职责：
  1. 自动注册所有 Agent（启动时调用一次）
  2. 按名称创建 Agent 实例
  3. 按名称检查 Agent 是否已注册
  4. 列出所有可用 Agent

设计原则：
  - 所有 Agent 创建必须经过 AgentFactory
  - 禁止业务代码直接 new Agent 或 import Agent 类
  - Agent 创建后由调用方负责执行和异常处理
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AgentFactory:
    """
    统一 Agent 工厂

    使用方式：
        # 启动时注册
        AgentFactory.initialize()

        # 创建 Agent
        agent = AgentFactory.create("requirement_agent")

        # 检查是否注册
        if AgentFactory.is_available("case_agent"):
            ...
    """

    _initialized = False

    @classmethod
    def initialize(cls) -> None:
        """初始化：触发 AgentRegistry 自动注册"""
        if cls._initialized:
            return

        try:
            from app.agents.factory import AgentRegistry
            AgentRegistry.auto_register()
            cls._initialized = True
            agent_count = len(AgentRegistry.list_agents())
            logger.info(
                f"AgentFactory | 初始化完成 | "
                f"已注册 {agent_count} 个 Agent"
            )
        except Exception as e:
            logger.error(f"AgentFactory | 初始化失败: {e}", exc_info=True)
            cls._initialized = True  # 避免重复尝试

    @classmethod
    def create(cls, agent_name: str, **kwargs) -> Any:
        """创建 Agent 实例

        Args:
            agent_name: Agent 名称（在 agent_config.yaml 中注册的名称）
            **kwargs: 传递给 Agent 构造函数的额外参数

        Returns:
            Agent 实例

        Raises:
            ValueError: Agent 未注册
        """
        cls.initialize()

        from app.agents.factory import AgentRegistry

        # 确保已注册
        if not AgentRegistry.is_registered(agent_name):
            # 再尝试一次自动注册
            AgentRegistry.auto_register()

        if not AgentRegistry.is_registered(agent_name):
            available = [a["agent_name"] for a in AgentRegistry.list_agents()]
            raise ValueError(
                f"Agent '{agent_name}' 未注册。"
                f"可用 Agent: {available[:20]}..."
            )

        agent = AgentRegistry.create(agent_name, **kwargs)
        return agent

    @classmethod
    def is_available(cls, agent_name: str) -> bool:
        """检查 Agent 是否可用"""
        cls.initialize()

        from app.agents.factory import AgentRegistry
        if not AgentRegistry.is_registered(agent_name):
            AgentRegistry.auto_register()
        return AgentRegistry.is_registered(agent_name)

    @classmethod
    def list_agents(cls) -> List[Dict[str, Any]]:
        """列出所有可用 Agent"""
        cls.initialize()

        from app.agents.factory import AgentRegistry
        return AgentRegistry.list_agents()

    @classmethod
    def get_config(cls, agent_name: str) -> Optional[Dict[str, Any]]:
        """获取 Agent 配置信息"""
        cls.initialize()

        from app.agents.factory import AgentRegistry
        config = AgentRegistry.get_config(agent_name)
        if config is None:
            return None
        return {
            "agent_name": config.agent_name,
            "display_name": config.display_name,
            "description": config.description,
            "model": config.model,
        }

    @classmethod
    async def dispatch_action(
        cls,
        agent: Any,
        action: str,
        input_data: Dict[str, Any],
    ) -> Any:
        """根据 action 调用 Agent 的对应方法

        这是编排器的核心方法：将 action 映射到 Agent 的方法名，
        并处理参数传递。

        action → method 映射：
          analyze   → analyze / execute / process
          generate  → generate / generate_cases / generate_script / execute
          review    → review / execute
          execute   → execute / run / run_script
          retrieve  → retrieve / search / execute
          parse     → parse / execute / process
          embed     → embed / embed_elements / execute
          store     → store / save / execute
          classify  → execute / classify / classify_sync
          infer     → infer / find_related_pages / execute
          build     → build / build_full_graph / execute
          update    → update / execute
          sync      → sync / execute

        参数适配：
          classify_sync 方法需要 text 参数，但 orchestrator 传入 requirement。
          此处自动做参数名映射，确保不同 Agent 的参数 key 都能对接。
        """
        import asyncio

        action_map = {
            "analyze": ["analyze", "execute", "process"],
            "generate": ["generate", "generate_cases", "generate_script", "execute"],
            "review": ["review", "execute"],
            "execute": ["execute", "run", "run_script"],
            "retrieve": ["retrieve", "search", "execute"],
            "parse": ["parse", "execute", "process"],
            "embed": ["embed", "embed_elements", "execute"],
            "store": ["store", "save", "execute"],
            # classify: execute 优先（async，参数 key 兼容性好），
            # classify_sync 最后（同步，参数 key 为 text 需要适配）
            "classify": ["execute", "classify", "classify_sync"],
            "infer": ["infer", "find_related_pages", "execute"],
            "build": ["build", "build_full_graph", "execute"],
            "update": ["update", "execute"],
            "sync": ["sync", "execute"],
        }

        method_names = action_map.get(action, [action, "execute"])

        for method_name in method_names:
            method = getattr(agent, method_name, None)
            if method is None:
                continue

            # 参数名适配：不同方法可能需要不同的参数名
            adapted_input = cls._adapt_params(method_name, input_data)

            # 尝试调用：先 **kwargs，再 dict 参数，最后无参
            try:
                if asyncio.iscoroutinefunction(method):
                    try:
                        return await method(**adapted_input) if isinstance(adapted_input, dict) else await method(adapted_input)
                    except TypeError:
                        return await method(adapted_input)
                else:
                    try:
                        return await asyncio.to_thread(method, **adapted_input) if isinstance(adapted_input, dict) else await asyncio.to_thread(method, adapted_input)
                    except TypeError:
                        return await asyncio.to_thread(method, adapted_input)
            except TypeError:
                try:
                    if asyncio.iscoroutinefunction(method):
                        return await method()
                    else:
                        return await asyncio.to_thread(method)
                except Exception:
                    continue
            except Exception:
                continue

        logger.warning(
            f"AgentFactory | Agent '{agent.__class__.__name__}' 无可用方法 | "
            f"action={action} | 降级返回输入数据"
        )
        return input_data

    @staticmethod
    def _adapt_params(method_name: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """参数名适配

        不同 Agent 方法可能使用不同的参数名：
          - execute(): requirement, urls, images, swagger_content, ...
          - classify_sync(): text, urls, script_content, ...
          - analyze(): requirement, image_paths, ...

        此方法将 orchestrator 的统一输入（requirement 等）
        映射为目标方法期望的参数名。
        """
        if not isinstance(input_data, dict):
            return input_data

        adapted = dict(input_data)

        # classify_sync 需要 text 参数，orchestrator 传入 requirement
        if method_name == "classify_sync":
            if "text" not in adapted and "requirement" in adapted:
                adapted["text"] = adapted["requirement"]

        # 部分旧 Agent 的 analyze 方法需要 image_paths，orchestrator 传入 images
        if method_name == "analyze":
            if "image_paths" not in adapted and "images" in adapted:
                adapted["image_paths"] = adapted["images"]

        return adapted
