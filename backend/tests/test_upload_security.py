"""P0-6: 上传大小 / 类型 / magic-bytes 统一校验。"""
import os
import sys
from io import BytesIO
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))
os.environ.setdefault("USE_SQLITE", "True")
os.environ.setdefault("APP_ENV", "development")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.upload_security import UploadRejected, validate_upload_bytes, max_upload_bytes
from app.api.requirement_input import router as requirement_input_router

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
PDF = b"%PDF-1.4\n" + b"1 0 obj\n" + b"\x00" * 16
JSON_SWAGGER = b'{"openapi":"3.0.0","info":{"title":"t","version":"1"}}'
SQL = b"CREATE TABLE users (id INT);\n"


def test_normal_png():
    v = validate_upload_bytes(PNG, "shot.png", "image/png")
    assert v.category == "image"
    assert v.size == len(PNG)
    assert v.original_name == "shot.png"


def test_chinese_filename():
    v = validate_upload_bytes(PNG, "登录页面截图.png", "image/png")
    assert v.category == "image"
    assert "登录页面截图" in v.safe_name
    assert v.safe_name.endswith(".png")


def test_special_char_filename():
    v = validate_upload_bytes(PNG, "a<script>../x.png", "image/png")
    assert v.category == "image"
    assert "<" not in v.safe_name
    assert "/" not in v.safe_name
    assert ".." not in v.safe_name


def test_empty_file_rejected():
    with pytest.raises(UploadRejected) as exc:
        validate_upload_bytes(b"", "empty.png", "image/png")
    assert exc.value.status_code == 400
    assert "空文件" in str(exc.value.detail)


def test_oversized_rejected(monkeypatch):
    from app.core import upload_security as us

    monkeypatch.setattr(us.settings, "MAX_UPLOAD_SIZE", 64)
    with pytest.raises(UploadRejected) as exc:
        validate_upload_bytes(PNG + b"x" * 80, "big.png", "image/png")
    assert exc.value.status_code == 413
    assert "超出限制" in str(exc.value.detail)


def test_non_image_extension_rejected():
    with pytest.raises(UploadRejected) as exc:
        validate_upload_bytes(b"hello world", "notes.txt", "text/plain")
    assert exc.value.status_code == 400
    assert "不支持的文件类型" in str(exc.value.detail)


def test_spoofed_extension_rejected():
    with pytest.raises(UploadRejected) as exc:
        validate_upload_bytes(b"MZ\x90\x00this is not a png", "malware.png", "image/png")
    assert exc.value.status_code == 400
    assert "不符" in str(exc.value.detail) or "不一致" in str(exc.value.detail)


def test_pdf_and_swagger_ok():
    pdf = validate_upload_bytes(PDF, "需求.pdf", "application/pdf")
    assert pdf.category == "pdf"
    swagger = validate_upload_bytes(JSON_SWAGGER, "openapi.json", "application/json")
    assert swagger.category == "swagger"
    schema = validate_upload_bytes(SQL, "schema.sql", "text/plain")
    assert schema.category == "schema"


def test_declared_category_mismatch():
    with pytest.raises(UploadRejected):
        validate_upload_bytes(PNG, "shot.png", "image/png", declared_category="pdf")


def _client():
    app = FastAPI()
    app.include_router(requirement_input_router, prefix="/api/v1/requirement-input")
    return TestClient(app)


