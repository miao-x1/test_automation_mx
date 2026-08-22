"""
EnvironmentManager - 测试环境管理服务

职责:
1. TestEnvironment CRUD(创建/查询/更新/删除/列表)
2. EnvironmentSecret 管理(添加/移除/列出密钥)
3. 敏感字段自动加密/解密
4. 自动选择环境(供 Agent 执行测试时调用)
5. 环境配置合并(将环境配置注入到执行 payload)

环境选择优先级:
1. 显式指定的 env_name / env_id
2. Plan.env 字段
3. 用户的默认环境(is_default=True)
4. 系统默认环境(name="test" 或第一个可用环境)

使用方式:
    mgr = get_environment_manager()
    env = mgr.create_environment({...}, user_id=1)
    config = mgr.get_runtime_config(env_name="test", user_id=1)
    # config = {"base_url": ..., "db": {...}, "api_key": ..., "variables": {...}}
"""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.crypto import decrypt, encrypt, is_encrypted, mask
from app.db.database import SessionLocal
from app.models.test_environment import EnvironmentSecret, TestEnvironment

logger = logging.getLogger(__name__)


# ============================================================
# 合法值
# ============================================================

# 支持的环境类型
_ENV_TYPES = {"dev", "test", "staging", "prod"}

# 敏感字段列表(存入时自动加密)
_SENSITIVE_FIELDS = {"db_password", "api_key", "api_secret"}

# 不可更新字段
_IMMUTABLE = {"id", "created_at", "updated_at"}


