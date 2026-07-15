"""
AgentRegistry - 统一 Agent 注册机制（YAML 驱动）

职责：
  1. 从 agent_config.yaml 加载 Agent 配置
  2. 动态注册 Agent 类到 AgentFactory
  3. 提供 Agent 查询接口（按名称、按能力）
  4. 提供 Agent 实例创建入口

使用方式：
  from app.agents.factory import AgentRegistry

  # 自动注册（启动时调用一次）
  AgentRegistry.auto_register()

  # 查询
  AgentRegistry.list_agents()
  AgentRegistry.get_config("requirement_agent")

  # 创建实例
  agent = AgentRegistry.create("requirement_agent")

设计原则：
  - 所有 Agent 配置集中管理在 agent_config.yaml
  - 新增 Agent 只需在 YAML 中添加一条配置
  - 禁止业务代码直接 new Agent，必须通过 Registry/Factory 创建
"""
import importlib
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

from app.core.logger import log


# ------------------------------------------------------------------
# 数据结构
# ------------------------------------------------------------------

@dataclass
class AgentConfigEntry:
    """YAML 中的单条 Agent 配置"""
    agent_name: str
    class_path: str          # e.g. "app.agent.requirement.requirement_agent.RequirementAgent"
    display_name: str = ""
    description: str = ""
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    system_prompt: Optional[str] = None
    # 运行时填充
    _module_path: str = ""
    _class_name: str = ""
    _agent_class: Optional[Type] = None

    def __post_init__(self):
        if "." in self.class_path:
            parts = self.class_path.rsplit(".", 1)
            self._module_path = parts[0]
            self._class_name = parts[1]


# ------------------------------------------------------------------
# AgentRegistry
# ------------------------------------------------------------------

