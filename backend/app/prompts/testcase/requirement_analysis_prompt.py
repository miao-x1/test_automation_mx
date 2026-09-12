"""
需求解析 Prompt

职责：理解用户输入的测试需求，提取业务模块、功能点、业务流程、测试范围。

输入：需求文本 + 可选的文档/图片描述
输出：JSON {
    business_module,      # 业务模块
    function_points,       # 功能点列表
    business_flow,         # 业务流程
    test_scope            # 测试范围
}
"""
from typing import List, Dict, Any, Optional


class RequirementAnalysisPrompt:
    """需求解析提示词模板"""

    SYSTEM_PROMPT = """你是一位真正懂软件测试的专业测试架构师，不是问答机器人。

你的职责：
1. 理解用户输入的测试需求（自然语言/文档/图片描述）
2. 识别业务模块、功能点、主流程和风险
3. 明确测试范围：包含、不包含、以及为什么不测
4. 运用 ISTQB 测试分析思维：先风险和范围，再功能拆解

要求：
- 即使用户只说“测一下登录”，也要从认证、会话、权限、异常、边界去理解系统
- 不要把测试范围写成“全部功能”
- 功能点要具体、可测试
- 输出必须是合法JSON，不要输出任何其他内容
- 不要编造需求中完全不存在的业务，但必须补上测试人员应主动识别的风险边界"""

    @staticmethod
    def build(
        requirement_text: str,
        document_context: Optional[str] = None,
        image_description: Optional[str] = None,
        expert_context: Optional[str] = None,
    ) -> str:
        """
        构建需求解析的完整提示词

        Args:
            requirement_text: 用户输入的需求文本
            document_context: 文档解析结果（PDF/Word/Swagger等）
            image_description: 图片描述信息

        Returns:
            完整的用户提示词
        """
        sections = []

        sections.append(f"## 测试需求\n{requirement_text}")

        if document_context:
            sections.append(f"## 文档信息\n{document_context}")

        if image_description:
            sections.append(f"## 截图描述\n{image_description}")

        if expert_context:
            sections.append(f"## 测试专家知识（必须用于分析，不要只复述）\n{expert_context}")

        sections.append("""## 输出格式
请按以下JSON格式输出（不要输出其他内容）：
```json
{
    "business_module": "业务模块名称（如：用户中心、订单管理）",
    "function_points": [
        {
            "name": "功能点名称",
            "description": "功能描述",
            "key_actions": ["关键操作1", "关键操作2"]
        }
    ],
    "business_flow": [
        {
            "step": 1,
            "action": "操作描述",
            "target": "目标页面/接口",
            "expected": "预期结果"
        }
    ],
    "test_scope": {
        "included": ["包含的测试范围"],
        "excluded": ["不包含的范围"],
        "priority_modules": ["优先测试的模块"]
    }
}
```

要求：
1. function_points 至少2个，每个必须有name和description
2. business_flow 按操作顺序排列，step从1开始
3. test_scope 必须明确included和excluded
4. 只输出JSON，不要输出任何其他文字""")

        return "\n\n".join(sections)
