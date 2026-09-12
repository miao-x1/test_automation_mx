"""
测试用例生成 Prompt

职责：根据测试点 + RAG上下文，生成结构化的标准测试用例。

输入：测试点 + RAG检索结果（历史用例、业务规则等）
输出：JSON {
    case_name,          # 用例名称
    precondition,       # 前置条件
    steps,              # 测试步骤
    expected_result,    # 预期结果
    priority,           # 优先级
    type               # 用例类型
}

设计原则：
- 不直接把全部知识库发送给LLM
- 只发送RAG检索后的TopK结果
- 生成的用例参考但不照搬历史用例
"""
from typing import List, Dict, Any, Optional


class TestCaseGeneratePrompt:
    """测试用例生成提示词模板"""

    SYSTEM_PROMPT = """你是一位真正懂软件测试的用例设计师。

你的职责：
1. 把测试点落成可执行、可独立运行的用例
2. 运用等价类、边界值、状态、权限、数据一致性等技术，而不是照抄用户原话
3. 参考历史用例和专家知识，但不照搬
4. 预期结果必须可验证

原则：
- 一条用例一个目的
- 前置条件含数据、账号、环境
- 步骤原子化
- 优先级跟风险走
- 不要把一个测试点拆成十几条无差异数据行，除非数据驱动确实必要"""

    @staticmethod
    def build(
        test_point: Dict[str, Any],
        rag_context: Optional[Dict[str, Any]] = None,
        expert_context: Optional[str] = None,
    ) -> str:
        """
        构建用例生成的完整提示词

        Args:
            test_point: 测试点信息（name, type, priority, scenario, description）
            rag_context: RAG检索结果（历史用例、业务规则等，已过滤TopK）

        Returns:
            完整的用户提示词
        """
        sections = []

        # 测试点信息
        sections.append(f"""## 测试点
- 名称: {test_point.get('name', '')}
- 类型: {test_point.get('type', '')}
- 优先级: {test_point.get('priority', '')}
- 场景: {test_point.get('scenario', '')}
- 描述: {test_point.get('description', '')}
- 期望行为: {test_point.get('expected_behavior', '')}""")

        # RAG上下文（已检索、过滤的TopK结果）
        if rag_context:
            rag_lines = []

            # 历史用例
            cases = rag_context.get("cases", [])
            if cases:
                rag_lines.append("### 历史相似用例（仅供参考，不要照搬）")
                for i, case in enumerate(cases[:5], 1):
                    name = case.get("case_name", case.get("title", ""))
                    desc = case.get("description", "")
                    steps = case.get("steps", [])
                    score = case.get("score", 0)
                    steps_str = ""
                    if isinstance(steps, list):
                        step_descs = []
                        for s in steps[:5]:
                            if isinstance(s, dict):
                                step_descs.append(s.get("step", s.get("action", s.get("description", ""))))
                            else:
                                step_descs.append(str(s))
                        steps_str = " → ".join(step_descs)
                    elif isinstance(steps, str):
                        steps_str = steps[:200]
                    rag_lines.append(f"{i}. {name} | 描述: {desc} | 步骤: {steps_str} | 相似度: {score}")

            # 业务规则/知识
            elements = rag_context.get("elements", [])
            if elements:
                rag_lines.append("\n### 相关页面元素")
                for i, elem in enumerate(elements[:10], 1):
                    name = elem.get("element_name", elem.get("name", ""))
                    etype = elem.get("element_type", elem.get("type", ""))
                    locator = elem.get("locator", "")
                    page = elem.get("page_name", elem.get("page_title", ""))
                    rag_lines.append(f"{i}. {name} | 类型: {etype} | 定位器: {locator} | 页面: {page}")

            # 脚本参考
            scripts = rag_context.get("scripts", [])
            if scripts:
                rag_lines.append("\n### 历史脚本参考")
                for i, script in enumerate(scripts[:3], 1):
                    name = script.get("script_name", "")
                    desc = script.get("description", "")
                    rag_lines.append(f"{i}. {name} | 描述: {desc}")

            if rag_lines:
                sections.append("## RAG检索结果\n" + "\n".join(rag_lines))
            else:
                sections.append("## RAG检索结果\n（无相关历史数据）")
        else:
            sections.append("## RAG检索结果\n（未启用RAG检索）")

        if expert_context:
            sections.append(f"## 测试专家知识\n{expert_context}")

        sections.append("""## 输出格式
请按以下JSON格式输出测试用例（不要输出其他内容）：
```json
{
    "case_name": "用例名称（简洁明确，体现测试目的）",
    "precondition": "前置条件（数据准备、环境要求、用户状态等）",
    "steps": [
        {
            "step_no": 1,
            "action": "操作类型（goto/fill/click/select/verify/wait/hover/scroll）",
            "description": "步骤描述（具体操作内容）",
            "target": "操作目标（页面/元素/接口）",
            "value": "输入值（如需要）",
            "expected": "该步骤的预期结果"
        }
    ],
    "expected_result": "最终预期结果（可验证的断言）",
    "priority": "优先级: P0/P1/P2/P3（与测试点一致）",
    "type": "用例类型: functional/error/boundary/permission/data_validation"
}
```

要求：
1. case_name 要体现测试场景，不超过50字
2. precondition 要包含所有必要的前置条件
3. steps 至少3步，每步都要有明确的action和expected
4. expected_result 要可验证、可量化
5. 参考RAG结果但不照搬历史用例
6. 只输出JSON，不要输出其他文字""")

        return "\n\n".join(sections)
