"""
ScriptGenerationAgent - 统一脚本生成入口

架构收敛目标：
  整个系统只能存在一个脚本生成入口。

职责：
  1. 脚本复用检查（前置，≥0.90 直接复用）
  2. 策略选择（StrategyAgent 6 种策略 + 降级链）
  3. 4 级降级生成链：
     Level 1: StrategyAgent + PromptBuilder（LLM 增强，质量最高）
     Level 2: FlowScriptGenerator（跨页面业务流，无 LLM）
     Level 3: RAG 增强（PlaywrightPrompt + LLM）
     Level 4: PlaywrightAgent（纯规则，无 LLM，兜底）
  4. 质量评估 + 重试注入

调用方式：
  # 通过 AgentRegistry
  from app.agents.factory import AgentRegistry
  agent = AgentRegistry.create("script_generation_agent")
  result = await agent.execute(payload)

  # 直接调用
  agent = ScriptGenerationAgent()
  result = await agent.execute(test_cases=..., elements=..., target_url=...)

内部组件：
  - StrategyAgent: 策略选择
  - PromptBuilder: Prompt 构建
  - ScriptReuseAgent: 复用检查
  - FlowScriptGenerator: Level 2 跨页面生成
  - PlaywrightAgent: Level 4 纯规则生成（替代旧模板拼接）

迁移说明：
  原 ScriptGenerator 的 generate() / execute() / _call_llm() / _evaluate_quality()
  / _inject_retry_logic() 逻辑完整迁移到本类。
  原 ScriptGenerator 标记为 @deprecated。
"""
import json
import re
import time as _time
from typing import Dict, Any, List, Optional

from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability
from app.agent.script.strategy_agent import StrategyAgent, Strategy, StrategyResult
from app.agent.script.prompt_builder import PromptBuilder
from app.agent.script.script_reuse_agent import ScriptReuseAgent
from app.core.config import settings
from app.core.logger import log
from app.core.llm import call_llm


