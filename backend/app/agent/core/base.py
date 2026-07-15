"""
Agent基类 - 统一架构

所有Agent继承BaseAgent，通过MessageBus通信，不直接互相调用。

支持：
- agent_name: Agent唯一标识
- model: 使用的LLM模型
- system_prompt: 系统提示词
- bus: MessageBus实例，用于发布/订阅消息
- emit(): 发布消息到MessageBus
- on_message(): 订阅消息

兼容旧架构：
- BaseAgent(ABC) 保留旧接口
- 新增统一基类方法
"""
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional
from app.core.logger import log
from app.agent.core.message_bus import MessageBus, Message


class BaseAgent(ABC):
    """
    Agent统一基类

    所有Agent通过MessageBus通信，不直接互相调用。

    子类必须实现：
    - agent_name: 类属性，Agent唯一标识
    - execute(): 核心执行方法
    """

    # 子类必须定义
    agent_name: str = ""
    model: Optional[str] = None
    system_prompt: Optional[str] = None

    def __init__(self):
        self._bus: Optional[MessageBus] = None
        self._agent_type = getattr(self, 'agent_name', '') or self.__class__.__name__.lower()

    @property
    def bus(self) -> MessageBus:
        """获取MessageBus实例（懒加载）"""
        if self._bus is None:
            self._bus = MessageBus()
        return self._bus

    @bus.setter
    def bus(self, value: MessageBus):
        self._bus = value

    def emit(self, event: str, data: Any = None) -> None:
        """
        发布消息到MessageBus

        Args:
            event: 事件名称，格式 {agent_name}.{event}
            data: 消息数据
        """
        topic = f"{self.agent_name}.{event}"
        self.bus.publish(topic, self.agent_name, data)

    def on_message(self, topic: str, handler: Callable[[Message], None]) -> None:
        """
        订阅消息

        Args:
            topic: 消息主题
            handler: 处理函数
        """
        self.bus.subscribe(topic, handler)

    def off_message(self, topic: str, handler: Callable[[Message], None]) -> None:
        """
        取消订阅

        Args:
            topic: 消息主题
            handler: 处理函数
        """
        self.bus.unsubscribe(topic, handler)

    @abstractmethod
    def execute(self, **kwargs) -> Any:
        """
        核心执行方法（子类实现）

        Returns:
            执行结果
        """
        pass

    def info(self) -> Dict[str, Any]:
        """获取Agent信息"""
        return {
            "agent_name": self.agent_name,
            "agent_type": self._agent_type,
            "model": self.model,
            "class": self.__class__.__name__,
        }


# ===== 兼容旧基类 =====

class BaseVisionAgent(ABC):
    """Vision分析Agent基类（兼容旧接口）"""

    def __init__(self, agent_type: str):
        self.agent_type = agent_type
        self.agent_name = agent_type

    @abstractmethod
    async def analyze_image(
        self,
        task_id: int,
        image_path: str
    ):
        """分析图片（Vision模式）"""
        pass


class BaseCrawlAgent(ABC):
    """页面抓取Agent基类（兼容旧接口）"""

    def __init__(self, agent_type: str):
        self.agent_type = agent_type
        self.agent_name = agent_type

    @abstractmethod
    async def crawl_page(
        self,
        task_id: int,
        url: str
    ):
        """抓取页面元素"""
        pass


class BaseMergeAgent(ABC):
    """元素融合Agent基类（兼容旧接口）"""

    def __init__(self, agent_type: str):
        self.agent_type = agent_type
        self.agent_name = agent_type

    @abstractmethod
    async def merge_elements(
        self,
        task_id: int,
        vision_elements: List[Dict[str, Any]],
        dom_elements: List[Dict[str, Any]]
    ):
        """融合Vision和DOM元素"""
        pass


class BaseCaseAgent(ABC):
    """测试用例生成Agent基类（兼容旧接口）"""

    def __init__(self, agent_type: str):
        self.agent_type = agent_type
        self.agent_name = agent_type

    @abstractmethod
    async def generate_cases(
        self,
        task_id: int,
        elements: List[Dict[str, Any]]
    ):
        """根据统一元素生成测试用例"""
        pass


class BaseScriptAgent(ABC):
    """脚本生成Agent基类（兼容旧接口）"""

    def __init__(self, agent_type: str):
        self.agent_type = agent_type
        self.agent_name = agent_type

    @abstractmethod
    async def generate_script(
        self,
        task_id: int,
        elements: List[Dict[str, Any]],
        cases: List[Dict[str, Any]],
        page_url: str = None
    ):
        """根据测试用例生成Playwright脚本"""
        pass
