"""
AgentSelector - 根据输入类型路由到合适的ParserAgent

支持的输入类型映射：
  pdf     → DocumentParserAgent
  doc     → DocumentParserAgent
  docx    → DocumentParserAgent
  word    → DocumentParserAgent
  url     → DocumentParserAgent (URL抓取后按文档处理)
  text    → DocumentParserAgent (直接文本处理)
  image   → ImageParserAgent (VL视觉模型识别页面截图)
  png     → ImageParserAgent
  jpg     → ImageParserAgent
  jpeg    → ImageParserAgent
  webp    → ImageParserAgent
"""
from typing import Any, Dict, Optional
from app.core.logger import log


class AgentSelector:
    """根据输入类型选择合适的ParserAgent"""

    # 输入类型 → Agent映射
    TYPE_AGENT_MAP = {
        # 文档类
        "pdf": "document_parser",
        "doc": "document_parser",
        "docx": "document_parser",
        "word": "document_parser",
        "url": "document_parser",
        "text": "document_parser",
        # 图片类
        "image": "image_parser",
        "png": "image_parser",
        "jpg": "image_parser",
        "jpeg": "image_parser",
        "webp": "image_parser",
    }

    def __init__(self):
        self._agents: Dict[str, Any] = {}

    def _get_agent(self, agent_type: str):
        """懒加载获取Agent实例"""
        if agent_type in self._agents:
            return self._agents[agent_type]

        agent_map = {
            "document_parser": "app.agent.case.document_parser:DocumentParserAgent",
            "image_parser": "app.agent.case.image_parser:ImageParserAgent",
        }

        module_path = agent_map.get(agent_type)
        if module_path:
            mod_name, cls_name = module_path.rsplit(":", 1)
            import importlib
            mod = importlib.import_module(mod_name)
            agent = getattr(mod, cls_name)()
        else:
            from app.agent.case.document_parser import DocumentParserAgent
            agent = DocumentParserAgent()

        self._agents[agent_type] = agent
        return agent

    def select(self, source_type: str) -> Any:
        """
        根据输入类型选择Agent

        Args:
            source_type: 输入类型 (pdf/doc/url/text/image/png/jpg)

        Returns:
            对应的ParserAgent实例
        """
        source_type = source_type.lower().strip()
        agent_type = self.TYPE_AGENT_MAP.get(source_type, "document_parser")
        agent = self._get_agent(agent_type)
        log.info(f"AgentSelector | source_type={source_type} → agent={agent_type}")
        return agent

    def parse(self, source_type: str, task_id: int, **kwargs) -> Dict[str, Any]:
        """
        解析输入内容

        Args:
            source_type: 输入类型
            task_id: 用例任务ID
            **kwargs: 额外参数 (file_path, url, raw_text 等)

        Returns:
            解析结果 dict，包含:
            - requirement_context: str (需求上下文)
            - structured_data: dict (结构化数据)
            - source_type: str
        """
        agent = self.select(source_type)
        result = agent.parse(task_id=task_id, source_type=source_type, **kwargs)
        log.info(f"AgentSelector | 解析完成 | source_type={source_type}, task_id={task_id}")
        return result
