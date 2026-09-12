"""全局项目级 Agent：总管入口。按用户目标选最短路径，产物落到测试资产。"""
from __future__ import annotations

import re
from typing import Any, Optional

from app.db.database import SessionLocal
from app.models.execution_record import ExecutionRecord
from app.services.asset_lifecycle import AssetLifecycleService
from app.services.project_indexer import ProjectIndexer
from app.services.project_memory import ProjectMemoryService
from app.services.testing_brain import (
    INTENT_PATHS,
    TestingBrainService,
    build_professional_cases,
    classify_intent,
    infer_module,
)

STOP = {"的", "了", "在", "哪里", "哪个", "什么", "如何", "怎么", "帮我", "一下", "这个", "那个", "功能", "请", "吗", "呢", "帮"}
SYNONYMS = {
    "登录": ["login", "auth", "authenticate", "signin", "LoginPage"],
    "注册": ["register", "signup"],
    "接口": ["api", "router", "endpoint"],
    "用户": ["user", "auth"],
    "测试": ["test", "spec"],
    "支付": ["pay", "payment", "checkout"],
    "订单": ["order"],
}


def _keywords(text: str) -> list[str]:
    raw = text or ""
    out: list[str] = []
    for key, syns in SYNONYMS.items():
        if key in raw:
            out.append(key)
            out.extend(syns)
    for word in re.findall(r"[A-Za-z_]{2,}", raw):
        if word.lower() in STOP:
            continue
        if word not in out:
            out.append(word)
    return out[:10]


