"""统一上传安全策略：大小、扩展名、声明 MIME、文件头（magic）必须同时通过。"""
from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, UploadFile

from app.core.config import settings

# 与 requirement_input / upload_task 共用的允许类别
ALLOWED_CATEGORIES = ("image", "pdf", "word", "video", "swagger", "schema")

_EXT_TO_CATEGORY = {
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".gif": "image",
    ".bmp": "image",
    ".pdf": "pdf",
    ".doc": "word",
    ".docx": "word",
    ".mp4": "video",
    ".avi": "video",
    ".mov": "video",
    ".mkv": "video",
    ".json": "swagger",
    ".yaml": "swagger",
    ".yml": "swagger",
    ".sql": "schema",
    ".ddl": "schema",
}

_CATEGORY_MIMES = {
    "image": {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif", "image/bmp"},
    "pdf": {"application/pdf"},
    "word": {
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/octet-stream",
    },
    "video": {"video/mp4", "video/x-msvideo", "video/quicktime", "video/x-matroska", "application/octet-stream"},
    "swagger": {"application/json", "application/x-yaml", "text/yaml", "text/x-yaml", "text/plain", "application/octet-stream"},
    "schema": {"text/plain", "application/sql", "application/octet-stream"},
}

_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+")


class UploadRejected(HTTPException):
    """上传被拒绝。size → 413，其余 → 400。"""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(status_code=status_code, detail=message)


@dataclass(frozen=True)
class ValidatedUpload:
    content: bytes
    category: str
    ext: str
    original_name: str
    safe_name: str
    size: int


def max_upload_bytes() -> int:
    return int(getattr(settings, "MAX_UPLOAD_SIZE", 10 * 1024 * 1024) or 10 * 1024 * 1024)


def _detect_category(content: bytes, ext: str) -> Optional[str]:
    if not content:
        return None
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image"
    if content.startswith(b"\xff\xd8\xff"):
        return "image"
    if content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
        return "image"
    if content.startswith(b"BM") and ext in {".bmp"}:
        return "image"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image"
    if content.startswith(b"%PDF"):
        return "pdf"
    if content.startswith(b"\xd0\xcf\x11\xe0"):
        return "word"
    if content.startswith(b"PK") and ext in {".docx"}:
        return "word"
    if len(content) >= 12 and content[4:8] == b"ftyp":
        return "video"
    if content.startswith(b"RIFF") and b"AVI" in content[8:16]:
        return "video"
    if ext in {".json", ".yaml", ".yml"} and _looks_like_swagger(content):
        return "swagger"
    if ext in {".sql", ".ddl"} and _looks_like_text(content):
        return "schema"
    return None


def _looks_like_text(content: bytes) -> bool:
    if b"\x00" in content[:4096]:
        return False
    try:
        content[:8192].decode("utf-8")
        return True
    except UnicodeDecodeError:
        try:
            content[:8192].decode("gbk")
            return True
        except UnicodeDecodeError:
            return False


def _looks_like_swagger(content: bytes) -> bool:
    if not _looks_like_text(content):
        return False
    head = content.lstrip()[:2048].lower()
    if head.startswith(b"{") or head.startswith(b"["):
        return True
    return b"openapi" in head or b"swagger" in head or head.startswith(b"---")


def _safe_filename(original: str, ext: str) -> str:
    base = os.path.basename(original or "file")
    stem, _ = os.path.splitext(base)
    stem = _UNSAFE_NAME.sub("_", stem).strip("._") or "file"
    stem = stem[:80]
    return f"{stem}_{uuid.uuid4().hex[:10]}{ext}"


def validate_upload_bytes(
    content: bytes,
    filename: str,
    declared_mime: Optional[str] = None,
    declared_category: str = "auto",
) -> ValidatedUpload:
    if not content:
        raise UploadRejected("空文件不能上传")

    limit = max_upload_bytes()
    if len(content) > limit:
        raise UploadRejected(
            f"文件大小超出限制（最大 {limit // 1024 // 1024}MB）",
            status_code=413,
        )

    original = os.path.basename(filename or "unknown")
    raw_ext = os.path.splitext(original)[1].lower()
    ext = ".jpg" if raw_ext == ".jpeg" else raw_ext

    ext_category = _EXT_TO_CATEGORY.get(ext)
    if not ext_category:
        raise UploadRejected(f"不支持的文件类型: {raw_ext or '无扩展名'}")

    if declared_category and declared_category != "auto":
        if declared_category not in ALLOWED_CATEGORIES:
            raise UploadRejected(f"不支持的文件类别: {declared_category}")
        if declared_category != ext_category:
            raise UploadRejected("文件扩展名与声明类别不一致")

    detected = _detect_category(content, ext if ext != ".jpg" else raw_ext)
    if not detected:
        raise UploadRejected("文件内容与扩展名不符，已拒绝（禁止伪造扩展名）")
    if detected != ext_category:
        raise UploadRejected("文件真实类型与扩展名不一致")

    mime = (declared_mime or "").split(";")[0].strip().lower()
    if mime and mime != "application/octet-stream":
        allowed_mimes = _CATEGORY_MIMES.get(detected, set())
        if mime not in allowed_mimes:
            raise UploadRejected(f"不支持的文件 MIME 类型: {mime}")

    save_ext = raw_ext or ext
    return ValidatedUpload(
        content=content,
        category=detected,
        ext=save_ext,
        original_name=original,
        safe_name=_safe_filename(original, save_ext),
        size=len(content),
    )


async def validate_upload_file(
    file: UploadFile,
    declared_category: str = "auto",
) -> ValidatedUpload:
    content = await file.read()
    return validate_upload_bytes(
        content=content,
        filename=file.filename or "unknown",
        declared_mime=file.content_type,
        declared_category=declared_category,
    )
