"""
CaseResult - 统一测试用例输出模型

解决三代CaseAgent输出格式不统一的问题：
  Gen1 generate():      {case_name, description, preconditions, steps, assertions}
  Gen1 generate_cases(): {step, progress, message, data: {cases: [...]}}
  Gen3 execute():        {cases: [{title, steps, expected_result, priority}], ...}

统一为：
  {
      cases: [UnifiedCase],
      case_count: int,
      source: str,          # "gen1" / "gen3" / "pipeline"
      coverage_notes: str,  # 覆盖说明（Gen3特有，Gen1留空）
      degradation_info: Optional[Dict],  # 降级信息
  }

每个 UnifiedCase:
  {
      case_name: str,           # 统一名称（Gen1: case_name, Gen3: title）
      description: str,         # 用例描述
      preconditions: List[str], # 前置条件
      steps: List[UnifiedStep], # 统一步骤格式
      assertions: List[Dict],   # 断言列表
      priority: str,            # 优先级 (high/medium/low)
      expected_result: str,     # 预期结果（Gen3特有，Gen1从assertions提取）
  }

每个 UnifiedStep:
  {
      action: str,          # 操作类型: goto/fill/click/verify_visible/verify_text/select_option/wait
      locator: str,         # 元素定位器
      value: str,           # 操作值
      description: str,     # 步骤描述
  }
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class UnifiedStep(BaseModel):
    """统一测试步骤"""
    action: str = Field(description="操作类型: goto/fill/click/verify_visible/verify_text/select_option/wait")
    locator: str = Field(default="", description="元素定位器")
    value: str = Field(default="", description="操作值")
    description: str = Field(default="", description="步骤描述")


class UnifiedCase(BaseModel):
    """统一测试用例"""
    case_name: str = Field(description="用例名称")
    description: str = Field(default="", description="用例描述")
    preconditions: List[str] = Field(default_factory=list, description="前置条件")
    steps: List[UnifiedStep] = Field(default_factory=list, description="测试步骤")
    assertions: List[Dict[str, Any]] = Field(default_factory=list, description="断言列表")
    priority: str = Field(default="medium", description="优先级: high/medium/low")
    expected_result: str = Field(default="", description="预期结果")


class CaseResult(BaseModel):
    """统一用例生成结果"""
    cases: List[UnifiedCase] = Field(default_factory=list, description="用例列表")
    case_count: int = Field(default=0, description="用例数量")
    source: str = Field(default="", description="来源: gen1/gen3/pipeline")
    coverage_notes: str = Field(default="", description="覆盖说明")
    degradation_info: Optional[Dict[str, Any]] = Field(default=None, description="降级信息")

    @classmethod
    def from_gen1_single(cls, case_data: Dict[str, Any]) -> "CaseResult":
        """
        从Gen1 generate()的单用例格式转换

        输入: {case_name, description, preconditions, steps, assertions}
        输出: CaseResult (cases数组包含1个用例)
        """
        case = UnifiedCase(
            case_name=case_data.get("case_name", "未命名用例"),
            description=case_data.get("description", ""),
            preconditions=case_data.get("preconditions", []),
            steps=[
                UnifiedStep(
                    action=s.get("action", ""),
                    locator=s.get("locator", ""),
                    value=s.get("value", ""),
                    description=s.get("description") or s.get("step", ""),
                )
                for s in case_data.get("steps", [])
                if isinstance(s, dict)
            ],
            assertions=case_data.get("assertions", []),
            priority=case_data.get("priority", "medium"),
            expected_result="",
        )
        return cls(cases=[case], case_count=1, source="gen1")

    @classmethod
    def from_gen1_multi(cls, cases_data: Dict[str, Any]) -> "CaseResult":
        """
        从Gen1 generate_cases()的多用例格式转换

        输入: {data: {cases: [...]}} 或 {cases: [...]}
        """
        raw_cases = []
        if "data" in cases_data and isinstance(cases_data["data"], dict):
            raw_cases = cases_data["data"].get("cases", [])
        elif "cases" in cases_data:
            raw_cases = cases_data["cases"]
        elif isinstance(cases_data, list):
            raw_cases = cases_data

        cases = []
        for raw in raw_cases:
            if not isinstance(raw, dict):
                continue
            case = UnifiedCase(
                case_name=raw.get("case_name", "未命名用例"),
                description=raw.get("description", ""),
                preconditions=raw.get("preconditions", []),
                steps=[
                    UnifiedStep(
                        action=s.get("action", ""),
                        locator=s.get("locator", ""),
                        value=s.get("value", ""),
                        description=s.get("description") or s.get("step", ""),
                    )
                    for s in raw.get("steps", [])
                    if isinstance(s, dict)
                ],
                assertions=raw.get("assertions", []),
                priority=raw.get("priority", "medium"),
                expected_result=raw.get("expected_result", ""),
            )
            cases.append(case)

        return cls(cases=cases, case_count=len(cases), source="gen1")

    @classmethod
    def from_gen3(cls, gen3_output: Dict[str, Any]) -> "CaseResult":
        """
        从Gen3 CaseAgent输出转换

        输入: {cases: [{title, steps, expected_result, priority, requirement_item_id}], ...}
        """
        raw_cases = gen3_output.get("cases", [])
        cases = []

        for raw in raw_cases:
            if not isinstance(raw, dict):
                continue
            # Gen3 的 steps 可能是简单字符串列表或字典列表
            unified_steps = []
            for s in raw.get("steps", []):
                if isinstance(s, str):
                    unified_steps.append(UnifiedStep(action="", description=s))
                elif isinstance(s, dict):
                    unified_steps.append(UnifiedStep(
                        action=s.get("action", ""),
                        locator=s.get("locator", ""),
                        value=s.get("value", ""),
                        description=s.get("description") or s.get("step", ""),
                    ))

            case = UnifiedCase(
                case_name=raw.get("title") or raw.get("case_name", "未命名用例"),
                description=raw.get("description", ""),
                preconditions=raw.get("preconditions", []),
                steps=unified_steps,
                assertions=raw.get("assertions", []),
                priority=raw.get("priority", "medium"),
                expected_result=raw.get("expected_result", ""),
            )
            cases.append(case)

        return cls(
            cases=cases,
            case_count=len(cases),
            source="gen3",
            coverage_notes=gen3_output.get("coverage_notes", ""),
        )

    def to_gen1_single(self) -> Dict[str, Any]:
        """转换为Gen1单用例格式（向后兼容）"""
        if not self.cases:
            return {}
        case = self.cases[0]
        return {
            "case_name": case.case_name,
            "description": case.description,
            "preconditions": case.preconditions,
            "steps": [
                {
                    "step": s.description,
                    "action": s.action,
                    "locator": s.locator,
                    "value": s.value,
                    "description": s.description,
                }
                for s in case.steps
            ],
            "assertions": case.assertions,
            "priority": case.priority,
        }

    def to_gen3_format(self) -> Dict[str, Any]:
        """转换为Gen3格式（向后兼容）"""
        return {
            "cases": [
                {
                    "title": c.case_name,
                    "description": c.description,
                    "preconditions": c.preconditions,
                    "steps": [
                        {"action": s.action, "locator": s.locator, "value": s.value, "description": s.description}
                        for s in c.steps
                    ],
                    "assertions": c.assertions,
                    "priority": c.priority,
                    "expected_result": c.expected_result,
                }
                for c in self.cases
            ],
            "case_count": self.case_count,
            "coverage_notes": self.coverage_notes,
        }

    def to_script_input(self) -> List[Dict[str, Any]]:
        """
        转换为脚本生成器的输入格式

        返回用例列表，每个用例都是ScriptGenerator可消费的格式
        """
        return [
            {
                "case_name": c.case_name,
                "description": c.description,
                "preconditions": c.preconditions,
                "steps": [
                    {"action": s.action, "locator": s.locator, "value": s.value, "description": s.description}
                    for s in c.steps
                ],
                "assertions": c.assertions,
                "priority": c.priority,
                "expected_result": c.expected_result,
            }
            for c in self.cases
        ]