class ProjectAgentService:
    def __init__(self):
        self.indexer = ProjectIndexer()
        self.memory = ProjectMemoryService()
        self.assets = AssetLifecycleService()
        self.brain = TestingBrainService()
        self.tasks = None

    def _task_service(self):
        if self.tasks is None:
            from app.services.project_test_task import ProjectTestTaskService
            self.tasks = ProjectTestTaskService()
        return self.tasks

    def ask(
        self,
        user_id: int,
        project_id: int,
        question: str,
        workspace: str = "understand",
        confirm: bool = False,
        test_task_id: Optional[int] = None,
    ) -> dict[str, Any]:
        question = (question or "").strip()
        if not question:
            raise ValueError("请输入问题")
        intent = classify_intent(question, workspace)
        keywords = _keywords(question)
        self.brain.indexer = self.indexer
        self.brain.memory = self.memory
        self.brain.assets = self.assets
        brain = self.brain.retrieve(
            user_id, project_id, question,
            test_task_id=test_task_id, workspace=workspace,
        )
        unique = self._unique_hits(brain.get("locations") or [], keywords, user_id, project_id, question)
        memory_hits = brain.get("memory") or []
        actions: list[dict[str, Any]] = []

        if intent == "answer":
            knowledge = self.brain.answer_knowledge(question)
            answer = (
                "已选择最短路径：直接回答。没有进入完整测试流程。\n\n"
                + (knowledge.get("answer") or "")
            )
            actions.append({"type": "answer", "used_cards": knowledge.get("used_cards") or []})
        elif intent == "analyze_requirement":
            actions.extend(self._analyze(user_id, project_id, question, test_task_id))
            answer = self._compose(question, workspace, unique, memory_hits, actions, intent)
        elif intent in {
            "generate_cases", "supplement_exception", "supplement_boundary",
            "check_coverage", "optimize_cases", "to_automation", "execute",
            "analyze_failure", "create_bug", "generate_report", "create_task", "full_test",
        }:
            actions.extend(self._route_work(user_id, project_id, question, intent, unique, test_task_id))
            answer = self._compose(question, workspace, unique, memory_hits, actions, intent)
        elif workspace == "design" and any(token in question for token in ("测试", "用例", "场景", "设计")) and intent == "locate":
            actions.extend(self._design(user_id, project_id, question, unique))
            answer = self._compose(question, workspace, unique, memory_hits, actions, "analyze_requirement")
            intent = "analyze_requirement"
        elif workspace == "execute":
            actions.extend(self._execute(user_id, project_id, question))
            answer = self._compose(question, workspace, unique, memory_hits, actions, intent)
        else:
            answer = self._compose(question, workspace, unique, memory_hits, actions, intent)

        self.memory.remember(
            user_id, project_id, kind="question", title=question[:80],
            content=question, workspace=workspace, extra={"intent": intent},
            test_task_id=test_task_id,
        )
        self.memory.remember(
            user_id, project_id, kind="message", title=question[:80],
            content=question, workspace=workspace, role="user",
            extra={"intent": intent}, test_task_id=test_task_id,
        )
        self.memory.remember(
            user_id, project_id, kind="message", title=f"回答：{question[:40]}",
            content=answer, workspace=workspace, role="assistant",
            extra={"hits": [{"path": i["path"], "name": i["name"], "line_start": i.get("line_start")} for i in unique[:8]], "intent": intent},
            test_task_id=test_task_id,
        )
        if unique:
            top = unique[0]
            self.memory.remember(
                user_id, project_id, kind="conclusion",
                title=f"{keywords[0] if keywords else question} 代码定位",
                content=f"{top['name']} @ {top['path']}:{top.get('line_start') or 1}",
                workspace=workspace,
                extra={"path": top["path"], "name": top["name"], "line_start": top.get("line_start")},
                test_task_id=test_task_id,
            )
            self.memory.remember(
                user_id, project_id, kind="focus",
                title=top.get("module") or top["path"],
                content=f"用户关注 {top['name']}（{top['path']}）",
                workspace=workspace, test_task_id=test_task_id,
            )
        if confirm:
            self.memory.remember(
                user_id, project_id, kind="confirmed",
                title=question[:80], content=answer, workspace=workspace,
                test_task_id=test_task_id,
            )
        return {
            "answer": answer,
            "workspace": workspace,
            "project_id": project_id,
            "intent": intent,
            "path": INTENT_PATHS.get(intent, intent),
            "test_task_id": test_task_id or next((a.get("test_task_id") for a in actions if a.get("test_task_id")), None),
            "locations": unique[:12],
            "memory_used": memory_hits[:6],
            "brain": brain.get("expert") or {},
            "actions": actions,
        }

    def _unique_hits(
        self,
        locations: list[dict[str, Any]],
        keywords: list[str],
        user_id: int,
        project_id: int,
        question: str,
    ) -> list[dict[str, Any]]:
        hits = list(locations)
        if not hits:
            for word in keywords or [question]:
                try:
                    hits.extend(self.indexer.query_index(user_id, project_id, keyword=word, limit=12))
                except Exception:
                    continue
        seen = set()
        unique = []
        for item in hits:
            key = (item.get("kind"), item.get("path"), item.get("name"), item.get("line_start"))
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    def _route_work(
        self,
        user_id: int,
        project_id: int,
        question: str,
        intent: str,
        hits: list[dict[str, Any]],
        test_task_id: Optional[int],
    ) -> list[dict[str, Any]]:
        tasks = self._task_service()
        module = infer_module(question)
        actions: list[dict[str, Any]] = []
        task = None
        try:
            if test_task_id:
                task = tasks.get_workspace(user_id, project_id, test_task_id)
            elif intent in {"create_task", "full_test", "generate_cases", "analyze_requirement"}:
                task = tasks.create_task(
                    user_id, project_id,
                    name=module if intent != "full_test" else "全项目测试",
                    requirement_text=question,
                    focus=module,
                )
            if task and intent != "create_task":
                op = "analyze" if intent in {"full_test", "analyze_requirement"} else intent
                if intent == "full_test":
                    analyzed = tasks.operate(user_id, project_id, task["id"], "analyze", {"query": question})
                    generated = tasks.operate(user_id, project_id, task["id"], "generate_cases", {"query": question})
                    coverage = tasks.operate(user_id, project_id, task["id"], "check_coverage", {"query": question})
                    actions.append({
                        "type": "full_test",
                        "test_task_id": task["id"],
                        "path": f"/test-tasks/{task['id']}",
                        "analysis": analyzed.get("analysis"),
                        "cases": generated.get("cases") or [],
                        "coverage": coverage.get("coverage"),
                        "assets": (analyzed.get("assets") or []) + (generated.get("assets") or []) + (coverage.get("assets") or []),
                    })
                else:
                    result = tasks.operate(user_id, project_id, task["id"], op, {"query": question})
                    actions.append({
                        "type": op,
                        "test_task_id": task["id"],
                        "path": f"/test-tasks/{task['id']}",
                        **{k: result.get(k) for k in ("cases", "coverage", "script", "execution", "diagnosis", "bug", "report", "assets", "analysis", "strategy") if result.get(k) is not None},
                    })
            elif task:
                actions.append({"type": "create_task", "test_task_id": task["id"], "path": f"/test-tasks/{task['id']}", "task": task})
        except Exception:
            if intent in {"generate_cases", "full_test"}:
                cases = build_professional_cases(module, question)
                created = self._design(user_id, project_id, question, hits)
                actions.append({"type": "generated_cases", "cases": cases})
                actions.extend(created)
            elif intent == "analyze_requirement":
                actions.extend(self._analyze(user_id, project_id, question, test_task_id))
            else:
                actions.extend(self._design(user_id, project_id, question, hits))
        return actions

    def _analyze(self, user_id: int, project_id: int, question: str, test_task_id: Optional[int]) -> list[dict[str, Any]]:
        analysis = self.brain.analyze(question)
        content = (
            f"目标：{infer_module(question)}\n"
            f"必测：{'；'.join((analysis.get('must_test') or [])[:5])}\n"
            f"按风险补充：{'；'.join((analysis.get('should_test') or [])[:4])}\n"
            f"思维：{'；'.join((analysis.get('thinking') or [])[:3])}"
        )
        created = self.assets.create_asset(
            user_id,
            name=f"{infer_module(question)} 需求分析",
            stage="01_analysis",
            category="测试范围",
            content=content,
            source="ai",
            project_id=project_id,
            ref_type="requirement",
            ref_id=test_task_id or 0,
        )
        self.memory.remember(
            user_id, project_id, kind="test_design",
            title=created.get("name") or "需求分析",
            content=content, workspace="design",
            extra={"asset_id": created.get("id"), "test_task_id": test_task_id},
            test_task_id=test_task_id,
        )
        return [{"type": "analyze_requirement", "analysis": analysis, "asset": created, "test_task_id": test_task_id}]

    def _design(self, user_id: int, project_id: int, question: str, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not any(token in question for token in ("测试", "用例", "场景", "设计")):
            return []
        loc = hits[0] if hits else None
        name = loc["name"] if loc else question[:20]
        content = (
            f"基于已索引代码设计测试。\n"
            f"目标：{name}\n"
            f"文件：{loc['path'] if loc else '未定位'}\n"
            f"行号：{loc.get('line_start') if loc else '-'}\n"
            f"建议覆盖：正常路径、错误凭证、空输入、权限异常。"
        )
        created = self.assets.create_asset(
            user_id,
            name=f"{name} 测试点",
            stage="03_design",
            category="测试点",
            content=content,
            source="ai",
            project_id=project_id,
        )
        self.memory.remember(
            user_id, project_id, kind="test_design",
            title=created.get("name") or name,
            content=content, workspace="design",
            extra={"asset_id": created.get("id"), "path": loc["path"] if loc else None},
        )
        return [{"type": "create_test_design", "asset": created}]

    def _execute(self, user_id: int, project_id: int, question: str) -> list[dict[str, Any]]:
        db = SessionLocal()
        try:
            q = db.query(ExecutionRecord).filter(ExecutionRecord.user_id == user_id)
            if hasattr(ExecutionRecord, "project_id"):
                q = q.filter((ExecutionRecord.project_id == project_id) | (ExecutionRecord.project_id.is_(None)))
            if any(token in question for token in ("失败", "fail", "错误")):
                q = q.filter(ExecutionRecord.status == "failed")
            rows = q.order_by(ExecutionRecord.id.desc()).limit(8).all()
            items = []
            for row in rows:
                item = {
                    "id": row.id,
                    "status": row.status,
                    "error": getattr(row, "error_message", None),
                    "report_path": getattr(row, "report_path", None),
                }
                items.append(item)
                self.memory.remember(
                    user_id, project_id, kind="test_execution",
                    title=f"执行 #{row.id}",
                    content=f"{row.status} {getattr(row, 'error_message', '') or ''}",
                    workspace="execute",
                    extra=item,
                )
            return [{"type": "list_executions", "items": items}]
        finally:
            db.close()

    def _compose(
        self,
        question: str,
        workspace: str,
        hits: list[dict[str, Any]],
        memory_hits: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        intent: str = "locate",
    ) -> str:
        path_name = INTENT_PATHS.get(intent, intent)
        lines = [
            f"当前工作区：{workspace}。已选择最短路径：{path_name}。",
            "以下结论来自共享 Testing Brain（测试专家 + 项目索引 + Project Memory），没有重新扫描整个仓库。",
        ]
        if intent == "answer":
            return "\n".join(lines)
        if memory_hits:
            lines.append("已复用的项目记忆：")
            for item in memory_hits[:4]:
                lines.append(f"- [{item['kind']}] {item['title']}：{(item.get('content') or '')[:120]}")
        if not hits:
            if workspace == "execute":
                lines.append("本次按执行记录查询，没有重新扫描仓库。")
            else:
                lines.append("索引里还没有匹配到代码位置。请先在项目理解中导入 GitHub 仓库。")
        else:
            lines.append("代码定位：")
            for item in hits[:8]:
                loc = f"{item['path']}:{item.get('line_start') or 1}"
                if item.get("line_end") and item["line_end"] != item.get("line_start"):
                    loc += f"-{item['line_end']}"
                lines.append(f"- {item['kind']} `{item['name']}` @ {loc}（模块 {item.get('module') or '-'}）")
                if item.get("snippet"):
                    lines.append("```")
                    lines.append(item["snippet"][:400])
                    lines.append("```")
            files = sorted({item["path"] for item in hits if item.get("path")})
            if files:
                lines.append("若要改这个功能，优先改这些文件：")
                for path in files[:8]:
                    lines.append(f"- {path}")
            apis = [item for item in hits if item.get("kind") == "api"]
            if apis:
                lines.append("相关 API：")
                for item in apis[:6]:
                    lines.append(f"- {item['name']} @ {item['path']}:{item.get('line_start') or 1}")
        for action in actions:
            if action.get("type") == "create_test_design":
                asset = action.get("asset") or {}
                lines.append(f"已写入测试设计资产：{asset.get('name')}（阶段 {asset.get('stage_name') or '测试设计'}）。")
            if action.get("type") == "analyze_requirement":
                analysis = action.get("analysis") or {}
                lines.append("需求/测试分析已写入项目资产，不必再走完整一站式流程。")
                for item in (analysis.get("must_test") or [])[:4]:
                    lines.append(f"- 必测：{item}")
            if action.get("type") in {"generate_cases", "generated_cases", "supplement_exception", "supplement_boundary"}:
                cases = action.get("cases") or []
                lines.append(f"已生成 {len(cases)} 条专业测试用例，并回写当前测试任务。")
            if action.get("type") == "full_test":
                lines.append("已按一站式最短闭环完成：创建测试任务 → 分析 → 生成用例 → 覆盖检查。产物已落入测试任务，而不是只留在对话里。")
            if action.get("test_task_id"):
                lines.append(f"打开测试任务工作台继续：/test-tasks/{action['test_task_id']}")
            if action.get("type") == "list_executions":
                items = action.get("items") or []
                if items:
                    lines.append("最近执行记录：")
                    for item in items:
                        lines.append(f"- #{item['id']} {item['status']} {item.get('error') or ''}")
                else:
                    lines.append("当前项目还没有匹配的执行记录。")
            if action.get("type") == "check_coverage":
                cov = action.get("coverage") or {}
                lines.append(f"覆盖率 {cov.get('score')}%。{cov.get('advice') or ''}")
            if action.get("type") == "to_automation":
                lines.append("已把当前用例转成 Playwright 草稿并写入脚本资产。")
            if action.get("type") == "create_bug":
                lines.append("缺陷已回写当前测试任务和项目缺陷资产。")
            if action.get("type") == "generate_report":
                lines.append("测试报告已写入当前测试任务。")
        return "\n".join(lines)
