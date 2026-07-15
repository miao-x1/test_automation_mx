"""
RequirementAgent - 需求解析Agent

职责：解析用户自然语言需求，拆解为测试步骤

输入："测试登录功能"
输出：
{
    "intent": "login_test",
    "steps": [
        "打开登录页面",
        "输入用户名",
        "输入密码",
        "点击登录按钮",
        "验证登录成功"
    ]
}

使用LLM（通义千问）进行需求理解和步骤拆解
"""
import json
import time as _time
from typing import Dict, Any, List, Optional
from app.core.config import settings
from app.core.logger import log
from app.core.llm import call_llm
from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability


class RequirementAgent(NewBaseAgent):
    """需求解析Agent"""

    agent_name = "requirement_agent"
    display_name = "需求解析Agent"
    description = "解析用户自然语言需求，拆解为测试步骤"
    capabilities = [AgentCapability.REQUIREMENT_PARSE]

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)
        self.agent_type = "requirement"
        self.model = None
        self.system_prompt = None

    def _build_prompt(self, requirement: str) -> str:
        """构建需求解析的提示词"""
        return f"""你是一个专业的测试需求分析师。请分析以下测试需求，拆解为结构化的测试信息。

需求：{requirement}

请按以下JSON格式输出（不要输出其他内容）：
{{
    "intent": "意图标识（英文下划线格式，如login_test、search_test、cart_test）",
    "summary": "需求概述（一句话）",
    "target_url": "目标网站URL（如果能推断出具体网站则给出完整URL，如 https://www.jd.com；无法推断则留空字符串）",
    "steps": [
        "步骤1",
        "步骤2",
        ...
    ],
    "business_flow": {{
        "name": "业务流程名称",
        "description": "流程描述",
        "stages": [
            {{"name": "阶段名", "actions": ["动作1", "动作2"]}}
        ]
    }},
    "test_points": [
        {{
            "point": "测试点描述",
            "type": "functional | boundary | exception | security | performance",
            "priority": "high | medium | low",
            "description": "为什么需要测试这个点"
        }}
    ],
    "risk_points": [
        {{
            "risk": "风险描述",
            "level": "high | medium | low",
            "impact": "影响范围",
            "mitigation": "缓解措施"
        }}
    ]
}}

要求：
1. intent使用英文下划线格式
2. steps是具体的操作步骤，每个步骤是一个简短的动宾短语，3-10个
3. 步骤应该覆盖完整的测试流程（打开页面→操作→验证）
4. target_url：如果能从需求中推断出目标网站，给出完整URL；否则留空
5. business_flow：将需求拆解为业务流程，包含阶段和每个阶段的操作
6. test_points：识别关键测试点，覆盖功能/边界/异常/安全/性能，至少3个
7. risk_points：识别潜在风险，评估影响和缓解措施，至少2个
8. 只输出JSON，不要输出其他内容"""

    def _call_llm(self, prompt: str) -> str:
        """调用LLM API"""
        # [DEBUG] 调用LLM前
        _start = _time.time()
        log.info(f"[DEBUG] 开始：RequirementAgent._call_llm | 输入：prompt_length={len(prompt)}")

        content = call_llm(
            "你是一个专业的测试需求分析师，擅长将自然语言需求拆解为具体的测试步骤。",
            prompt,
            temperature=0.3,
        )

        # [DEBUG] LLM返回后
        _elapsed = _time.time() - _start
        log.info(f"[DEBUG] 结束：RequirementAgent._call_llm | 输出：content_length={len(content)} | 耗时：{_elapsed:.2f}s")

        return content

    def _parse_result(self, raw: str) -> Dict[str, Any]:
        """解析LLM返回的JSON"""
        try:
            data = json.loads(raw)
            # 验证必要字段
            intent = data.get("intent", "unknown_test")
            steps = data.get("steps", [])
            summary = data.get("summary", "")
            target_url = data.get("target_url", "")

            if not steps:
                steps = [summary] if summary else ["执行测试"]

            # 新增结构化字段（向后兼容：LLM未返回时给默认值）
            business_flow = data.get("business_flow", {
                "name": summary or intent,
                "description": summary,
                "stages": [{"name": "主流程", "actions": steps}],
            })
            test_points = data.get("test_points", [])
            risk_points = data.get("risk_points", [])

            return {
                "intent": intent,
                "summary": summary,
                "target_url": target_url,
                "steps": steps,
                "business_flow": business_flow,
                "test_points": test_points,
                "risk_points": risk_points,
            }
        except json.JSONDecodeError:
            log.warning(f"需求解析JSON解析失败，原始内容: {raw[:200]}")
            return {
                "intent": "unknown_test",
                "summary": raw[:100],
                "target_url": "",
                "steps": [raw[:100]],
                "business_flow": {
                    "name": "未知流程",
                    "description": raw[:100],
                    "stages": [{"name": "主流程", "actions": [raw[:100]]}],
                },
                "test_points": [],
                "risk_points": [],
            }

    def _extract_url_from_requirement(self, requirement: str) -> str:
        """从需求文本中提取URL"""
        import re
        # 匹配常见URL模式
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        urls = re.findall(url_pattern, requirement)
        if urls:
            return urls[0]

        # 匹配常见网站名称
        site_map = {
            '京东': 'https://www.jd.com',
            '淘宝': 'https://www.taobao.com',
            '天猫': 'https://www.tmall.com',
            '百度': 'https://www.baidu.com',
            '微信': 'https://weixin.qq.com',
            '微博': 'https://weibo.com',
            '抖音': 'https://www.douyin.com',
            'bilibili': 'https://www.bilibili.com',
            'B站': 'https://www.bilibili.com',
            '知乎': 'https://www.zhihu.com',
            'github': 'https://github.com',
            'google': 'https://www.google.com',
        }
        for name, url in site_map.items():
            if name.lower() in requirement.lower():
                return url

        return ""

    def analyze(self, requirement: str) -> Dict[str, Any]:
        """
        解析用户需求

        Args:
            requirement: 自然语言需求，如"测试登录功能"

        Returns:
            解析结果，包含intent和steps
        """
        # [DEBUG] 进入函数
        _analyze_start = _time.time()
        log.info(f"[DEBUG] 开始：RequirementAgent.analyze | 输入：requirement={requirement[:80]}")

        prompt = self._build_prompt(requirement)
        raw = self._call_llm(prompt)
        result = self._parse_result(raw)

        # 如果LLM没有返回target_url，尝试从需求文本中提取
        if not result.get("target_url"):
            result["target_url"] = self._extract_url_from_requirement(requirement)

        # [DEBUG] 结束
        _analyze_elapsed = _time.time() - _analyze_start
        log.info(f"[DEBUG] 结束：RequirementAgent.analyze | 输出：intent={result['intent']}, steps={len(result['steps'])}, target_url={result.get('target_url', '')} | 耗时：{_analyze_elapsed:.2f}s")

        log.info(f"RequirementAgent | 解析完成 | intent={result['intent']}, steps={len(result['steps'])}, target_url={result.get('target_url', '')}")
        return result

    def execute(self, **kwargs) -> Dict[str, Any]:
        """统一执行入口（BaseAgent接口，兼容管道payload键名）"""
        requirement = kwargs.get("requirement", "")
        if not requirement:
            # 兼容管道嵌套格式
            req_analysis = kwargs.get("requirement_analysis")
            if isinstance(req_analysis, dict):
                requirement = req_analysis.get("summary", "") or req_analysis.get("intent", "")
        result = self.analyze(requirement)
        self.emit("parsed", result)
        return result

    def emit(self, event: str, data: Any = None) -> None:
        """发布消息到MessageBus"""
        from app.agent.core.message_bus import MessageBus
        bus = MessageBus()
        bus.publish(f"{self.agent_name}.{event}", self.agent_name, data)

    async def execute_async(self, payload: Dict[str, Any], ctx=None) -> Dict[str, Any]:
        """GraphFlow兼容入口 — 返回完整业务数据供下游节点使用"""
        requirement = payload.get("requirement", "")
        result = self.analyze(requirement)
        # 返回完整业务数据（GraphFlow下游依赖这些字段）
        return {
            "status": "success",
            "step": "requirement",
            "task_id": payload.get("task_id", ""),
            "intent": result.get("intent", ""),
            "summary": result.get("summary", ""),
            "target_url": result.get("target_url", ""),
            "steps": result.get("steps", []),
            "business_flow": result.get("business_flow", {}),
            "test_points": result.get("test_points", []),
            "risk_points": result.get("risk_points", []),
            "requirement_items": [{
                "intent": result.get("intent", ""),
                "description": result.get("summary", ""),
                "steps": result.get("steps", []),
            }],
        }
