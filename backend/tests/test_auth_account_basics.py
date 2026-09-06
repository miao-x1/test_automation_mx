"""注册 / 验证码 / 短信 / 忘记密码基础能力。"""
import os
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))
os.environ.setdefault("USE_SQLITE", "True")
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SMS_PROVIDER", "console")
os.environ.setdefault("SMS_ECHO_CODE", "True")
os.environ.setdefault("CAPTCHA_REQUIRED", "True")

from app.services.captcha_service import create_captcha, verify_captcha
from app.services.sms_provider import mask_phone


def test_captcha_roundtrip():
    payload = create_captcha()
    assert payload["captcha_id"]
    assert payload["image"].startswith("data:image/svg+xml")
    assert verify_captcha(payload["captcha_id"], payload["debug_text"])
    assert not verify_captcha(payload["captcha_id"], payload["debug_text"])


def test_captcha_rejects_wrong_text():
    payload = create_captcha()
    assert not verify_captcha(payload["captcha_id"], "XXXX")


def test_phone_mask():
    assert mask_phone("13812345678") == "138****5678"


if __name__ == "__main__":
    test_captcha_roundtrip()
    test_captcha_rejects_wrong_text()
    test_phone_mask()
    print("ok")
