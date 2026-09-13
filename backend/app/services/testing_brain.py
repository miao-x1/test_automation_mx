"""共享 Testing Brain：测试专家 + 项目记忆 + 代码索引 + 测试资产。

全局 Agent 与测试任务工作台共用这一层，不另建一套 AI。
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from app.knowledge.testing_expert.service import get_testing_expert
from app.services.asset_lifecycle import AssetLifecycleService
from app.services.project_indexer import ProjectIndexer
from app.services.project_memory import ProjectMemoryService

INTENT_PATHS = {
    "answer": "直接回答",
    "locate": "项目代码定位",
    "analyze_requirement": "需求分析",
    "generate_cases": "生成测试用例",
    "supplement_exception": "补充异常场景",
    "supplement_boundary": "补充边界场景",
    "check_coverage": "检查测试覆盖率",
    "optimize_cases": "优化测试用例",
    "to_automation": "转自动化测试",
    "execute": "执行测试",
    "analyze_failure": "分析失败原因",
    "create_bug": "生成缺陷",
    "generate_report": "生成测试报告",
    "full_test": "一站式全面测试",
    "create_task": "创建测试任务",
}

_ANSWER_HINTS = ("什么是", "什么叫", "解释一下", "怎么理解", "定义")
_COUNT_HINTS = ("几个", "多少", "数量", "有几")
_LOCATE_HINTS = ("哪个文件", "在哪", "定位", "代码在", "找一下", "哪段代码")
_FULL_HINTS = ("全面测试", "完整测试", "帮我测试这个项目", "帮我测这个项目", "一站式")
_CASE_HINTS = ("测试用例", "给我", "生成用例", "写用例", "出用例")
_ANALYZE_HINTS = ("分析这个需求", "分析需求", "需求分析")
_EXCEPTION_HINTS = ("异常场景", "补充异常", "异常用例")
_BOUNDARY_HINTS = ("边界场景", "补充边界", "边界用例")
_COVERAGE_HINTS = ("覆盖率", "覆盖检查", "缺什么用例")
_OPTIMIZE_HINTS = ("优化用例", "优化测试用例", "精简用例")
_AUTO_HINTS = ("转自动化", "playwright", "生成脚本", "自动化脚本")
_EXECUTE_HINTS = ("执行", "跑一下", "跑这些用例", "开始测试")
_FAIL_HINTS = ("失败原因", "为什么失败", "分析失败", "定位失败")
_BUG_HINTS = ("生成bug", "提缺陷", "生成缺陷", "记一个bug")
_REPORT_HINTS = ("测试报告", "生成报告")
_TASK_HINTS = ("创建测试任务", "新建测试任务")


def _contains(text: str, tokens: tuple[str, ...]) -> bool:
    low = text.lower()
    return any((token.lower() in low) if token.isascii() else (token in text) for token in tokens)


def classify_intent(question: str, workspace: str = "understand") -> str:
    text = (question or "").strip()
    if _contains(text, _FULL_HINTS):
        return "full_test"
    if _contains(text, _ANALYZE_HINTS):
        return "analyze_requirement"
    if _contains(text, _EXCEPTION_HINTS):
        return "supplement_exception"
    if _contains(text, _BOUNDARY_HINTS):
        return "supplement_boundary"
    if _contains(text, _COVERAGE_HINTS):
        return "check_coverage"
    if _contains(text, _OPTIMIZE_HINTS):
        return "optimize_cases"
    if _contains(text, _AUTO_HINTS):
        return "to_automation"
    if _contains(text, _FAIL_HINTS):
        return "analyze_failure"
    if _contains(text, _BUG_HINTS):
        return "create_bug"
    if _contains(text, _REPORT_HINTS):
        return "generate_report"
    if _contains(text, _TASK_HINTS):
        return "create_task"
    if _contains(text, _ANSWER_HINTS) and "测试" in text and "用例" not in text:
        return "answer"
    if _contains(text, _COUNT_HINTS):
        return "answer"
    if _contains(text, _LOCATE_HINTS):
        return "locate"
    if _contains(text, _CASE_HINTS) or ("用例" in text and any(token in text for token in ("给", "生成", "写", "出"))):
        return "generate_cases"
    if text.startswith("帮我测试") and "这个项目" not in text:
        return "create_task"
    if any(token in text for token in ("设计测试", "测试设计", "帮我设计")):
        return "analyze_requirement"
    if _contains(text, _EXECUTE_HINTS) and "测试" in text:
        return "execute"
    if workspace == "execute" and any(token in text for token in ("失败", "执行", "回归")):
        return "execute" if "失败" not in text else "analyze_failure"
    if workspace == "design" and any(token in text for token in ("用例", "场景", "测试点")):
        return "generate_cases" if "用例" in text else "analyze_requirement"
    return "locate"


def infer_module(text: str) -> str:
    raw = (text or "").strip()
    for token in ("登录", "注册", "支付", "订单", "购物车", "搜索", "权限", "上传", "密码"):
        if token in raw:
            return token
    cleaned = re.sub(r"(帮我|请|一下|这个|那个|功能|测试|用例|生成|分析|全面|项目)", "", raw)
    cleaned = cleaned.strip(" 。，、")
    return cleaned[:20] or "当前功能"


def build_professional_cases(
    module: str,
    query: str,
    case_types: Optional[list[str]] = None,
    start_index: int = 1,
) -> list[dict[str, Any]]:
    """用测试专家手册生成专业表格用例，不依赖在线 LLM。"""
    wanted = set(case_types or ["functional", "error", "boundary", "permission"])
    analysis = get_testing_expert().analyze_task(query or module)
    playbook = analysis.get("playbook") or {}
    must = list(playbook.get("must") or analysis.get("must_test") or [])
    should = list(playbook.get("should") or analysis.get("should_test") or [])
    prefix = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]", "", module).upper()[:8] or "CASE"
    rows: list[dict[str, Any]] = []

    def add(name: str, case_type: str, priority: str, steps: list[str], expected: str, data: str = ""):
        if case_type not in wanted:
            return
        idx = start_index + len(rows)
        rows.append({
            "case_code": f"TC-{prefix}-{idx:03d}",
            "module": module,
            "scenario": name,
            "case_name": name,
            "precondition": f"已进入{module}相关页面，测试数据可用。",
            "steps": [{"no": i + 1, "action": step, "data": data} for i, step in enumerate(steps)],
            "test_data": data or "使用项目已有账号/接口数据",
            "expected_result": expected,
            "priority": priority,
            "type": case_type,
            "tags": [module, case_type, priority],
            "status": "draft",
        })

    for item in must[:6]:
        add(item, "functional", "P0", [f"准备{module}前置数据", item, "核对页面与接口结果"], f"{item}成立，状态与数据一致。")
    for item in should[:4]:
        kind = "boundary" if any(token in item for token in ("边界", "超长", "空", "超时")) else "error"
        add(item, kind, "P1", [f"构造{module}异常输入", item, "观察拒绝与提示"], f"{item}被正确拒绝，不产生脏数据。")
    if "permission" in wanted:
        add(f"{module}无权限访问被拒绝", "permission", "P0", ["使用无权限账号访问", "同时打对应接口"], "页面与接口均拒绝，不泄露越权数据。")
    if not rows:
        add(f"{module}主路径可用", "functional", "P0", [f"打开{module}", "提交合法数据"], "主路径成功，结果可验证。")
    return rows


def check_case_coverage(cases: list[dict[str, Any]], query: str) -> dict[str, Any]:
    analysis = get_testing_expert().analyze_task(query)
    must = list(analysis.get("must_test") or [])
    should = list(analysis.get("should_test") or [])
    blob = " ".join(
        f"{item.get('case_name') or ''} {item.get('scenario') or ''} {item.get('type') or ''}"
        for item in cases
    )
    covered = [item for item in must if item[:6] in blob or any(token in blob for token in item.split()[:2])]
    missing = [item for item in must if item not in covered]
    types = {item.get("type") or "functional" for item in cases}
    return {
        "must_test": must,
        "should_test": should,
        "covered": covered,
        "missing": missing,
        "case_count": len(cases),
        "type_coverage": sorted(types),
        "score": round(100 * (len(covered) / len(must)), 1) if must else (100.0 if cases else 0.0),
        "advice": "先补 must 中的缺口，再按风险加 should，不要无脑堆低价值用例。" if missing else "必测项已覆盖，可按风险补异常/边界。",
    }


def cases_to_playwright(cases: list[dict[str, Any]], module: str) -> str:
    lines = [
        "import { test, expect } from '@playwright/test';",
        "",
        f"// 由测试任务「{module}」用例转换，需按项目实际选择器补全。",
        "",
    ]
    for item in cases[:12]:
        name = item.get("case_code") or item.get("case_name") or "case"
        title = item.get("case_name") or name
        lines.append(f"test('{name} {title}', async ({{ page }}) => {{")
        lines.append(f"  // 前置：{item.get('precondition') or '无'}")
        for step in item.get("steps") or []:
            if isinstance(step, dict):
                lines.append(f"  // {step.get('no')}. {step.get('action')} / {step.get('data') or ''}")
            else:
                lines.append(f"  // {step}")
        lines.append(f"  // 预期：{item.get('expected_result') or ''}")
        lines.append("  await page.goto('/');")
        lines.append("});")
        lines.append("")
    return "\n".join(lines)


class TestingBrainService:
    def __init__(self):
        self.expert = get_testing_expert()
        self.memory = ProjectMemoryService()
        self.indexer = ProjectIndexer()
        self.assets = AssetLifecycleService()

    def retrieve(
        self,
        user_id: int,
        project_id: int,
        query: str,
        test_task_id: Optional[int] = None,
        workspace: Optional[str] = None,
    ) -> dict[str, Any]:
        expert = self.expert.retrieve_for_task(query or "", top_k=5)
        memory_hits: list[dict[str, Any]] = []
        locations: list[dict[str, Any]] = []
        assets: list[dict[str, Any]] = []
        try:
            memory_hits = self.memory.search(user_id, project_id, query[:40] or "项目")
            if test_task_id:
                task_hits = [
                    item for item in memory_hits
                    if str((item.get("extra") or {}).get("test_task_id") or "") == str(test_task_id)
                ]
                if task_hits:
                    memory_hits = task_hits + [item for item in memory_hits if item not in task_hits]
        except Exception:
            memory_hits = []
        try:
            locations = self.indexer.query_index(user_id, project_id, keyword=query[:40], limit=12)
        except Exception:
            locations = []
        try:
            packed = self.assets.list_assets(user_id, keyword=query[:40], project_id=project_id, page_size=8)
            assets = packed.get("items") or []
        except Exception:
            assets = []
        return {
            "query": query,
            "workspace": workspace,
            "test_task_id": test_task_id,
            "expert": {
                "prompt": expert.get("prompt") or "",
                "cards": [{"id": item.get("id"), "title": item.get("title")} for item in (expert.get("cards") or [])[:5]],
                "playbooks": [item.get("title") for item in (expert.get("playbooks") or [])[:2]],
                "thinking": expert.get("thinking") or [],
            },
            "memory": memory_hits[:8],
            "locations": locations[:12],
            "assets": [{"id": item.get("id"), "name": item.get("name"), "stage": item.get("stage")} for item in assets[:8]],
            "context_prompt": self._context_prompt(query, expert, memory_hits, locations, test_task_id),
        }

    def answer_knowledge(self, question: str) -> dict[str, Any]:
        return self.expert.answer(question)

    def analyze(self, task: str) -> dict[str, Any]:
        return self.expert.analyze_task(task)

    @staticmethod
    def _context_prompt(
        query: str,
        expert: dict[str, Any],
        memory_hits: list[dict[str, Any]],
        locations: list[dict[str, Any]],
        test_task_id: Optional[int],
    ) -> str:
        parts = [expert.get("prompt") or ""]
        if test_task_id:
            parts.append(f"当前测试任务 ID={test_task_id}，优先使用该任务已有需求、用例和结果，不要让用户重述项目。")
        if memory_hits:
            parts.append("项目记忆：" + "；".join(f"{item.get('title')}" for item in memory_hits[:4]))
        if locations:
            parts.append("代码定位：" + "；".join(f"{item.get('name')}@{item.get('path')}" for item in locations[:4]))
        parts.append(f"用户目标：{query}")
        return "\n".join(p for p in parts if p)

    @staticmethod
    def dumps(data: Any) -> str:
        return json.dumps(data, ensure_ascii=False)