class AgentRegistry:
    """
    统一 Agent 注册器

    从 agent_config.yaml 加载配置，动态注册到 AgentFactory。
    所有 Agent 创建必须经过本 Registry 或 AgentFactory。

    新增 Agent 步骤：
      1. 在 agent_config.yaml 中添加一条配置
      2. 确保对应的 Agent 类文件存在
      3. 无需修改任何其它代码
    """

    _configs: Dict[str, AgentConfigEntry] = {}
    _model_aliases: Dict[str, str] = {}
    _registered: bool = False
    _lock = threading.Lock()

    # ------------------------------------------------------------------
    # 初始化与加载
    # ------------------------------------------------------------------

    @classmethod
    def _find_yaml_path(cls) -> str:
        """定位 agent_config.yaml"""
        current = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(current, "agent_config.yaml")

    @classmethod
    def _load_yaml(cls) -> Dict:
        """加载 YAML 配置"""
        yaml_path = cls._find_yaml_path()
        if not os.path.isfile(yaml_path):
            log.warning(f"AgentRegistry | YAML 配置文件不存在: {yaml_path}")
            return {"agents": [], "model_aliases": {}}

        try:
            import yaml
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return data or {}
        except ImportError:
            log.error("AgentRegistry | PyYAML 未安装，使用内置默认配置")
            return {"agents": [], "model_aliases": {}}
        except Exception as e:
            log.error(f"AgentRegistry | 加载 YAML 失败: {e}")
            return {"agents": [], "model_aliases": {}}

    @classmethod
    def _parse_configs(cls, yaml_data: Dict) -> None:
        """解析 YAML 数据为 AgentConfigEntry"""
        agents_list = yaml_data.get("agents", [])
        for item in agents_list:
            name = item.get("agent_name", "")
            if not name:
                continue
            entry = AgentConfigEntry(
                agent_name=name,
                class_path=item.get("class_path", ""),
                display_name=item.get("display_name", name),
                description=item.get("description", ""),
                model=item.get("model"),
                temperature=item.get("temperature"),
                max_tokens=item.get("max_tokens"),
                system_prompt=item.get("system_prompt"),
            )
            cls._configs[name] = entry

        # 模型别名
        cls._model_aliases = yaml_data.get("model_aliases", {})

        log.info(
            f"AgentRegistry | YAML 解析完成 | "
            f"agents={len(cls._configs)} | aliases={len(cls._model_aliases)}"
        )

    # ------------------------------------------------------------------
    # 自动注册
    # ------------------------------------------------------------------

    @classmethod
    def auto_register(cls) -> Dict[str, bool]:
        """自动注册所有 Agent 到 AgentFactory

        启动时调用一次，将 YAML 中所有 Agent 注册。

        Returns:
            {agent_name: success} 字典
        """
        with cls._lock:
            if cls._registered:
                log.debug("AgentRegistry | 已注册，跳过")
                return {}

            # 加载 YAML
            yaml_data = cls._load_yaml()
            cls._parse_configs(yaml_data)

            results: Dict[str, bool] = {}

            # 动态导入并注册
            for name, entry in cls._configs.items():
                try:
                    module = importlib.import_module(entry._module_path)
                    agent_class = getattr(module, entry._class_name)

                    # 设置类属性
                    agent_class.agent_name = name
                    if not getattr(agent_class, "display_name", "") or agent_class.display_name == "Base Agent":
                        agent_class.display_name = entry.display_name
                    if not getattr(agent_class, "description", ""):
                        agent_class.description = entry.description

                    entry._agent_class = agent_class
                    results[name] = True

                except ImportError as e:
                    log.warning(f"AgentRegistry | 跳过 '{name}' (导入失败): {e}")
                    results[name] = False
                except AttributeError as e:
                    log.warning(f"AgentRegistry | 跳过 '{name}' (类不存在): {e}")
                    results[name] = False
                except Exception as e:
                    log.warning(f"AgentRegistry | 跳过 '{name}' (注册失败): {e}")
                    results[name] = False

            # 注册到 AgentFactory（旧工厂）
            cls._register_to_factory()

            cls._registered = True
            success_count = sum(1 for v in results.values() if v)
            log.info(
                f"AgentRegistry | 注册完成 | "
                f"成功 {success_count}/{len(results)} | "
                f"失败 {len(results) - success_count}"
            )

            return results

    @classmethod
    def _register_to_factory(cls) -> None:
        """将已加载的 Agent 注册到旧的 AgentFactory（兼容）"""
        try:
            from app.agent.factory.agent_factory import AgentFactory
            from app.agent.core.config import create_default_config

            for name, entry in cls._configs.items():
                if entry._agent_class is None:
                    continue
                try:
                    config = create_default_config(
                        agent_name=name,
                        display_name=entry.display_name,
                        description=entry.description,
                    )
                    config.model_name = entry.model or ""
                    config.temperature = entry.temperature or 0.3
                    AgentFactory.register(name, entry._agent_class, config)
                except Exception as e:
                    log.debug(f"AgentRegistry | 注册到旧Factory '{name}' 失败: {e}")

        except ImportError:
            log.debug("AgentRegistry | 旧 AgentFactory 不可用，跳过兼容注册")

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    @classmethod
    def list_agents(cls) -> List[Dict[str, Any]]:
        """列出所有已注册 Agent"""
        results = []
        for name, entry in cls._configs.items():
            results.append({
                "agent_name": name,
                "class_name": entry._class_name,
                "display_name": entry.display_name,
                "description": entry.description,
                "model": entry.model,
                "temperature": entry.temperature,
                "system_prompt": entry.system_prompt[:50] + "..." if entry.system_prompt and len(entry.system_prompt) > 50 else entry.system_prompt,
                "loaded": entry._agent_class is not None,
            })
        return results

    @classmethod
    def get_config(cls, agent_name: str) -> Optional[AgentConfigEntry]:
        """获取 Agent 配置"""
        return cls._configs.get(agent_name)

    @classmethod
    def get_agent_class(cls, agent_name: str) -> Optional[Type]:
        """获取 Agent 类"""
        entry = cls._configs.get(agent_name)
        if entry and entry._agent_class:
            return entry._agent_class
        return None

    @classmethod
    def is_registered(cls, agent_name: str) -> bool:
        """检查 Agent 是否已注册"""
        entry = cls._configs.get(agent_name)
        return entry is not None and entry._agent_class is not None

    @classmethod
    def count(cls) -> int:
        """获取已注册 Agent 数量"""
        return sum(1 for e in cls._configs.values() if e._agent_class is not None)

    @classmethod
    def resolve_model_alias(cls, alias: str) -> str:
        """解析模型别名到实际模型名"""
        return cls._model_aliases.get(alias, alias)

    # ------------------------------------------------------------------
    # 实例创建
    # ------------------------------------------------------------------

    @classmethod
    def create(cls, agent_name: str, **kwargs) -> Any:
        """创建 Agent 实例

        Args:
            agent_name: Agent 名称
            **kwargs: 传递给 Agent 构造函数的额外参数

        Returns:
            Agent 实例

        Raises:
            ValueError: Agent 不存在或未加载
        """
        entry = cls._configs.get(agent_name)
        if entry is None:
            raise ValueError(
                f"Agent '{agent_name}' 未在 agent_config.yaml 中注册。"
                f"可用 Agent: {list(cls._configs.keys())}"
            )

        if entry._agent_class is None:
            raise ValueError(
                f"Agent '{agent_name}' 类未加载（导入失败）。"
                f"class_path={entry.class_path}"
            )

        try:
            return entry._agent_class(**kwargs)
        except Exception as e:
            raise ValueError(
                f"创建 Agent '{agent_name}' 失败: {e}"
            ) from e

    # ------------------------------------------------------------------
    # 手动注册（动态扩展）
    # ------------------------------------------------------------------

    @classmethod
    def register(
        cls,
        agent_name: str,
        agent_class: Type,
        display_name: str = "",
        description: str = "",
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        system_prompt: Optional[str] = None,
    ) -> None:
        """手动注册自定义 Agent（运行时动态扩展）

        Args:
            agent_name: Agent 名称
            agent_class: Agent 类
            display_name: 显示名称
            description: 描述
            model: 依赖模型
            temperature: 温度参数
            system_prompt: 系统提示词
        """
        with cls._lock:
            entry = AgentConfigEntry(
                agent_name=agent_name,
                class_path=f"{agent_class.__module__}.{agent_class.__name__}",
                display_name=display_name or getattr(agent_class, "display_name", agent_name),
                description=description or getattr(agent_class, "description", ""),
                model=model,
                temperature=temperature,
                system_prompt=system_prompt,
            )
            entry._agent_class = agent_class
            cls._configs[agent_name] = entry

            log.info(
                f"AgentRegistry | 手动注册 | "
                f"name={agent_name} | class={agent_class.__name__}"
            )

    # ------------------------------------------------------------------
    # 重置（测试用）
    # ------------------------------------------------------------------

    @classmethod
    def reset(cls) -> None:
        """重置注册状态（测试用）"""
        with cls._lock:
            cls._configs = {}
            cls._model_aliases = {}
            cls._registered = False


# ------------------------------------------------------------------
# 便捷函数
# ------------------------------------------------------------------

def auto_register_agents() -> Dict[str, bool]:
    """便捷函数：自动注册所有 Agent"""
    return AgentRegistry.auto_register()
