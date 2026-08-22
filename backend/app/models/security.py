"""
企业级安全模块数据模型

包含四张表:
  1. api_key        - API Key 管理(哈希存储,支持过期/范围/使用统计)
  2. operation_log  - 操作日志(记录所有 API 调用,含请求体脱敏)
  3. audit_event    - 审计事件(权限变更/密钥操作/数据访问/安全告警)
  4. masking_rule   - 脱敏规则(字段级配置,支持多种脱敏策略)

安全设计要点:
  - API Key 仅存 SHA-256 哈希,明文只在创建时返回一次
  - 敏感字段加密使用 app.core.crypto (Fernet AES-128)
  - 操作日志的 request_body 在入库前自动脱敏
  - 审计事件分级(info/warning/critical)支持告警
  - 所有表支持软删除和用户级数据隔离
"""
import enum
import hashlib
import json
import secrets
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import Column, String, Integer, Text, Boolean, Float, DateTime, Index, ForeignKey
from sqlalchemy.orm import relationship

from app.models.base import BaseModel, OwnedModel


# ============================================================
# 枚举定义
# ============================================================

class AuditEventType(str, enum.Enum):
    """审计事件类型"""
    PERMISSION_CHANGE = "permission_change"   # 权限变更
    API_KEY_OPERATION = "api_key_operation"    # API Key 操作
    DATA_ACCESS = "data_access"                # 敏感数据访问
    SECURITY_ALERT = "security_alert"          # 安全告警
    LOGIN_EVENT = "login_event"               # 登录事件
    CONFIG_CHANGE = "config_change"            # 配置变更


class AuditSeverity(str, enum.Enum):
    """审计事件严重级别"""
    INFO = "info"               # 常规操作
    WARNING = "warning"         # 需关注
    CRITICAL = "critical"       # 严重告警


class MaskType(str, enum.Enum):
    """脱敏类型"""
    PHONE = "phone"             # 手机号: 138****1234
    EMAIL = "email"             # 邮箱: a***@example.com
    ID_CARD = "id_card"         # 身份证: 110***********1234
    BANK_CARD = "bank_card"     # 银行卡: 6222****1234
    API_KEY = "api_key"         # API密钥: sk-***1234
    PASSWORD = "password"      # 密码: ******
    TOKEN = "token"             # Token: ***...
    CUSTOM = "custom"           # 自定义(保留尾N位)


# ============================================================
# 1. API Key 管理模型
# ============================================================

class ApiKey(OwnedModel):
    """API Key 管理表

    安全设计:
    - key_hash 存储 SHA-256 哈希,不可逆
    - key_prefix 存储前8位用于展示识别
    - 明文 key 仅在创建时返回一次
    - 支持 scope 权限范围限制
    - 支持 expires_at 过期时间
    - 记录 last_used_at / last_used_ip / usage_count
    """
    __tablename__ = "api_key"

    # ===== 基本信息 =====
    name = Column(
        String(100), nullable=False,
        comment="API Key 名称"
    )
    description = Column(
        String(500), nullable=True,
        comment="描述"
    )

    # ===== 密钥存储(安全) =====
    key_prefix = Column(
        String(16), nullable=False, index=True,
        comment="Key前8位(展示用,如 sk-abc12)"
    )
    key_hash = Column(
        String(128), nullable=False, unique=True,
        comment="SHA-256 哈希值(不可逆)"
    )

    # ===== 权限范围 =====
    scopes = Column(
        Text, nullable=True,
        comment="权限范围(JSON数组,如 [\"read\",\"write\",\"admin\"])"
    )

    # ===== 生命周期 =====
    expires_at = Column(
        DateTime, nullable=True,
        comment="过期时间(NULL=永不过期)"
    )
    is_active = Column(
        Boolean, default=True, nullable=False, index=True,
        comment="是否激活"
    )
    is_deleted = Column(
        Boolean, default=False, nullable=False,
        comment="是否删除(软删除)"
    )

    # ===== 使用统计 =====
    last_used_at = Column(
        DateTime, nullable=True,
        comment="最后使用时间"
    )
    last_used_ip = Column(
        String(50), nullable=True,
        comment="最后使用IP"
    )
    usage_count = Column(
        Integer, default=0,
        comment="使用次数"
    )

    # ===== 索引 =====
    __table_args__ = (
        Index("idx_apikey_user_active", "user_id", "is_active"),
        Index("idx_apikey_prefix", "key_prefix"),
        Index("idx_apikey_expires", "expires_at"),
    )

    def __repr__(self):
        return f"<ApiKey(id={self.id}, name={self.name}, prefix={self.key_prefix})>"

    def to_dict(self, include_hash: bool = False) -> Dict[str, Any]:
        """转字典

        Args:
            include_hash: 是否包含 key_hash(仅内部审计用)
        """
        result = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "key_prefix": self.key_prefix,
            "scopes": self._parse_json(self.scopes),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_active": self.is_active,
            "is_expired": self._is_expired(),
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "last_used_ip": self.last_used_ip,
            "usage_count": self.usage_count or 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "user_id": self.user_id,
            "created_by": self.created_by,
        }
        if include_hash:
            result["key_hash"] = self.key_hash
        return result

    def _is_expired(self) -> bool:
        """是否已过期"""
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at

    @staticmethod
    def _parse_json(value: Optional[str]) -> Any:
        """JSON 字段安全解析"""
        if not value:
            return None
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None

    # ============================================================
    # 静态工具方法
    # ============================================================

    @staticmethod
    def generate_key(prefix: str = "sk") -> tuple:
        """生成新的 API Key

        Returns:
            (plaintext_key, key_prefix, key_hash)
            明文仅此一次返回
        """
        random_part = secrets.token_urlsafe(32)
        plaintext = f"{prefix}_{random_part}"
        key_prefix = plaintext[:12]
        key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
        return plaintext, key_prefix, key_hash

    @staticmethod
    def hash_key(plaintext: str) -> str:
        """计算 API Key 的 SHA-256 哈希"""
        return hashlib.sha256(plaintext.encode()).hexdigest()


