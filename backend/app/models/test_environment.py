"""
测试环境数据模型

TestEnvironment: 测试环境配置(dev/test/staging/prod)
EnvironmentSecret: 环境变量/密钥的通用存储(可加密)

设计要点:
1. 敏感字段(db_password, api_key, api_secret)存入时由服务层加密
2. to_dict() 返回脱敏后的数据,不暴露明文
3. to_dict_with_secrets() 返回解密后的完整数据(仅内部使用)
4. 环境名称唯一(dev/test/staging/prod),用 unique index 约束
5. 支持 is_default 标记,每个用户只能有一个默认环境
"""
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import Boolean, Column, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.crypto import decrypt, mask
from app.models.base import OwnedModel


# ============================================================
# 测试环境
# ============================================================

class TestEnvironment(OwnedModel):
    """测试环境

    支持四种环境: dev / test / staging / prod
    每种环境管理: URL / 数据库 / 账号 / 密钥
    """
    __tablename__ = "test_environment"

    # 基本信息
    name = Column(String(50), nullable=False, comment="环境名称: dev/test/staging/prod")
    display_name = Column(String(100), nullable=True, comment="显示名称")
    description = Column(Text, nullable=True, comment="环境描述")

    # 环境类型(固定四种)
    env_type = Column(String(20), nullable=False, default="test",
                     comment="环境类型: dev/test/staging/prod")

    # URL 配置
    base_url = Column(String(500), nullable=True, comment="基础 URL(被测系统入口)")
    api_url = Column(String(500), nullable=True, comment="API 基础 URL")
    web_url = Column(String(500), nullable=True, comment="Web 基础 URL")

    # 数据库配置
    db_host = Column(String(200), nullable=True, comment="数据库地址")
    db_port = Column(Integer, nullable=True, comment="数据库端口")
    db_name = Column(String(100), nullable=True, comment="数据库名称")
    db_user = Column(String(100), nullable=True, comment="数据库用户名")
    db_password = Column(Text, nullable=True, comment="数据库密码(加密存储)")

    # API 凭证
    api_key = Column(Text, nullable=True, comment="API Key(加密存储)")
    api_secret = Column(Text, nullable=True, comment="API Secret(加密存储)")

    # 额外配置
    headers_json = Column(Text, nullable=True, comment="全局请求头(JSON)")
    variables_json = Column(Text, nullable=True, comment="全局变量(JSON)")
    tags = Column(String(500), nullable=True, comment="标签(逗号分隔)")

    # 状态
    is_active = Column(Boolean, default=True, nullable=False, index=True,
                       comment="是否启用")
    is_default = Column(Boolean, default=False, nullable=False, index=True,
                        comment="是否为默认环境")
    is_deleted = Column(Boolean, default=False, index=True, comment="是否删除")

    # 关联密钥
    secrets = relationship("EnvironmentSecret", back_populates="environment",
                            cascade="all, delete-orphan",
                            order_by="EnvironmentSecret.key_name")

    def to_dict(self, include_secrets: bool = False) -> Dict[str, Any]:
        """转为字典

        Args:
            include_secrets: True=包含解密后的敏感字段(仅内部使用)
                             False=敏感字段脱敏(默认,API 返回用)
        """
        result = {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "env_type": self.env_type,
            "base_url": self.base_url,
            "api_url": self.api_url,
            "web_url": self.web_url,
            "db_host": self.db_host,
            "db_port": self.db_port,
            "db_name": self.db_name,
            "db_user": self.db_user,
            # 敏感字段处理
            "db_password": self._safe_value(self.db_password, include_secrets),
            "api_key": self._safe_value(self.api_key, include_secrets),
            "api_secret": self._safe_value(self.api_secret, include_secrets),
            "headers_json": self.headers_json,
            "variables_json": self.variables_json,
            "tags": self.tags,
            "is_active": self.is_active,
            "is_default": self.is_default,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        if include_secrets:
            result["secrets"] = [s.to_dict(decrypt_value=True) for s in (self.secrets or [])]
        else:
            result["secrets"] = [s.to_dict(decrypt_value=False) for s in (self.secrets or [])]

        return result

    def _safe_value(self, value: Optional[str], reveal: bool) -> Optional[str]:
        """处理敏感字段值

        Args:
            value: 原始值(可能是明文或密文)
            reveal: True=解密返回明文,False=脱敏返回
        """
        if value is None or value == "":
            return value
        if reveal:
            return decrypt(value)
        return mask(value)

    def __repr__(self) -> str:
        return f"<TestEnvironment {self.env_type}:{self.name}>"


# ============================================================
# 环境密钥(通用 Key-Value 存储)
# ============================================================

class EnvironmentSecret(OwnedModel):
    """环境密钥/变量

    通用 Key-Value 存储,用于存放额外的不在 TestEnvironment
    主表中的敏感配置(如第三方 Token、SSH Key 等)。

    value 字段加密存储。
    """
    __tablename__ = "environment_secret"

    environment_id = Column(Integer, ForeignKey("test_environment.id", ondelete="CASCADE"),
                            nullable=False, index=True, comment="所属环境 ID")
    key_name = Column(String(100), nullable=False, comment="密钥名称")
    value = Column(Text, nullable=True, comment="密钥值(加密存储)")
    value_type = Column(String(20), default="string",
                        comment="值类型: string/json/base64")
    description = Column(Text, nullable=True, comment="描述")
    is_sensitive = Column(Boolean, default=True, nullable=False,
                          comment="是否敏感(敏感则加密)")

    environment = relationship("TestEnvironment", back_populates="secrets")

    def to_dict(self, decrypt_value: bool = False) -> Dict[str, Any]:
        """转为字典

        Args:
            decrypt_value: True=解密 value,False=脱敏
        """
        from app.core.crypto import mask as _mask

        raw_value = self.value
        if raw_value is None or raw_value == "":
            display_value = raw_value
        elif decrypt_value:
            display_value = decrypt(raw_value)
        else:
            if self.is_sensitive:
                display_value = _mask(raw_value)
            else:
                display_value = raw_value

        return {
            "id": self.id,
            "environment_id": self.environment_id,
            "key_name": self.key_name,
            "value": display_value,
            "value_type": self.value_type,
            "description": self.description,
            "is_sensitive": self.is_sensitive,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<EnvironmentSecret {self.key_name}>"


# ============================================================
# 复合索引
# ============================================================

# 环境名称查询索引(软删除模式下唯一性由应用层校验)
Index("idx_env_user_name", TestEnvironment.user_id, TestEnvironment.name)
Index("idx_env_type", TestEnvironment.env_type, TestEnvironment.is_active)
Index("idx_secret_env_key", EnvironmentSecret.environment_id, EnvironmentSecret.key_name)
