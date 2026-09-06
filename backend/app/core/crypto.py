"""
敏感数据加密工具

基于 cryptography.Fernet 实现对称加密,用于保护测试环境中的
数据库密码、API Key、API Secret 等敏感信息。

特点:
1. Fernet 对称加密(AES-128-CBC + HMAC-SHA256)
2. 主密钥从 SECRET_KEY 派生(无需额外配置)
3. 提供 encrypt() / decrypt() 函数
4. 提供 mask() 函数(脱敏显示,如 "sk-***1234")
5. 纯函数,无状态,线程安全

使用方式:
    from app.core.crypto import encrypt, decrypt, mask

    cipher = encrypt("my_password")
    # 'gAAAAABh...=='
    plain = decrypt(cipher)
    # 'my_password'

    mask("sk-abcdef123456")
    # 'sk-***3456'

设计要点:
- 加密失败不抛异常,返回 None(避免日志泄漏)
- 解密失败返回原文(兼容历史明文数据)
- 密钥派生使用 PBKDF2HMAC + SHA256,迭代 480000 次
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

# 派生密钥用的固定 salt(不改也不影响安全性,只是让相同 SECRET_KEY 产出相同 Fernet key)
# 16 bytes,base64 后 22 字符
_SALT = b"test_automation_env_salt_v1"

# 缓存的 Fernet 实例(进程级单例)
_fernet: Optional[Fernet] = None


def _get_fernet() -> Fernet:
    """获取 Fernet 实例(单例)

    从 settings.SECRET_KEY 派生 32 字节密钥,再用 Fernet 构建。
    """
    global _fernet
    if _fernet is not None:
        return _fernet

    from app.core.config import settings

    secret = settings.SECRET_KEY
    if not secret:
        raise RuntimeError("SECRET_KEY 未配置，无法派生加密密钥")

    # 用 PBKDF2HMAC 从 SECRET_KEY 派生 32 字节密钥
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        iterations=480000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(secret.encode("utf-8")))

    _fernet = Fernet(key)
    return _fernet


def encrypt(plaintext: Optional[str]) -> Optional[str]:
    """加密明文

    Args:
        plaintext: 待加密的明文(为 None 或空串则原样返回)

    Returns:
        加密后的密文(base64 字符串,以 'gAAAAA' 开头)
        若 plaintext 为 None/空串,原样返回

    Raises:
        无(加密失败返回 None,并记录日志)
    """
    if plaintext is None:
        return None
    if plaintext == "":
        return ""

    # 已经是密文的不再重复加密(简单判断:以 gAAAAA 开头)
    if plaintext.startswith("gAAAAA"):
        return plaintext

    try:
        f = _get_fernet()
        token = f.encrypt(plaintext.encode("utf-8"))
        return token.decode("utf-8")
    except Exception as e:
        logger.error(f"[crypto] encrypt failed: {e}", exc_info=True)
        return None


def decrypt(ciphertext: Optional[str]) -> Optional[str]:
    """解密密文

    Args:
        ciphertext: 待解密的密文

    Returns:
        解密后的明文
        若 ciphertext 为 None/空串,原样返回
        若解密失败(非密文或密钥不匹配),返回原文(兼容历史明文数据)
    """
    if ciphertext is None:
        return None
    if ciphertext == "":
        return ""

    # 非密文(不以 gAAAAA 开头)直接返回原文
    if not ciphertext.startswith("gAAAAA"):
        return ciphertext

    try:
        f = _get_fernet()
        plain = f.decrypt(ciphertext.encode("utf-8"))
        return plain.decode("utf-8")
    except InvalidToken:
        # 密钥不匹配或数据损坏,返回原文(可能是明文数据)
        logger.warning("[crypto] decrypt failed (invalid token), returning raw value")
        return ciphertext
    except Exception as e:
        logger.error(f"[crypto] decrypt failed: {e}", exc_info=True)
        return ciphertext


def is_encrypted(value: Optional[str]) -> bool:
    """判断字符串是否为加密后的密文"""
    if not value:
        return False
    return value.startswith("gAAAAA")


def mask(value: Optional[str], visible_chars: int = 4) -> str:
    """脱敏显示

    保留最后 visible_chars 个字符,前面用 *** 代替。
    对于短于 visible_chars 的字符串,全部用 *** 代替。

    Args:
        value: 原始值(可能是明文或密文)
        visible_chars: 保留可见字符数

    Returns:
        脱敏后的字符串,如 "sk-***3456"
    """
    if value is None:
        return ""
    if value == "":
        return ""

    # 如果是密文,先解密
    plain = decrypt(value)

    if plain is None or plain == "":
        return "***"

    if len(plain) <= visible_chars:
        return "***"

    return f"***{plain[-visible_chars:]}"


def generate_key() -> str:
    """生成一个新的 Fernet 密钥(用于初始化或轮换)

    Returns:
        base64 编码的密钥字符串
    """
    return Fernet.generate_key().decode("utf-8")


def reset_fernet() -> None:
    """重置缓存的 Fernet 实例(测试用)"""
    global _fernet
    _fernet = None
