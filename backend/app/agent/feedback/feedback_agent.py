"""
FeedbackAgent - 用户反馈分析Agent

职责：
- 分析脚本执行失败原因
- 生成修复建议，供重新生成脚本时使用
- 提取反馈上下文，传递给RequirementFlowService
一个把"执行失败日志 + 用户反馈 + 脚本问题"
转换成"可用于重生成脚本的修复Prompt"的闭环模块。
"""
import json
import time as _time
from typing import Dict, Any, Optional
from app.core.logger import log
from app.core.config import settings
from app.core.llm import call_llm
from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability


class FeedbackAgent(NewBaseAgent):
    """用户反馈分析Agent"""

    agent_name = "feedback_agent"
    display_name = "反馈分析Agent"
    description = "分析脚本执行失败原因，生成修复建议与反馈上下文，供重新生成脚本使用"
    capabilities = [AgentCapability.FEEDBACK]

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)
        self.agent_type = "feedback"
        self.model = None
        self.system_prompt = None

    def _call_llm(self, prompt: str) -> str:
        """调用LLM API进行失败分析"""
        _start = _time.time()
        log.info(f"[DEBUG] 开始：FeedbackAgent._call_llm | prompt_length={len(prompt)}")

        content = call_llm(
            "你是一个资深的自动化测试工程师，擅长分析Playwright脚本执行失败的原因并给出修复建议。",
            prompt,
            temperature=0.2,
        )

        _elapsed = _time.time() - _start
        log.info(f"[DEBUG] 结束：FeedbackAgent._call_llm | content_length={len(content)} | 耗时：{_elapsed:.2f}s")

        return content

    def _build_analysis_prompt(
        self,
        requirement: str,
        script_content: str,
        exec_result: Dict[str, Any],
    ) -> str:
        """构建LLM失败分析提示词"""
        log_content = (exec_result.get("log_content", "") or "")[-3000:]
        error_message = (exec_result.get("error_message", "") or "")[:500]
        script_snippet = (script_content or "")[-2000:]
        failed_count = exec_result.get("failed_count", 0)
        success_count = exec_result.get("success_count", 0)

        return f"""请分析以下自动化测试脚本执行失败的原因，并给出修复建议。

原始需求：{requirement[:500]}

执行结果：
- 成功步骤数：{success_count}
- 失败步骤数：{failed_count}
- 错误信息：{error_message}

执行日志（最后3000字符）：
{log_content}

脚本内容（最后2000字符）：
{script_snippet}

请按以下JSON格式输出：
{{
    "failure_reasons": ["原因1", "原因2", ...],
    "fix_suggestions": ["建议1", "建议2", ...],
    "failed_steps": ["失败步骤1", "失败步骤2", ...],
    "root_cause": "根本原因总结",
    "severity": "high | medium | low"
}}

要求：
1. failure_reasons：具体的失败原因，不要笼统描述
2. fix_suggestions：可操作的修复建议，对应每个失败原因
3. failed_steps：从日志中提取的具体失败步骤
4. root_cause：一句话总结根本原因
5. 只输出JSON，不要输出其他内容"""

    def _parse_llm_analysis(self, raw: str) -> Dict[str, Any]:
        """解析LLM返回的失败分析JSON"""
        try:
            cleaned = raw.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            data = json.loads(cleaned)
            return {
                "failure_reasons": data.get("failure_reasons", []),
                "fix_suggestions": data.get("fix_suggestions", []),
                "failed_steps": data.get("failed_steps", []),
                "root_cause": data.get("root_cause", ""),
                "severity": data.get("severity", "medium"),
            }
        except (json.JSONDecodeError, Exception) as e:
            log.warning(f"FeedbackAgent LLM分析JSON解析失败: {e}, raw={raw[:200]}")
            return {}

    def analyze_failure(
        self,
        requirement: str,
        script_content: str,
        exec_result: Dict[str, Any],
        user_comment: str = "",
        score: int = 0,
    ) -> Dict[str, Any]:
        """
        分析脚本执行失败原因

        优先使用LLM进行深度分析，失败时回退到规则分析。

        Args:
            requirement: 原始需求
            script_content: 生成的脚本内容
            exec_result: 执行结果 {status, error_message, log_content, failed_count, success_count}
            user_comment: 用户反馈评论
            score: 用户评分

        Returns:
            {
                "failure_reasons": [...],
                "fix_suggestions": [...],
                "failed_steps": [...],
                "feedback_context": "...",
                "root_cause": "...",
                "severity": "..."
            }
        """
        log.info(f"FeedbackAgent.analyze_failure | 需求: {requirement[:30]}... | 评分: {score}")

        _start = _time.time()
        log.info(f"[DEBUG] 开始：FeedbackAgent.analyze_failure | score={score}, failed_count={exec_result.get('failed_count', 0)}")

        failure_reasons = []
        fix_suggestions = []
        failed_steps = []
        root_cause = ""
        severity = "medium"

        log_content = exec_result.get("log_content", "") or ""
        error_message = exec_result.get("error_message", "") or ""
        failed_count = exec_result.get("failed_count", 0)
        success_count = exec_result.get("success_count", 0)

        # 1. 尝试LLM深度分析
        try:
            prompt = self._build_analysis_prompt(requirement, script_content, exec_result)
            raw = self._call_llm(prompt)
            llm_analysis = self._parse_llm_analysis(raw)
            if llm_analysis:
                failure_reasons = llm_analysis.get("failure_reasons", [])
                fix_suggestions = llm_analysis.get("fix_suggestions", [])
                failed_steps = llm_analysis.get("failed_steps", [])
                root_cause = llm_analysis.get("root_cause", "")
                severity = llm_analysis.get("severity", "medium")
                log.info(f"FeedbackAgent | LLM分析成功 | 原因: {len(failure_reasons)}, 建议: {len(fix_suggestions)}")
        except Exception as e:
            log.warning(f"FeedbackAgent | LLM分析失败，回退到规则分析 | error={e}")

        # 2. 规则分析补充（LLM未覆盖或失败时）
        if not failure_reasons:
            if error_message:
                failure_reasons.append(f"执行错误: {error_message[:200]}")

            for line in log_content.split("\n"):
                line_lower = line.lower()
                if "fail" in line_lower or "error" in line_lower or "timeout" in line_lower:
                    failed_steps.append(line.strip()[:200])
                if len(failed_steps) >= 5:
                    break

            if script_content:
                script_issues = self._analyze_script_issues(script_content)
                failure_reasons.extend(script_issues.get("reasons", []))
                fix_suggestions.extend(script_issues.get("suggestions", []))

        # 3. 用户反馈补充
        if user_comment:
            failure_reasons.append(f"用户反馈: {user_comment[:200]}")

        if score <= 2:
            fix_suggestions.append("脚本整体质量较差，建议重新生成并优先修复失败步骤")
        elif score <= 3:
            fix_suggestions.append("脚本部分步骤存在问题，建议针对性修复失败步骤")

        # 4. 生成反馈上下文
        feedback_context = self._build_feedback_context(
            requirement=requirement,
            failure_reasons=failure_reasons,
            fix_suggestions=fix_suggestions,
            failed_steps=failed_steps,
            user_comment=user_comment,
        )

        result = {
            "failure_reasons": failure_reasons[:5],
            "fix_suggestions": fix_suggestions[:5],
            "failed_steps": failed_steps[:5],
            "feedback_context": feedback_context,
            "root_cause": root_cause,
            "severity": severity,
            "score": score,
            "failed_count": failed_count,
            "success_count": success_count,
        }

        _elapsed = _time.time() - _start
        log.info(
            f"FeedbackAgent.analyze_failure | 分析完成 | "
            f"原因: {len(failure_reasons)} | 建议: {len(fix_suggestions)} | "
            f"失败步骤: {len(failed_steps)} | 耗时: {_elapsed:.2f}s"
        )

        return result

    def _analyze_script_issues(self, script_content: str) -> Dict[str, Any]:
        """分析脚本中的常见问题"""
        reasons = []
        suggestions = []

        # 检查硬编码等待
        if "wait_for_timeout" in script_content:
            reasons.append("脚本使用了硬编码等待(wait_for_timeout)，可能导致时序问题")
            suggestions.append("建议使用wait_for_load_state或wait_for_selector替代硬编码等待")

        # 检查缺少断言
        assert_count = script_content.count("expect(") + script_content.count("assert ")
        if assert_count == 0:
            reasons.append("脚本缺少断言验证，无法确认操作结果")
            suggestions.append("建议添加expect断言验证每个关键步骤的结果")

        # 检查定位器质量
        if 'page.get_by_text("' in script_content or "page.get_by_role(" in script_content:
            reasons.append("脚本使用了语义定位器(get_by_text/get_by_role)，可能不够稳定")
            suggestions.append("建议使用CSS选择器或XPath定位器，更加精确和稳定")

        # 检查是否有导航步骤
        if "page.goto" not in script_content and "page.url" not in script_content:
            reasons.append("脚本缺少页面导航步骤(page.goto)")
            suggestions.append("建议在脚本开头添加page.goto导航到目标页面")

        return {"reasons": reasons, "suggestions": suggestions}

    def _build_feedback_context(
        self,
        requirement: str,
        failure_reasons: list,
        fix_suggestions: list,
        failed_steps: list,
        user_comment: str,
    ) -> str:
        """构建反馈上下文字符串，用于注入重新生成的Prompt"""
        parts = [f"原始需求: {requirement}"]

        if failure_reasons:
            parts.append("失败原因:")
            for i, r in enumerate(failure_reasons[:3], 1):
                parts.append(f"  {i}. {r}")

        if failed_steps:
            parts.append("失败步骤:")
            for i, s in enumerate(failed_steps[:3], 1):
                parts.append(f"  {i}. {s}")

        if fix_suggestions:
            parts.append("修复建议:")
            for i, s in enumerate(fix_suggestions[:3], 1):
                parts.append(f"  {i}. {s}")

        if user_comment:
            parts.append(f"用户反馈: {user_comment}")

        parts.append("请优先修复上述失败步骤，生成更稳定可靠的脚本。")

        return "\n".join(parts)
