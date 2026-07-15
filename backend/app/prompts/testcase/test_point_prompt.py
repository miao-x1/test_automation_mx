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

    SYSTEM_PROMPT = """你是一位资深测试专家，擅长从需求中分析全面的测试点。

你的职责：
1. 根据需求分析结果，识别所有需要测试的场景
2. 按测试类型分类（功能/异常/边界/权限/数据校验）
3. 为每个测试点分配优先级
4. 确保测试覆盖完整，不遗漏关键场景

测试点类型说明：
- functional: 正常功能流程测试
- error: 异常流程、错误处理测试
- boundary: 边界值、极限值测试
- permission: 权限验证、角色控制测试
- data_validation: 数据校验、格式验证测试

优先级说明：
- P0: 核心功能，阻塞性测试，必须通过
- P1: 重要功能，影响主流程
- P2: 一般功能，非阻塞性
- P3: 边缘场景，低频使用

要求：
- 输出必须是合法JSON数组
- 每个测试点必须有name、type、priority、scenario
- 测试点要具体、可执行、可验证
- 正常流程测试点优先级不低于P1
- 异常和边界测试点至少各1个
- 不要编造需求中不存在的测试场景"""

    @staticmethod
    def build(
        business_module: str,
        function_points: List[Dict[str, Any]],
        business_flow: List[Dict[str, Any]],
        test_scope: Dict[str, Any],
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
        "expected_behavior": "期望的系统行为"
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