class EnvironmentManager:
    """测试环境管理服务

    所有方法同步,通过 SessionLocal 管理数据库连接。
    敏感字段在 create/update 时自动加密,在 get_runtime_config 时自动解密。
    """

    # ------------------------------------------------------------------ #
    #  会话管理                                                          #
    # ------------------------------------------------------------------ #

    @contextmanager
    def _session(self) -> Iterator[Session]:
        """事务会话上下文管理器"""
        db = SessionLocal()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ------------------------------------------------------------------ #
    #  加密辅助                                                          #
    # ------------------------------------------------------------------ #

    def _encrypt_field(self, value: Optional[str]) -> Optional[str]:
        """加密敏感字段(已加密的不再重复)"""
        if value is None or value == "":
            return value
        if is_encrypted(value):
            return value
        return encrypt(value)

    def _decrypt_field(self, value: Optional[str]) -> Optional[str]:
        """解密敏感字段"""
        if value is None or value == "":
            return value
        return decrypt(value)

    # ------------------------------------------------------------------ #
    #  CRUD                                                              #
    # ------------------------------------------------------------------ #

    def create_environment(
        self,
        payload: Dict[str, Any],
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """创建测试环境

        敏感字段(db_password, api_key, api_secret)自动加密。
        """
        name = (payload.get("name") or "").strip()
        if not name:
            raise ValueError("name is required")

        env_type = payload.get("env_type", "test")
        if env_type not in _ENV_TYPES:
            raise ValueError(f"invalid env_type: {env_type}, must be one of {_ENV_TYPES}")

        with self._session() as db:
            # 校验同名环境(软删除除外)
            existed = db.query(TestEnvironment).filter(
                TestEnvironment.name == name,
                TestEnvironment.is_deleted == False,
            ).first()
            if existed is not None:
                if user_id is not None and existed.user_id == user_id:
                    raise ValueError(f"environment '{name}' already exists")
                # 不同用户允许同名,继续

            # 如果设为默认,先清除同用户的其他默认
            is_default = payload.get("is_default", False)
            if is_default and user_id is not None:
                self._clear_default(db, user_id)

            env = TestEnvironment(
                name=name,
                display_name=payload.get("display_name"),
                description=payload.get("description"),
                env_type=env_type,
                base_url=payload.get("base_url"),
                api_url=payload.get("api_url"),
                web_url=payload.get("web_url"),
                db_host=payload.get("db_host"),
                db_port=payload.get("db_port"),
                db_name=payload.get("db_name"),
                db_user=payload.get("db_user"),
                # 加密敏感字段
                db_password=self._encrypt_field(payload.get("db_password")),
                api_key=self._encrypt_field(payload.get("api_key")),
                api_secret=self._encrypt_field(payload.get("api_secret")),
                headers_json=payload.get("headers_json"),
                variables_json=payload.get("variables_json"),
                tags=payload.get("tags"),
                is_active=payload.get("is_active", True),
                is_default=is_default,
                user_id=user_id,
                created_by=user_id,
            )
            db.add(env)
            db.flush()
            env_id = env.id
            result = env.to_dict(include_secrets=False)

        logger.info(f"[EnvironmentManager] created environment id={env_id} name={name} type={env_type}")
        return result

    def get_environment(
        self,
        env_id: int,
        *,
        include_secrets: bool = False,
        user_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """获取环境详情

        Args:
            env_id: 环境 ID
            include_secrets: True=返回解密后的敏感字段(仅内部使用)
            user_id: 用户 ID(数据隔离)
        """
        db = SessionLocal()
        try:
            q = db.query(TestEnvironment).filter(
                TestEnvironment.id == env_id,
                TestEnvironment.is_deleted == False,
            )
            if user_id is not None:
                q = q.filter(TestEnvironment.user_id == user_id)
            env = q.first()
            if env is None:
                return None
            return env.to_dict(include_secrets=include_secrets)
        finally:
            db.close()

    def get_by_name(
        self,
        name: str,
        *,
        include_secrets: bool = False,
        user_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """按名称查询环境"""
        db = SessionLocal()
        try:
            q = db.query(TestEnvironment).filter(
                TestEnvironment.name == name,
                TestEnvironment.is_deleted == False,
                TestEnvironment.is_active == True,
            )
            if user_id is not None:
                q = q.filter(TestEnvironment.user_id == user_id)
            env = q.first()
            if env is None:
                return None
            return env.to_dict(include_secrets=include_secrets)
        finally:
            db.close()

    def update_environment(
        self,
        env_id: int,
        payload: Dict[str, Any],
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """更新环境(部分更新)

        敏感字段如果提供了新值,自动加密。
        """
        if "env_type" in payload and payload["env_type"] not in _ENV_TYPES:
            raise ValueError(f"invalid env_type: {payload['env_type']}")

        with self._session() as db:
            q = db.query(TestEnvironment).filter(
                TestEnvironment.id == env_id,
                TestEnvironment.is_deleted == False,
            )
            if user_id is not None:
                q = q.filter(TestEnvironment.user_id == user_id)
            env = q.first()
            if env is None:
                raise ValueError(f"TestEnvironment not found: {env_id}")

            # 处理默认环境切换
            if payload.get("is_default") and user_id is not None:
                self._clear_default(db, user_id, exclude_id=env_id)

            for key, value in payload.items():
                if key in _IMMUTABLE:
                    continue
                if key in _SENSITIVE_FIELDS:
                    # 敏感字段:有值才加密(空值不更新)
                    if value is not None and value != "":
                        value = self._encrypt_field(value)
                    elif value == "":
                        setattr(env, key, "")
                        continue
                    else:
                        continue  # None 不更新
                if hasattr(env, key):
                    setattr(env, key, value)

            db.flush()
            result = env.to_dict(include_secrets=False)

        logger.info(f"[EnvironmentManager] updated environment id={env_id}")
        return result

    def delete_environment(
        self,
        env_id: int,
        *,
        hard: bool = False,
        user_id: Optional[int] = None,
    ) -> bool:
        """删除环境(默认软删除)"""
        with self._session() as db:
            q = db.query(TestEnvironment).filter(TestEnvironment.id == env_id)
            if user_id is not None:
                q = q.filter(TestEnvironment.user_id == user_id)
            env = q.first()
            if env is None:
                return False

            if hard:
                db.delete(env)
            else:
                env.is_deleted = True
                env.is_active = False
                env.is_default = False
            db.flush()

        logger.info(f"[EnvironmentManager] deleted environment id={env_id} hard={hard}")
        return True

    def list_environments(
        self,
        *,
        env_type: Optional[str] = None,
        is_active: Optional[bool] = None,
        keyword: Optional[str] = None,
        user_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """分页查询环境列表"""
        db = SessionLocal()
        try:
            q = db.query(TestEnvironment).filter(
                TestEnvironment.is_deleted == False,
            )
            if user_id is not None:
                q = q.filter(TestEnvironment.user_id == user_id)
            if env_type:
                q = q.filter(TestEnvironment.env_type == env_type)
            if is_active is not None:
                q = q.filter(TestEnvironment.is_active == is_active)
            if keyword:
                q = q.filter(TestEnvironment.name.like(f"%{keyword}%"))

            total = q.count()
            items = (
                q.order_by(desc(TestEnvironment.updated_at))
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )

            return {
                "items": [e.to_dict(include_secrets=False) for e in items],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        finally:
            db.close()

    def set_default(
        self,
        env_id: int,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """设为默认环境(清除其他默认)"""
        with self._session() as db:
            q = db.query(TestEnvironment).filter(
                TestEnvironment.id == env_id,
                TestEnvironment.is_deleted == False,
            )
            if user_id is not None:
                q = q.filter(TestEnvironment.user_id == user_id)
            env = q.first()
            if env is None:
                raise ValueError(f"TestEnvironment not found: {env_id}")

            self._clear_default(db, user_id, exclude_id=env_id)
            env.is_default = True
            env.is_active = True
            db.flush()
            result = env.to_dict(include_secrets=False)

        logger.info(f"[EnvironmentManager] set default environment id={env_id}")
        return result

    def _clear_default(
        self,
        db: Session,
        user_id: Optional[int],
        exclude_id: Optional[int] = None,
    ) -> None:
        """清除指定用户的默认环境标记"""
        q = db.query(TestEnvironment).filter(
            TestEnvironment.is_default == True,
            TestEnvironment.is_deleted == False,
        )
        if user_id is not None:
            q = q.filter(TestEnvironment.user_id == user_id)
        if exclude_id is not None:
            q = q.filter(TestEnvironment.id != exclude_id)
        for e in q.all():
            e.is_default = False

    # ------------------------------------------------------------------ #
    #  Secret 管理                                                       #
    # ------------------------------------------------------------------ #

    def add_secret(
        self,
        env_id: int,
        key_name: str,
        value: str,
        *,
        value_type: str = "string",
        description: Optional[str] = None,
        is_sensitive: bool = True,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """添加环境密钥"""
        with self._session() as db:
            env = db.query(TestEnvironment).filter(
                TestEnvironment.id == env_id,
                TestEnvironment.is_deleted == False,
            ).first()
            if env is None:
                raise ValueError(f"TestEnvironment not found: {env_id}")

            # 校验 key_name 不重复
            existed = db.query(EnvironmentSecret).filter(
                EnvironmentSecret.environment_id == env_id,
                EnvironmentSecret.key_name == key_name,
            ).first()
            if existed is not None:
                raise ValueError(f"secret '{key_name}' already exists in environment {env_id}")

            secret = EnvironmentSecret(
                environment_id=env_id,
                key_name=key_name,
                value=encrypt(value) if is_sensitive and value else value,
                value_type=value_type,
                description=description,
                is_sensitive=is_sensitive,
                user_id=user_id,
                created_by=user_id,
            )
            db.add(secret)
            db.flush()
            result = secret.to_dict(decrypt_value=False)

        logger.info(f"[EnvironmentManager] added secret '{key_name}' to env {env_id}")
        return result

    def remove_secret(self, env_id: int, key_name: str) -> bool:
        """移除环境密钥"""
        with self._session() as db:
            secret = db.query(EnvironmentSecret).filter(
                EnvironmentSecret.environment_id == env_id,
                EnvironmentSecret.key_name == key_name,
            ).first()
            if secret is None:
                return False
            db.delete(secret)
            db.flush()
        return True

    def list_secrets(
        self,
        env_id: int,
        *,
        reveal: bool = False,
    ) -> List[Dict[str, Any]]:
        """列出环境密钥"""
        db = SessionLocal()
        try:
            secrets = db.query(EnvironmentSecret).filter(
                EnvironmentSecret.environment_id == env_id,
            ).order_by(EnvironmentSecret.key_name).all()
            return [s.to_dict(decrypt_value=reveal) for s in secrets]
        finally:
            db.close()

    def get_secret_value(self, env_id: int, key_name: str) -> Optional[str]:
        """获取单个密钥的解密值"""
        db = SessionLocal()
        try:
            secret = db.query(EnvironmentSecret).filter(
                EnvironmentSecret.environment_id == env_id,
                EnvironmentSecret.key_name == key_name,
            ).first()
            if secret is None:
                return None
            return decrypt(secret.value) if secret.value else None
        finally:
            db.close()

    # ------------------------------------------------------------------ #
    #  自动选择环境                                                      #
    # ------------------------------------------------------------------ #

    def select_environment(
        self,
        *,
        env_name: Optional[str] = None,
        env_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """自动选择环境

        选择优先级:
        1. 显式 env_id
        2. 显式 env_name
        3. 用户的默认环境(is_default=True)
        4. name="test" 的环境
        5. 第一个可用环境

        Returns:
            环境字典(脱敏),找不到返回 None
        """
        db = SessionLocal()
        try:
            q = db.query(TestEnvironment).filter(
                TestEnvironment.is_deleted == False,
                TestEnvironment.is_active == True,
            )
            if user_id is not None:
                q = q.filter(TestEnvironment.user_id == user_id)

            # 1. 按 env_id 查找
            if env_id is not None:
                env = q.filter(TestEnvironment.id == env_id).first()
                if env:
                    return env.to_dict(include_secrets=False)

            # 2. 按 env_name 查找
            if env_name:
                env = q.filter(TestEnvironment.name == env_name).first()
                if env:
                    return env.to_dict(include_secrets=False)
                # 按 env_type 查找
                env = q.filter(TestEnvironment.env_type == env_name).first()
                if env:
                    return env.to_dict(include_secrets=False)

            # 3. 用户的默认环境
            default_q = q.filter(TestEnvironment.is_default == True)
            env = default_q.first()
            if env:
                return env.to_dict(include_secrets=False)

            # 4. name="test" 的环境
            env = q.filter(TestEnvironment.name == "test").first()
            if env:
                return env.to_dict(include_secrets=False)

            # 5. 第一个可用环境
            env = q.order_by(TestEnvironment.id).first()
            if env:
                return env.to_dict(include_secrets=False)

            return None
        finally:
            db.close()

    def get_runtime_config(
        self,
        *,
        env_name: Optional[str] = None,
        env_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """获取运行时环境配置(解密后的完整配置)

        供 ExecutionFlow / Agent 使用:
        - base_url: 被测系统入口
        - api_url: API 基础 URL
        - db: 数据库连接配置(含解密密码)
        - api_key: API Key(解密)
        - api_secret: API Secret(解密)
        - headers: 全局请求头(dict)
        - variables: 全局变量(dict)
        - secrets: 额外密钥(dict,已解密)

        Returns:
            解密后的运行时配置字典,找不到环境返回 None
        """
        db = SessionLocal()
        try:
            q = db.query(TestEnvironment).filter(
                TestEnvironment.is_deleted == False,
                TestEnvironment.is_active == True,
            )
            if user_id is not None:
                q = q.filter(TestEnvironment.user_id == user_id)

            env = None

            # 按优先级查找
            if env_id is not None:
                env = q.filter(TestEnvironment.id == env_id).first()
            if env is None and env_name:
                env = q.filter(
                    (TestEnvironment.name == env_name) |
                    (TestEnvironment.env_type == env_name)
                ).first()
            if env is None:
                env = q.filter(TestEnvironment.is_default == True).first()
            if env is None:
                env = q.filter(TestEnvironment.name == "test").first()
            if env is None:
                env = q.order_by(TestEnvironment.id).first()

            if env is None:
                return None

            # 构建运行时配置
            headers = {}
            if env.headers_json:
                try:
                    headers = json.loads(env.headers_json)
                except Exception:
                    pass

            variables = {}
            if env.variables_json:
                try:
                    variables = json.loads(env.variables_json)
                except Exception:
                    pass

            # 额外密钥
            secrets_dict = {}
            for secret in (env.secrets or []):
                secrets_dict[secret.key_name] = decrypt(secret.value) if secret.value else None

            return {
                "env_id": env.id,
                "env_name": env.name,
                "env_type": env.env_type,
                "base_url": env.base_url,
                "api_url": env.api_url,
                "web_url": env.web_url,
                "db": {
                    "host": env.db_host,
                    "port": env.db_port,
                    "name": env.db_name,
                    "user": env.db_user,
                    "password": self._decrypt_field(env.db_password),
                },
                "api_key": self._decrypt_field(env.api_key),
                "api_secret": self._decrypt_field(env.api_secret),
                "headers": headers,
                "variables": variables,
                "secrets": secrets_dict,
            }
        finally:
            db.close()

    def merge_with_plan_config(
        self,
        plan_env: str,
        plan_base_url: Optional[str],
        plan_variables: Dict[str, Any],
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """将环境配置与 Plan 配置合并

        合并优先级: Plan 级配置 > 环境级配置
        (Plan 的 base_url / variables 覆盖环境的)

        Returns:
            合并后的运行时配置:
            {
                "env_name": "test",
                "base_url": "...",       # Plan 优先
                "api_url": "...",
                "db": {...},
                "api_key": "...",
                "api_secret": "...",
                "headers": {...},
                "variables": {...},      # 合并
                "secrets": {...},
            }
        """
        # 1. 获取环境运行时配置
        env_config = self.get_runtime_config(
            env_name=plan_env,
            user_id=user_id,
        )

        if env_config is None:
            # 环境不存在,返回 Plan 级配置
            logger.warning(
                f"[EnvironmentManager] environment '{plan_env}' not found, using plan config only"
            )
            return {
                "env_name": plan_env or "test",
                "base_url": plan_base_url or "",
                "api_url": None,
                "web_url": None,
                "db": {},
                "api_key": None,
                "api_secret": None,
                "headers": {},
                "variables": plan_variables or {},
                "secrets": {},
            }

        # 2. 合并:Plan 配置优先
        merged = dict(env_config)

        # base_url: Plan 优先
        if plan_base_url:
            merged["base_url"] = plan_base_url

        # variables: 合并(Environment 的被 Plan 的覆盖)
        env_vars = env_config.get("variables", {})
        merged_vars = dict(env_vars)
        if plan_variables:
            merged_vars.update(plan_variables)
        merged["variables"] = merged_vars

        return merged

    # ------------------------------------------------------------------ #
    #  测试连接                                                          #
    # ------------------------------------------------------------------ #

    async def test_connection(
        self,
        env_id: int,
        *,
        test_type: str = "http",
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """测试环境连通性

        Args:
            env_id: 环境 ID
            test_type: 测试类型(http/db)
            user_id: 用户 ID

        Returns:
            {"success": bool, "latency_ms": float, "error": str}
        """
        config = self.get_runtime_config(env_id=env_id, user_id=user_id)
        if config is None:
            return {"success": False, "error": "environment not found", "latency_ms": 0}

        import time

        if test_type == "http":
            return await self._test_http_connection(config)
        elif test_type == "db":
            return await self._test_db_connection(config)
        else:
            return {"success": False, "error": f"unknown test_type: {test_type}", "latency_ms": 0}

    async def _test_http_connection(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """测试 HTTP 连通性"""
        import httpx
        url = config.get("base_url") or config.get("api_url")
        if not url:
            return {"success": False, "error": "no base_url or api_url configured", "latency_ms": 0}

        headers = config.get("headers", {})
        if config.get("api_key"):
            headers["Authorization"] = f"Bearer {config['api_key']}"

        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=10, verify=False) as client:
                resp = await client.get(url, headers=headers)
                latency = (time.time() - start) * 1000
                success = resp.status_code < 500
                return {
                    "success": success,
                    "status_code": resp.status_code,
                    "latency_ms": round(latency, 2),
                    "error": None if success else f"HTTP {resp.status_code}",
                }
        except Exception as e:
            latency = (time.time() - start) * 1000
            return {
                "success": False,
                "latency_ms": round(latency, 2),
                "error": str(e),
            }

    async def _test_db_connection(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """测试数据库连通性"""
        import asyncio
        db = config.get("db", {})
        host = db.get("host")
        port = db.get("port")
        if not host or not port:
            return {"success": False, "error": "no db_host or db_port configured", "latency_ms": 0}

        start = time.time()
        try:
            # 用 socket 连接测试
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=5,
            )
            writer.close()
            await writer.wait_closed()
            latency = (time.time() - start) * 1000
            return {
                "success": True,
                "latency_ms": round(latency, 2),
                "error": None,
            }
        except Exception as e:
            latency = (time.time() - start) * 1000
            return {
                "success": False,
                "latency_ms": round(latency, 2),
                "error": str(e),
            }

    # ------------------------------------------------------------------ #
    #  统计                                                              #
    # ------------------------------------------------------------------ #

    def get_stats(self, *, user_id: Optional[int] = None) -> Dict[str, Any]:
        """获取环境统计"""
        db = SessionLocal()
        try:
            q = db.query(TestEnvironment).filter(TestEnvironment.is_deleted == False)
            if user_id is not None:
                q = q.filter(TestEnvironment.user_id == user_id)
            all_envs = q.all()

            type_stats = {}
            for t in _ENV_TYPES:
                type_stats[t] = sum(1 for e in all_envs if e.env_type == t)

            return {
                "total": len(all_envs),
                "by_type": type_stats,
                "active": sum(1 for e in all_envs if e.is_active),
                "default_count": sum(1 for e in all_envs if e.is_default),
            }
        finally:
            db.close()


# ============================================================
# 单例
# ============================================================

_manager: Optional[EnvironmentManager] = None


def get_environment_manager() -> EnvironmentManager:
    global _manager
    if _manager is None:
        _manager = EnvironmentManager()
    return _manager


def reset_environment_manager() -> None:
    """重置单例(测试用)"""
    global _manager
    _manager = None
