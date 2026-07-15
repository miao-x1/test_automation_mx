"""
ReviewAgent - 用例审查Agent

职责：对生成的测试用例进行质量审查

审查维度：
1. 完整性：是否有前置条件、步骤、预期结果
2. 可执行性：步骤是否清晰可执行
3. 覆盖度：是否覆盖了主要场景
4. 规范性：命名、格式是否符合规范
"""
import json
import time as _time
from typing import Any, Dict, List, Optional
from app.core.config import settings
from app.core.logger import log
from app.agent.core.base import BaseAgent


class ReviewAgent(BaseAgent):
    """用例审查Agent"""

    agent_name = "review"

    def __init__(self):
        super().__init__()
        self.model = None
        self.system_prompt = "你是一个专业的测试用例审查专家，擅长评估用例质量并给出改进建议。"

    def execute(self, **kwargs) -> Any:
        """统一执行入口（兼容管道payload键名）"""
        cases = kwargs.get("cases") or kwargs.get("test_cases") or []
        if isinstance(cases, dict):
            cases = cases.get("cases", [])
        requirement_context = kwargs.get("requirement_context") or kwargs.get("requirement") or ""
        return self.review(cases=cases, requirement_context=requirement_context)

    async def execute_async(self, payload: Dict[str, Any], ctx=None) -> Dict[str, Any]:
        """GraphFlow兼容入口"""
        cases = payload.get("cases") or payload.get("test_cases") or []
        if isinstance(cases, dict):
            cases = cases.get("cases", [])
        requirement_context = payload.get("requirement_context") or payload.get("requirement") or ""
        result = self.review(cases=cases, requirement_context=requirement_context)
        # 适配GraphFlow下游：返回approved_cases/rejected_cases格式
        return {
            "status": "success",
            "step": "review",
            "approved_cases": result.get("reviewed_cases", []),
            "rejected_cases": [],
            "review_notes": "; ".join(result.get("issues", [])),
            "quality_score": result.get("quality_score", 0),
            "suggestions": result.get("suggestions", []),
        }

    def review(self, cases: List[Dict[str, Any]], requirement_context: str = "") -> Dict[str, Any]:
        """
        审查测试用例

        Args:
            cases: 用例列表
            requirement_context: 需求上下文

        Returns:
            {
                "reviewed_cases": [...],  # 审查后的用例（含review字段）
                "quality_score": float,   # 质量评分 0-100
                "issues": [...],          # 发现的问题
                "suggestions": [...]      # 改进建议
            }
        """
        _start = _time.time()
        log.info(f"ReviewAgent | 开始审查 | cases={len(cases)}")

        # 基础规则审查（不依赖LLM）
        issues = []
        reviewed_cases = []
        total_score = 0

        for i, case in enumerate(cases):
            case_issues = []
            score = 100

            # 完整性检查
            if not case.get("title"):
                case_issues.append("缺少用例标题")
                score -= 15
            if not case.get("steps"):
                case_issues.append("缺少测试步骤")
                score -= 20
            if not case.get("expected"):
                case_issues.append("缺少预期结果")
                score -= 20
            if not case.get("precondition"):
                case_issues.append("缺少前置条件")
                score -= 5

            # 可执行性检查
            steps = case.get("steps", "")
            if steps and len(steps) < 10:
                case_issues.append("步骤描述过于简短")
                score -= 10

            # 优先级检查
            priority = case.get("priority", "medium")
            if priority not in ("high", "medium", "low"):
                case_issues.append(f"无效优先级: {priority}")
                score -= 5

            total_score += max(score, 0)

            reviewed_case = {**case, "review": {"score": max(score, 0), "issues": case_issues}}
            reviewed_cases.append(reviewed_case)
            issues.extend([f"用例{i+1}: {iss}" for iss in case_issues])

        quality_score = total_score / len(cases) if cases else 0

        # 尝试LLM审查（可选）
        suggestions = []
        if cases and requirement_context and settings.QWEN_API_KEY:
            try:
                suggestions = self._llm_review(cases[:5], requirement_context)
            except Exception as e:
                log.warning(f"ReviewAgent | LLM审查失败: {e}")

        self.emit("reviewed", {"quality_score": quality_score, "issue_count": len(issues)})

        _elapsed = _time.time() - _start
        log.info(f"ReviewAgent | 审查完成 | score={quality_score:.1f}, issues={len(issues)} | 耗时={_elapsed:.2f}s")

        return {
            "reviewed_cases": reviewed_cases,
            "quality_score": quality_score,
            "issues": issues,
            "suggestions": suggestions,
        }

    def _llm_review(self, cases: List[Dict], requirement_context: str) -> List[str]:
        """LLM审查（可选增强）"""
        import httpx

        cases_text = json.dumps(cases, ensure_ascii=False, indent=2)[:3000]
        prompt = f"""请审查以下测试用例，给出3-5条改进建议（每条一行，简洁明了）：

需求：{requirement_context[:1000]}

用例：{cases_text}

只输出建议列表，不要其他内容。"""

        api_key = settings.QWEN_API_KEY
        url = settings.QWEN_API_URL
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": settings.QWEN_MODEL.replace("-vl-plus", "-plus").replace("-vl-max", "-max"),
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
        }

        response = httpx.post(url, json=payload, headers=headers, timeout=30)
        result = response.json()

        if "choices" in result:
            content = result["choices"][0]["message"]["content"]
            return [line.strip().lstrip("0123456789.-) ") for line in content.split("\n") if line.strip()]

        return []
