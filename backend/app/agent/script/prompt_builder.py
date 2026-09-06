"""
PromptBuilder - 增强型脚本生成Prompt构建器

根据StrategyAgent选择的策略，构建包含以下特性的Prompt：
1. 优先定位器：按稳定性排序使用定位器
2. 失败降级：每个步骤提供备选定位策略
3. 多页面切换：支持Graph业务流中的页面导航
4. 重试策略：生成自动重试逻辑

支持输出格式：
- Midscene: AI驱动的视觉测试脚本
- Playwright: 标准Playwright脚本
- YAML: 声明式测试配置
"""
import json
from typing import Dict, Any, List, Optional
from app.agent.script.strategy_agent import Strategy, StrategyResult
from app.core.logger import log


class PromptBuilder:
    """增强型脚本生成Prompt构建器"""

    # ==================== Midscene Prompt ====================

    @staticmethod
    def build_midscene_prompt(
        case_data: Dict[str, Any],
        elements: List[Dict],
        target_url: str = "",
        graph_business_flow: List[Dict] = None,
        strategy: StrategyResult = None,
        retry_count: int = 2,
    ) -> tuple:
        """构建Midscene脚本生成Prompt"""
        strategy = strategy or StrategyResult()

        elements_ctx = PromptBuilder._build_elements_with_priority(elements, strategy)
        flow_ctx = PromptBuilder._build_flow_context(graph_business_flow)
        retry_ctx = PromptBuilder._build_retry_strategy(retry_count, strategy)

        case_name = case_data.get("case_name", "unnamed_test")
        description = case_data.get("description", "")
        steps = case_data.get("steps", [])

        system_prompt = """你是一个专业的Midscene.js测试脚本工程师。Midscene是AI驱动的UI自动化测试框架，使用自然语言描述操作步骤，AI自动识别和操作页面元素。

核心特点：
- 使用 aiAction() 执行自然语言描述的操作
- 使用 aiQuery() 查询页面元素
- 使用 aiAssert() 进行AI驱动的断言
- 支持自动重试和降级策略

脚本模板：
```javascript
import { AIContext, createAIPage } from '@midscene/web';

const ai = createAIPage(page);

// 带重试的操作
await ai.aiAction('操作描述', { retry: 2, timeout: 5000 });

// 查询元素
const result = await ai.aiQuery('查询描述');

// AI断言
await ai.aiAssert('断言描述');
```

要求：
1. 使用自然语言描述每个操作步骤
2. 为关键步骤添加重试策略
3. 添加降级定位器注释
4. 只输出JavaScript脚本代码"""

        user_prompt = f"""请根据以下信息生成Midscene.js测试脚本。

目标URL: {target_url}
用例名称: {case_name}
用例描述: {description}

测试步骤:
{json.dumps(steps, ensure_ascii=False, indent=2)}

{elements_ctx}

{flow_ctx}

{retry_ctx}

策略: {strategy.primary.value}（置信度: {strategy.confidence:.0%}）
降级链: {' → '.join(s.value for s in strategy.degradation_chain)}

请生成完整的Midscene.js测试脚本，只输出代码。"""

        return system_prompt, user_prompt

    # ==================== Playwright Prompt (增强版) ====================

    @staticmethod
    def build_playwright_prompt(
        case_data: Dict[str, Any],
        elements: List[Dict],
        target_url: str = "",
        history_scripts: List[Dict] = None,
        graph_business_flow: List[Dict] = None,
        strategy: StrategyResult = None,
        retry_count: int = 2,
        feedback_context: str = "",
    ) -> tuple:
        """构建增强版Playwright脚本生成Prompt"""
        strategy = strategy or StrategyResult()

        elements_ctx = PromptBuilder._build_elements_with_priority(elements, strategy)
        history_ctx = PromptBuilder._build_history_context(history_scripts or [])
        flow_ctx = PromptBuilder._build_flow_context(graph_business_flow)
        retry_ctx = PromptBuilder._build_retry_strategy(retry_count, strategy)
        degradation_ctx = PromptBuilder._build_degradation_hints(elements, strategy)

        case_name = case_data.get("case_name", "unnamed_test")
        description = case_data.get("description", "")
        steps = case_data.get("steps", [])
        assertions = case_data.get("assertions", [])

        feedback_section = ""
        if feedback_context:
            feedback_section = f"\n⚠️ 用户反馈与修复要求:\n{feedback_context}"

        validated_exprs = [
            e.get("playwright_expr")
            for e in (elements or [])
            if isinstance(e, dict) and e.get("locator_validated") and e.get("playwright_expr")
        ]
        validated_rule = ""
        if validated_exprs:
            validated_rule = (
                "\n已验证定位器（必须原样写入脚本，禁止改写、禁止编造 fallback）:\n"
                + "\n".join(f"- {expr}" for expr in validated_exprs)
                + "\n禁止使用未验证的 get_by_role/get_by_placeholder。禁止 safe_click 多策略猜测。\n"
            )

        system_prompt = f"""你是一个专业的Playwright测试脚本工程师。生成高质量、稳定的自动化测试脚本。

核心原则：
1. 优先使用稳定定位器（data-testid > aria-label > placeholder > label > role+name > 稳定CSS/id > text > xpath）
2. 每个操作步骤必须包含失败降级逻辑
3. 多页面场景使用正确的页面切换模式
4. 关键步骤添加自动重试
5. 当前策略: {strategy.primary.value}（置信度: {strategy.confidence:.0%}）
{validated_rule}

脚本结构模板：
```python
import re
from playwright.sync_api import Page, expect

def test_xxx(page: Page):
    # 导航到目标页面
    page.goto("URL")
    page.wait_for_load_state("networkidle")

    # 带降级的元素定位
    def safe_click(page, **locators):
        \"\"\"按优先级尝试定位器，失败后降级\"\"\"
        for strategy_name, locator_value in locators.items():
            try:
                if strategy_name == "test_id":
                    page.get_by_test_id(locator_value).click(timeout=3000)
                    return
                elif strategy_name == "css":
                    page.locator(locator_value).click(timeout=3000)
                    return
                elif strategy_name == "xpath":
                    page.locator(f"xpath={{}}".format(locator_value)).click(timeout=3000)
                    return
            except Exception:
                continue
        raise Exception(f"所有定位器均失败: {{locators}}")

    # 带重试的操作
    for attempt in range({retry_count}):
        try:
            # 操作步骤
            break
        except Exception as e:
            if attempt == {retry_count - 1}:
                raise
            page.wait_for_timeout(1000)
```"""

        user_prompt = f"""请根据以下信息生成增强版Playwright脚本。

目标URL: {target_url}
用例名称: {case_name}
用例描述: {description}

测试步骤:
{json.dumps(steps, ensure_ascii=False, indent=2)}

断言:
{json.dumps(assertions, ensure_ascii=False, indent=2)}

{elements_ctx}

{degradation_ctx}

{flow_ctx}

{history_ctx}

{retry_ctx}
{feedback_section}

请生成完整的Playwright Python脚本，只输出代码，不要markdown包裹。"""

        return system_prompt, user_prompt

    # ==================== YAML Prompt ====================

    @staticmethod
    def build_yaml_prompt(
        case_data: Dict[str, Any],
        elements: List[Dict],
        target_url: str = "",
        graph_business_flow: List[Dict] = None,
        strategy: StrategyResult = None,
    ) -> tuple:
        """构建YAML脚本生成Prompt"""
        strategy = strategy or StrategyResult()

        elements_ctx = PromptBuilder._build_elements_with_priority(elements, strategy)
        flow_ctx = PromptBuilder._build_flow_context(graph_business_flow)

        case_name = case_data.get("case_name", "unnamed_test")
        steps = case_data.get("steps", [])

        system_prompt = """你是一个YAML测试配置生成工程师。生成声明式测试配置，格式如下：

```yaml
name: 测试名称
target: 目标URL
steps:
  - name: 步骤描述
    action: click/input/wait/navigate/assert
    locator:
      primary: css=#id
      fallback: xpath=//button
    value: 输入值（仅input需要）
    retry: 2
    timeout: 5000
```

要求：每个步骤提供primary和fallback定位器，支持retry字段。"""

        user_prompt = f"""请生成YAML测试配置。

目标URL: {target_url}
用例名称: {case_name}

测试步骤:
{json.dumps(steps, ensure_ascii=False, indent=2)}

{elements_ctx}

{flow_ctx}

策略: {strategy.primary.value}
请生成完整的YAML配置，只输出YAML内容。"""

        return system_prompt, user_prompt

    # ==================== 内部方法 ====================

    @staticmethod
    def _build_elements_with_priority(elements: List[Dict], strategy: StrategyResult) -> str:
        """构建带优先级排序的元素上下文"""
        if not elements:
            return "（暂无页面元素信息）"

        lines = ["相关页面元素（按定位器稳定性排序，必须优先使用）:"]
        validated = [e for e in elements if isinstance(e, dict) and e.get("locator_validated")]
        if validated:
            lines.append("以下 playwright_expr 已在真实页面验证，必须原样使用：")
        for i, elem in enumerate(elements[:20], 1):
            name = elem.get("element_name", elem.get("name", ""))
            etype = elem.get("element_type", elem.get("type", ""))

            # 按优先级列出可用定位器
            locators = []
            for loc_type in strategy.locator_priority:
                val = elem.get(loc_type, "")
                if not val and loc_type == "css_selector":
                    val = elem.get("css", elem.get("css_selector", ""))
                if val:
                    locators.append(f"{loc_type}={val}")

            expr = elem.get("playwright_expr") or ""
            if expr:
                locators.insert(0, f"playwright={expr}")
            locator_str = " | ".join(locators) if locators else "无稳定定位器"
            page = elem.get("page_name", elem.get("page_url", ""))
            page_str = f" | 页面: {page}" if page else ""

            lines.append(f"  {i}. {name} ({etype}) | 定位器: {locator_str}{page_str}")

        return "\n".join(lines)

    @staticmethod
    def _build_degradation_hints(elements: List[Dict], strategy: StrategyResult) -> str:
        """构建降级提示"""
        if any(isinstance(e, dict) and e.get("locator_validated") for e in (elements or [])):
            return "定位器已在真实页面验证。禁止编造 fallback，必须原样使用 playwright_expr。"
        if not strategy.degradation_chain or len(strategy.degradation_chain) <= 1:
            return ""

        lines = ["定位器降级策略（主定位器失败时按顺序尝试）:"]
        for i, elem in enumerate(elements[:10], 1):
            name = elem.get("element_name", elem.get("name", ""))
            fallbacks = []

            for loc_type in strategy.locator_priority:
                val = elem.get(loc_type, "")
                if not val and loc_type == "css_selector":
                    val = elem.get("css", elem.get("css_selector", ""))
                if val:
                    fallbacks.append(f"{loc_type}={val}")

            if len(fallbacks) > 1:
                lines.append(f"  {name}: {' → '.join(fallbacks)}")

        return "\n".join(lines) if len(lines) > 1 else ""

    @staticmethod
    def _build_flow_context(graph_business_flow: List[Dict]) -> str:
        """构建多页面业务流上下文"""
        if not graph_business_flow:
            return ""

        lines = ["多页面业务流（注意页面切换）:"]
        for i, flow in enumerate(graph_business_flow[:5], 1):
            page_title = flow.get("page_title", "")
            page_url = flow.get("page_url", "")
            lines.append(f"  页面{i}: {page_title} ({page_url})")

            nav_targets = flow.get("navigation_targets", [])
            for nt in nav_targets[:3]:
                trigger = nt.get("trigger_element", "")
                target = nt.get("target_page_title", "")
                lines.append(f"    → 点击[{trigger}] 跳转到 {target}")

        return "\n".join(lines)

    @staticmethod
    def _build_history_context(scripts: List[Dict]) -> str:
        """构建历史脚本上下文"""
        if not scripts:
            return ""

        lines = ["历史相似脚本（参考代码风格）:"]
        for i, script in enumerate(scripts[:2], 1):
            name = script.get("script_name", "")
            content = script.get("script_content", "")
            score = script.get("score", 0)
            preview = content[:400] if content else ""
            lines.append(f"--- 脚本{i}: {name} (相似度: {score}) ---\n{preview}\n---")

        return "\n\n".join(lines)

    @staticmethod
    def _build_retry_strategy(retry_count: int, strategy: StrategyResult) -> str:
        """构建重试策略说明"""
        lines = [f"重试策略: 关键步骤最多重试{retry_count}次"]

        if strategy.degradation_chain:
            chain_str = " → ".join(s.value.upper() for s in strategy.degradation_chain)
            lines.append(f"降级链: {chain_str}")

        lines.append("重试间隔: 1秒（首次）→ 2秒（第二次）→ 3秒（第三次）")
        lines.append("重试条件: 定位器超时、元素不可见、网络错误")

        return "\n".join(lines)
