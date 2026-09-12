"""Project Memory：绑定 User → Organization → Project，跨三个工作区共享。"""
from __future__ import annotations

import json
from typing import Any, Optional

from app.db.database import SessionLocal
from app.models.project_explorer import ProjectMemoryItem
from app.models.team import Project


KINDS = {
    "understanding", "structure", "question", "confirmed", "focus",
    "conclusion", "test_design", "test_execution", "message",
}


class ProjectMemoryService:
    def snapshot(self, user_id: int, project_id: int) -> dict[str, Any]:
        db = SessionLocal()
        try:
            rows = db.query(ProjectMemoryItem).filter(
                ProjectMemoryItem.user_id == user_id,
                ProjectMemoryItem.project_id == project_id,
            ).order_by(ProjectMemoryItem.updated_at.desc()).all()
            grouped: dict[str, list[dict[str, Any]]] = {kind: [] for kind in KINDS}
            messages = []
            for row in rows:
                item = self._row(row)
                if row.kind == "message":
                    messages.append(item)
                else:
                    grouped.setdefault(row.kind, []).append(item)
            return {
                "project_id": project_id,
                "counts": {kind: len(items) for kind, items in grouped.items()},
                "understanding": grouped.get("understanding", [])[:8],
                "structure": grouped.get("structure", [])[:8],
                "questions": grouped.get("question", [])[:12],
                "confirmed": grouped.get("confirmed", [])[:12],
                "focus": grouped.get("focus", [])[:12],
                "conclusions": grouped.get("conclusion", [])[:12],
                "test_design": grouped.get("test_design", [])[:8],
                "test_execution": grouped.get("test_execution", [])[:8],
                "messages": list(reversed(messages[:40])),
            }
        finally:
            db.close()

    def remember(
        self,
        user_id: int,
        project_id: int,
        *,
        kind: str,
        title: str,
        content: str,
        workspace: Optional[str] = None,
        role: Optional[str] = None,
        extra: Optional[dict[str, Any]] = None,
        test_task_id: Optional[int] = None,
    ) -> dict[str, Any]:
        if kind not in KINDS:
            raise ValueError("未知记忆类型")
        db = SessionLocal()
        try:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                raise ValueError("项目不存在")
            row = None
            if kind != "message":
                row = db.query(ProjectMemoryItem).filter(
                    ProjectMemoryItem.user_id == user_id,
                    ProjectMemoryItem.project_id == project_id,
                    ProjectMemoryItem.kind == kind,
                    ProjectMemoryItem.title == title[:255],
                ).first()
            if not row:
                row = ProjectMemoryItem(
                    user_id=user_id,
                    created_by=user_id,
                    organization_id=project.organization_id,
                    project_id=project_id,
                )
                db.add(row)
            row.kind = kind
            row.title = title[:255]
            row.content = content
            row.workspace = workspace
            row.role = role
            packed = dict(extra or {})
            if test_task_id:
                packed["test_task_id"] = test_task_id
            row.extra_json = json.dumps(packed, ensure_ascii=False) if packed else None
            if hasattr(row, "test_task_id") and test_task_id:
                row.test_task_id = test_task_id
            db.commit()
            db.refresh(row)
            return self._row(row)
        finally:
            db.close()

    def search(self, user_id: int, project_id: int, keyword: str, limit: int = 12) -> list[dict[str, Any]]:
        db = SessionLocal()
        try:
            like = f"%{keyword.strip()}%"
            rows = db.query(ProjectMemoryItem).filter(
                ProjectMemoryItem.user_id == user_id,
                ProjectMemoryItem.project_id == project_id,
                (ProjectMemoryItem.title.like(like)) | (ProjectMemoryItem.content.like(like)),
            ).order_by(ProjectMemoryItem.updated_at.desc()).limit(limit * 3).all()
            preferred = [row for row in rows if row.kind in {"conclusion", "focus", "understanding", "confirmed", "test_design", "test_execution"}]
            rest = [row for row in rows if row not in preferred]
            return [self._row(row) for row in (preferred + rest)[:limit]]
        finally:
            db.close()

    @staticmethod
    def _row(row: ProjectMemoryItem) -> dict[str, Any]:
        extra = {}
        if row.extra_json:
            try:
                extra = json.loads(row.extra_json)
            except Exception:
                extra = {}
        return {
            "id": row.id,
            "kind": row.kind,
            "title": row.title,
            "content": row.content,
            "workspace": row.workspace,
            "role": row.role,
            "extra": extra,
            "test_task_id": getattr(row, "test_task_id", None) or extra.get("test_task_id"),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
