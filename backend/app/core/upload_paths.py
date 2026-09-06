"""把上传接口返回的相对路径解析成磁盘上的真实文件。"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional

from app.core.config import settings


def resolve_upload_path(path: str) -> str:
    text = (path or "").strip()
    if not text:
        return ""
    raw = Path(text)
    if raw.is_file():
        return str(raw.resolve())
    joined = Path(settings.UPLOAD_DIR) / text
    if joined.is_file():
        return str(joined.resolve())
    return str(joined)


def resolve_upload_paths(paths: Optional[Iterable[str]]) -> List[str]:
    if not paths:
        return []
    resolved: List[str] = []
    for item in paths:
        if isinstance(item, str) and item.strip():
            resolved.append(resolve_upload_path(item))
    return resolved
