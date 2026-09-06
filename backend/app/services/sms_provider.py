"""短信发送适配：console / http / aliyun。从不在日志打印完整手机号。"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from app.core.config import settings
from app.core.logger import log


def mask_phone(phone: str) -> str:
    if len(phone) < 7:
        return "***"
    return f"{phone[:3]}****{phone[-4:]}"


class SmsError(RuntimeError):
    pass


def send_sms(phone: str, code: str, purpose: str) -> None:
    provider = (settings.SMS_PROVIDER or "console").strip().lower()
    if provider == "console":
        log.info(f"SMS_CONSOLE | to={mask_phone(phone)} | purpose={purpose} | code={code}")
        return
    if provider == "http":
        _send_http(phone, code, purpose)
        return
    if provider == "aliyun":
        _send_aliyun(phone, code)
        return
    raise SmsError("未支持的短信通道")


def _send_http(phone: str, code: str, purpose: str) -> None:
    url = (settings.SMS_WEBHOOK_URL or "").strip()
    if not url:
        raise SmsError("未配置 SMS_WEBHOOK_URL")
    payload = json.dumps({
        "phone": phone,
        "code": code,
        "purpose": purpose,
        "token": settings.SMS_WEBHOOK_TOKEN or "",
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status >= 300:
                raise SmsError("短信网关返回失败")
    except SmsError:
        raise
    except Exception as exc:
        log.warning(f"SMS_HTTP_FAIL | to={mask_phone(phone)} | error={exc}")
        raise SmsError("短信发送失败") from exc


def _send_aliyun(phone: str, code: str) -> None:
    access_key = (settings.SMS_ACCESS_KEY_ID or "").strip()
    secret = (settings.SMS_ACCESS_KEY_SECRET or "").strip()
    sign_name = (settings.SMS_SIGN_NAME or "").strip()
    template = (settings.SMS_TEMPLATE_CODE or "").strip()
    if not all([access_key, secret, sign_name, template]):
        raise SmsError("阿里云短信未配置完整")

    params = {
        "AccessKeyId": access_key,
        "Action": "SendSms",
        "Format": "JSON",
        "PhoneNumbers": phone,
        "RegionId": "cn-hangzhou",
        "SignName": sign_name,
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": str(time.time_ns()),
        "SignatureVersion": "1.0",
        "TemplateCode": template,
        "TemplateParam": json.dumps({"code": code}, ensure_ascii=False),
        "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "Version": "2017-05-25",
    }
    query = "&".join(
        f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(str(v), safe='')}"
        for k, v in sorted(params.items())
    )
    string_to_sign = "GET&%2F&" + urllib.parse.quote(query, safe="")
    key = (secret + "&").encode("utf-8")
    signature = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha1).digest()
    import base64
    params["Signature"] = base64.b64encode(signature).decode("ascii")
    url = "https://dysmsapi.aliyuncs.com/?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if body.get("Code") != "OK":
            log.warning(f"SMS_ALIYUN_FAIL | to={mask_phone(phone)} | code={body.get('Code')}")
            raise SmsError("短信发送失败")
    except SmsError:
        raise
    except Exception as exc:
        log.warning(f"SMS_ALIYUN_FAIL | to={mask_phone(phone)} | error={exc}")
        raise SmsError("短信发送失败") from exc
