"""测试生命周期资产中心。扩展现有 asset_registry，不另建业务表。"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.asset_registry import (
    AssetRegistry,
    AssetRegistrySource,
    AssetRegistryStatus,
    AssetRelation,
    AssetRelationType,
)
from app.schemas.asset_registry import AssetCreate, RelationCreate
from app.services.asset_registry_service import AssetRegistryService
from app.services.asset_relation_service import AssetRelationService

PILLARS: list[dict[str, Any]] = [
    {"key": "workspace", "code": "01", "name": "工作空间", "order": 1,
     "summary": "项目选择、环境、任务和整体状态", "stage_keys": []},
    {"key": "understand", "code": "02", "name": "项目理解", "order": 2,
     "summary": "系统探索、页面地图、功能与业务认知", "stage_keys": ["01_analysis"]},
    {"key": "design", "code": "03", "name": "测试设计", "order": 3,
     "summary": "测试计划、场景、用例、数据与脚本",
     "stage_keys": ["02_plan", "03_design", "04_cases", "05_scripts"]},
    {"key": "execute", "code": "04", "name": "测试执行", "order": 4,
     "summary": "执行、缺陷、回归、报告与归档",
     "stage_keys": ["06_execution", "07_defect", "08_regression", "09_report", "10_archive"]},
]

STAGES: list[dict[str, Any]] = [
    {"key": "01_analysis", "code": "01", "name": "需求分析", "order": 1,
     "pillar": "understand", "pillar_name": "项目理解",
     "categories": ["需求文档", "功能清单", "页面分析", "业务流程", "测试范围", "风险点",
                    "页面地图", "页面结构", "页面元素", "业务关系", "用户角色/权限",
                    "接口/API关系", "数据关系", "系统依赖", "项目知识库"]},
    {"key": "02_plan", "code": "02", "name": "测试计划", "order": 2,
     "pillar": "design", "pillar_name": "测试设计",
     "categories": ["测试计划", "测试策略", "测试范围", "测试环境", "测试资源", "测试进度"]},
    {"key": "03_design", "code": "03", "name": "测试设计", "order": 3,
     "pillar": "design", "pillar_name": "测试设计",
     "categories": ["测试场景", "测试点", "测试数据", "测试矩阵", "测试设计文档", "测试覆盖率"]},
    {"key": "04_cases", "code": "04", "name": "测试用例", "order": 4,
     "pillar": "design", "pillar_name": "测试设计",
     "categories": ["功能测试用例", "接口测试用例", "UI测试用例", "异常测试用例", "边界测试用例", "回归测试用例"]},
    {"key": "05_scripts", "code": "05", "name": "测试脚本", "order": 5,
     "pillar": "design", "pillar_name": "测试设计",
     "categories": ["UI自动化脚本", "API自动化脚本", "数据库脚本", "Playwright脚本", "辅助测试脚本", "自动化测试脚本"]},
    {"key": "06_execution", "code": "06", "name": "测试执行", "order": 6,
     "pillar": "execute", "pillar_name": "测试执行",
     "categories": ["测试执行记录", "执行结果", "测试截图", "测试视频", "执行日志", "测试数据", "失败分析"]},
    {"key": "07_defect", "code": "07", "name": "缺陷管理", "order": 7,
     "pillar": "execute", "pillar_name": "测试执行",
     "categories": ["缺陷记录", "缺陷复现步骤", "缺陷截图", "缺陷视频", "缺陷日志", "缺陷修复记录", "缺陷验证"]},
    {"key": "08_regression", "code": "08", "name": "回归测试", "order": 8,
     "pillar": "execute", "pillar_name": "测试执行",
     "categories": ["回归测试记录", "回归测试用例", "回归执行结果", "缺陷验证结果"]},
    {"key": "09_report", "code": "09", "name": "测试报告", "order": 9,
     "pillar": "execute", "pillar_name": "测试执行",
     "categories": ["测试报告", "测试结果统计", "用例统计", "缺陷统计", "覆盖率", "风险评估", "发布建议"]},
    {"key": "10_archive", "code": "10", "name": "测试归档", "order": 10,
     "pillar": "execute", "pillar_name": "测试执行",
     "categories": ["最终测试用例", "最终测试脚本", "最终测试报告", "测试基线", "项目测试资产快照"]},
]

STAGE_MAP = {item["key"]: item for item in STAGES}

TYPE_BY_STAGE = {
    "01_analysis": "requirement",
    "02_plan": "test_plan",
    "03_design": "test_design",
    "04_cases": "test_case",
    "05_scripts": "script",
    "06_execution": "execution",
    "07_defect": "defect",
    "08_regression": "regression",
    "09_report": "test_report",
    "10_archive": "archive",
}

NEXT_RELATION = {
    "01_analysis": AssetRelationType.COVERS,
    "02_plan": AssetRelationType.DERIVED_FROM,
    "03_design": AssetRelationType.DERIVED_FROM,
    "04_cases": AssetRelationType.PRODUCES,
    "05_scripts": AssetRelationType.PRODUCES,
    "06_execution": AssetRelationType.CAUSED,
    "07_defect": AssetRelationType.REGRESSED,
    "08_regression": AssetRelationType.REPORTS,
    "09_report": AssetRelationType.CONTAINS,
}


def _meta(asset: AssetRegistry) -> dict:
    raw = asset.extra_metadata
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _origin(source: str) -> str:
    if source == AssetRegistrySource.AI:
        return "AI生成"
    if source == AssetRegistrySource.AUTO:
        return "自动生成"
    return "人工创建"


def serialize(asset: AssetRegistry, relation_count: int = 0) -> dict[str, Any]:
    meta = _meta(asset)
    stage = asset.module or meta.get("stage") or ""
    info = STAGE_MAP.get(stage) or {}
    return {
        "id": asset.id,
        "asset_code": asset.asset_code,
        "name": asset.name,
        "asset_type": asset.asset_type,
        "category": meta.get("category") or info.get("name") or asset.asset_type,
        "stage": stage,
        "stage_name": info.get("name") or stage,
        "pillar": info.get("pillar") or "",
        "pillar_name": info.get("pillar_name") or "",
        "project_id": meta.get("project_id"),
        "origin": _origin(asset.source),
        "source": asset.source,
        "created_by": asset.created_by,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
        "updated_at": asset.updated_at.isoformat() if asset.updated_at else None,
        "status": asset.status,
        "version": asset.version,
        "tags": [t for t in (asset.tags or "").split(",") if t],
        "reusable": bool(meta.get("reusable", True)),
        "summary": asset.summary,
        "description": asset.description,
        "content": meta.get("content") or asset.description or "",
        "ref_type": asset.ref_type,
        "ref_id": asset.ref_id,
        "relation_count": relation_count,
    }


class AssetLifecycleService:
    def __init__(self):
        self.assets = AssetRegistryService()
        self.relations = AssetRelationService()

    def stages(self, user_id: int, project_id: Optional[int] = None) -> list[dict[str, Any]]:
        db = SessionLocal()
        try:
            assets = db.query(AssetRegistry).filter(
                AssetRegistry.user_id == user_id,
                AssetRegistry.is_deleted == False,  # noqa: E712
            ).all()
            if project_id:
                assets = [a for a in assets if str(_meta(a).get("project_id") or "") == str(project_id)]
            counts: dict[str, dict[str, Any]] = {}
            for asset in assets:
                key = asset.module or ""
                stat = counts.setdefault(key, {"count": 0, "updated_at": None})
                stat["count"] += 1
                if asset.updated_at and (stat["updated_at"] is None or asset.updated_at > stat["updated_at"]):
                    stat["updated_at"] = asset.updated_at
            result = []
            for stage in STAGES:
                stat = counts.get(stage["key"]) or {"count": 0, "updated_at": None}
                count = int(stat["count"] or 0)
                updated = stat["updated_at"]
                result.append({
                    **stage,
                    "asset_count": count,
                    "status": "已有资产" if count else "待沉淀",
                    "updated_at": updated.isoformat() if isinstance(updated, datetime) else None,
                })
            return result
        finally:
            db.close()

    def pillars(self, user_id: int, project_id: Optional[int] = None) -> list[dict[str, Any]]:
        stages = self.stages(user_id, project_id)
        by_key = {item["key"]: item for item in stages}
        result = []
        for pillar in PILLARS:
            children = [by_key[key] for key in pillar["stage_keys"] if key in by_key]
            count = sum(int(item.get("asset_count") or 0) for item in children)
            latest = None
            for item in children:
                updated = item.get("updated_at")
                if updated and (latest is None or updated > latest):
                    latest = updated
            result.append({
                **pillar,
                "asset_count": count,
                "status": "已有资产" if count else "待沉淀",
                "updated_at": latest,
                "stages": children,
            })
        return result

    def list_assets(
        self,
        user_id: int,
        *,
        stage: Optional[str] = None,
        keyword: Optional[str] = None,
        asset_type: Optional[str] = None,
        status: Optional[str] = None,
        source: Optional[str] = None,
        project_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        db = SessionLocal()
        try:
            q = db.query(AssetRegistry).filter(
                AssetRegistry.user_id == user_id,
                AssetRegistry.is_deleted == False,  # noqa: E712
            )
            if stage:
                q = q.filter(AssetRegistry.module == stage)
            if asset_type:
                q = q.filter(AssetRegistry.asset_type == asset_type)
            if status:
                q = q.filter(AssetRegistry.status == status)
            if source:
                q = q.filter(AssetRegistry.source == source)
            if keyword:
                like = f"%{keyword.strip()}%"
                q = q.filter(or_(
                    AssetRegistry.name.like(like),
                    AssetRegistry.summary.like(like),
                    AssetRegistry.tags.like(like),
                    AssetRegistry.asset_code.like(like),
                ))
            items = q.order_by(AssetRegistry.updated_at.desc()).all()
            if project_id:
                items = [a for a in items if str(_meta(a).get("project_id") or "") == str(project_id)]
            total = len(items)
            start = max(page - 1, 0) * page_size
            page_items = items[start:start + page_size]
            counts = self._relation_counts(db, [a.id for a in page_items])
            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "items": [serialize(a, counts.get(a.id, 0)) for a in page_items],
            }
        finally:
            db.close()

    def create_asset(
        self,
        user_id: int,
        *,
        name: str,
        stage: str,
        category: Optional[str] = None,
        content: Optional[str] = None,
        source: str = "manual",
        status: str = AssetRegistryStatus.DRAFT,
        tags: Optional[list[str]] = None,
        project_id: Optional[int] = None,
        reusable: bool = True,
        ref_type: Optional[str] = None,
        ref_id: int = 0,
        related_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        if stage not in STAGE_MAP:
            raise ValueError("未知测试阶段")
        asset_type = TYPE_BY_STAGE[stage]
        created = self.assets.create_asset(
            AssetCreate(
                name=name.strip(),
                asset_type=asset_type,
                ref_type=ref_type or asset_type,
                ref_id=ref_id,
                summary=(content or "")[:500] or name,
                description=content,
                module=stage,
                tags=tags if tags else ([category] if category else None),
                source=source if source in AssetRegistrySource.ALL else "manual",
                extra_metadata={
                    "stage": stage,
                    "category": category or STAGE_MAP[stage]["categories"][0],
                    "content": content or "",
                    "project_id": project_id,
                    "reusable": reusable,
                },
            ),
            user_id=user_id,
            created_by=user_id,
        )
        if status != AssetRegistryStatus.DRAFT:
            db = SessionLocal()
            try:
                row = db.query(AssetRegistry).filter(AssetRegistry.id == created["id"]).first()
                if row:
                    row.status = status
                    db.commit()
                    created["status"] = status
            finally:
                db.close()
        for target_id in related_ids or []:
            self.link(user_id, created["id"], int(target_id))
        return self.get_asset(user_id, created["id"])

    def get_asset(self, user_id: int, asset_id: int) -> dict[str, Any]:
        db = SessionLocal()
        try:
            asset = db.query(AssetRegistry).filter(
                AssetRegistry.id == asset_id,
                AssetRegistry.user_id == user_id,
                AssetRegistry.is_deleted == False,  # noqa: E712
            ).first()
            if not asset:
                raise ValueError("资产不存在")
            relations = db.query(AssetRelation).filter(
                AssetRelation.is_deleted == False,  # noqa: E712
                or_(AssetRelation.source_id == asset_id, AssetRelation.target_id == asset_id),
            ).all()
            ids = {asset_id}
            for rel in relations:
                ids.add(rel.source_id)
                ids.add(rel.target_id)
            peers = {
                row.id: row
                for row in db.query(AssetRegistry).filter(AssetRegistry.id.in_(list(ids))).all()
            }
            upstream, downstream, similar, defects, cases, scripts, runs = [], [], [], [], [], [], []
            for rel in relations:
                other_id = rel.target_id if rel.source_id == asset_id else rel.source_id
                other = peers.get(other_id)
                if not other:
                    continue
                item = {**serialize(other), "relation_type": rel.relation_type}
                if rel.target_id == asset_id:
                    upstream.append(item)
                else:
                    downstream.append(item)
                if other.asset_type == "defect":
                    defects.append(item)
                if other.asset_type == "test_case":
                    cases.append(item)
                if other.asset_type == "script":
                    scripts.append(item)
                if other.asset_type == "execution":
                    runs.append(item)
            similar = [
                serialize(row)
                for row in db.query(AssetRegistry).filter(
                    AssetRegistry.user_id == user_id,
                    AssetRegistry.module == asset.module,
                    AssetRegistry.id != asset.id,
                    AssetRegistry.is_deleted == False,  # noqa: E712
                ).order_by(AssetRegistry.updated_at.desc()).limit(8).all()
            ]
            data = serialize(asset, len(relations))
            data["relations"] = {
                "upstream": upstream,
                "downstream": downstream,
                "similar": similar,
                "defects": defects,
                "cases": cases,
                "scripts": scripts,
                "runs": runs,
            }
            data["versions"] = [
                {
                    "version": asset.version,
                    "updated_at": data["updated_at"],
                    "source": asset.source,
                }
            ]
            return data
        finally:
            db.close()

    def update_asset(self, user_id: int, asset_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        db = SessionLocal()
        try:
            asset = db.query(AssetRegistry).filter(
                AssetRegistry.id == asset_id,
                AssetRegistry.user_id == user_id,
                AssetRegistry.is_deleted == False,  # noqa: E712
            ).first()
            if not asset:
                raise ValueError("资产不存在")
            meta = _meta(asset)
            if payload.get("name"):
                asset.name = payload["name"].strip()
            if "content" in payload:
                asset.description = payload["content"]
                asset.summary = (payload["content"] or "")[:500]
                meta["content"] = payload["content"]
            if "category" in payload:
                meta["category"] = payload["category"]
            if "status" in payload and payload["status"] in AssetRegistryStatus.ALL:
                asset.status = payload["status"]
            if "tags" in payload and isinstance(payload["tags"], list):
                asset.tags = ",".join(payload["tags"])
            if "reusable" in payload:
                meta["reusable"] = bool(payload["reusable"])
            asset.extra_metadata = json.dumps(meta, ensure_ascii=False)
            db.commit()
        finally:
            db.close()
        return self.get_asset(user_id, asset_id)

    def link(self, user_id: int, source_id: int, target_id: int, relation_type: Optional[str] = None) -> dict[str, Any]:
        if source_id == target_id:
            raise ValueError("不能关联自己")
        db = SessionLocal()
        try:
            source = db.query(AssetRegistry).filter(AssetRegistry.id == source_id).first()
            rel_type = relation_type or NEXT_RELATION.get(source.module if source else "", AssetRelationType.DERIVED_FROM)
        finally:
            db.close()
        try:
            return self.relations.create_relation(
                RelationCreate(source_id=source_id, target_id=target_id, relation_type=rel_type),
                user_id=user_id,
            )
        except Exception as exc:
            if "已存在" in str(exc) or "冲突" in str(exc):
                return {"source_id": source_id, "target_id": target_id, "relation_type": rel_type}
            raise

    def reuse_candidates(self, user_id: int, keyword: str, stage: Optional[str] = None) -> list[dict[str, Any]]:
        data = self.list_assets(user_id, stage=stage, keyword=keyword, page=1, page_size=8)
        return [item for item in data["items"] if item.get("reusable")]

    def sink_requirement(self, task) -> dict[str, int]:
        """分析完成后把需求/用例/脚本沉淀到对应阶段。"""
        user_id = getattr(task, "user_id", None)
        if not user_id:
            return {}
        project_id = getattr(task, "project_id", None)
        created: dict[str, int] = {}
        req = self._upsert_ref(
            user_id,
            name=getattr(task, "task_name", None) or f"需求 #{task.id}",
            stage="01_analysis",
            category="页面分析" if getattr(task, "page_elements", None) else "需求文档",
            content=getattr(task, "requirement", "") or "",
            source="ai",
            ref_type="requirement",
            ref_id=task.id,
            project_id=project_id,
            status=AssetRegistryStatus.ACTIVE,
        )
        created["requirement"] = req
        cases = []
        raw_cases = getattr(task, "generated_case", None)
        if raw_cases:
            try:
                cases = json.loads(raw_cases) if isinstance(raw_cases, str) else raw_cases
            except Exception:
                cases = []
        if isinstance(cases, list):
            for index, case in enumerate(cases[:20], start=1):
                title = case.get("title") if isinstance(case, dict) else f"用例 {index}"
                steps = case.get("steps") if isinstance(case, dict) else case
                case_id = self._upsert_ref(
                    user_id,
                    name=str(title or f"TC_{task.id}_{index}"),
                    stage="04_cases",
                    category="功能测试用例",
                    content=json.dumps(steps, ensure_ascii=False, default=str) if not isinstance(steps, str) else steps,
                    source="ai",
                    ref_type="test_case",
                    ref_id=task.id * 1000 + index,
                    project_id=project_id,
                    status=AssetRegistryStatus.ACTIVE,
                )
                self.link(user_id, req, case_id, AssetRelationType.COVERS)
                created[f"case_{index}"] = case_id
        script = getattr(task, "generated_script", None)
        if script:
            reused = getattr(task, "script_source", "") == "reused"
            script_id = self._upsert_ref(
                user_id,
                name=f"{getattr(task, 'task_name', None) or task.id} 自动化脚本",
                stage="05_scripts",
                category="Playwright脚本",
                content=script,
                source="ai" if not reused else "auto",
                ref_type="script",
                ref_id=getattr(task, "task_id", None) or task.id,
                project_id=project_id,
                status=AssetRegistryStatus.ACTIVE,
            )
            last_case = next((v for k, v in created.items() if k.startswith("case_")), req)
            self.link(user_id, last_case, script_id, AssetRelationType.IMPLEMENTS)
            created["script"] = script_id
        return created

    def sink_execution(self, record, task=None) -> dict[str, int]:
        user_id = getattr(record, "user_id", None)
        if not user_id:
            return {}
        project_id = getattr(record, "project_id", None)
        run_id = self._upsert_ref(
            user_id,
            name=f"执行 #{record.id}",
            stage="06_execution",
            category="测试执行记录",
            content=getattr(record, "log_content", None) or getattr(record, "status", "") or "",
            source="auto",
            ref_type="execution",
            ref_id=record.id,
            project_id=project_id,
            status=AssetRegistryStatus.ACTIVE,
        )
        created = {"execution": run_id}
        if getattr(record, "screenshot_path", None):
            shot_id = self._upsert_ref(
                user_id,
                name=f"执行截图 #{record.id}",
                stage="06_execution",
                category="测试截图",
                content=record.screenshot_path,
                source="auto",
                ref_type="execution",
                ref_id=record.id * 10 + 1,
                project_id=project_id,
                status=AssetRegistryStatus.ACTIVE,
            )
            self.link(user_id, run_id, shot_id, AssetRelationType.CONTAINS)
            created["screenshot"] = shot_id
        if getattr(record, "log_content", None):
            log_id = self._upsert_ref(
                user_id,
                name=f"执行日志 #{record.id}",
                stage="06_execution",
                category="执行日志",
                content=str(record.log_content)[:8000],
                source="auto",
                ref_type="execution",
                ref_id=record.id * 10 + 2,
                project_id=project_id,
                status=AssetRegistryStatus.ACTIVE,
            )
            self.link(user_id, run_id, log_id, AssetRelationType.CONTAINS)
            created["log"] = log_id
        script_id = self._find_ref(user_id, "script", getattr(task, "task_id", None) or getattr(task, "id", 0))
        if script_id:
            self.link(user_id, script_id, run_id, AssetRelationType.PRODUCES)
        defect_id = None
        if getattr(record, "status", "") == "failed":
            defect_id = self._upsert_ref(
                user_id,
                name=f"缺陷 #{record.id}",
                stage="07_defect",
                category="缺陷记录",
                content=getattr(record, "error_message", None) or getattr(record, "log_content", "") or "执行失败",
                source="auto",
                ref_type="defect",
                ref_id=record.id,
                project_id=project_id,
                status=AssetRegistryStatus.ACTIVE,
            )
            self.link(user_id, run_id, defect_id, AssetRelationType.CAUSED)
            created["defect"] = defect_id
        if getattr(record, "status", "") == "success" and getattr(record, "error_message", None):
            regression_id = self._upsert_ref(
                user_id,
                name=f"回归验证 #{record.id}",
                stage="08_regression",
                category="缺陷验证结果",
                content=getattr(record, "analysis_result", None) or "回归执行通过",
                source="auto",
                ref_type="regression",
                ref_id=record.id,
                project_id=project_id,
                status=AssetRegistryStatus.ACTIVE,
            )
            self.link(user_id, regression_id, defect_id or run_id, AssetRelationType.REGRESSED)
            created["regression"] = regression_id
        if getattr(record, "report_path", None) or getattr(record, "status", "") in {"success", "failed", "cancelled"}:
            report_id = self._upsert_ref(
                user_id,
                name=f"测试报告 #{record.id}",
                stage="09_report",
                category="测试报告",
                content=getattr(record, "report_path", None) or getattr(record, "analysis_result", None) or "",
                source="auto",
                ref_type="test_report",
                ref_id=record.id,
                project_id=project_id,
                status=AssetRegistryStatus.ACTIVE,
            )
            self.link(user_id, report_id, run_id, AssetRelationType.REPORTS)
            if script_id:
                self.link(user_id, report_id, script_id, AssetRelationType.CONTAINS)
            if defect_id:
                self.link(user_id, report_id, defect_id, AssetRelationType.CONTAINS)
            created["report"] = report_id
        return created

    def _upsert_ref(
        self,
        user_id: int,
        *,
        name: str,
        stage: str,
        category: str,
        content: str,
        source: str,
        ref_type: str,
        ref_id: int,
        project_id: Optional[int],
        status: str,
    ) -> int:
        existing = self._find_ref(user_id, ref_type, ref_id)
        if existing:
            return existing
        created = self.create_asset(
            user_id,
            name=name,
            stage=stage,
            category=category,
            content=str(content or "")[:8000],
            source=source,
            status=status,
            project_id=project_id,
            ref_type=ref_type,
            ref_id=int(ref_id or 0),
        )
        return int(created["id"])

    def _find_ref(self, user_id: int, ref_type: str, ref_id: int) -> Optional[int]:
        if not ref_id:
            return None
        db = SessionLocal()
        try:
            row = db.query(AssetRegistry).filter(
                AssetRegistry.user_id == user_id,
                AssetRegistry.ref_type == ref_type,
                AssetRegistry.ref_id == ref_id,
                AssetRegistry.is_deleted == False,  # noqa: E712
            ).first()
            return row.id if row else None
        finally:
            db.close()

    def _relation_counts(self, db: Session, ids: list[int]) -> dict[int, int]:
        if not ids:
            return {}
        rows = db.query(AssetRelation.source_id, func.count(AssetRelation.id)).filter(
            AssetRelation.source_id.in_(ids),
            AssetRelation.is_deleted == False,  # noqa: E712
        ).group_by(AssetRelation.source_id).all()
        counts = {row[0]: row[1] for row in rows}
        rows = db.query(AssetRelation.target_id, func.count(AssetRelation.id)).filter(
            AssetRelation.target_id.in_(ids),
            AssetRelation.is_deleted == False,  # noqa: E712
        ).group_by(AssetRelation.target_id).all()
        for asset_id, count in rows:
            counts[asset_id] = counts.get(asset_id, 0) + count
        return counts
