"""
CaseAgent - 统一测试用例生成Agent

三种用例生成场景（均支持RAG增强）：
  - generate()            → Web UI 测试用例（Playwright步骤），主pipeline第6步
  - generate_rag_cases()  → RAG增强用例（文本需求+知识库参考）
  - compile_stream()      → API测试用例流式生成（结构化HTTP请求）
  - compile()             → API测试用例批量编译

所有用例生成场景统一入口。
"""
import json
import time as _time
from typing import Any, Dict, List, Optional, Generator
from app.core.config import settings
from app.core.logger import log
from app.core.llm import call_llm
from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability

# RAG限制常量
RAG_TOP_K = 3
RAG_CHUNK_MAX_TOKENS = 500


class CaseAgent(NewBaseAgent):
    """统一测试用例生成Agent"""

    agent_name = "case_agent"
    display_name = "用例生成Agent"
    description = "根据需求解析结果与RAG召回的元素，结合LLM生成标准测试用例"
    capabilities = [AgentCapability.CASE_GENERATE]

    CASE_TYPE_LABELS = {
        "functional": "功能测试用例",
        "boundary": "边界值测试用例",
        "error": "异常/错误测试用例",
        "compatibility": "兼容性测试用例",
        "security": "安全测试用例",
    }

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)
        self.agent_type = "case"
        self.model = None
        self.system_prompt = None

    # ================================================================== #
    #  公共 LLM 调用                                                      #
    # ================================================================== #

    def _call_llm(self, prompt: str, system_prompt: str = None, temperature: float = 0.3) -> str:
        """调用LLM API"""
        _start = _time.time()
        log.info(f"[DEBUG] 开始：CaseAgent._call_llm | prompt_length={len(prompt)}")

        sys_content = system_prompt or "你是一个专业的测试用例设计师，擅长根据需求和页面元素生成详细的测试用例。"
        content = call_llm(sys_content, prompt, temperature=temperature)

        _elapsed = _time.time() - _start
        log.info(f"[DEBUG] 结束：CaseAgent._call_llm | content_length={len(content)} | 耗时：{_elapsed:.2f}s")

        return content

    def emit(self, event: str, data: Any = None) -> None:
        """发布消息到MessageBus"""
        from app.agent.core.message_bus import MessageBus
        bus = MessageBus()
        bus.publish(f"{self.agent_name}.{event}", self.agent_name, data)

    # ================================================================== #
    #  场景1: Web UI 用例生成（主pipeline使用）                            #
    # ================================================================== #

    def _build_elements_context(self, elements: List[Dict[str, Any]]) -> str:
        """构建RAG召回元素的上下文信息"""
        if not elements:
            return "（暂无相关页面元素信息）"

        lines = []
        for i, elem in enumerate(elements[:15], 1):
            name = elem.get("element_name", "")
            etype = elem.get("element_type", "")
            locator = elem.get("locator", "")
            page = elem.get("page_name", "")
            score = elem.get("score", 0)
            lines.append(f"{i}. 元素: {name} | 类型: {etype} | 定位器: {locator} | 页面: {page} | 相似度: {score}")

        return "\n".join(lines)

    def _build_web_prompt(self, requirement: str, intent: str, steps: List[str], elements: List[Dict[str, Any]]) -> str:
        """构建Web UI用例生成的提示词"""
        elements_ctx = self._build_elements_context(elements)
        steps_str = "\n".join(f"- {s}" for s in steps)

        return f"""你是一个专业的测试用例设计师。请根据以下信息生成详细的测试用例。

需求：{requirement}
意图：{intent}
测试步骤：
{steps_str}

相关页面元素（来自RAG检索）：
{elements_ctx}

请按以下JSON格式输出（不要输出其他内容）：
{{
    "case_name": "用例名称",
    "description": "用例描述",
    "preconditions": ["前置条件1", "前置条件2"],
    "steps": [
        {{
            "step": "步骤描述",
            "action": "操作类型（goto/fill/click/verify_visible/verify_text/select_option/wait）",
            "locator": "定位器（从上面元素中选取，如果没有匹配的元素则留空）",
            "value": "操作值",
            "description": "步骤说明"
        }}
    ],
    "assertions": [
        {{
            "type": "断言类型（visible/text/url/title）",
            "locator": "定位器",
            "expected": "期望值",
            "description": "断言说明"
        }}
    ]
}}

要求：
1. steps要覆盖完整的测试流程
2. 优先使用上面提供的页面元素和定位器
3. 如果没有合适的定位器，locator字段留空，后续会由脚本生成器处理
4. action类型只能是: goto, fill, click, verify_visible, verify_text, select_option, wait
5. assertions至少包含1个验证步骤
6. 只输出JSON，不要输出其他内容"""

    def _parse_web_result(self, raw: str) -> Dict[str, Any]:
        """解析Web UI用例的LLM返回"""
        try:
            data = json.loads(raw)
            return {
                "case_name": data.get("case_name", "未命名用例"),
                "description": data.get("description", ""),
                "preconditions": data.get("preconditions", []),
                "steps": data.get("steps", []),
                "assertions": data.get("assertions", []),
            }
        except json.JSONDecodeError:
            log.warning(f"用例生成JSON解析失败，原始内容: {raw[:200]}")
            return {
                "case_name": "未命名用例",
                "description": raw[:200],
                "preconditions": [],
                "steps": [],
                "assertions": [],
            }

    def generate(
        self,
        requirement: str,
        intent: str,
        steps: List[str],
        elements: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Web UI 用例生成（主pipeline第6步使用）

        Returns: 统一格式 CaseResult (dict化)
        """
        _gen_start = _time.time()
        log.info(f"[DEBUG] 开始：CaseAgent.generate | intent={intent}, elements={len(elements)}, steps={len(steps)}")

        prompt = self._build_web_prompt(requirement, intent, steps, elements)
        raw = self._call_llm(prompt)
        result = self._parse_web_result(raw)

        _gen_elapsed = _time.time() - _gen_start
        log.info(f"[DEBUG] 结束：CaseAgent.generate | case_name={result['case_name']}, steps={len(result['steps'])} | 耗时：{_gen_elapsed:.2f}s")

        from app.models.case_result import CaseResult
        case_result = CaseResult.from_gen1_single(result)
        return case_result.model_dump()

    # ================================================================== #
    #  场景2: RAG增强用例生成（原 CaseGeneratorV2）                        #
    # ================================================================== #

    def generate_rag_cases(
        self,
        requirement_context: Any,
        retrieved_context: Optional[Dict[str, Any]] = None,
        case_types: Optional[List[str]] = None,
        max_cases: int = 20,
        focus_areas: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        RAG增强的用例生成

        合并自 CaseGeneratorV2.generate()
        """
        if not case_types:
            case_types = ["functional", "boundary", "error"]

        prompt = self._build_rag_prompt(requirement_context, retrieved_context, case_types, max_cases, focus_areas)

        try:
            raw = self._call_llm(
                prompt,
                system_prompt="你是一个企业级测试架构师，擅长根据需求和知识库参考生成全面、高质量的测试用例。",
                temperature=0.4,
            )
            result = self._parse_rag_result(raw, case_types)

            if retrieved_context:
                refs = retrieved_context.get("references", []) or []
                for case in result.get("cases", []):
                    if not case.get("references"):
                        case["references"] = refs[:5]

            self.emit("generated", {"total": result.get("total", 0)})
            return result
        except Exception as e:
            log.error(f"CaseAgent.generate_rag_cases | 生成失败: {e}")
            return {"cases": [], "total": 0, "error": str(e)}

    def _build_rag_prompt(
        self,
        req_ctx: Any,
        ret_ctx: Optional[Dict[str, Any]],
        case_types: List[str],
        max_cases: int,
        focus_areas: Optional[List[str]],
    ) -> str:
        """构建RAG增强提示词（合并自 CaseGeneratorV2._build_prompt）"""
        sections = []

        # 业务目标
        if isinstance(req_ctx, dict):
            goal = req_ctx.get("business_goal", "") or req_ctx.get("summary", "")
        else:
            goal = str(req_ctx)[:500]

        if goal:
            sections.append(f"# 需求概述\n{goal}")

        # 结构化内容
        if isinstance(req_ctx, dict):
            structured = self._structured_section(req_ctx)
            if structured:
                sections.append(structured)

        # RAG参考
        rag_section = self._rag_section(ret_ctx)
        if rag_section:
            sections.append(rag_section)

        if focus_areas:
            sections.append(f"# 重点关注\n" + "\n".join(f"- {a}" for a in focus_areas))

        type_descs = []
        for ct in case_types:
            label = self.CASE_TYPE_LABELS.get(ct, ct)
            type_descs.append(f"- {label}")
        sections.append(f"# 要求生成的用例类型\n" + "\n".join(type_descs))

        sections.append(f"""# 输出格式（严格JSON，最多{max_cases}条）
{{
    "cases": [
        {{
            "title": "用例标题",
            "case_type": "{",".join(case_types)}",
            "precondition": "前置条件",
            "steps": "1. 步骤1\\n2. 步骤2",
            "expected": "预期结果",
            "priority": "high/medium/low",
            "tags": "标签",
            "references": []
        }}
    ]
}}

要求：
1. 每个用例必须有明确的标题、前置条件、测试步骤和预期结果
2. 步骤要具体可操作
3. 尽量利用知识库中提供的信息来丰富用例细节
4. 只输出JSON""")

        return "\n\n".join(sections)

    def _structured_section(self, ctx: Dict[str, Any]) -> Optional[str]:
        """构建结构化内容部分（合并自 CaseGeneratorV2._structured_section）"""
        parts = ["## 结构化需求内容"]

        apis = ctx.get("apis", [])
        if apis:
            parts.append("\n### API 接口")
            for api in apis[:10]:
                parts.append(f"- {api.get('method', '')} {api.get('path', '')}: {api.get('summary', '')}")

        entities = ctx.get("entities", [])
        if entities:
            parts.append("\n### 数据实体")
            for ent in entities[:8]:
                fields = ", ".join(f.get("name", "") for f in ent.get("fields", [])[:5])
                parts.append(f"- {ent.get('entity_name', '')}: [{fields}]")

        flows = ctx.get("flows", [])
        if flows:
            parts.append("\n### 业务流程")
            for flow in flows[:5]:
                steps_summary = " → ".join(s.get("action", "") for s in flow.get("steps", [])[:4])
                parts.append(f"- {flow.get('flow_name', '')}: {steps_summary}")

        constraints = ctx.get("constraints", [])
        if constraints:
            parts.append("\n### 业务约束")
            for c in constraints[:8]:
                parts.append(f"- [{c.get('constraint_type', '')}] {c.get('description', '')}")

        pages = ctx.get("pages", [])
        if pages:
            parts.append("\n### 涉及页面")
            for p in pages[:5]:
                parts.append(f"- {p.get('page_name', '')}")

        if len(parts) == 1:
            return None
        return "\n".join(parts)

    def _rag_section(self, ret_ctx: Optional[Dict[str, Any]]) -> Optional[str]:
        """构建RAG参考部分（合并自 CaseGeneratorV2._rag_section）"""
        if not ret_ctx:
            return None

        parts = ["## 知识库参考"]
        chunks = ret_ctx.get("chunks", []) or ret_ctx.get("context", {}).get("chunks", [])
        for i, chunk in enumerate(chunks[:5], 1):
            text = chunk.get("text", "")[:800]
            source = chunk.get("source", "")
            parts.append(f"### 参考{i}\n来源: {source}\n内容: {text}")

        if len(parts) == 1:
            return None
        return "\n".join(parts)

    def _parse_rag_result(self, raw: str, case_types: List[str]) -> Dict[str, Any]:
        """解析RAG用例结果（合并自 CaseGeneratorV2._parse_result）"""
        try:
            data = json.loads(raw)
            cases = data.get("cases", [])
            return {"cases": cases, "total": len(cases), "case_types": case_types}
        except json.JSONDecodeError:
            log.warning(f"CaseAgent | RAG用例JSON解析失败: {raw[:200]}")
            return {"cases": [], "total": 0}

    # ================================================================== #
    #  场景3: API测试用例流式生成（原 CaseCompilerAgent）                 #
    # ================================================================== #

    def compile(
        self,
        features: List[Dict[str, Any]],
        rag_context: Optional[Dict[str, Any]] = None,
        requirement_context: str = "",
        source_type: str = "text",
    ) -> Dict[str, Any]:
        """
        批量编译API测试用例（内部逐条生成后汇总）

        合并自 CaseCompilerAgent.compile()
        """
        all_cases = []
        for case in self.compile_stream(
            features=features,
            rag_context=rag_context,
            requirement_context=requirement_context,
        ):
            all_cases.append(case)
        return {"cases": all_cases, "total": len(all_cases)}

    def compile_stream(
        self,
        features: List[Dict[str, Any]],
        rag_context: Optional[Dict[str, Any]] = None,
        requirement_context: str = "",
    ) -> Generator[Dict[str, Any], None, None]:
        """
        逐条生成API测试用例（流式）

        合并自 CaseCompilerAgent.compile_stream()
        """
        log.info(f"CaseAgent.compile_stream | 开始流式编译 | features={len(features)}")

        slim_rag = self._slim_rag_context(rag_context)
        slim_requirement = requirement_context[:500] if requirement_context else ""
        case_counter = 1

        for feature in features:
            feature_input = self._extract_minimal_input(feature)
            prompt = self._build_api_prompt(feature_input, slim_rag, slim_requirement, case_counter)

            try:
                raw = self._call_llm(
                    prompt,
                    system_prompt=(
                        "你是一个专业的测试用例编译器。你的任务是将单个测试意图转换为结构化的可执行测试用例。\n\n"
                        "你必须为每个测试点生成完整的HTTP请求结构，包括：\n"
                        "- method: HTTP方法\n"
                        "- url: 请求路径\n"
                        "- headers: 请求头（含Authorization）\n"
                        "- body: 请求体（含测试数据）\n"
                        "- pre_steps: 前置步骤（如登录获取token）\n"
                        "- variables: 变量定义（如{{token}}）\n"
                        "- assertions: 断言规则\n\n"
                        "你不生成代码，不执行测试，不直接调用接口。\n"
                        "每次只生成一个feature的测试用例。"
                    ),
                    temperature=0.2,
                )
                cases = self._parse_api_result(raw, case_counter, feature_input.get("name", ""))

                risk_level = feature.get("risk_level", "medium")
                risk_to_priority = {"high": "P0", "medium": "P1", "low": "P2"}
                feature_title = feature_input.get("name", "")
                feature_type = feature_input.get("type", "API")

                for c in cases:
                    if c.get("priority") in (None, "", "medium", "high", "low"):
                        c["priority"] = risk_to_priority.get(risk_level, "P1")
                    c["feature_ref"] = feature_title
                    c["type"] = feature_type
                    yield c

                case_counter += len(cases)
            except Exception as e:
                log.warning(f"CaseAgent.compile_stream | 编译feature失败 [{feature_input.get('name', '')}]: {e}")

        log.info(f"CaseAgent.compile_stream | 流式编译完成 | total={case_counter - 1}")

    def compile_single(
        self,
        feature: Dict[str, Any],
        rag_context: Optional[Dict[str, Any]] = None,
        requirement_context: str = "",
        case_id_start: int = 1,
    ) -> List[Dict[str, Any]]:
        """编译单个feature（用于并行worker）"""
        feature_input = self._extract_minimal_input(feature)
        slim_rag = self._slim_rag_context(rag_context)
        slim_requirement = requirement_context[:500] if requirement_context else ""

        prompt = self._build_api_prompt(feature_input, slim_rag, slim_requirement, case_id_start)
        raw = self._call_llm(
            prompt,
            system_prompt="你是一个专业的测试用例编译器。将测试意图转换为结构化可执行测试用例。",
            temperature=0.2,
        )
        cases = self._parse_api_result(raw, case_id_start, feature_input.get("name", ""))

        risk_level = feature.get("risk_level", "medium")
        risk_to_priority = {"high": "P0", "medium": "P1", "low": "P2"}
        feature_title = feature_input.get("name", "")
        feature_type = feature_input.get("type", "API")

        for c in cases:
            if c.get("priority") in (None, "", "medium", "high", "low"):
                c["priority"] = risk_to_priority.get(risk_level, "P1")
            c["feature_ref"] = feature_title
            c["type"] = feature_type

        return cases

    @staticmethod
    def _extract_minimal_input(feature: Dict[str, Any]) -> Dict[str, Any]:
        """提取最小化输入：只保留 feature/api/test_focus"""
        return {
            "name": feature.get("name", feature.get("title", "")),
            "type": feature.get("type", "API"),
            "test_focus": feature.get("test_focus", feature.get("test_points", [])),
            "risk_level": feature.get("risk_level", "medium"),
        }

    @staticmethod
    def _slim_rag_context(rag_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """精简RAG上下文：top_k <= 3, chunk <= 500 tokens"""
        if not rag_context:
            return {}

        ctx = rag_context.get("context", {})
        slim = {"apis": [], "entities": [], "constraints": []}
        max_chars = RAG_CHUNK_MAX_TOKENS * 3

        for key in ("apis", "entities", "constraints"):
            items = ctx.get(key, [])[:RAG_TOP_K]
            for item in items:
                text = item.get("text", "")
                if len(text) > max_chars:
                    text = text[:max_chars] + "..."
                slim[key].append({"text": text})

        return {"context": slim}

    def _build_api_prompt(
        self,
        feature: Dict[str, Any],
        rag_context: Dict[str, Any],
        requirement_context: str,
        case_id_start: int,
    ) -> str:
        """构建API用例编译prompt（合并自 CaseCompilerAgent._build_single_prompt）"""
        title = feature.get("name", "")
        ftype = feature.get("type", "API")
        test_points = feature.get("test_focus", [])

        sections = [
            "# 任务：将测试意图编译为结构化可执行测试用例\n",
            f"## 功能: {title} (类型: {ftype})\n",
            f"## 测试点\n" + "\n".join(f"- {tp}" for tp in test_points) + "\n",
        ]

        if requirement_context:
            sections.append(f"\n## 需求摘要\n{requirement_context}\n")

        if rag_context:
            ctx = rag_context.get("context", {})
            if ctx.get("apis"):
                api_texts = [a.get("text", "")[:300] for a in ctx["apis"][:RAG_TOP_K]]
                sections.append(f"\n## 相关API\n" + "\n".join(api_texts) + "\n")
            if ctx.get("entities"):
                ent_texts = [e.get("text", "")[:200] for e in ctx["entities"][:RAG_TOP_K]]
                sections.append(f"\n## 相关数据实体\n" + "\n".join(ent_texts) + "\n")
            if ctx.get("constraints"):
                c_texts = [c.get("text", "")[:200] for c in ctx["constraints"][:RAG_TOP_K]]
                sections.append(f"\n## 业务约束\n" + "\n".join(c_texts) + "\n")

        sections.append(f"""
## 输出格式（严格JSON，case_id从{case_id_start}开始）
{{
    "cases": [
        {{
            "case_id": "TC{case_id_start:03d}",
            "title": "用例标题",
            "method": "POST",
            "url": "/api/xxx",
            "headers": {{
                "Content-Type": "application/json",
                "Authorization": "Bearer {{{{token}}}}"
            }},
            "pre_steps": [
                {{
                    "name": "获取token",
                    "request": {{
                        "method": "POST",
                        "url": "/auth/login",
                        "headers": {{"Content-Type": "application/json"}},
                        "body": {{"username": "admin", "password": "123456"}}
                    }},
                    "extract": {{"token": "$.data.token"}}
                }}
            ],
            "variables": {{
                "token": "{{{{token}}}}"
            }},
            "body": {{}},
            "assertions": [
                {{"type": "equals", "path": "$.code", "expected": 200}},
                {{"type": "not_empty", "path": "$.data"}}
            ],
            "priority": "P0",
            "tags": ["标签1"]
        }}
    ]
}}

## assertion type 可选值
- equals / not_equals / contains / not_contains / not_empty / is_type / regex / greater_than / less_than

## priority 可选值: P0, P1, P2, P3

## 要求
1. 每个case必须包含完整的HTTP请求结构（method/url/headers/body）
2. 需要认证的接口必须包含pre_steps中的登录步骤
3. 需要认证的接口headers中必须包含Authorization: Bearer {{{{token}}}}
4. 必须为每个测试点生成对应的测试数据和断言
5. path使用JSONPath格式（如$.code, $.data.id）
6. 变量使用双花括号格式（如{{{{token}}}}）
7. 只输出JSON
""")
        return "\n".join(sections)

    def _parse_api_result(self, raw: str, case_id_start: int, feature_title: str) -> List[Dict]:
        """解析API用例结果（合并自 CaseCompilerAgent._parse_result）"""
        try:
            data = json.loads(raw)
            cases = data.get("cases", [])
            for i, c in enumerate(cases):
                if "case_id" not in c:
                    c["case_id"] = f"TC{case_id_start + i:03d}"
                if "method" not in c:
                    c["method"] = "POST"
                if "url" not in c:
                    c["url"] = ""
                if "headers" not in c:
                    c["headers"] = {"Content-Type": "application/json"}
                if "pre_steps" not in c:
                    c["pre_steps"] = []
                if "variables" not in c:
                    c["variables"] = {}
                if "body" not in c:
                    c["body"] = {}
                if "assertions" not in c:
                    c["assertions"] = []
                if "tags" not in c:
                    c["tags"] = []
                if "priority" not in c:
                    c["priority"] = "P1"
                if "steps" in c and "method" not in c:
                    for step in c["steps"]:
                        action = step.get("action", "")
                        if action.upper() in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                            c["method"] = action.upper()
                            c["url"] = step.get("url", "")
                            c["headers"] = step.get("headers", {})
                            c["body"] = step.get("body", {})
                            break
            return cases
        except json.JSONDecodeError:
            log.warning(f"CaseAgent | API用例JSON解析失败: {raw[:200]}")
            return []

    # ================================================================== #
    #  统一执行入口                                                       #
    # ================================================================== #

    def execute(self, **kwargs) -> Dict[str, Any]:
        """统一执行入口（BaseAgent接口，兼容管道payload键名）"""
        # 兼容管道键名：requirement_analysis / rag_context / test_cases
        req_analysis = kwargs.get("requirement_analysis") or kwargs.get("requirement")
        if isinstance(req_analysis, dict):
            requirement = req_analysis.get("summary", "") or req_analysis.get("intent", "")
            intent = req_analysis.get("intent", "unknown")
            steps = req_analysis.get("steps", [])
            target_url = req_analysis.get("target_url", "")
        else:
            requirement = kwargs.get("requirement", "")
            intent = kwargs.get("intent", "unknown")
            steps = kwargs.get("steps", [])
            target_url = kwargs.get("target_url", "")

        elements = kwargs.get("elements") or kwargs.get("rag_context") or []
        if isinstance(elements, dict):
            elements = elements.get("elements", [])

        # 如果有 requirement + intent → Web UI 用例
        if requirement and intent:
            result = self.generate(
                requirement=requirement,
                intent=intent,
                steps=steps,
                elements=elements,
            )
        # 如果有 requirement_context → RAG增强用例
        elif "requirement_context" in kwargs:
            result = self.generate_rag_cases(
                requirement_context=kwargs["requirement_context"],
                retrieved_context=kwargs.get("retrieved_context"),
                case_types=kwargs.get("case_types"),
                max_cases=kwargs.get("max_cases", 20),
            )
        # 如果有 features → API用例编译
        elif "features" in kwargs:
            result = self.compile(
                features=kwargs["features"],
                rag_context=kwargs.get("rag_context"),
                requirement_context=kwargs.get("requirement_context", ""),
            )
        else:
            result = {"cases": [], "total": 0, "error": "无法识别的输入参数"}

        self.emit("generated", result)
        return result

    # ================================================================== #
    #  兼容旧流程（异步生成器）                                            #
    # ================================================================== #

    async def generate_cases(
        self,
        task_id: int,
        elements: List[Dict[str, Any]]
    ) -> Any:
        """兼容旧流程：根据统一元素生成测试用例（异步生成器）"""
        from app.services.context_router import get_context_router, ContextType

        router = get_context_router()
        task = router.query_by_id(ContextType.TASK, record_id=task_id)
        if not task:
            yield {"step": "error", "message": f"任务 {task_id} 不存在"}
            return

        page_url = task.get("page_url", "") or ""
        requirement = f"测试页面 {page_url} 的功能"

        yield {"step": "分析元素", "progress": 10, "message": f"正在分析 {len(elements)} 个页面元素..."}

        elem_summary = []
        for el in elements[:20]:
            name = el.get("element_name", el.get("name", ""))
            etype = el.get("element_type", el.get("type", ""))
            locator = el.get("locator", "")
            elem_summary.append(f"- {name}({etype}): {locator}")

        elements_text = "\n".join(elem_summary) if elem_summary else "无元素信息"

        yield {"step": "生成用例", "progress": 40, "message": "正在调用LLM生成测试用例..."}

        prompt = f"""你是一个专业的测试用例设计师。请根据以下页面元素生成测试用例。

页面URL: {page_url}

页面元素：
{elements_text}

请按以下JSON格式输出（不要输出其他内容）：
{{
    "cases": [
        {{
            "case_name": "用例名称",
            "description": "用例描述",
            "preconditions": ["前置条件"],
            "steps": [
                {{
                    "step": "步骤描述",
                    "action": "操作类型（goto/fill/click/verify_visible/verify_text/select_option/wait）",
                    "locator": "定位器",
                    "value": "操作值",
                    "description": "步骤说明"
                }}
            ],
            "assertions": [
                {{
                    "type": "断言类型（visible/text/url/title）",
                    "locator": "定位器",
                    "expected": "期望值",
                    "description": "断言说明"
                }}
            ]
        }}
    ]
}}

要求：
1. 根据页面元素生成1-3个合理的测试用例
2. 优先使用上面提供的定位器
3. 只输出JSON"""

        try:
            raw = self._call_llm(prompt)
            data = json.loads(raw)
            cases = data.get("cases", [])
            yield {"step": "result", "progress": 100, "message": f"生成 {len(cases)} 个测试用例", "data": {"cases": cases}}
        except Exception as e:
            log.error(f"CaseAgent.generate_cases失败: {e}")
            yield {"step": "error", "message": str(e)}
