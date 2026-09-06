"""短信验证码签发与校验。"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.verification_code import VerificationCode, VerificationPurpose
from app.services.sms_provider import SmsError, send_sms


class VerifyError(RuntimeError):
    pass


_PURPOSES = {VerificationPurpose.REGISTER, VerificationPurpose.RESET}


def _hash_code(phone: str, purpose: str, code: str) -> str:
    raw = f"{phone}:{purpose}:{code}".encode("utf-8")
    return hmac.new(settings.SECRET_KEY.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def issue_sms_code(db: Session, phone: str, purpose: str, ip: str | None = None) -> str:
    if purpose not in _PURPOSES:
        raise VerifyError("验证码用途无效")
    now = datetime.now()
    recent = (
        db.query(VerificationCode)
        .filter(
            VerificationCode.phone == phone,
            VerificationCode.purpose == purpose,
            VerificationCode.created_at >= now - timedelta(seconds=settings.SMS_RESEND_SECONDS),
        )
        .order_by(VerificationCode.id.desc())
        .first()
    )
    if recent:
        raise VerifyError(f"发送过于频繁，请 {settings.SMS_RESEND_SECONDS} 秒后再试")

    code = f"{secrets.randbelow(1000000):06d}"
    row = VerificationCode(
        phone=phone,
        purpose=purpose,
        code_hash=_hash_code(phone, purpose, code),
        expires_at=now + timedelta(seconds=settings.SMS_CODE_TTL_SECONDS),
        consumed=False,
        request_ip=ip,
    )
    db.add(row)
    db.commit()
    try:
        send_sms(phone, code, purpose)
    except SmsError as exc:
        raise VerifyError(str(exc)) from exc
    return code


def consume_sms_code(db: Session, phone: str, purpose: str, code: str) -> None:
    if purpose not in _PURPOSES or not code:
        raise VerifyError("验证码无效")
    now = datetime.now()
    digest = _hash_code(phone, purpose, code.strip())
    row = (
        db.query(VerificationCode)
        .filter(
            VerificationCode.phone == phone,
            VerificationCode.purpose == purpose,
            VerificationCode.consumed.is_(False),
            VerificationCode.expires_at >= now,
        )
        .order_by(VerificationCode.id.desc())
        .first()
    )
    if not row or not hmac.compare_digest(row.code_hash, digest):
        raise VerifyError("验证码错误或已过期")
    row.consumed = True
    db.commit()
