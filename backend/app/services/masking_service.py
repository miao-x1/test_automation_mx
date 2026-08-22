"""
敏感数据脱敏服务

功能:
  1. 内置脱敏策略(phone/email/id_card/bank_card/api_key/password/token)
  2. 自动类型检测(根据值格式推断敏感类型)
  3. 字典级脱敏(按 MaskingRule 配置批量脱敏)
  4. 脱敏规则管理 CRUD

设计:
  - 纯函数脱敏(mask_value)无状态,可独立调用
  - MaskingService 单例管理规则缓存
  - 支持 MaskingRule 数据库持久化 + 内存缓存
  - 规则匹配优先级: 字段名精确 > 正则匹配 > 自动检测
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.security import MaskingRule, MaskType

logger = logging.getLogger(__name__)

# ============================================================
# 内置敏感字段名列表(用于自动检测)
# ============================================================

_SENSITIVE_FIELD_NAMES = {
    "password", "passwd", "pwd", "secret", "token", "api_key", "apikey",
    "api_secret", "access_token", "refresh_token", "private_key", "secret_key",
    "db_password", "database_password", "db_pwd", "credential", "authorization",
    "auth_token", "session_token", "bearer_token",
}

# 敏感字段名正则模式(模糊匹配)
_SENSITIVE_FIELD_PATTERNS = [
    re.compile(r".*password.*", re.IGNORECASE),
    re.compile(r".*secret.*", re.IGNORECASE),
    re.compile(r".*token.*", re.IGNORECASE),
    re.compile(r".*api[_-]?key.*", re.IGNORECASE),
    re.compile(r".*credential.*", re.IGNORECASE),
    re.compile(r".*private.*", re.IGNORECASE),
]

# 数据格式正则(用于自动检测值类型)
_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
_ID_CARD_RE = re.compile(r"^\d{17}[\dXx]$")
_BANK_CARD_RE = re.compile(r"^\d{16,19}$")


# ============================================================
# 纯函数: 脱敏策略
# ============================================================

def mask_phone(value: str) -> str:
    """手机号脱敏: 138****1234"""
    if not value or len(value) < 7:
        return "****"
    return value[:3] + "****" + value[-4:]


def mask_email(value: str) -> str:
    """邮箱脱敏: a***@example.com"""
    if not value or "@" not in value:
        return "****"
    local, domain = value.split("@", 1)
    if len(local) <= 1:
        return "*" + "@" + domain
    return local[0] + "***@" + domain


def mask_id_card(value: str) -> str:
    """身份证脱敏: 110***********1234"""
    if not value or len(value) < 10:
        return "****"
    return value[:3] + "*" * (len(value) - 7) + value[-4:]


def mask_bank_card(value: str) -> str:
    """银行卡脱敏: 6222****1234"""
    if not value or len(value) < 8:
        return "****"
    return value[:4] + "****" + value[-4:]


def mask_api_key(value: str, visible_chars: int = 4) -> str:
    """API密钥脱敏: sk-***1234"""
    if not value:
        return "****"
    if len(value) <= visible_chars:
        return "*" * len(value)
    return value[: min(4, len(value) - visible_chars)] + "***" + value[-visible_chars:]


def mask_password(value: str) -> str:
    """密码脱敏: ******"""
    if not value:
        return ""
    return "*" * min(len(value), 8)


def mask_token(value: str, visible_chars: int = 4) -> str:
    """Token脱敏: ***...1234"""
    if not value:
        return "****"
    if len(value) <= visible_chars:
        return "*" * len(value)
    return "***" + value[-visible_chars:]


def mask_custom(value: str, visible_chars: int = 4, custom_mask: Optional[str] = None) -> str:
    """自定义脱敏: 保留尾部N位"""
    if not value:
        return "****"
    if len(value) <= visible_chars:
        return "*" * len(value)
    if custom_mask:
        # 支持 {start} {end} 占位符
        start_len = min(3, len(value) - visible_chars)
        return custom_mask.replace("{start}", value[:start_len]).replace(
            "{end}", value[-visible_chars:]
        )
    return "*" * (len(value) - visible_chars) + value[-visible_chars:]


def mask_value(
    value: Any,
    mask_type: str,
    visible_chars: int = 4,
    custom_mask: Optional[str] = None,
) -> Optional[str]:
    """根据脱敏类型脱敏

    Args:
        value: 原始值
        mask_type: 脱敏类型(phone/email/id_card/bank_card/api_key/password/token/custom)
        visible_chars: 可见字符数
        custom_mask: 自定义格式

    Returns:
        脱敏后的值
    """
    if value is None:
        return None
    s = str(value)
    if not s:
        return s

    mask_type_lower = mask_type.lower() if mask_type else "custom"

    if mask_type_lower == MaskType.PHONE.value:
        return mask_phone(s)
    elif mask_type_lower == MaskType.EMAIL.value:
        return mask_email(s)
    elif mask_type_lower == MaskType.ID_CARD.value:
        return mask_id_card(s)
    elif mask_type_lower == MaskType.BANK_CARD.value:
        return mask_bank_card(s)
    elif mask_type_lower == MaskType.API_KEY.value:
        return mask_api_key(s, visible_chars)
    elif mask_type_lower == MaskType.PASSWORD.value:
        return mask_password(s)
    elif mask_type_lower == MaskType.TOKEN.value:
        return mask_token(s, visible_chars)
    else:
        return mask_custom(s, visible_chars, custom_mask)


def auto_detect_mask_type(value: Any) -> Optional[str]:
    """自动检测值的敏感类型

    Returns:
        检测到的 MaskType 或 None
    """
    if value is None:
        return None
    s = str(value)
    if not s:
        return None

    if _PHONE_RE.match(s):
        return MaskType.PHONE.value
    if _EMAIL_RE.match(s):
        return MaskType.EMAIL.value
    if _ID_CARD_RE.match(s):
        return MaskType.ID_CARD.value
    if _BANK_CARD_RE.match(s) and len(s) >= 16:
        return MaskType.BANK_CARD.value
    return None


def is_sensitive_field(field_name: str) -> bool:
    """判断字段名是否为敏感字段

    匹配规则:
    1. 精确匹配内置敏感字段名列表
    2. 正则模糊匹配(password/secret/token/api_key等)
    """
    if not field_name:
        return False
    name_lower = field_name.lower()
    if name_lower in _SENSITIVE_FIELD_NAMES:
        return True
    for pattern in _SENSITIVE_FIELD_PATTERNS:
        if pattern.match(field_name):
            return True
    return False


def get_default_mask_type(field_name: str) -> str:
    """根据字段名获取默认脱敏类型"""
    name_lower = field_name.lower() if field_name else ""
    if "password" in name_lower or "pwd" in name_lower:
        return MaskType.PASSWORD.value
    if "token" in name_lower:
        return MaskType.TOKEN.value
    if "api_key" in name_lower or "apikey" in name_lower or "secret_key" in name_lower:
        return MaskType.API_KEY.value
    if "email" in name_lower:
        return MaskType.EMAIL.value
    if "phone" in name_lower or "mobile" in name_lower or "tel" in name_lower:
        return MaskType.PHONE.value
    if "id_card" in name_lower or "idcard" in name_lower:
        return MaskType.ID_CARD.value
    if "bank" in name_lower:
        return MaskType.BANK_CARD.value
    return MaskType.CUSTOM.value


# ============================================================
# 脱敏服务(管理规则 + 字典级脱敏)
# ============================================================

class MaskingService:
    """敏感数据脱敏服务

    管理脱敏规则并提供字典级批量脱敏。
    """

    def __init__(self):
        self._rules_cache: Optional[List[Dict]] = None
        self._cache_loaded = False

    def _load_rules(self, db: Session) -> List[Dict]:
        """加载激活的脱敏规则"""
        if self._cache_loaded and self._rules_cache is not None:
            return self._rules_cache

        rules = db.query(MaskingRule).filter(
            MaskingRule.is_active == True,
            MaskingRule.is_deleted == False,
        ).all()
        self._rules_cache = [r.to_dict() for r in rules]
        self._cache_loaded = True
        return self._rules_cache

    def reload_rules(self) -> None:
        """清除缓存,下次调用时重新加载"""
        self._cache_loaded = False
        self._rules_cache = None

    def mask_dict(
        self,
        data: Dict[str, Any],
        rules: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """对字典数据进行脱敏

        匹配优先级:
        1. 规则字段名精确匹配
        2. 规则正则匹配
        3. 内置敏感字段检测
        4. 自动类型检测

        Args:
            data: 原始字典
            rules: 脱敏规则列表(为空则从数据库加载)

        Returns:
            脱敏后的字典
        """
        if not data or not isinstance(data, dict):
            return data

        if rules is None:
            db = SessionLocal()
            try:
                rules = self._load_rules(db)
            finally:
                db.close()

        result = {}
        for key, value in data.items():
            result[key] = self._mask_field(key, value, rules)
        return result

    def _mask_field(
        self,
        field_name: str,
        value: Any,
        rules: List[Dict],
    ) -> Any:
        """对单个字段脱敏"""
        if value is None:
            return None

        # 1. 规则精确匹配
        for rule in rules:
            if rule.get("field_name") and rule["field_name"].lower() == field_name.lower():
                return mask_value(
                    value, rule["mask_type"],
                    rule.get("visible_chars", 4),
                    rule.get("custom_mask"),
                )

        # 2. 规则正则匹配
        for rule in rules:
            pattern = rule.get("field_pattern")
            if pattern:
                try:
                    if re.match(pattern, field_name, re.IGNORECASE):
                        return mask_value(
                            value, rule["mask_type"],
                            rule.get("visible_chars", 4),
                            rule.get("custom_mask"),
                        )
                except re.error:
                    continue

        # 3. 内置敏感字段检测
        if is_sensitive_field(field_name):
            mask_type = get_default_mask_type(field_name)
            return mask_value(value, mask_type)

        # 4. 自动类型检测(仅对字符串值)
        if isinstance(value, str):
            detected = auto_detect_mask_type(value)
            if detected:
                return mask_value(value, detected)

        # 5. 嵌套字典递归
        if isinstance(value, dict):
            return self.mask_dict(value, rules)
        if isinstance(value, list):
            return [self.mask_dict(v, rules) if isinstance(v, dict) else v for v in value]

        return value

    def mask_json_string(self, json_str: str, rules: Optional[List[Dict]] = None) -> str:
        """对 JSON 字符串进行脱敏

        Args:
            json_str: JSON 格式字符串
            rules: 脱敏规则

        Returns:
            脱敏后的 JSON 字符串
        """
        if not json_str:
            return json_str
        try:
            data = json.loads(json_str)
            masked = self.mask_dict(data, rules) if isinstance(data, dict) else data
            return json.dumps(masked, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            return json_str

    # ============================================================
    # 脱敏规则 CRUD
    # ============================================================

    def create_rule(self, payload: Dict) -> Dict:
        """创建脱敏规则"""
        name = (payload.get("name") or "").strip()
        if not name:
            raise ValueError("name is required")
        mask_type = payload.get("mask_type")
        if not mask_type:
            raise ValueError("mask_type is required")

        db = SessionLocal()
        try:
            rule = MaskingRule(
                name=name,
                description=payload.get("description", ""),
                field_name=payload.get("field_name"),
                field_pattern=payload.get("field_pattern"),
                mask_type=mask_type,
                visible_chars=payload.get("visible_chars", 4),
                custom_mask=payload.get("custom_mask"),
                is_active=payload.get("is_active", True),
                is_deleted=False,
            )
            db.add(rule)
            db.commit()
            db.refresh(rule)
            self.reload_rules()
            return rule.to_dict()
        finally:
            db.close()

    def list_rules(
        self,
        *,
        is_active: Optional[bool] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """脱敏规则列表"""
        db = SessionLocal()
        try:
            q = db.query(MaskingRule).filter(MaskingRule.is_deleted == False)
            if is_active is not None:
                q = q.filter(MaskingRule.is_active == is_active)
            total = q.count()
            items = (
                q.order_by(desc(MaskingRule.created_at))
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            return {
                "items": [r.to_dict() for r in items],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        finally:
            db.close()

    def get_rule(self, rule_id: int) -> Optional[Dict]:
        """获取脱敏规则详情"""
        db = SessionLocal()
        try:
            rule = db.query(MaskingRule).filter(
                MaskingRule.id == rule_id,
                MaskingRule.is_deleted == False,
            ).first()
            return None if rule is None else rule.to_dict()
        finally:
            db.close()

    def update_rule(self, rule_id: int, payload: Dict) -> Dict:
        """更新脱敏规则"""
        db = SessionLocal()
        try:
            rule = db.query(MaskingRule).filter(
                MaskingRule.id == rule_id,
                MaskingRule.is_deleted == False,
            ).first()
            if rule is None:
                raise ValueError(f"MaskingRule not found: {rule_id}")

            immutable = {"id", "created_at", "updated_at"}
            for key, value in payload.items():
                if key in immutable:
                    continue
                if hasattr(rule, key):
                    setattr(rule, key, value)

            db.commit()
            db.refresh(rule)
            self.reload_rules()
            return rule.to_dict()
        finally:
            db.close()

    def delete_rule(self, rule_id: int, hard: bool = False) -> bool:
        """删除脱敏规则"""
        db = SessionLocal()
        try:
            rule = db.query(MaskingRule).filter(
                MaskingRule.id == rule_id,
                MaskingRule.is_deleted == False,
            ).first()
            if rule is None:
                return False
            if hard:
                db.delete(rule)
            else:
                rule.is_deleted = True
                rule.is_active = False
            db.commit()
            self.reload_rules()
            return True
        finally:
            db.close()

    def init_default_rules(self) -> int:
        """初始化默认脱敏规则(仅在无规则时创建)"""
        db = SessionLocal()
        try:
            existing = db.query(MaskingRule).filter(
                MaskingRule.is_deleted == False
            ).count()
            if existing > 0:
                return 0

            defaults = [
                {"name": "密码脱敏", "field_name": "password", "mask_type": "password"},
                {"name": "Token脱敏", "field_name": "token", "mask_type": "token"},
                {"name": "API Key脱敏", "field_name": "api_key", "mask_type": "api_key"},
                {"name": "Secret脱敏", "field_name": "secret", "mask_type": "api_key"},
                {"name": "手机号脱敏", "field_name": "phone", "mask_type": "phone"},
                {"name": "邮箱脱敏", "field_name": "email", "mask_type": "email"},
                {"name": "身份证脱敏", "field_name": "id_card", "mask_type": "id_card"},
                {"name": "银行卡脱敏", "field_name": "bank_card", "mask_type": "bank_card"},
                {"name": "DB密码脱敏", "field_name": "db_password", "mask_type": "password"},
                {"name": "API Secret脱敏", "field_name": "api_secret", "mask_type": "api_key"},
                {"name": "访问Token脱敏", "field_name": "access_token", "mask_type": "token"},
                {"name": "刷新Token脱敏", "field_name": "refresh_token", "mask_type": "token"},
                # 正则规则
                {"name": "密码字段模糊匹配", "field_pattern": ".*password.*",
                 "mask_type": "password", "description": "匹配所有含password的字段"},
                {"name": "Token字段模糊匹配", "field_pattern": ".*token.*",
                 "mask_type": "token", "description": "匹配所有含token的字段"},
                {"name": "Secret字段模糊匹配", "field_pattern": ".*secret.*",
                 "mask_type": "api_key", "description": "匹配所有含secret的字段"},
                {"name": "API Key字段模糊匹配", "field_pattern": ".*api[_-]?key.*",
                 "mask_type": "api_key", "description": "匹配所有含api_key/apikey的字段"},
            ]

            for d in defaults:
                rule = MaskingRule(is_active=True, is_deleted=False, **d)
                db.add(rule)
            db.commit()
            self.reload_rules()
            logger.info(f"[MaskingService] 初始化默认脱敏规则 {len(defaults)} 条")
            return len(defaults)
        finally:
            db.close()


# ============================================================
# 单例
# ============================================================
_service: Optional[MaskingService] = None


def get_masking_service() -> MaskingService:
    global _service
    if _service is None:
        _service = MaskingService()
    return _service


def reset_masking_service() -> None:
    """重置单例(测试用)"""
    global _service
    _service = None
