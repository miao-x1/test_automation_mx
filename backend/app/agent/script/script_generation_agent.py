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
import asyncio
import json
import re
import time as _time
from typing import Dict, Any, List, Optional

from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability
from app.agent.script.strategy_agent import StrategyAgent, Strategy, StrategyResult
from app.agent.script.prompt_builder import PromptBuilder
from app.agent.script.script_reuse_agent import ScriptReuseAgent
from app.agent.script.locator_builder import (
    enrich_elements,
    extract_url,
    script_has_invalid_locators,
    usable_elements,
)
from app.agent.script.locator_validator import (
    LOCATOR_GENERATION_FAILED,
    script_uses_validated,
    validate_locators_on_page,
)
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
        case_data = kwargs.get("case_data") or kwargs.get("test_cases") or kwargs.get("cases") or {}
        if isinstance(case_data, list):
            case_data = {
                "cases": case_data,
                "case_name": (case_data[0] or {}).get("case_name", "") if case_data else "",
                "steps": (case_data[0] or {}).get("steps", []) if case_data else [],
                "assertions": (case_data[0] or {}).get("assertions", []) if case_data else [],
            }
        elements = kwargs.get("elements") or kwargs.get("rag_context") or []
        if isinstance(elements, dict):
            elements = elements.get("elements", [])
        page_elements = kwargs.get("page_elements")
        if isinstance(page_elements, dict):
            extra = []
            for item in page_elements.values():
                if isinstance(item, list):
                    extra.extend(item)
            if extra:
                elements = list(elements or []) + extra
        elif isinstance(page_elements, list) and page_elements:
            elements = list(elements or []) + page_elements
        target_url = kwargs.get("target_url", "")
        requirement = kwargs.get("requirement", "")
        if isinstance(case_data, dict) and requirement and not case_data.get("requirement"):
            case_data = {**case_data, "requirement": requirement}
        self._assertion_blob = f"{requirement} {case_data if isinstance(case_data, dict) else ''}"
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

        target_url = extract_url(
            target_url,
            case_data if isinstance(case_data, dict) else {},
            elements,
            requirement,
            kwargs.get("page_url"),
        )
        elements = enrich_elements(elements if isinstance(elements, list) else [])
        if not usable_elements(elements):
            from app.agent.script.locator_builder import infer_elements_from_cases
            infer_source = case_data
            if isinstance(case_data, dict) and isinstance(case_data.get("cases"), list):
                infer_source = case_data["cases"]
            inferred = infer_elements_from_cases(infer_source)
            if inferred:
                elements = inferred
        if isinstance(case_data, dict) and not target_url:
            nested_cases = case_data.get("cases") if isinstance(case_data.get("cases"), list) else [case_data]
            target_url = extract_url(target_url, *nested_cases)

        if not target_url:
            return self._fail(
                script_format,
                "缺少真实目标 URL，无法生成可执行脚本。请提供页面地址，不要使用 TODO_REPLACE。",
            )
        if (
            not usable_elements(elements)
            and not self._steps_have_locators(case_data)
            and not self._has_interactive_steps(case_data)
        ):
            return self._fail(
                script_format,
                "无法确定稳定定位器。请先完成 UI 识别，或为步骤提供 role/label/placeholder/test_id/text/css/xpath。",
            )

        validation = await asyncio.to_thread(
            validate_locators_on_page,
            target_url,
            elements if isinstance(elements, list) else [],
            case_data,
        )
        if validation.get("status") != "SUCCESS":
            return self._fail(
                script_format,
                validation.get("error") or f"{LOCATOR_GENERATION_FAILED}: 真实页面无法验证定位器",
            )
        elements = validation.get("elements") or []
        log.info(
            f"[ScriptGenerationAgent] Locator 已验证 | "
            f"count={len(elements)} exprs={[e.get('playwright_expr') for e in elements]}"
        )

        try:
            validated_script = self._generate_from_template(
                case_data if isinstance(case_data, dict) else {},
                elements,
                target_url,
            )
            accepted = self._accept_script(validated_script, {
                "script_content": validated_script,
                "script_format": script_format,
                "script_quality": 0.95,
                "degradation_info": {
                    "level": 1,
                    "source": "validated_locator",
                    "quality": "high",
                    "action_required": False,
                    "message": "Locator 已在真实页面验证，使用已验证定位器生成脚本",
                },
                "reuse_info": None,
                "strategy_used": None,
                "generation_time_ms": 0,
            })
            if accepted and script_uses_validated(validated_script, elements):
                log.info("[ScriptGenerationAgent] 已验证 locator 脚本生成成功")
                return accepted
        except Exception as exc:
            log.warning(f"[ScriptGenerationAgent] 已验证 locator 模板失败，继续降级: {exc}")

        # ---- Step 0: 复用检查 ----
        if requirement:
            try:
                reuse_result = self.reuse_agent.check_reuse(requirement, top_k=1)
                if reuse_result.get("reuse") and reuse_result.get("script_content"):
                    reused = reuse_result["script_content"]
                    invalid = script_has_invalid_locators(reused)
                    if invalid:
                        log.warning(f"[ScriptGenerationAgent] 复用脚本不可执行，继续生成: {invalid}")
                    elif not script_uses_validated(reused, elements):
                        log.warning("[ScriptGenerationAgent] 复用脚本未包含已验证 locator，继续生成")
                    else:
                        log.info(
                            f"[ScriptGenerationAgent] 复用命中 | "
                            f"similarity={reuse_result.get('similarity', 0):.4f}"
                        )
                        return {
                            "status": "SUCCESS",
                            "script_content": reused,
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
            accepted = self._accept_validated_script(
                result.get("script_content", ""), result, elements, case_data, target_url
            )
            if accepted:
                log.info("[ScriptGenerationAgent] Level 1 成功")
                return accepted
            raise ValueError(script_has_invalid_locators(result.get("script_content", "")) or "脚本不可执行")

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
                    accepted = self._accept_validated_script(script_content, {
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
                    }, elements, case_data, target_url)
                    if accepted:
                        log.info("[ScriptGenerationAgent] Level 2 成功")
                        return accepted
                    raise ValueError(script_has_invalid_locators(script_content) or "脚本不可执行")
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
                accepted = self._accept_validated_script(script_content, {
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
                }, elements, case_data, target_url)
                if accepted:
                    log.info("[ScriptGenerationAgent] Level 3 成功")
                    return accepted
                raise ValueError(script_has_invalid_locators(script_content) or "脚本不可执行")
        except Exception as e:
            log.warning(f"[ScriptGenerationAgent] Level 3 失败: {e}")

        # ---- Level 4: 纯规则生成（PlaywrightAgent，无 LLM，兜底）----
        log.warning("[ScriptGenerationAgent] Level 4: 规则模板兜底")
        try:
            script_content = self._generate_level4(
                case_data=case_data,
                elements=elements,
                target_url=target_url,
            )
            accepted = self._accept_validated_script(script_content, {
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
            }, elements, case_data, target_url)
            if accepted:
                return accepted
        except Exception as e:
            log.warning(f"[ScriptGenerationAgent] Level 4 失败: {e}")
        return self._fail(script_format, "无法确定稳定定位器，已拒绝生成空 locator / TODO_REPLACE 脚本。")

    def _fail(self, script_format: str, message: str) -> Dict[str, Any]:
        log.error(f"[ScriptGenerationAgent] {message}")
        return {
            "status": "FAILED",
            "error": message,
            "message": message,
            "script_content": "",
            "script_format": script_format,
            "script_quality": 0.0,
            "degradation_info": {
                "level": -1,
                "source": "validation",
                "quality": "none",
                "action_required": True,
                "message": message,
            },
            "reuse_info": None,
            "strategy_used": None,
            "generation_time_ms": 0,
        }

    @staticmethod
    def _inject_visible_text_assertions(script_content: str, blob: str) -> str:
        text = script_content or ""
        extra: List[str] = []
        if "登录成功" in (blob or "") and "登录成功" not in text:
            extra.append('    expect(page.get_by_text("登录成功")).to_be_visible()')
        if not extra:
            return text
        return text.rstrip() + "\n" + "\n".join(extra) + "\n"

    def _accept_script(self, script_content: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        invalid = script_has_invalid_locators(script_content)
        if invalid:
            log.warning(f"[ScriptGenerationAgent] 拒绝不可执行脚本: {invalid}")
            return None
        script_content = self._inject_visible_text_assertions(
            script_content,
            str(payload.get("_assertion_blob") or getattr(self, "_assertion_blob", "") or ""),
        )
        payload["status"] = "SUCCESS"
        payload["script_content"] = script_content
        return payload

    def _accept_validated_script(
        self,
        script_content: str,
        payload: Dict[str, Any],
        elements: List[Dict],
        case_data: Any,
        target_url: str,
    ) -> Optional[Dict[str, Any]]:
        if (
            script_content
            and not script_has_invalid_locators(script_content)
            and script_uses_validated(script_content, elements)
        ):
            return self._accept_script(script_content, payload)
        try:
            rewritten = self._generate_from_template(
                case_data if isinstance(case_data, dict) else {},
                elements,
                target_url,
            )
        except Exception as exc:
            log.warning(f"[ScriptGenerationAgent] 已验证 locator 模板重写失败: {exc}")
            return None
        accepted = self._accept_script(rewritten, payload)
        if accepted:
            accepted["locator_rewritten"] = True
        return accepted

    @staticmethod
    def _has_interactive_steps(case_data: Any) -> bool:
        if not isinstance(case_data, dict):
            return False
        steps = list(case_data.get("steps") or [])
        for case in case_data.get("cases") or []:
            if isinstance(case, dict):
                steps.extend(case.get("steps") or [])
        for step in steps:
            if isinstance(step, str) and any(tok in step for tok in ("输入", "点击", "填写", "fill", "click")):
                return True
            if not isinstance(step, dict):
                continue
            action = str(step.get("action") or "").lower()
            desc = str(step.get("description") or step.get("step") or "")
            if action in {"fill", "input", "type", "click", "submit"}:
                return True
            if any(tok in desc for tok in ("输入", "点击", "填写", "fill", "click")):
                return True
        return False

    @staticmethod
    def _steps_have_locators(case_data: Any) -> bool:
        if not isinstance(case_data, dict):
            return False
        for step in case_data.get("steps") or []:
            if isinstance(step, dict) and (
                step.get("locator") or step.get("playwright_expr") or step.get("css_selector")
            ):
                return True
        return False

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

            try:
                asyncio.get_running_loop()
            except RuntimeError:
                script = asyncio.run(_collect())
            else:
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    script = pool.submit(asyncio.run, _collect()).result()

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
        from app.agent.script.locator_builder import _normalize_case_steps, infer_fill_value

        steps = case_data.get("steps", []) if isinstance(case_data, dict) else []
        if (not steps or not isinstance(steps, list)) and isinstance(case_data, dict):
            if isinstance(case_data.get("cases"), list) and case_data["cases"]:
                steps = _normalize_case_steps(case_data["cases"][0])
            else:
                steps = _normalize_case_steps(case_data)
        assertions = case_data.get("assertions", []) if isinstance(case_data, dict) else []

        # 构建元素映射（已验证 locator 按意图优先）
        elem_map = {}
        fill_expr = ""
        click_expr = ""
        for elem in elements:
            if isinstance(elem, dict):
                name = elem.get("element_name") or elem.get("name") or ""
                locator = (
                    elem.get("playwright_expr")
                    or elem.get("locator")
                    or elem.get("best_locator")
                    or elem.get("css_selector")
                    or elem.get("xpath")
                    or ""
                )
                if name and locator:
                    elem_map[name.lower()] = locator
                intent = str(elem.get("intent") or "").lower()
                etype = str(elem.get("type") or "").lower()
                if locator and not fill_expr and (
                    intent in {"fill", "search", "input"} or etype in {"input", "searchbox", "textarea"}
                ):
                    fill_expr = locator
                if locator and not click_expr and (
                    intent == "click" or etype in {"button", "link"}
                ):
                    click_expr = locator

        lines = [
            "import re",
            "from playwright.sync_api import Page, expect",
            "",
            "",
        ]

        case_name = case_data.get("case_name", "test_case") if isinstance(case_data, dict) else "test_case"
        safe_name = "".join(c if c.isascii() and (c.isalnum() or c == "_") else "_" for c in case_name).strip("_")
        if not safe_name or not safe_name.isidentifier():
            safe_name = "generated_flow"

        lines.append(f"def test_{safe_name}(page: Page):")
        if target_url:
            lines.append(f'    page.goto("{target_url}")')
            lines.append('    page.wait_for_load_state("domcontentloaded")')

        last_fill_value = ""
        last_fill_is_search = False
        for step in steps:
            if not isinstance(step, dict):
                continue
            action = step.get("action", "")
            locator = step.get("locator", "")
            value = step.get("value", "")
            desc = step.get("description") or step.get("step", "")
            if not action and desc:
                if any(tok in desc for tok in ("输入", "填写", "填入")) or "fill" in desc.lower():
                    action = "fill"
                elif any(tok in desc for tok in ("点击", "单击")) or "click" in desc.lower():
                    action = "click"

            if not locator and action in {"fill", "input", "type"} and fill_expr:
                locator = fill_expr
            elif not locator and action in {"click", "submit"} and click_expr:
                locator = click_expr
            elif not locator and desc:
                for key, val in elem_map.items():
                    if key in desc.lower():
                        locator = val
                        break
            if not locator and desc:
                if any(tok in desc for tok in ("输入", "填写", "搜索")) and fill_expr:
                    locator = fill_expr
                elif any(tok in desc for tok in ("点击", "单击")) and click_expr:
                    locator = click_expr

            def _target(loc: str) -> str:
                if loc.startswith("page."):
                    return loc
                return f'page.locator("{loc}")'

            if action == "goto" and value:
                if value.rstrip("/") != (target_url or "").rstrip("/"):
                    lines.append(f'    page.goto("{value}")')
            elif action == "fill" and locator:
                fill_value = value or infer_fill_value(step, case_data)
                last_fill_value = fill_value or last_fill_value
                desc_text = str(desc or "")
                last_fill_is_search = any(tok in desc_text.lower() for tok in ("搜索", "search", "查询"))
                lines.append(f'    {_target(locator)}.fill("{fill_value}")')
            elif action == "click" and locator:
                lines.append(f"    {_target(locator)}.click()")
                lines.append('    page.wait_for_load_state("domcontentloaded")')
            elif action == "verify_visible" and locator:
                lines.append(f"    expect({_target(locator)}).to_be_visible()")
            elif action == "verify_text" and locator:
                lines.append(f'    expect({_target(locator)}).to_have_text("{value}")')
            elif action == "wait":
                continue

        if last_fill_value and last_fill_is_search:
            from urllib.parse import quote
            encoded = quote(last_fill_value, safe="")
            pattern = f"{re.escape(encoded)}|{re.escape(last_fill_value)}"
            lines.append(f'    expect(page).to_have_url(re.compile(r"{pattern}"))')

        for assertion in assertions:
            if not isinstance(assertion, dict):
                continue
            atype = assertion.get("type", "")
            alocator = assertion.get("locator", "")
            aexpected = assertion.get("expected", "")
            if atype == "visible" and alocator:
                target = alocator if str(alocator).startswith("page.") else f'page.locator("{alocator}")'
                lines.append(f"    expect({target}).to_be_visible()")
            elif atype == "text" and alocator:
                lines.append(f'    expect(page.locator("{alocator}")).to_have_text("{aexpected}")')
            elif atype == "url" and not last_fill_value:
                lines.append(f'    expect(page).to_have_url("{aexpected}")')

        case_blob = " ".join(
            str((case_data or {}).get(k) or "")
            for k in ("description", "requirement", "case_name")
        ) if isinstance(case_data, dict) else ""
        if "登录成功" in case_blob and "登录成功" not in "\n".join(lines):
            lines.append('    expect(page.get_by_text("登录成功")).to_be_visible()')

        if not steps and not assertions:
            raise ValueError("无法确定稳定定位器，拒绝生成仅含 TODO 的模板脚本")

        generated = "\n".join(lines) + "\n"
        from app.agent.script.locator_builder import script_has_invalid_locators
        invalid = script_has_invalid_locators(generated)
        if invalid:
            raise ValueError(invalid)
        return generated

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
