"""
测试点分析 Prompt

职责：根据需求解析结果，分析并生成全面的测试点列表。

输入：RequirementAnalysisResult（业务模块、功能点、业务流程、测试范围）
输出：JSON 测试点列表，覆盖：
- 正常流程
- 异常流程
- 边界条件
- 权限验证
- 数据校验
"""
from typing import List, Dict, Any, Optional


class TestPointPrompt:
    """测试点分析提示词模板"""

    SYSTEM_PROMPT = """你是一位真正懂软件测试的专业测试分析师。

你的职责不是把能想到的都写成测试点，而是：
1. 先识别用户伤害和产品风险
2. 再选择测试技术（等价类、边界值、状态迁移、决策表、场景法、错误推测、安全、一致性）
3. 再按 P0/P1/P2/P3 取舍
4. 主动覆盖正常、异常、边界、权限、会话/数据，但低价值项标P3或明确不测

测试点类型：
- functional / error / boundary / permission / data_validation

优先级：
- P0: 资金、登录鉴权、数据损坏、发布阻断
- P1: 主流程重要分支
- P2: 一般功能
- P3: 低频或低伤害

要求：
- 输出合法JSON数组
- 每个测试点有name、type、priority、scenario、technique
- 不要无脑生成十几条重复特殊字符用例
- 异常和边界至少各1个，但必须值得测"""

    @staticmethod
    def build(
        business_module: str,
        function_points: List[Dict[str, Any]],
        business_flow: List[Dict[str, Any]],
        test_scope: Dict[str, Any],
        expert_context: Optional[str] = None,
    ) -> str:
        """
        构建测试点分析的完整提示词

        Args:
            business_module: 业务模块名称
            function_points: 功能点列表
            business_flow: 业务流程列表
            test_scope: 测试范围

        Returns:
            完整的用户提示词
        """
        sections = []

        sections.append(f"## 业务模块\n{business_module}")

        # 功能点
        fp_lines = []
        for fp in function_points:
            name = fp.get("name", "")
            desc = fp.get("description", "")
            actions = fp.get("key_actions", [])
            fp_lines.append(f"- {name}: {desc}")
            if actions:
                fp_lines.append(f"  关键操作: {', '.join(actions)}")
        sections.append("## 功能点\n" + "\n".join(fp_lines))

        # 业务流程
        flow_lines = []
        for flow in business_flow:
            step = flow.get("step", "")
            action = flow.get("action", "")
            target = flow.get("target", "")
            expected = flow.get("expected", "")
            flow_lines.append(f"{step}. {action} → {target} (预期: {expected})")
        sections.append("## 业务流程\n" + "\n".join(flow_lines))

        # 测试范围
        scope_lines = []
        included = test_scope.get("included", [])
        excluded = test_scope.get("excluded", [])
        priority = test_scope.get("priority_modules", [])
        if included:
            scope_lines.append(f"包含: {', '.join(included)}")
        if excluded:
            scope_lines.append(f"不包含: {', '.join(excluded)}")
        if priority:
            scope_lines.append(f"优先: {', '.join(priority)}")
        sections.append("## 测试范围\n" + "\n".join(scope_lines))

        if expert_context:
            sections.append(f"## 测试专家知识（按风险选题，不要堆用例）\n{expert_context}")

        sections.append("""## 输出格式
请按以下JSON格式输出测试点列表（不要输出其他内容）：
```json
[
    {
        "name": "测试点名称（如：账号密码登录）",
        "type": "测试类型: functional/error/boundary/permission/data_validation",
        "priority": "优先级: P0/P1/P2/P3",
        "scenario": "测试场景描述",
        "description": "详细说明测试什么",
        "expected_behavior": "期望的系统行为",
        "technique": "使用的测试技术，如等价类/边界值/状态迁移/安全"
    }
]
```

要求：
1. 至少包含5个测试点
2. 每种测试类型至少1个测试点
3. P0级测试点至少1个
4. 测试点名称简洁明确
5. 只输出JSON数组，不要输出其他文字""")

        return "\n\n".join(sections)
