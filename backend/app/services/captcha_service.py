"""自托管图形验证码（SVG，无第三方）。"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from threading import Lock

from app.core.config import settings

_TTL_SECONDS = 300
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_store: dict[str, tuple[str, float]] = {}
_lock = Lock()


def _hash_text(captcha_id: str, text: str) -> str:
    raw = f"{captcha_id}:{text.upper()}".encode("utf-8")
    return hmac.new(settings.SECRET_KEY.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def _purge_locked(now: float) -> None:
    expired = [key for key, (_, exp) in _store.items() if exp <= now]
    for key in expired:
        _store.pop(key, None)


def _svg(text: str) -> str:
    chars = []
    for i, ch in enumerate(text):
        x = 18 + i * 28
        y = 28 + (i % 2) * 4
        rotate = (i * 11) % 17 - 8
        chars.append(
            f'<text x="{x}" y="{y}" fill="#1c1c1c" font-size="26" '
            f'font-family="monospace" transform="rotate({rotate} {x} {y})">{ch}</text>'
        )
    lines = []
    for i in range(4):
        lines.append(
            f'<line x1="{8 + i * 17}" y1="{8 + (i * 9) % 24}" '
            f'x2="{110 - i * 13}" y2="{36 - (i * 5) % 18}" '
            f'stroke="#c8c2bb" stroke-width="1"/>'
        )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="140" height="44" '
        'viewBox="0 0 140 44" role="img" aria-label="captcha">'
        '<rect width="140" height="44" fill="#f6f3ee"/>'
        + "".join(lines)
        + "".join(chars)
        + "</svg>"
    )


def create_captcha() -> dict:
    text = "".join(secrets.choice(_ALPHABET) for _ in range(4))
    captcha_id = secrets.token_urlsafe(16)
    now = time.time()
    with _lock:
        _purge_locked(now)
        _store[captcha_id] = (_hash_text(captcha_id, text), now + _TTL_SECONDS)
    return {
        "captcha_id": captcha_id,
        "image": "data:image/svg+xml;utf8," + _svg(text).replace("#", "%23"),
        "expires_in": _TTL_SECONDS,
        "debug_text": text,
    }


def verify_captcha(captcha_id: str, text: str, *, consume: bool = True) -> bool:
    if not captcha_id or not text:
        return False
    now = time.time()
    with _lock:
        _purge_locked(now)
        item = _store.get(captcha_id)
        if not item:
            return False
        digest, exp = item
        if exp <= now:
            _store.pop(captcha_id, None)
            return False
        ok = hmac.compare_digest(digest, _hash_text(captcha_id, text.strip()))
        if consume:
            _store.pop(captcha_id, None)
        return ok
