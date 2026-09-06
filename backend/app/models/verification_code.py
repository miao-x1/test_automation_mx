"""短信验证码持久化（跨 worker 生效，不存明文）。"""
from sqlalchemy import Column, String, DateTime, Boolean, Index

from app.models.base import BaseModel


class VerificationPurpose:
    REGISTER = "register"
    RESET = "reset"


class VerificationCode(BaseModel):
    __tablename__ = "verification_code"

    phone = Column(String(20), nullable=False, index=True, comment="手机号")
    purpose = Column(String(20), nullable=False, comment="用途: register/reset")
    code_hash = Column(String(64), nullable=False, comment="验证码哈希")
    expires_at = Column(DateTime, nullable=False, comment="过期时间")
    consumed = Column(Boolean, nullable=False, default=False, comment="是否已使用")
    request_ip = Column(String(64), nullable=True, comment="请求 IP")


Index("idx_verify_phone_purpose", VerificationCode.phone, VerificationCode.purpose)