# ============================================================
# 2. 操作日志模型
# ============================================================

class OperationLog(OwnedModel):
    """操作日志表

    记录所有 API 调用,用于审计追溯。
    request_body 入库前已脱敏。
    """
    __tablename__ = "operation_log"

    # ===== 用户信息(冗余,便于查询) =====
    username = Column(
        String(50), nullable=True, index=True,
        comment="操作用户名(冗余)"
    )

    # ===== 操作信息 =====
    action = Column(
        String(50), nullable=False, index=True,
        comment="操作动作: create/update/delete/login/logout/execute等"
    )
    method = Column(
        String(10), nullable=False,
        comment="HTTP方法: GET/POST/PUT/DELETE"
    )
    path = Column(
        String(500), nullable=False,
        comment="API路径"
    )

    # ===== 资源信息 =====
    resource_type = Column(
        String(50), nullable=True, index=True,
        comment="资源类型: task/asset/execution等"
    )
    resource_id = Column(
        Integer, nullable=True,
        comment="资源ID"
    )

    # ===== 请求信息 =====
    ip_address = Column(
        String(50), nullable=True, index=True,
        comment="客户端IP"
    )
    user_agent = Column(
        String(500), nullable=True,
        comment="User-Agent"
    )
    request_body = Column(
        Text, nullable=True,
        comment="请求体(已脱敏)"
    )

    # ===== 响应信息 =====
    response_status = Column(
        Integer, nullable=True,
        comment="响应状态码"
    )
    duration = Column(
        Float, nullable=True,
        comment="耗时(秒)"
    )
    error_message = Column(
        Text, nullable=True,
        comment="错误信息(如有)"
    )

    # ===== 索引 =====
    __table_args__ = (
        Index("idx_oplog_user_created", "user_id", "created_at"),
        Index("idx_oplog_action_created", "action", "created_at"),
        Index("idx_oplog_resource", "resource_type", "resource_id"),
        Index("idx_oplog_ip_created", "ip_address", "created_at"),
    )

    def __repr__(self):
        return f"<OperationLog(id={self.id}, action={self.action}, path={self.path})>"

    def to_dict(self) -> Dict[str, Any]:
        """转字典"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "username": self.username,
            "action": self.action,
            "method": self.method,
            "path": self.path,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "request_body": self._parse_json(self.request_body),
            "response_status": self.response_status,
            "duration": self.duration,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @staticmethod
    def _parse_json(value: Optional[str]) -> Any:
        """JSON 字段安全解析"""
        if not value:
            return None
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value  # 非JSON返回原文


# ============================================================
# 3. 审计事件模型
# ============================================================

class AuditEvent(OwnedModel):
    """审计事件表

    用于记录安全相关事件:
    - 权限变更(角色分配/移除)
    - API Key 操作(创建/撤销/使用)
    - 敏感数据访问(解密明文)
    - 安全告警(异常登录/暴力破解)
    - 配置变更(安全配置修改)
    """
    __tablename__ = "audit_event"

    # ===== 事件类型 =====
    event_type = Column(
        String(30), nullable=False, index=True,
        comment="事件类型: permission_change/api_key_operation/data_access/security_alert等"
    )
    severity = Column(
        String(20), default="info", nullable=False, index=True,
        comment="严重级别: info/warning/critical"
    )

    # ===== 用户信息 =====
    username = Column(
        String(50), nullable=True, index=True,
        comment="操作用户名(冗余)"
    )

    # ===== 操作信息 =====
    action = Column(
        String(100), nullable=False,
        comment="具体动作描述"
    )

    # ===== 目标资源 =====
    target_type = Column(
        String(50), nullable=True, index=True,
        comment="目标资源类型"
    )
    target_id = Column(
        String(100), nullable=True,
        comment="目标资源ID(字符串以兼容非整数ID)"
    )

    # ===== 详细信息 =====
    details = Column(
        Text, nullable=True,
        comment="详细信息(JSON)"
    )

    # ===== 环境信息 =====
    ip_address = Column(
        String(50), nullable=True, index=True,
        comment="客户端IP"
    )

    # ===== 索引 =====
    __table_args__ = (
        Index("idx_auditevent_type_severity", "event_type", "severity"),
        Index("idx_auditevent_user_created", "user_id", "created_at"),
        Index("idx_auditevent_target", "target_type", "target_id"),
        Index("idx_auditevent_critical", "severity", "created_at"),
    )

    def __repr__(self):
        return f"<AuditEvent(id={self.id}, type={self.event_type}, severity={self.severity})>"

    def to_dict(self) -> Dict[str, Any]:
        """转字典"""
        return {
            "id": self.id,
            "event_type": self.event_type,
            "severity": self.severity,
            "user_id": self.user_id,
            "username": self.username,
            "action": self.action,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "details": self._parse_json(self.details),
            "ip_address": self.ip_address,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @staticmethod
    def _parse_json(value: Optional[str]) -> Any:
        """JSON 字段安全解析"""
        if not value:
            return None
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value


# ============================================================
# 4. 脱敏规则模型
# ============================================================

class MaskingRule(BaseModel):
    """脱敏规则表

    配置字段级脱敏策略,用于操作日志和API响应的自动脱敏。
    规则匹配优先级: 字段名精确 > 正则匹配 > 自动检测。
    """
    __tablename__ = "masking_rule"

    # ===== 规则信息 =====
    name = Column(
        String(100), nullable=False,
        comment="规则名称"
    )
    description = Column(
        String(500), nullable=True,
        comment="规则描述"
    )

    # ===== 匹配条件 =====
    field_name = Column(
        String(100), nullable=True, index=True,
        comment="字段名(精确匹配,如 password/api_key/db_password)"
    )
    field_pattern = Column(
        String(200), nullable=True,
        comment="字段名正则匹配(如 .*secret.* / .*token.*)"
    )

    # ===== 脱敏策略 =====
    mask_type = Column(
        String(20), nullable=False,
        comment="脱敏类型: phone/email/id_card/bank_card/api_key/password/token/custom"
    )
    visible_chars = Column(
        Integer, default=4,
        comment="可见字符数(尾部)"
    )
    custom_mask = Column(
        String(50), nullable=True,
        comment="自定义脱敏格式(如 {start}***{end})"
    )

    # ===== 状态 =====
    is_active = Column(
        Boolean, default=True, nullable=False, index=True,
        comment="是否激活"
    )
    is_deleted = Column(
        Boolean, default=False, nullable=False,
        comment="是否删除"
    )

    # ===== 索引 =====
    __table_args__ = (
        Index("idx_maskrule_field_active", "field_name", "is_active"),
        Index("idx_maskrule_active", "is_active"),
    )

    def __repr__(self):
        return f"<MaskingRule(id={self.id}, name={self.name}, type={self.mask_type})>"

    def to_dict(self) -> Dict[str, Any]:
        """转字典"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "field_name": self.field_name,
            "field_pattern": self.field_pattern,
            "mask_type": self.mask_type,
            "visible_chars": self.visible_chars or 4,
            "custom_mask": self.custom_mask,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
