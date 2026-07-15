"""
ScriptParser - 脚本解析器

支持解析：
- Playwright (Python)
- Midscene (JavaScript)
- YAML
- JSON
"""
import json
import re
from typing import Dict, Any, List, Optional
from app.core.logger import log
from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability


class ParsedScript:
    """解析后的脚本结构"""
    def __init__(self):
        self.script_type: str = ""  # playwright/midscene/yaml/json
        self.language: str = ""     # python/javascript/yaml/json
        self.name: str = ""
        self.description: str = ""
        self.target_url: str = ""
        self.steps: List[Dict] = []
        self.imports: List[str] = []
        self.functions: List[str] = []
        self.selectors: List[Dict] = []
        self.assertions: List[str] = []
        self.raw_content: str = ""
        self.valid: bool = True
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def to_dict(self) -> Dict:
        return {
            "script_type": self.script_type,
            "language": self.language,
            "name": self.name,
            "description": self.description,
            "target_url": self.target_url,
            "steps": self.steps,
            "imports": self.imports,
            "functions": self.functions,
            "selectors": self.selectors,
            "assertions": self.assertions,
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
        }


class ScriptParser(NewBaseAgent):
    """脚本解析器"""

    agent_name = "script_parser"
    display_name = "Script Parser"
    description = "脚本解析器 - 支持解析Playwright/Midscene/YAML/JSON"
    capabilities = [AgentCapability.SCRIPT_PARSE]

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)

    def parse(self, content: str, filename: str = "") -> ParsedScript:
        """根据文件名和内容自动识别并解析脚本"""
        result = ParsedScript()
        result.raw_content = content

        # 识别脚本类型
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        script_type = self._detect_type(content, ext)
        result.script_type = script_type

        if script_type == "playwright":
            result.language = "python"
            self._parse_playwright(content, result)
        elif script_type == "midscene":
            result.language = "javascript"
            self._parse_midscene(content, result)
        elif script_type == "yaml":
            result.language = "yaml"
            self._parse_yaml(content, result)
        elif script_type == "json":
            result.language = "json"
            self._parse_json(content, result)
        else:
            result.valid = False
            result.errors.append("无法识别脚本类型")

        return result

    def _detect_type(self, content: str, ext: str) -> str:
        """自动检测脚本类型"""
        # 按扩展名
        if ext in ("py",):
            if "playwright" in content.lower() or "from playwright" in content:
                return "playwright"
            return "playwright"  # Python脚本默认当playwright处理
        if ext in ("js", "ts", "mjs"):
            if "midscene" in content.lower():
                return "midscene"
            return "midscene"
        if ext in ("yml", "yaml"):
            return "yaml"
        if ext == "json":
            return "json"

        # 按内容检测
        if "from playwright" in content or "playwright.sync_api" in content:
            return "playwright"
        if "midscene" in content or "aiAction" in content or "createAIPage" in content:
            return "midscene"
        if content.strip().startswith("{") or content.strip().startswith("["):
            try:
                json.loads(content)
                return "json"
            except Exception:
                pass
        if re.search(r'^[a-z_]+:', content, re.MULTILINE):
            return "yaml"

        return "playwright"  # 默认

    def _parse_playwright(self, content: str, result: ParsedScript):
        """解析Playwright Python脚本"""
        # 提取import
        result.imports = re.findall(r'^(?:from|import)\s+.+$', content, re.MULTILINE)

        # 提取函数名
        test_funcs = re.findall(r'def\s+(test_\w+)', content)
        result.functions = test_funcs
        if test_funcs:
            result.name = test_funcs[0].replace("test_", "").replace("_", " ").title()

        # 提取URL
        urls = re.findall(r'(?:page\.goto|\.goto)\s*\(\s*["\']([^"\']+)["\']', content)
        if urls:
            result.target_url = urls[0]

        # 提取选择器
        locators = re.findall(
            r'(?:locator|get_by_\w+|\.fill|\.click|\.type)\s*\(\s*["\']([^"\']+)["\']',
            content
        )
        for loc in locators:
            result.selectors.append({"value": loc, "type": self._classify_locator(loc)})

        # 提取断言
        assertions = re.findall(r'(?:expect|assert)\s*\(.+', content)
        result.assertions = assertions[:10]

        # 生成步骤
        steps = self._extract_playwright_steps(content)
        result.steps = steps

        # 描述
        docstrings = re.findall(r'"""([\s\S]*?)"""', content)
        if docstrings:
            result.description = docstrings[0].strip()[:200]

    def _extract_playwright_steps(self, content: str) -> List[Dict]:
        """从Playwright脚本提取步骤"""
        steps = []
        lines = content.split("\n")
        step_num = 0
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("import") or stripped.startswith("from"):
                continue
            # goto
            goto_match = re.match(r'.*page\.goto\s*\(\s*["\']([^"\']+)["\']', stripped)
            if goto_match:
                step_num += 1
                steps.append({"step": step_num, "action": "navigate", "target": goto_match.group(1), "raw": stripped})
                continue
            # click
            click_match = re.match(r'.*\.click\s*\(\s*(.*)', stripped)
            if click_match:
                step_num += 1
                steps.append({"step": step_num, "action": "click", "raw": stripped})
                continue
            # fill
            fill_match = re.match(r'.*\.fill\s*\(\s*["\']([^"\']*)["\']\s*\)', stripped)
            if fill_match:
                step_num += 1
                steps.append({"step": step_num, "action": "input", "value": fill_match.group(1), "raw": stripped})
                continue
            # assert/expect
            if "expect(" in stripped or "assert " in stripped:
                step_num += 1
                steps.append({"step": step_num, "action": "assert", "raw": stripped})
                continue
            # wait
            if "wait_for" in stripped:
                step_num += 1
                steps.append({"step": step_num, "action": "wait", "raw": stripped})
                continue
        return steps

    def _parse_midscene(self, content: str, result: ParsedScript):
        """解析Midscene JavaScript脚本"""
        result.imports = re.findall(r'^(?:import|require)\s+.+$', content, re.MULTILINE)

        # 提取函数名
        funcs = re.findall(r'(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=)', content)
        result.functions = [f[0] or f[1] for f in funcs if f[0] or f[1]]

        # 提取URL
        urls = re.findall(r'(?:page\.goto|\.goto)\s*\(\s*["\']([^"\']+)["\']', content)
        if urls:
            result.target_url = urls[0]

        # 提取aiAction步骤
        actions = re.findall(r'aiAction\s*\(\s*["\']([^"\']+)["\']', content)
        for i, action in enumerate(actions, 1):
            result.steps.append({"step": i, "action": "ai_action", "description": action})

        # 提取aiQuery
        queries = re.findall(r'aiQuery\s*\(\s*["\']([^"\']+)["\']', content)
        for q in queries:
            result.steps.append({"step": len(result.steps) + 1, "action": "ai_query", "description": q})

        # 提取aiAssert
        asserts = re.findall(r'aiAssert\s*\(\s*["\']([^"\']+)["\']', content)
        for a in asserts:
            result.assertions.append(a)

        if not result.name:
            result.name = "Midscene Test"

    def _parse_yaml(self, content: str, result: ParsedScript):
        """解析YAML脚本"""
        try:
            import yaml
            data = yaml.safe_load(content)
        except Exception as e:
            result.valid = False
            result.errors.append(f"YAML解析失败: {e}")
            return

        if not isinstance(data, dict):
            result.valid = False
            result.errors.append("YAML格式不正确，期望字典结构")
            return

        result.name = data.get("name", "YAML Test")
        result.description = data.get("description", "")
        result.target_url = data.get("target", data.get("url", ""))

        # 解析步骤
        yaml_steps = data.get("steps", [])
        for i, s in enumerate(yaml_steps, 1):
            if isinstance(s, dict):
                step = {
                    "step": i,
                    "action": s.get("action", ""),
                    "name": s.get("name", ""),
                    "raw": str(s),
                }
                locator = s.get("locator", {})
                if isinstance(locator, dict):
                    step["primary_locator"] = locator.get("primary", "")
                    step["fallback_locator"] = locator.get("fallback", "")
                if s.get("value"):
                    step["value"] = s["value"]
                result.steps.append(step)
                if isinstance(locator, dict) and locator.get("primary"):
                    result.selectors.append({"value": locator["primary"], "type": "css"})
            else:
                result.steps.append({"step": i, "action": str(s)})

    def _parse_json(self, content: str, result: ParsedScript):
        """解析JSON脚本"""
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            result.valid = False
            result.errors.append(f"JSON解析失败: {e}")
            return

        if isinstance(data, dict):
            result.name = data.get("name", "JSON Test")
            result.description = data.get("description", "")
            result.target_url = data.get("target", data.get("url", ""))

            json_steps = data.get("steps", data.get("testSteps", []))
            for i, s in enumerate(json_steps, 1):
                if isinstance(s, dict):
                    result.steps.append({
                        "step": i,
                        "action": s.get("action", s.get("type", "")),
                        "name": s.get("name", ""),
                        "value": s.get("value", ""),
                        "raw": str(s),
                    })
                else:
                    result.steps.append({"step": i, "action": str(s)})
        elif isinstance(data, list):
            for i, s in enumerate(data, 1):
                result.steps.append({"step": i, "raw": str(s)})

    def _classify_locator(self, locator: str) -> str:
        """分类定位器类型"""
        if locator.startswith("#") or locator.startswith("[id="):
            return "id"
        if locator.startswith("[name="):
            return "name"
        if locator.startswith("[data-testid") or locator.startswith("[data-test"):
            return "test_id"
        if locator.startswith("//") or locator.startswith("xpath="):
            return "xpath"
        if locator.startswith(".") or locator.startswith("[") or ">" in locator:
            return "css"
        return "text"