def test_requirement_input_upload_png_http():
    client = _client()
    resp = client.post(
        "/api/v1/requirement-input/upload",
        files={"file": ("正常图片.png", BytesIO(PNG), "image/png")},
        data={"file_category": "image"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["file_type"] == "image"
    assert os.path.isfile(body["file_path"])
    os.remove(body["file_path"])


def test_requirement_input_reject_txt_http():
    client = _client()
    resp = client.post(
        "/api/v1/requirement-input/upload",
        files={"file": ("notes.txt", BytesIO(b"not an image"), "text/plain")},
        data={"file_category": "auto"},
    )
    assert resp.status_code == 400
    assert "不支持" in resp.json()["detail"]


def test_requirement_input_reject_empty_http():
    client = _client()
    resp = client.post(
        "/api/v1/requirement-input/upload",
        files={"file": ("empty.png", BytesIO(b""), "image/png")},
        data={"file_category": "image"},
    )
    assert resp.status_code == 400
    assert "空文件" in resp.json()["detail"]


def test_requirement_input_reject_spoof_http():
    client = _client()
    resp = client.post(
        "/api/v1/requirement-input/upload",
        files={"file": ("fake.png", BytesIO(b"just text pretending"), "image/png")},
        data={"file_category": "image"},
    )
    assert resp.status_code == 400


def test_requirement_input_reject_oversize_http(monkeypatch):
    from app.core import upload_security as us

    monkeypatch.setattr(us.settings, "MAX_UPLOAD_SIZE", 32)
    client = _client()
    resp = client.post(
        "/api/v1/requirement-input/upload",
        files={"file": ("big.png", BytesIO(PNG + b"z" * 64), "image/png")},
        data={"file_category": "image"},
    )
    assert resp.status_code == 413
    assert "超出限制" in resp.json()["detail"]


def test_max_upload_bytes_default():
    assert max_upload_bytes() >= 1024


def _requirement_client():
    from app.api.requirement import router as requirement_router

    app = FastAPI()
    app.include_router(requirement_router, prefix="/requirement")
    return TestClient(app)


def _upload_dir_snapshot():
    from app.core.config import settings

    image_dir = Path(settings.UPLOAD_DIR) / "requirement_images"
    if not image_dir.exists():
        return set()
    return {p.name for p in image_dir.iterdir() if p.is_file()}


def test_requirement_upload_images_valid_png():
    client = _requirement_client()
    before = _upload_dir_snapshot()
    resp = client.post(
        "/requirement/upload_images",
        files=[("files", ("shot.png", BytesIO(PNG), "image/png"))],
    )
    assert resp.status_code == 200
    body = resp.json()
    paths = (body.get("data") or {}).get("image_paths") or []
    assert paths and paths[0].endswith(".png")
    from app.core.config import settings
    full = Path(settings.UPLOAD_DIR) / paths[0]
    assert full.is_file()
    full.unlink()
    leftover = _upload_dir_snapshot() - before
    for name in leftover:
        (Path(settings.UPLOAD_DIR) / "requirement_images" / name).unlink(missing_ok=True)


def test_requirement_upload_images_valid_jpeg():
    client = _requirement_client()
    resp = client.post(
        "/requirement/upload_images",
        files=[("files", ("shot.jpg", BytesIO(JPEG), "image/jpeg"))],
    )
    assert resp.status_code == 200
    paths = (resp.json().get("data") or {}).get("image_paths") or []
    assert paths and (paths[0].endswith(".jpg") or paths[0].endswith(".jpeg"))
    from app.core.config import settings
    full = Path(settings.UPLOAD_DIR) / paths[0]
    assert full.is_file()
    full.unlink()


def test_requirement_upload_images_fake_png_rejected():
    client = _requirement_client()
    before = _upload_dir_snapshot()
    resp = client.post(
        "/requirement/upload_images",
        files=[("files", ("evil.png", BytesIO(b"not-a-real-png"), "image/png"))],
    )
    assert resp.status_code in {400, 415, 422}
    after = _upload_dir_snapshot()
    assert after == before


def test_requirement_upload_images_fake_jpeg_rejected():
    client = _requirement_client()
    before = _upload_dir_snapshot()
    resp = client.post(
        "/requirement/upload_images",
        files=[("files", ("evil.jpg", BytesIO(b"JFIF-but-not-really"), "image/jpeg"))],
    )
    assert resp.status_code in {400, 415, 422}
    assert _upload_dir_snapshot() == before


def test_requirement_upload_images_oversized(monkeypatch):
    from app.core import upload_security as us
    from app.core.config import settings

    monkeypatch.setattr(us.settings, "MAX_UPLOAD_SIZE", 32)
    client = _requirement_client()
    before = _upload_dir_snapshot()
    resp = client.post(
        "/requirement/upload_images",
        files=[("files", ("big.png", BytesIO(PNG + b"z" * 64), "image/png"))],
    )
    assert resp.status_code == 413
    assert _upload_dir_snapshot() == before


def test_requirement_upload_images_invalid_extension():
    client = _requirement_client()
    before = _upload_dir_snapshot()
    resp = client.post(
        "/requirement/upload_images",
        files=[("files", ("notes.exe", BytesIO(PNG), "image/png"))],
    )
    assert resp.status_code in {400, 415, 422}
    assert _upload_dir_snapshot() == before


def test_requirement_upload_images_mismatched_mime():
    client = _requirement_client()
    before = _upload_dir_snapshot()
    resp = client.post(
        "/requirement/upload_images",
        files=[("files", ("shot.png", BytesIO(PNG), "application/pdf"))],
    )
    assert resp.status_code in {400, 415, 422}
    assert _upload_dir_snapshot() == before
