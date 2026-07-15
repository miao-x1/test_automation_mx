"""
用例审核 Prompt

职责：审核测试用例质量，检查步骤完整性、预期明确性、异常覆盖度。

输入：测试用例（case_name, precondition, steps, expected_result）
输出：JSON {
    score,          # 质量评分（0-100）
    suggestions,    # 改进建议列表
    issues          # 问题列表
}

检查项：
- 步骤是否完整
- 预期是否明确
- 是否覆盖异常
- 前置条件是否充分
- 优先级是否合理
"""
from typing import List, Dict, Any, Optional


class ReviewPrompt:
    """用例审核提示词模板"""

    SYSTEM_PROMPT = """你是一位资深QA审核专家，负责审核测试用例的质量。

你的职责：
1. 检查测试用例的步骤是否完整、可执行
2. 检查预期结果是否明确、可验证
3. 检查前置条件是否充分
4. 检查是否覆盖异常场景
5. 评估优先级是否合理
6. 给出质量评分和改进建议

评分标准：
- 90-100: 优秀，步骤完整、预期明确、覆盖全面
- 70-89: 良好，基本完整但有改进空间
- 50-69: 合格，存在明显问题需要修改
- 0-49: 不合格，需要重新设计

审核维度：
1. 步骤完整性：步骤是否覆盖完整测试流程
2. 预期明确性：每个步骤的预期结果是否可验证
3. 异常覆盖：是否考虑了异常输入和错误处理
4. 前置条件：数据准备和环境要求是否充分
5. 可执行性：步骤是否具体、可操作
6. 优先级合理性：优先级是否与测试点一致

要求：
- 输出必须是合法JSON
- score是0-100的整数
- suggestions至少1条（如果score<100）
- 只输出JSON，不要输出其他内容"""

    @staticmethod
    def build(
        case_name: str,
        precondition: str,
        steps: List[Dict[str, Any]],
        expected_result: str,
        priority: str,
        case_type: str,
        test_point_info: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        构建用例审核的完整提示词

        Args:
            case_name: 用例名称
            precondition: 前置条件
            steps: 测试步骤列表
            expected_result: 预期结果
            priority: 优先级
            case_type: 用例类型
            test_point_info: 关联的测试点信息

        Returns:
            完整的用户提示词
        """
        sections = []

        # 用例基本信息
        sections.append(f"""## 待审核用例
- 用例名称: {case_name}
- 优先级: {priority}
- 类型: {case_type}
- 前置条件: {precondition}
- 预期结果: {expected_result}""")

        # 测试步骤
        step_lines = []
        for i, step in enumerate(steps, 1):
            no = step.get("step_no", i)
            action = step.get("action", "")
            desc = step.get("description", "")
            target = step.get("target", "")
            value = step.get("value", "")
            expected = step.get("expected", "")
            step_lines.append(
                f"步骤{no}: {action} - {desc} | 目标: {target} | 值: {value} | 预期: {expected}"
            )
        sections.append("## 测试步骤\n" + "\n".join(step_lines))

        # 关联测试点信息
        if test_point_info:
            sections.append(f"""## 关联测试点
- 名称: {test_point_info.get('name', '')}
- 场景: {test_point_info.get('scenario', '')}
- 描述: {test_point_info.get('description', '')}""")

        sections.append("""## 输出格式
请按以下JSON格式输出审核结果（不要输出其他内容）：
```json
{
    "score": 85,
    "review_result": "pass",
    "suggestions": [
        "改进建议1（具体、可操作）",
        "改进建议2"
    ],
    "issues": [
        {
            "severity": "high/medium/low",
            "category": "step_completeness/expected_clarity/exception_coverage/precondition/priority",
            "description": "问题描述",
            "suggestion": "修改建议"
        }
    ]
}
```

review_result 取值：
- pass: 通过（score >= 80）
- need_revision: 需修改（50 <= score < 80）
- reject: 拒绝（score < 50）

要求：
1. score是0-100的整数
2. 如果score < 100，suggestions至少1条
3. issues按severity从高到低排列
4. 只输出JSON，不要输出其他文字""")

        return "\n\n".join(sections)
