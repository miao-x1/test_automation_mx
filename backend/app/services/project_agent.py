"""全局项目级 Agent：总管入口。按用户目标选最短路径，产物落到测试资产。"""
from __future__ import annotations

import re
from typing import Any, Optional

from app.db.database import SessionLocal
from app.models.execution_record import ExecutionRecord
from app.models.team import Project
from app.services.asset_lifecycle import AssetLifecycleService
from app.services.project_indexer import ProjectIndexer
from app.services.project_memory import ProjectMemoryService
from app.services.project_understanding import ProjectUnderstandingService
from app.services.requirement_analysis_doc import RequirementAnalysisDocService
from app.services.test_design_doc import TestDesignDocService
from app.services.test_pipeline import TestPipelineService
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
        self.understanding = ProjectUnderstandingService()
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
        memory_hits = [item for item in (brain.get("memory") or []) if item.get("kind") not in {"question", "message"}]
        actions: list[dict[str, Any]] = []

        if intent == "design_test" or (intent == "analyze_requirement" and workspace == "design"):
            actions.extend(self._design_test_doc(user_id, project_id, question))
            answer = self._work_answer(actions)
        elif intent == "analyze_requirement":
            actions.extend(self._analyze_requirement_doc(user_id, project_id, question))
            answer = self._work_answer(actions)
        elif intent in {
            "prepare_data", "prepare_accounts", "check_env", "run_batch", "draft_bugs", "regress",
        } or (intent == "generate_report" and not test_task_id):
            actions.extend(self._pipeline_work(user_id, project_id, question, intent))
            answer = self._work_answer(actions)
        elif intent in {
            "generate_cases", "supplement_exception", "supplement_boundary",
            "check_coverage", "optimize_cases", "to_automation", "execute",
            "analyze_failure", "create_bug", "generate_report", "create_task", "full_test",
        }:
            actions.extend(self._route_work(user_id, project_id, question, intent, unique, test_task_id))
            answer = self._work_answer(actions)
        elif workspace == "design" and any(token in question for token in ("测试", "用例", "场景", "设计")) and intent == "locate":
            actions.extend(self._design_test_doc(user_id, project_id, question))
            answer = self._work_answer(actions)
            intent = "design_test"
        elif workspace == "execute" and intent in {"execute", "analyze_failure"}:
            actions.extend(self._execute(user_id, project_id, question))
            answer = self._work_answer(actions)
        else:
            answer = self._answer_current_project(user_id, project_id, question, unique)
            if intent == "locate" and any(token in question for token in ("几个", "多少", "数量", "有几", "什么是", "什么叫", "解释一下", "做什么", "是什么项目")):
                intent = "answer"
            elif intent not in {"locate", "answer"}:
                intent = "answer"

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
            extra={"intent": intent},
            test_task_id=test_task_id,
        )
        if unique and intent == "locate":
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

    def _project_name(self, project_id: int, snap: Optional[dict[str, Any]] = None) -> str:
        name = ((snap or {}).get("project") or {}).get("name")
        if name:
            return name
        try:
            db = SessionLocal()
            try:
                row = db.query(Project).filter(Project.id == project_id).first()
                return (row.name if row else "") or "当前项目"
            finally:
                db.close()
        except Exception:
            return "当前项目"

    def _knowledge_answer(self, question: str) -> Optional[str]:
        q = question or ""
        if not any(token in q for token in ("什么是", "什么叫", "解释一下", "怎么理解", "定义")):
            return None
        if any(token in q for token in ("这个项目", "当前项目", "本项目")):
            return None
        try:
            cards = (self.brain.expert.retrieve(q, top_k=1, include_playbooks=False).get("cards") or [])
        except Exception:
            return None
        if not cards:
            return None
        primary = cards[0]
        title = (primary.get("title") or "").strip()
        principle = (primary.get("principle") or "").strip()
        if not principle:
            return None
        return f"{title}：{principle}" if title else principle

    def _answer_current_project(
        self,
        user_id: int,
        project_id: int,
        question: str,
        hits: list[dict[str, Any]],
    ) -> str:
        knowledge = self._knowledge_answer(question)
        if knowledge:
            return knowledge
        try:
            snap = self.understanding.snapshot(user_id, project_id)
        except Exception:
            snap = {"imported": False}
        name = self._project_name(project_id, snap)
        q = question
        scale = snap.get("scale") or {}
        imported = bool(snap.get("imported"))

        def count_of(kind: str, scale_key: str, items_key: str) -> int:
            if imported and scale.get(scale_key) is not None:
                return int(scale.get(scale_key) or 0)
            rows = self.indexer.query_index(user_id, project_id, kind=kind, limit=200)
            if rows:
                return len(rows)
            return len(snap.get(items_key) or [])

        if any(token in q for token in ("几个", "多少", "数量", "有几")) and any(token in q.lower() for token in ("api", "接口", "endpoint")):
            if not imported and count_of("api", "apis", "apis") == 0:
                return f"当前项目「{name}」还没有导入或分析代码，统计不到接口。"
            return f"当前项目「{name}」有 {count_of('api', 'apis', 'apis')} 个接口。"
        if any(token in q for token in ("几个", "多少", "数量", "有几")) and any(token in q for token in ("页面", "page")):
            if not imported and count_of("page", "pages", "pages") == 0:
                return f"当前项目「{name}」还没有导入或分析代码，统计不到页面。"
            return f"当前项目「{name}」有 {count_of('page', 'pages', 'pages')} 个页面。"
        if any(token in q for token in ("几个", "多少", "数量", "有几")) and any(token in q for token in ("功能", "模块")):
            key = "features" if "功能" in q else "modules"
            kind = "feature" if key == "features" else "module"
            n = count_of(kind, key, key)
            label = "个功能" if key == "features" else "个模块"
            return f"当前项目「{name}」有 {n} {label}。"
        if any(token in q for token in ("哪些接口", "有哪些 api", "有哪些API", "接口列表")):
            apis = snap.get("apis") or self.indexer.query_index(user_id, project_id, kind="api", limit=40)
            names = [item.get("name") for item in apis if item.get("name")]
            if not names:
                return f"当前项目「{name}」还没有解析出接口。"
            return "、".join(names[:20]) + ("。" if len(names) <= 20 else f" 等，共 {len(names)} 个。")
        if any(token in q for token in ("做什么", "是什么项目", "介绍一下", "项目介绍", "概述")):
            project = snap.get("project") or {}
            desc = project.get("description") or ""
            stack = "、".join(project.get("stack") or [])
            if not imported:
                return f"当前项目是「{name}」，还没有导入代码，我只能看到项目名称。"
            parts = [f"当前项目是「{name}」。"]
            if desc:
                desc = desc.strip()
                if desc and not desc.endswith(("。", "！", "？", ".", "!", "?")):
                    desc += "。"
                parts.append(desc)
            if stack:
                parts.append(f"技术栈：{stack}。")
            return "".join(parts)
        if hits and any(token in q for token in ("在哪", "哪个文件", "定位", "找一下", "哪里")):
            top = hits[0]
            return f"{top.get('name')} 在 {top.get('path')}:{top.get('line_start') or 1}。"
        if hits:
            top = hits[0]
            return f"在当前项目「{name}」里，和这个问题最相关的是 {top.get('name')}（{top.get('path')}）。"
        if not imported:
            return f"当前项目「{name}」还没有导入代码，我回答不了这个问题。"
        return f"当前项目「{name}」里没有找到和这个问题直接对应的结果。"

    def _work_answer(self, actions: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for action in actions:
            if action.get("type") == "create_test_design":
                asset = action.get("asset") or {}
                lines.append(f"已写入测试设计：{asset.get('name') or '测试设计'}。")
            if action.get("type") == "analyze_requirement":
                lines.append("需求已分析并写入当前项目。")
            if action.get("type") == "pipeline":
                lines.append(action.get("summary") or "已写入测试链路数据。")
            if action.get("type") == "design_test":
                doc = action.get("document") or {}
                summary = ((doc.get("interaction") or {}).get("summary") or "").strip()
                questions = ((doc.get("interaction") or {}).get("questions") or [])[:3]
                if summary:
                    lines.append(summary)
                else:
                    counts = doc.get("counts") or {}
                    lines.append(
                        f"已完成测试设计，共 {counts.get('objects') or 0} 个测试对象、"
                        f"{counts.get('scenarios') or 0} 个测试场景。"
                    )
                headline = ((doc.get("plan") or {}).get("headline") or "").strip()
                if headline and headline not in (summary or ""):
                    lines.append(headline)
                if questions:
                    lines.append("关键问题（可跳过）：")
                    for item in questions:
                        lines.append(f"- {item.get('question')}")
                lines.append("结果已写入测试设计工作台，均追溯到需求分析。打开 /design 查看对象、场景和来源需求，本阶段不生成完整测试用例。")
            if action.get("type") == "requirement_analysis":
                doc = action.get("document") or {}
                summary = ((doc.get("interaction") or {}).get("summary") or "").strip()
                questions = ((doc.get("interaction") or {}).get("questions") or [])[:3]
                if summary:
                    lines.append(summary)
                else:
                    counts = doc.get("counts") or {}
                    lines.append(
                        f"已完成需求分析，共识别 {counts.get('functions') or 0} 项功能、"
                        f"{counts.get('rules') or 0} 条业务规则。"
                    )
                if questions:
                    lines.append("关键问题（可跳过）：")
                    for item in questions:
                        lines.append(f"- {item.get('question')}")
                lines.append("结构化结果已写入「需求分析」，不会在本阶段生成测试用例。")
            if action.get("type") in {"generate_cases", "generated_cases", "supplement_exception", "supplement_boundary"}:
                lines.append(f"已生成 {len(action.get('cases') or [])} 条用例。")
            if action.get("type") == "full_test":
                lines.append("已按当前项目完成分析、生成用例和覆盖检查。")
            if action.get("type") == "list_executions":
                items = action.get("items") or []
                lines.append(f"当前项目最近有 {len(items)} 条执行记录。" if items else "当前项目还没有执行记录。")
            if action.get("type") == "check_coverage":
                cov = action.get("coverage") or {}
                lines.append(f"覆盖率 {cov.get('score')}%。")
            if action.get("type") == "to_automation":
                lines.append("已转成自动化草稿。")
            if action.get("type") == "create_bug":
                lines.append("缺陷已写入当前项目。")
            if action.get("type") == "generate_report":
                lines.append("报告已写入当前测试任务。")
        return "\n".join(lines) or "已按当前项目处理。"

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
        kind_score = {
            "page": 8, "api": 8, "function": 7, "feature": 7,
            "component": 6, "file": 4, "module": 3, "element": 0,
        }
        q = (question or "").lower()

        def score(item: dict[str, Any]) -> int:
            name = item.get("name") or ""
            path = item.get("path") or ""
            points = kind_score.get(item.get("kind") or "", 2)
            if "(" in name or "e.target" in name or len(name) > 48:
                points -= 8
            blob = f"{name} {path}".lower()
            for index, word in enumerate(keywords or []):
                key = (word or "").lower()
                if not key:
                    continue
                if name.lower() == key:
                    points += 20
                elif key in blob:
                    points += max(6, 12 - index)
            if any(token in q for token in ("页面", "page")) and item.get("kind") == "page":
                points += 6
            if any(token in q for token in ("接口", "api")) and item.get("kind") == "api":
                points += 6
            return points

        unique.sort(key=score, reverse=True)
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
            elif intent in {"create_task", "full_test", "analyze_requirement"}:
                task = tasks.create_task(
                    user_id, project_id,
                    name=module if intent != "full_test" else "全项目测试",
                    requirement_text=question,
                    focus=module,
                )
            elif intent == "generate_cases" and not test_task_id:
                from app.services.case_workbench import CaseWorkbenchService
                generated = CaseWorkbenchService().generate(user_id, project_id, {"source_type": "TEXT", "text": question})
                actions.append({
                    "type": "generate_cases",
                    "path": "/test-tasks",
                    "cases": generated.get("created") or [],
                    "quality": generated.get("quality"),
                    "summary": f"已生成 {generated.get('count') or 0} 条结构化用例，状态为 AI_GENERATED，需评审后才能执行。",
                })
                return actions
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

    def _pipeline_work(self, user_id: int, project_id: int, question: str, intent: str) -> list[dict[str, Any]]:
        pipe = TestPipelineService(self.memory)
        path = "/prepare"
        summary = ""
        document: dict[str, Any] = {}
        try:
            if intent == "prepare_data":
                match = re.search(r"(\d+)", question or "")
                data = pipe.generate_data(user_id, project_id, int(match.group(1)) if match else 20)
                document = data
                summary = f"已生成 {data['count']} 条测试数据，ID 从 {data['created'][0]['id']} 到 {data['created'][-1]['id']}。"
                path = "/prepare"
            elif intent == "prepare_accounts":
                match = re.search(r"(\d+)", question or "")
                data = pipe.generate_accounts(user_id, project_id, int(match.group(1)) if match else 10)
                document = data
                summary = f"已生成 {data['count']} 个账号清单，状态均为待在实际系统中创建。"
                path = "/prepare"
            elif intent == "check_env":
                document = pipe.check_environment(user_id, project_id)
                fail = len([item for item in document.get("env_checks") or [] if item.get("status") == "FAIL"])
                unknown = len([item for item in document.get("env_checks") or [] if item.get("status") == "UNKNOWN"])
                summary = f"环境检查完成。FAIL {fail}，UNKNOWN {unknown}。UNKNOWN 不会记为通过。"
                path = "/prepare"
            elif intent == "run_batch":
                document = pipe.create_run_batch(user_id, project_id)
                summary = f"已创建执行批次 {document['id']}，共 {document['stats']['total']} 条，全部为 NOT_EXECUTED。"
                path = "/execute"
            elif intent == "draft_bugs":
                data = pipe.draft_bugs_from_fails(user_id, project_id)
                document = data
                summary = f"已从 FAIL 记录生成 {data['count']} 条缺陷草稿，需确认后提交。"
                path = "/defects"
            elif intent == "regress":
                defects = pipe.get_defects(user_id, project_id)
                bug_ids = [item["id"] for item in (defects.get("bugs") or []) if item.get("status") not in {"CLOSED", "REJECTED", "DUPLICATE"}]
                document = pipe.create_regression(user_id, project_id, bug_ids[:8])
                summary = f"已创建回归批次 {document['id']}，用例 {document['stats']['total']} 条。"
                path = "/regression"
            else:
                document = pipe.generate_report(user_id, project_id)
                summary = f"已汇总测试报告 {document['id']}。{document.get('conclusion')}"
                path = "/report"
        except ValueError as exc:
            summary = str(exc)
        return [{"type": "pipeline", "intent": intent, "document": document, "summary": summary, "path": path}]

    def _design_test_doc(self, user_id: int, project_id: int, question: str) -> list[dict[str, Any]]:
        docs = TestDesignDocService(self.memory)
        document = docs.design_from_question(user_id, project_id, question)
        return [{
            "type": "design_test",
            "document": document,
            "path": "/design",
        }]

    def _analyze_requirement_doc(self, user_id: int, project_id: int, question: str) -> list[dict[str, Any]]:
        docs = RequirementAnalysisDocService(self.memory)
        try:
            project_name = self._project_name(project_id)
        except Exception:
            project_name = ""
        document = docs.analyze_from_question(
            user_id, project_id, question, project_name=project_name,
        )
        return [{
            "type": "requirement_analysis",
            "document": document,
            "path": "/understand/requirements",
        }]

    def _analyze(self, user_id: int, project_id: int, question: str, test_task_id: Optional[int]) -> list[dict[str, Any]]:
        try:
            confirmed = RequirementAnalysisDocService(self.memory).get(user_id, project_id)
        except Exception:
            confirmed = {}
        if confirmed.get("status") == "confirmed" and confirmed.get("design_input"):
            question = f"{confirmed['design_input']}\n\n{question}"
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
