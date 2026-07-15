"""
RequirementPrompt - 需求解析Prompt模板

职责：将自然语言需求解析为结构化的测试意图和步骤
"""


class RequirementPrompt:
    """需求解析提示词模板"""

    SYSTEM_PROMPT = """你是一个专业的测试需求分析师，擅长将自然语言需求拆解为具体的测试步骤。你需要：
1. 准确理解用户的测试意图
2. 识别涉及的关键操作和页面元素
3. 提取可能的目标URL
4. 将需求拆解为可执行的测试步骤序列"""

    @staticmethod
    def build(requirement: str) -> str:
        """
        构建需求解析提示词

        Args:
            requirement: 用户输入的自然语言需求

        Returns:
            完整的提示词
        """
        return f"""请分析以下测试需求，将其拆解为具体的测试步骤。

需求：{requirement}

请按以下JSON格式输出（不要输出其他内容）：
{{
    "intent": "意图标识（英文下划线格式，如login_test、search_test、cart_test）",
    "summary": "需求概述（一句话）",
    "target_url": "目标网站URL（如果能推断出具体网站则给出完整URL，如 https://www.jd.com；无法推断则留空字符串）",
    "keywords": ["关键词1", "关键词2"],
    "steps": [
        "步骤1",
        "步骤2"
    ]
}}

要求：
1. intent使用英文下划线格式，简洁明了
2. keywords提取需求中的核心关键词，用于后续RAG检索
3. steps是具体的操作步骤，每个步骤是一个简短的动宾短语
4. 步骤应该覆盖完整的测试流程（打开页面→操作→验证）
5. 步骤数量控制在3-10个
6. target_url：如果能从需求中推断出目标网站，给出完整URL；否则留空
7. 只输出JSON，不要输出其他内容"""