class ScriptGenerationAgent(NewBaseAgent):
    """统一脚本生成 Agent — 系统中唯一的脚本生成入口

    整合能力：
      - 复用检查（ScriptReuseAgent）
      - 策略选择（StrategyAgent）
      - Prompt 构建（PromptBuilder）
      - 4 级降级生成链
      - 质量评估 + 重试注入
    """

    agent_name = "script_generation_agent"
    display_name = "脚本生成Agent（统一入口）"
    description = (
        "统一脚本生成入口。整合复用检查、策略选择、4级降级链、质量评估。"
        "系统内所有脚本生成必须经过此 Agent。"
    )
    capabilities = [AgentCapability.SCRIPT_GENERATE]

    # ==================== 初始化 ====================

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)
        self.strategy_agent = StrategyAgent()
        self.prompt_builder = PromptBuilder()
        self.reuse_agent = ScriptReuseAgent()

    # ==================== 管道兼容入口 ====================

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """管道统一入口 — 包含复用检查 + 4 级降级策略链

        接受以下参数名（兼容多套管道的 payload 键）：
          case_data / test_cases: 用例数据
          elements / rag_context: 页面元素
          target_url: 目标 URL
          requirement: 原始需求文本
          history_scripts: 历史相似脚本
          graph_business_flow / flow_context: Graph 推理业务流
          image_paths: 上传截图路径
          execution_records: 历史执行记录
          script_format: 输出格式 (playwright/midscene/yaml)
          feedback_context: 用户反馈
          retry_count: 重试次数

        Returns:
            {
                script_content: str,
                script_format: str,
                script_quality: float,
                degradation_info: { level, source, quality, action_required, message },
                reuse_info: Optional[dict],
                strategy_used: Optional[dict],
                ...
            }
        """
        # ---- 参数适配（兼容多套管道键名）----
        case_data = kwargs.get("case_data") or kwargs.get("test_cases") or {}
        elements = kwargs.get("elements") or kwargs.get("rag_context") or []
        if isinstance(elements, dict):
            elements = elements.get("elements", [])
        target_url = kwargs.get("target_url", "")
        requirement = kwargs.get("requirement", "")
        history_scripts = kwargs.get("history_scripts")
        graph_business_flow = (
            kwargs.get("graph_business_flow")
            or kwargs.get("flow_context")
        )
        if isinstance(graph_business_flow, dict):
            graph_business_flow = graph_business_flow.get("flows", [])
        image_paths = kwargs.get("image_paths")
        execution_records = kwargs.get("execution_records")
        script_format = kwargs.get("script_format", "playwright")
        feedback_context = kwargs.get("feedback_context", "")
        retry_count = kwargs.get("retry_count", 2)

        # 如果没有 case_data，从 requirement 构建最小结构
        if not case_data and requirement:
            case_data = {
                "case_name": requirement[:50],
                "description": requirement,
                "steps": [],
                "assertions": [],
            }

        # ---- Step 0: 复用检查 ----
        if requirement:
            try:
                reuse_result = self.reuse_agent.check_reuse(requirement, top_k=1)
                if reuse_result.get("reuse") and reuse_result.get("script_content"):
                    log.info(
                        f"[ScriptGenerationAgent] 复用命中 | "
                        f"similarity={reuse_result.get('similarity', 0):.4f}"
                    )
                    return {
                        "script_content": reuse_result["script_content"],
                        "script_format": script_format,
                        "script_quality": 1.0,
                        "degradation_info": {
                            "level": 0,
                            "source": "reuse",
                            "quality": "high",
                            "action_required": False,
                            "message": (
                                f"已复用历史脚本（相似度: "
                                f"{reuse_result.get('similarity', 0):.4f}）"
                            ),
                        },
                        "reuse_info": reuse_result,
                        "strategy_used": None,
                        "generation_time_ms": 0,
                    }
            except Exception as e:
                log.warning(f"[ScriptGenerationAgent] 复用检查失败，继续生成: {e}")

        # ---- Level 1: StrategyAgent + PromptBuilder（LLM 增强）----
        try:
            log.info("[ScriptGenerationAgent] Level 1: 策略增强生成")
            result = self._generate_level1(
                case_data=case_data,
                elements=elements,
                target_url=target_url,
                history_scripts=history_scripts,
                graph_business_flow=graph_business_flow,
                image_paths=image_paths,
                execution_records=execution_records,
                script_format=script_format,
                feedback_context=feedback_context,
                retry_count=retry_count,
            )
            result["degradation_info"] = {
                "level": 1,
                "source": "strategy",
                "quality": "high",
                "action_required": False,
                "message": "使用 StrategyAgent 策略生成，质量最高",
            }
            log.info("[ScriptGenerationAgent] Level 1 成功")
            return result

        except Exception as e:
            log.warning(f"[ScriptGenerationAgent] Level 1 失败: {e}")

        # ---- Level 2: FlowScriptGenerator（跨页面，无 LLM）----
        if graph_business_flow and isinstance(graph_business_flow, list) and len(graph_business_flow) >= 2:
            try:
                log.info("[ScriptGenerationAgent] Level 2: FlowScriptGenerator 跨页面生成")
                script_content = self._generate_level2(
                    case_data=case_data,
                    elements=elements,
                    graph_business_flow=graph_business_flow,
                    target_url=target_url,
                )
                if script_content:
                    log.info("[ScriptGenerationAgent] Level 2 成功")
                    return {
                        "script_content": script_content,
                        "script_format": script_format,
                        "script_quality": 0.7,
                        "degradation_info": {
                            "level": 2,
                            "source": "flow",
                            "quality": "medium",
                            "action_required": True,
                            "message": "增强生成失败，已降级为 FlowScriptGenerator 跨页面生成",
                        },
                        "reuse_info": None,
                        "strategy_used": None,
                        "generation_time_ms": 0,
                    }
            except Exception as e:
                log.warning(f"[ScriptGenerationAgent] Level 2 失败: {e}")

        # ---- Level 3: RAG 增强（PlaywrightPrompt + LLM）----
        try:
            log.info("[ScriptGenerationAgent] Level 3: RAG 增强生成")
            script_content = self._generate_level3(
                case_data=case_data,
                elements=elements,
                target_url=target_url,
                requirement=requirement,
            )
            if script_content:
                log.info("[ScriptGenerationAgent] Level 3 成功")
                return {
                    "script_content": script_content,
                    "script_format": script_format,
                    "script_quality": 0.5,
                    "degradation_info": {
                        "level": 3,
                        "source": "rag",
                        "quality": "medium",
                        "action_required": True,
                        "message": "已降级为标准 RAG + LLM 生成，建议审查脚本",
                    },
                    "reuse_info": None,
                    "strategy_used": None,
                    "generation_time_ms": 0,
                }
        except Exception as e:
            log.warning(f"[ScriptGenerationAgent] Level 3 失败: {e}")

        # ---- Level 4: 纯规则生成（PlaywrightAgent，无 LLM，兜底）----
        log.warning("[ScriptGenerationAgent] Level 4: 规则模板兜底")
        script_content = self._generate_level4(
            case_data=case_data,
            elements=elements,
            target_url=target_url,
        )
        return {
            "script_content": script_content,
            "script_format": script_format,
            "script_quality": 0.2,
            "degradation_info": {
                "level": 4,
                "source": "rule",
                "quality": "low",
                "action_required": True,
                "message": "LLM 生成全部失败，已使用规则模板生成，必须人工修改",
            },
            "reuse_info": None,
            "strategy_used": None,
            "generation_time_ms": 0,
        }

    # ==================== Level 1: 策略增强生成 ====================

    def _generate_level1(
        self,
        case_data: Dict[str, Any],
        elements: List[Dict],
        target_url: str = "",
        history_scripts: List[Dict] = None,
        graph_business_flow: List[Dict] = None,
        image_paths: List[str] = None,
        execution_records: List[Dict] = None,
        script_format: str = "playwright",
        feedback_context: str = "",
        retry_count: int = 2,
    ) -> Dict[str, Any]:
        """Level 1: StrategyAgent 选策略 → PromptBuilder 构建 → LLM 调用 → 重试注入 → 质量评估"""
        start_time = _time.time()

        # 1. 策略选择
        strategy = self.strategy_agent.select(
            elements=elements,
            image_paths=image_paths,
            graph_business_flow=graph_business_flow,
            history_scripts=history_scripts,
            execution_records=execution_records,
            has_url=bool(target_url),
        )

        log.info(
            f"[ScriptGenerationAgent] 策略: {strategy.primary.value}, "
            f"置信度: {strategy.confidence:.2f}"
        )

        # 2. 构建 Prompt
        if script_format == "midscene":
            system_prompt, user_prompt = self.prompt_builder.build_midscene_prompt(
                case_data=case_data,
                elements=elements,
                target_url=target_url,
                graph_business_flow=graph_business_flow,
                strategy=strategy,
                retry_count=retry_count,
            )
        elif script_format == "yaml":
            system_prompt, user_prompt = self.prompt_builder.build_yaml_prompt(
                case_data=case_data,
                elements=elements,
                target_url=target_url,
                graph_business_flow=graph_business_flow,
                strategy=strategy,
            )
        else:
            system_prompt, user_prompt = self.prompt_builder.build_playwright_prompt(
                case_data=case_data,
                elements=elements,
                target_url=target_url,
                history_scripts=history_scripts,
                graph_business_flow=graph_business_flow,
                strategy=strategy,
                retry_count=retry_count,
                feedback_context=feedback_context,
            )

        # 3. 调用 LLM
        script_content = self._call_llm(system_prompt, user_prompt)

        # 4. 后处理：注入重试逻辑（仅 Playwright）
        if script_format == "playwright" and retry_count > 0:
            script_content = self._inject_retry_logic(script_content, retry_count, strategy)

        # 5. 质量评估
        script_quality = self._evaluate_quality(script_content, elements, strategy)

        # 6. 重试策略配置
        retry_strategy = {
            "max_retries": retry_count,
            "retry_intervals": [1000 * (i + 1) for i in range(retry_count)],
            "degradation_chain": [s.value for s in strategy.degradation_chain],
            "retry_on": ["TimeoutError", "Error", "AssertionError"],
        }

        elapsed = int((_time.time() - start_time) * 1000)

        return {
            "script_content": script_content,
            "script_format": script_format,
            "script_quality": script_quality,
            "retry_strategy": retry_strategy,
            "strategy_used": strategy.to_dict(),
            "degradation_chain": [s.value for s in strategy.degradation_chain],
            "generation_time_ms": elapsed,
            "reuse_info": None,
        }

    # ==================== Level 2: 跨页面生成 ====================

    def _generate_level2(
        self,
        case_data: Dict[str, Any],
        elements: List[Dict],
        graph_business_flow: List[Dict],
        target_url: str = "",
    ) -> str:
        """Level 2: FlowScriptGenerator 跨页面业务流脚本"""
        from app.agent.requirement.flow_script_generator import FlowScriptGenerator

        flow_gen = FlowScriptGenerator()

        # 尝试从 graph_business_flow 构建 FlowGraph
        flow_graph = self._build_flow_graph(graph_business_flow, target_url)
        if flow_graph is None:
            raise ValueError("无法从 graph_business_flow 构建 FlowGraph")

        return flow_gen.generate(
            flow_graph=flow_graph,
            elements=elements,
            case_data=case_data,
        )

    def _build_flow_graph(self, graph_business_flow: List[Dict], entry_url: str = ""):
        """从 graph_business_flow 列表构建 FlowGraph 对象"""
        try:
            from app.agent.requirement.flow_parser import FlowGraph, PageNode, PageTransition

            if not graph_business_flow:
                return None

            pages = []
            transitions = []
            variables = {}

            for i, flow in enumerate(graph_business_flow):
                if not isinstance(flow, dict):
                    continue
                page = PageNode(
                    page_id=flow.get("page_id", f"page_{i}"),
                    title=flow.get("title", flow.get("page_title", f"Page {i+1}")),
                    url=flow.get("url", ""),
                    page_type=flow.get("page_type", "generic"),
                    actions=flow.get("actions", []),
                )
                pages.append(page)

                nav = flow.get("navigation", {})
                if nav and nav.get("target"):
                    transition = PageTransition(
                        from_page=page.page_id,
                        to_page=nav["target"],
                        trigger=nav.get("trigger", ""),
                        trigger_locator=nav.get("trigger_locator", ""),
                        variables_out=nav.get("variables_out", []),
                    )
                    transitions.append(transition)

                for var_name, var_val in flow.get("variables", {}).items():
                    variables[var_name] = var_val

            flow_graph = FlowGraph(
                pages=pages,
                transitions=transitions,
                variables=variables,
                entry_url=entry_url,
            )
            return flow_graph
        except Exception as e:
            log.warning(f"[ScriptGenerationAgent] 构建 FlowGraph 失败: {e}")
            return None

    # ==================== Level 3: RAG 增强 ====================

    def _generate_level3(
        self,
        case_data: Dict[str, Any],
        elements: List[Dict],
        target_url: str = "",
        requirement: str = "",
    ) -> str:
        """Level 3: PlaywrightPrompt + LLM"""
        from app.prompts.playwright_prompt import PlaywrightPrompt

        prompt = PlaywrightPrompt.build(
            requirement=requirement or case_data.get("description", ""),
            case_data=case_data,
            elements=elements,
            target_url=target_url,
        )
        return self._call_llm(prompt.get("system", ""), prompt.get("user", ""))

    # ==================== Level 4: 纯规则模板 ====================

    def _generate_level4(
        self,
        case_data: Dict[str, Any],
        elements: List[Dict],
        target_url: str = "",
    ) -> str:
        """Level 4: 纯模板拼接（无 LLM，兜底保底）

        优先使用 PlaywrightAgent 的规则生成能力（比旧模板更完善），
        如果 PlaywrightAgent 不可用则降级到基础模板。
        """
        # 尝试使用 PlaywrightAgent（更完善的规则生成）
        try:
            import asyncio
            from app.agent.vision.playwright_agent import PlaywrightAgent

            agent = PlaywrightAgent()

            # PlaywrightAgent.generate_script 是 async generator
            async def _collect():
                script = ""
                async for chunk in agent.generate_script(
                    task_id=0,
                    elements=elements,
                    cases=[case_data] if case_data else [],
                    page_url=target_url,
                ):
                    if chunk.get("step") == "result" and chunk.get("data", {}).get("script"):
                        script = chunk["data"]["script"]
                        break
                return script

            loop = asyncio.new_event_loop()
            try:
                script = loop.run_until_complete(_collect())
            finally:
                loop.close()

            if script:
                return script
        except Exception as e:
            log.warning(f"[ScriptGenerationAgent] PlaywrightAgent 生成失败，降级到基础模板: {e}")

        # 基础模板兜底
        return self._generate_from_template(case_data, elements, target_url)

    def _generate_from_template(
        self,
        case_data: Dict[str, Any],
        elements: List[Dict],
        target_url: str = "",
    ) -> str:
        """基础模板拼接（最终兜底）"""
        steps = case_data.get("steps", []) if isinstance(case_data, dict) else []
        assertions = case_data.get("assertions", []) if isinstance(case_data, dict) else []

        # 构建元素映射
        elem_map = {}
        for elem in elements:
            if isinstance(elem, dict):
                name = elem.get("element_name") or elem.get("name") or ""
                locator = elem.get("locator") or elem.get("css_selector") or elem.get("xpath") or ""
                if name and locator:
                    elem_map[name.lower()] = locator

        lines = [
            "import pytest",
            "from playwright.sync_api import Page, expect",
            "",
            "",
            "class TestGenerated:",
            '    """自动生成 - 模板模式（Level 4 降级）"""',
            "",
        ]

        case_name = case_data.get("case_name", "test_case") if isinstance(case_data, dict) else "test_case"
        safe_name = "".join(c if c.isalnum() or c == "_" else "_" for c in case_name).strip("_")
        if not safe_name:
            safe_name = "test_case"

        lines.append(f"    def test_{safe_name}(self, page: Page):")
        if target_url:
            lines.append(f'        page.goto("{target_url}")')

        for step in steps:
            if not isinstance(step, dict):
                continue
            action = step.get("action", "")
            locator = step.get("locator", "")
            value = step.get("value", "")
            desc = step.get("description") or step.get("step", "")

            if not locator and desc:
                for key, val in elem_map.items():
                    if key in desc.lower():
                        locator = val
                        break

            if action == "goto" and value:
                lines.append(f'        page.goto("{value}")')
            elif action == "fill" and locator:
                lines.append(f'        page.locator("{locator}").fill("{value}")')
            elif action == "click" and locator:
                lines.append(f'        page.locator("{locator}").click()')
            elif action == "verify_visible" and locator:
                lines.append(f'        expect(page.locator("{locator}")).to_be_visible()')
            elif action == "verify_text" and locator:
                lines.append(f'        expect(page.locator("{locator}")).to_have_text("{value}")')
            elif action == "wait":
                lines.append(f'        page.wait_for_timeout(2000)')
            elif desc:
                lines.append(f"        # TODO: {desc}")
                if locator:
                    lines.append(f'        # locator: {locator}')

        for assertion in assertions:
            if not isinstance(assertion, dict):
                continue
            atype = assertion.get("type", "")
            alocator = assertion.get("locator", "")
            aexpected = assertion.get("expected", "")
            if atype == "visible" and alocator:
                lines.append(f'        expect(page.locator("{alocator}")).to_be_visible()')
            elif atype == "text" and alocator:
                lines.append(f'        expect(page.locator("{alocator}")).to_have_text("{aexpected}")')
            elif atype == "url":
                lines.append(f'        expect(page).to_have_url("{aexpected}")')

        if not steps and not assertions:
            lines.append("        # TODO: 请手动补充测试步骤")
            lines.append("        pass")

        lines.append("")
        return "\n".join(lines)

    # ==================== LLM 调用 ====================

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """调用 LLM 生成脚本"""
        content = call_llm(system_prompt, user_prompt, temperature=0.2)

        # 去除 markdown 代码块
        for prefix in ["```python", "```javascript", "```yaml", "```"]:
            if content.startswith(prefix):
                content = content[len(prefix):]
        if content.endswith("```"):
            content = content[:-3]

        return content.strip()

    # ==================== 重试注入 ====================

    def _inject_retry_logic(self, script: str, retry_count: int, strategy: StrategyResult) -> str:
        """向 Playwright 脚本注入重试辅助函数"""
        if "for attempt in range" in script or "retry" in script.lower():
            return script

        retry_helper = '''
# ===== 自动重试与降级策略 =====
import time as _time

def _safe_action(action_fn, max_retries=%d, retry_intervals=None):
    """带重试的操作执行器"""
    if retry_intervals is None:
        retry_intervals = [1000 * (i + 1) for i in range(max_retries)]
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return action_fn()
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                _time.sleep(retry_intervals[attempt] / 1000)
    raise last_error

def _locate_element(page, **locators):
    """按优先级尝试定位器，失败后降级"""
    for strategy_name, value in locators.items():
        if not value:
            continue
        try:
            if strategy_name in ("test_id", "data-testid"):
                return page.get_by_test_id(value)
            elif strategy_name in ("id",):
                return page.locator(f"#{value}")
            elif strategy_name in ("name",):
                return page.locator(f'[name="{value}"]')
            elif strategy_name in ("css", "css_selector"):
                return page.locator(value)
            elif strategy_name in ("xpath",):
                return page.locator(f"xpath={value}")
            elif strategy_name in ("text", "aria-label", "placeholder"):
                return page.get_by_text(value) if strategy_name == "text" else page.locator(f'[{strategy_name}="{value}"]')
        except Exception:
            continue
    raise Exception(f"所有定位器均失败: {locators}")
# ===== 结束：自动重试与降级策略 =====

''' % retry_count

        import_match = re.search(r'(from playwright\.sync_api import[^\n]+\n)', script)
        if import_match:
            insert_pos = import_match.end()
            script = script[:insert_pos] + retry_helper + script[insert_pos:]
        else:
            script = retry_helper + script

        return script

    # ==================== 质量评估 ====================

    def _evaluate_quality(self, script: str, elements: List[Dict], strategy: StrategyResult) -> float:
        """评估脚本质量（0-1 分，7 个维度）"""
        if not script:
            return 0.0

        score = 0.0

        # 1. 定位器使用（+0.3）
        locator_patterns = [
            r'locator\(', r'get_by_test_id\(', r'get_by_text\(',
            r'get_by_role\(', r'\.fill\(', r'\.click\(',
        ]
        locator_count = sum(1 for p in locator_patterns if re.search(p, script))
        score += min(locator_count / 3, 1.0) * 0.3

        # 2. 等待逻辑（+0.15）
        wait_patterns = [r'wait_for', r'wait_for_load_state', r'wait_for_timeout', r'wait_for_selector']
        if any(re.search(p, script) for p in wait_patterns):
            score += 0.15

        # 3. 断言（+0.15）
        assert_patterns = [r'expect\(', r'assert ', r'to_be_visible', r'to_have_text', r'aiAssert']
        if any(re.search(p, script) for p in assert_patterns):
            score += 0.15

        # 4. 重试逻辑（+0.15）
        retry_patterns = [r'retry', r'for attempt in', r'_safe_action', r'max_retries']
        if any(re.search(p, script) for p in retry_patterns):
            score += 0.15

        # 5. 降级逻辑（+0.1）
        degradation_patterns = [r'_locate_element', r'fallback', r'except.*continue', r'try:.*except']
        if any(re.search(p, script, re.DOTALL) for p in degradation_patterns):
            score += 0.1

        # 6. 策略置信度（+0.15）
        score += strategy.confidence * 0.15

        # 7. 脚本长度合理性（+0.05）
        if 200 < len(script) < 10000:
            score += 0.05

        return min(score, 1.0)
