"""
API Key 管理服务

功能:
  1. 创建 API Key(明文只返回一次,存储 SHA-256 哈希)
  2. 验证 API Key(哈希比对)
  3. 撤销/停用 API Key
  4. 查询/列表 API Key(脱敏显示)
  5. 使用统计(记录 last_used_at / last_used_ip / usage_count)
  6. 过期检查

安全设计:
  - 明文 API Key 仅在创建时返回一次,之后不可查询
  - 数据库存储 SHA-256 哈希(不可逆)
  - key_prefix 存储前12位用于展示识别
  - 支持 scope 权限范围
  - 支持 expires_at 过期时间
  - 撤销操作记录审计事件
"""
import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.security import ApiKey

logger = logging.getLogger(__name__)


class ApiKeyService:
    """API Key 管理服务"""

    # 不可更新字段
    _IMMUTABLE = {"id", "created_at", "updated_at", "user_id", "created_by",
                  "key_hash", "key_prefix"}

    def create_key(
        self,
        *,
        name: str,
        description: str = "",
        scopes: Optional[List[str]] = None,
        expires_at: Optional[datetime] = None,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """创建 API Key

        Args:
            name: Key名称
            description: 描述
            scopes: 权限范围列表
            expires_at: 过期时间
            user_id: 用户ID

        Returns:
            包含 plaintext_key(仅此一次) + key信息
        """
        if not name or not name.strip():
            raise ValueError("name is required")

        # 生成密钥
        plaintext_key, key_prefix, key_hash = ApiKey.generate_key()

        db = SessionLocal()
        try:
            api_key = ApiKey(
                name=name.strip(),
                description=description,
                key_prefix=key_prefix,
                key_hash=key_hash,
                scopes=json.dumps(scopes, ensure_ascii=False) if scopes else None,
                expires_at=expires_at,
                is_active=True,
                is_deleted=False,
                usage_count=0,
                user_id=user_id,
                created_by=user_id,
            )
            db.add(api_key)
            db.commit()
            db.refresh(api_key)

            result = api_key.to_dict()
            result["plaintext_key"] = plaintext_key  # 明文仅返回一次
            result["warning"] = "请妥善保存 API Key,此为唯一一次明文展示"

            logger.info(
                f"[ApiKeyService] 创建API Key id={api_key.id} "
                f"name={name} prefix={key_prefix}"
            )
            return result
        finally:
            db.close()

    def validate_key(self, plaintext_key: str) -> Optional[Dict[str, Any]]:
        """验证 API Key

        Args:
            plaintext_key: 明文API Key

        Returns:
            有效则返回Key信息(含scope),无效返回None
        """
        if not plaintext_key:
            return None

        key_hash = ApiKey.hash_key(plaintext_key)

        db = SessionLocal()
        try:
            api_key = db.query(ApiKey).filter(
                ApiKey.key_hash == key_hash,
                ApiKey.is_active == True,
                ApiKey.is_deleted == False,
            ).first()

            if api_key is None:
                return None

            # 检查过期
            if api_key._is_expired():
                logger.warning(
                    f"[ApiKeyService] API Key已过期 id={api_key.id}"
                )
                return None

            return api_key.to_dict()
        finally:
            db.close()

    def record_usage(
        self,
        key_id: int,
        ip_address: Optional[str] = None,
    ) -> None:
        """记录API Key使用

        Args:
            key_id: Key ID
            ip_address: 请求IP
        """
        db = SessionLocal()
        try:
            api_key = db.query(ApiKey).filter(
                ApiKey.id == key_id
            ).first()
            if api_key:
                api_key.last_used_at = datetime.now()
                api_key.last_used_ip = ip_address
                api_key.usage_count = (api_key.usage_count or 0) + 1
                db.commit()
        except Exception as e:
            logger.error(f"[ApiKeyService] 记录使用失败: {e}")
            db.rollback()
        finally:
            db.close()

    def revoke_key(
        self,
        key_id: int,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """撤销API Key(停用)

        Args:
            key_id: Key ID
            user_id: 操作者用户ID(数据隔离)
        """
        db = SessionLocal()
        try:
            q = db.query(ApiKey).filter(
                ApiKey.id == key_id,
                ApiKey.is_deleted == False,
            )
            if user_id is not None:
                q = q.filter(ApiKey.user_id == user_id)
            api_key = q.first()
            if api_key is None:
                raise ValueError(f"ApiKey not found: {key_id}")

            api_key.is_active = False
            db.commit()
            db.refresh(api_key)

            logger.info(f"[ApiKeyService] 撤销API Key id={key_id}")
            return api_key.to_dict()
        finally:
            db.close()

    def list_keys(
        self,
        *,
        is_active: Optional[bool] = None,
        user_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """API Key列表(分页,脱敏)"""
        db = SessionLocal()
        try:
            q = db.query(ApiKey).filter(ApiKey.is_deleted == False)
            if user_id is not None:
                q = q.filter(ApiKey.user_id == user_id)
            if is_active is not None:
                q = q.filter(ApiKey.is_active == is_active)

            total = q.count()
            items = (
                q.order_by(desc(ApiKey.created_at))
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            return {
                "items": [k.to_dict() for k in items],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        finally:
            db.close()

    def get_key(
        self,
        key_id: int,
        *,
        user_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """获取API Key详情"""
        db = SessionLocal()
        try:
            q = db.query(ApiKey).filter(
                ApiKey.id == key_id,
                ApiKey.is_deleted == False,
            )
            if user_id is not None:
                q = q.filter(ApiKey.user_id == user_id)
            api_key = q.first()
            return None if api_key is None else api_key.to_dict()
        finally:
            db.close()

    def update_key(
        self,
        key_id: int,
        payload: Dict[str, Any],
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """更新API Key信息(名称/描述/范围/过期)"""
        db = SessionLocal()
        try:
            q = db.query(ApiKey).filter(
                ApiKey.id == key_id,
                ApiKey.is_deleted == False,
            )
            if user_id is not None:
                q = q.filter(ApiKey.user_id == user_id)
            api_key = q.first()
            if api_key is None:
                raise ValueError(f"ApiKey not found: {key_id}")

            for key, value in payload.items():
                if key in self._IMMUTABLE:
                    continue
                if key == "scopes" and isinstance(value, list):
                    value = json.dumps(value, ensure_ascii=False)
                if hasattr(api_key, key):
                    setattr(api_key, key, value)

            db.commit()
            db.refresh(api_key)
            return api_key.to_dict()
        finally:
            db.close()

    def delete_key(
        self,
        key_id: int,
        *,
        hard: bool = False,
        user_id: Optional[int] = None,
    ) -> bool:
        """删除API Key"""
        db = SessionLocal()
        try:
            q = db.query(ApiKey).filter(
                ApiKey.id == key_id,
                ApiKey.is_deleted == False,
            )
            if user_id is not None:
                q = q.filter(ApiKey.user_id == user_id)
            api_key = q.first()
            if api_key is None:
                return False
            if hard:
                db.delete(api_key)
            else:
                api_key.is_deleted = True
                api_key.is_active = False
            db.commit()
            return True
        finally:
            db.close()

    def cleanup_expired(self) -> int:
        """清理已过期的Key(停用)"""
        db = SessionLocal()
        try:
            now = datetime.now()
            expired_keys = db.query(ApiKey).filter(
                ApiKey.is_active == True,
                ApiKey.is_deleted == False,
                ApiKey.expires_at.isnot(None),
                ApiKey.expires_at < now,
            ).all()

            count = 0
            for key in expired_keys:
                key.is_active = False
                count += 1

            if count > 0:
                db.commit()
                logger.info(f"[ApiKeyService] 清理过期Key {count} 个")
            return count
        finally:
            db.close()

    def get_stats(self, *, user_id: Optional[int] = None) -> Dict[str, Any]:
        """API Key统计"""
        db = SessionLocal()
        try:
            q = db.query(ApiKey).filter(ApiKey.is_deleted == False)
            if user_id is not None:
                q = q.filter(ApiKey.user_id == user_id)
            keys = q.all()

            active = [k for k in keys if k.is_active]
            expired = [k for k in keys if k._is_expired()]
            total_usage = sum(k.usage_count or 0 for k in keys)

            return {
                "total": len(keys),
                "active": len(active),
                "inactive": len(keys) - len(active),
                "expired": len(expired),
                "total_usage": total_usage,
            }
        finally:
            db.close()


# ============================================================
# 单例
# ============================================================
_service: Optional[ApiKeyService] = None


def get_api_key_service() -> ApiKeyService:
    global _service
    if _service is None:
        _service = ApiKeyService()
    return _service


def reset_api_key_service() -> None:
    """重置单例(测试用)"""
    global _service
    _service = None
