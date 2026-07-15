"""
ScriptValidator - 脚本校验器

校验脚本语法、结构、依赖是否正确
"""
import re
from typing import Dict, Any, List
from app.agent.script.script_parser import ParsedScript
from app.core.logger import log
from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability


class ValidationResult:
    """校验结果"""
    def __init__(self):
        self.valid: bool = True
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.score: float = 0.0  # 0-1 质量评分

    def to_dict(self) -> Dict:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "score": self.score,
        }


class ScriptValidator(NewBaseAgent):
    """脚本校验器"""

    agent_name = "script_validator"
    display_name = "Script Validator"
    description = "脚本校验器 - 校验脚本语法、结构、依赖是否正确"
    capabilities = [AgentCapability.SCRIPT_VALIDATE]

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)

    def validate(self, parsed: ParsedScript) -> ValidationResult:
        """校验解析后的脚本"""
        result = ValidationResult()

        if not parsed.valid:
            result.valid = False
            result.errors = parsed.errors[:]
            result.score = 0.0
            return result

        # 按类型校验
        if parsed.script_type == "playwright":
            self._validate_playwright(parsed, result)
        elif parsed.script_type == "midscene":
            self._validate_midscene(parsed, result)
        elif parsed.script_type == "yaml":
            self._validate_yaml(parsed, result)
        elif parsed.script_type == "json":
            self._validate_json(parsed, result)

        # 通用校验
        self._validate_common(parsed, result)

        # 计算质量评分
        result.score = self._calculate_score(parsed, result)

        return result

    def _validate_playwright(self, parsed: ParsedScript, result: ValidationResult):
        """校验Playwright脚本"""
        content = parsed.raw_content

        # 必须有playwright import
        if "playwright" not in content:
            result.warnings.append("未检测到playwright导入，请确保已安装playwright")

        # 必须有test函数
        if not parsed.functions:
            result.warnings.append("未检测到test_函数，请确保脚本包含测试函数")

        # 检查是否有page.goto
        if not parsed.target_url and "goto" not in content:
            result.warnings.append("未检测到page.goto，脚本可能缺少页面导航")

        # 检查是否有断言
        if not parsed.assertions:
            result.warnings.append("未检测到断言，建议添加验证步骤")

        # 检查语法错误（简单检查）
        try:
            compile(content, '<script>', 'exec')
        except SyntaxError as e:
            result.errors.append(f"Python语法错误: {e.msg} (行{e.lineno})")
            result.valid = False

    def _validate_midscene(self, parsed: ParsedScript, result: ValidationResult):
        """校验Midscene脚本"""
        content = parsed.raw_content

        if "midscene" not in content and "aiAction" not in content:
            result.warnings.append("未检测到Midscene相关代码")

        if not parsed.steps:
            result.warnings.append("未检测到aiAction步骤")

    def _validate_yaml(self, parsed: ParsedScript, result: ValidationResult):
        """校验YAML脚本"""
        if not parsed.name:
            result.warnings.append("YAML缺少name字段")
        if not parsed.target_url:
            result.warnings.append("YAML缺少target/url字段")
        if not parsed.steps:
            result.errors.append("YAML缺少steps字段")
            result.valid = False

        # 检查步骤是否有action
        for step in parsed.steps:
            if not step.get("action"):
                result.warnings.append(f"步骤{step.get('step', '?')}缺少action字段")

    def _validate_json(self, parsed: ParsedScript, result: ValidationResult):
        """校验JSON脚本"""
        if not parsed.steps:
            result.warnings.append("JSON缺少steps字段")

    def _validate_common(self, parsed: ParsedScript, result: ValidationResult):
        """通用校验"""
        content = parsed.raw_content

        # 检查空脚本
        if len(content.strip()) < 10:
            result.errors.append("脚本内容过短")
            result.valid = False

        # 检查硬编码凭据
        if re.search(r'(?:password|passwd|pwd|secret|token)\s*[=:]\s*["\'][^"\']{3,}["\']', content, re.IGNORECASE):
            result.warnings.append("脚本中可能包含硬编码的凭据，建议使用环境变量")

        # 检查过长的sleep
        if re.search(r'sleep\s*\(\s*(\d+)\s*\)', content):
            match = re.search(r'sleep\s*\(\s*(\d+)\s*\)', content)
            if match and int(match.group(1)) > 10:
                result.warnings.append(f"检测到过长的sleep({match.group(1)})，建议使用wait_for替代")

    def _calculate_score(self, parsed: ParsedScript, result: ValidationResult) -> float:
        """计算脚本质量评分"""
        if not result.valid:
            return 0.0

        score = 0.5  # 基础分

        # 有步骤 +0.1
        if parsed.steps:
            score += 0.1
        # 有断言 +0.1
        if parsed.assertions:
            score += 0.1
        # 有URL +0.1
        if parsed.target_url:
            score += 0.1
        # 有选择器 +0.05
        if parsed.selectors:
            score += 0.05
        # 无警告 +0.1
        if not result.warnings:
            score += 0.1
        # 无错误 +0.05
        if not result.errors:
            score += 0.05

        return min(score, 1.0)
