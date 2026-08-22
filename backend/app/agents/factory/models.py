"""
Agent 元数据 DB 操作 - 数据库持久化层

将 AgentSpec 同步到 agent_registry 表，支持运行时动态管理。
Agent 管理中心的核心数据访问层,提供:
  1. Specs ↔ DB 双向同步
  2. 动态注册/移除 Agent (CRUD)
  3. 配置热更新 (config 字段)
  4. 版本管理
  5. 状态追踪
"""
import json
import logging
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.agent_registry import AgentRegistry
from app.agents.factory.config import AgentSpec

logger = logging.getLogger(__name__)


class AgentMetadataStore:
    """Agent 元数据数据库存储

    提供 AgentSpec ↔ DB 的双向同步。
    启动时从 DB 加载，运行时变更写回 DB。
    """

    # ============================================================
    # 同步
    # ============================================================

    @staticmethod
    def sync_from_specs(db: Session, specs: List[AgentSpec]) -> int:
        """将内存中的 AgentSpec 列表同步到数据库

        对于已存在的记录更新，不存在的插入。
        不会删除 DB 中有但 specs 中没有的记录（保留手动添加的）。

        Args:
            db: 数据库会话
            specs: AgentSpec 列表

        Returns:
            同步的记录数
        """
        synced = 0
        for spec in specs:
            existing = db.query(AgentRegistry).filter(
                AgentRegistry.agent_name == spec.name
            ).first()

            if existing:
                # 更新已有记录(保留 config/version/status 不被覆盖)
                existing.display_name = spec.display_name
                existing.description = spec.description
                existing.agent_type = spec.agent_type
                existing.module_path = spec.module_path
                existing.class_name = spec.class_name
                existing.model_name = spec.model.model_name if spec.model else None
                existing.model_provider = spec.model.provider if spec.model else None
                existing.system_prompt = spec.system_prompt
                existing.tools = json.dumps(spec.tools, ensure_ascii=False)
                existing.capabilities = json.dumps(spec.capabilities, ensure_ascii=False)
                existing.enabled = spec.enabled
                existing.prompt_path = spec.prompt_template or ""
            else:
                # 新增记录
                record = AgentRegistry(
                    agent_name=spec.name,
                    agent_type=spec.agent_type,
                    display_name=spec.display_name,
                    description=spec.description,
                    module_path=spec.module_path,
                    class_name=spec.class_name,
                    model_name=spec.model.model_name if spec.model else None,
                    model_provider=spec.model.provider if spec.model else None,
                    system_prompt=spec.system_prompt,
                    tools=json.dumps(spec.tools, ensure_ascii=False),
                    capabilities=json.dumps(spec.capabilities, ensure_ascii=False),
                    status="registered",
                    enabled=spec.enabled,
                    version="1.0.0",
                    config=json.dumps(spec.metadata, ensure_ascii=False) if spec.metadata else None,
                )
                db.add(record)

            synced += 1

        db.commit()
        logger.info(f"[AgentMetadataStore] Synced {synced} agent specs to DB")
        return synced

    # ============================================================
    # 查询
    # ============================================================

    @staticmethod
    def get_by_name(db: Session, agent_name: str) -> Optional[AgentRegistry]:
        """按名称获取 Agent 注册信息"""
        return db.query(AgentRegistry).filter(
            AgentRegistry.agent_name == agent_name
        ).first()

    @staticmethod
    def list_all(
        db: Session,
        enabled_only: bool = False,
        agent_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[AgentRegistry]:
        """列出所有 Agent 注册信息(支持过滤)"""
        query = db.query(AgentRegistry)
        if enabled_only:
            query = query.filter(AgentRegistry.enabled == True)
        if agent_type:
            query = query.filter(AgentRegistry.agent_type == agent_type)
        if status:
            query = query.filter(AgentRegistry.status == status)
        return query.order_by(AgentRegistry.agent_name).all()

    @staticmethod
    def search(
        db: Session,
        keyword: str,
        limit: int = 50,
    ) -> List[AgentRegistry]:
        """搜索 Agent (按名称/显示名/描述模糊匹配)"""
        pattern = f"%{keyword}%"
        return db.query(AgentRegistry).filter(
            or_(
                AgentRegistry.agent_name.like(pattern),
                AgentRegistry.display_name.like(pattern),
                AgentRegistry.description.like(pattern),
            )
        ).limit(limit).all()

    # ============================================================
    # CRUD - 注册/删除
    # ============================================================

    @staticmethod
    def create(
        db: Session,
        agent_name: str,
        agent_type: str = "llm",
        display_name: str = "",
        description: str = "",
        module_path: str = "",
        class_name: str = "",
        model_name: Optional[str] = None,
        model_provider: Optional[str] = None,
        system_prompt: str = "",
        tools: Optional[List[str]] = None,
        capabilities: Optional[List[str]] = None,
        enabled: bool = True,
        version: str = "1.0.0",
        config: Optional[Dict[str, Any]] = None,
    ) -> AgentRegistry:
        """创建 Agent 注册记录(动态注册)

        Args:
            db: 数据库会话
            agent_name: Agent 唯一名称
            agent_type: 类型 (llm/tool/runtime/adapter)
            display_name: 显示名
            description: 描述
            module_path: Python 模块路径
            class_name: 类名
            model_name: 模型名
            model_provider: 模型提供商
            system_prompt: 系统提示词
            tools: 工具列表
            capabilities: 能力列表
            enabled: 是否启用
            version: 版本号
            config: 配置字典

        Returns:
            AgentRegistry 记录

        Raises:
            ValueError: agent_name 已存在
        """
        existing = db.query(AgentRegistry).filter(
            AgentRegistry.agent_name == agent_name
        ).first()
        if existing:
            raise ValueError(f"Agent '{agent_name}' 已存在")

        record = AgentRegistry(
            agent_name=agent_name,
            agent_type=agent_type,
            display_name=display_name or agent_name,
            description=description,
            module_path=module_path,
            class_name=class_name,
            model_name=model_name,
            model_provider=model_provider,
            system_prompt=system_prompt,
            tools=json.dumps(tools or [], ensure_ascii=False),
            capabilities=json.dumps(capabilities or [], ensure_ascii=False),
            status="registered",
            enabled=enabled,
            version=version,
            config=json.dumps(config, ensure_ascii=False) if config else None,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        logger.info(f"[AgentMetadataStore] 创建 Agent: {agent_name} v{version}")
        return record

    @staticmethod
    def delete(db: Session, agent_name: str) -> bool:
        """删除 Agent 注册记录

        Args:
            db: 数据库会话
            agent_name: Agent 名称

        Returns:
            True: 删除成功 / False: 不存在
        """
        record = db.query(AgentRegistry).filter(
            AgentRegistry.agent_name == agent_name
        ).first()
        if record is None:
            return False
        db.delete(record)
        db.commit()
        logger.info(f"[AgentMetadataStore] 删除 Agent: {agent_name}")
        return True

    @staticmethod
    def update(
        db: Session,
        agent_name: str,
        **updates,
    ) -> Optional[AgentRegistry]:
        """更新 Agent 注册记录(全量更新)

        支持更新的字段:
            display_name, description, agent_type, module_path, class_name,
            model_name, model_provider, system_prompt, prompt_path,
            tools(list), capabilities(list), enabled(bool), version(str),
            config(dict), metadata(dict)

        Args:
            db: 数据库会话
            agent_name: Agent 名称
            **updates: 要更新的字段

        Returns:
            更新后的记录, None 表示不存在
        """
        record = db.query(AgentRegistry).filter(
            AgentRegistry.agent_name == agent_name
        ).first()
        if record is None:
            return None

        # 字段映射
        list_fields = {"tools", "capabilities"}
        dict_fields = {"config", "metadata"}
        metadata_key = "metadata_json"

        for key, value in updates.items():
            if value is None:
                continue
            if key in list_fields:
                setattr(record, key, json.dumps(value, ensure_ascii=False))
            elif key == "metadata":
                setattr(record, metadata_key, json.dumps(value, ensure_ascii=False))
            elif key in dict_fields:
                setattr(record, key, json.dumps(value, ensure_ascii=False))
            elif hasattr(record, key):
                setattr(record, key, value)

        db.commit()
        db.refresh(record)
        logger.info(f"[AgentMetadataStore] 更新 Agent: {agent_name}")
        return record

    # ============================================================
    # 状态管理
    # ============================================================

    @staticmethod
    def update_status(db: Session, agent_name: str, status: str) -> bool:
        """更新 Agent 状态

        状态值: registered/initialized/running/stopped/error
        """
        record = db.query(AgentRegistry).filter(
            AgentRegistry.agent_name == agent_name
        ).first()
        if record is None:
            return False
        record.status = status
        db.commit()
        logger.info(f"[AgentMetadataStore] Agent '{agent_name}' status → {status}")
        return True

    @staticmethod
    def toggle_enabled(db: Session, agent_name: str, enabled: bool) -> bool:
        """启用/禁用 Agent"""
        record = db.query(AgentRegistry).filter(
            AgentRegistry.agent_name == agent_name
        ).first()
        if record is None:
            return False
        record.enabled = enabled
        db.commit()
        logger.info(f"[AgentMetadataStore] Agent '{agent_name}' enabled → {enabled}")
        return True

    # ============================================================
    # 配置管理
    # ============================================================

    @staticmethod
    def update_config(db: Session, agent_name: str, config: Dict[str, Any]) -> bool:
        """更新 Agent 配置(config 字段)

        Args:
            db: 数据库会话
            agent_name: Agent 名称
            config: 配置字典

        Returns:
            True: 更新成功 / False: Agent 不存在
        """
        record = db.query(AgentRegistry).filter(
            AgentRegistry.agent_name == agent_name
        ).first()
        if record is None:
            return False
        record.config = json.dumps(config, ensure_ascii=False)
        db.commit()
        logger.info(f"[AgentMetadataStore] Agent '{agent_name}' config 已更新")
        return True

    @staticmethod
    def get_config(db: Session, agent_name: str) -> Optional[Dict[str, Any]]:
        """获取 Agent 配置"""
        record = db.query(AgentRegistry).filter(
            AgentRegistry.agent_name == agent_name
        ).first()
        if record is None:
            return None
        return json.loads(record.config) if record.config else {}

    @staticmethod
    def update_model(db: Session, agent_name: str, model_name: str, provider: str) -> bool:
        """更新 Agent 模型配置"""
        record = db.query(AgentRegistry).filter(
            AgentRegistry.agent_name == agent_name
        ).first()
        if record is None:
            return False
        record.model_name = model_name
        record.model_provider = provider
        db.commit()
        logger.info(f"[AgentMetadataStore] Agent '{agent_name}' model → {provider}/{model_name}")
        return True

    # ============================================================
    # 版本管理
    # ============================================================

    @staticmethod
    def update_version(db: Session, agent_name: str, version: str) -> bool:
        """更新 Agent 版本号

        Args:
            db: 数据库会话
            agent_name: Agent 名称
            version: 新版本号 (如 "1.1.0")

        Returns:
            True: 更新成功 / False: Agent 不存在
        """
        record = db.query(AgentRegistry).filter(
            AgentRegistry.agent_name == agent_name
        ).first()
        if record is None:
            return False
        old_version = record.version
        record.version = version
        # 将旧版本存入 metadata
        metadata = json.loads(record.metadata_json) if record.metadata_json else {}
        if "version_history" not in metadata:
            metadata["version_history"] = []
        metadata["version_history"].append({
            "version": old_version,
            "updated_at": str(record.updated_at) if record.updated_at else None,
        })
        metadata["previous_version"] = old_version
        record.metadata_json = json.dumps(metadata, ensure_ascii=False)
        db.commit()
        logger.info(f"[AgentMetadataStore] Agent '{agent_name}' version: {old_version} → {version}")
        return True

    @staticmethod
    def get_version_history(db: Session, agent_name: str) -> List[Dict[str, Any]]:
        """获取 Agent 版本历史"""
        record = db.query(AgentRegistry).filter(
            AgentRegistry.agent_name == agent_name
        ).first()
        if record is None:
            return []
        metadata = json.loads(record.metadata_json) if record.metadata_json else {}
        return metadata.get("version_history", [])

    # ============================================================
    # 统计
    # ============================================================

    @staticmethod
    def get_stats(db: Session) -> Dict[str, Any]:
        """获取 Agent 注册统计信息"""
        from sqlalchemy import func

        total = db.query(func.count(AgentRegistry.id)).scalar() or 0
        enabled = db.query(func.count(AgentRegistry.id)).filter(
            AgentRegistry.enabled == True
        ).scalar() or 0
        disabled = total - enabled

        # 按类型统计
        type_counts = db.query(
            AgentRegistry.agent_type,
            func.count(AgentRegistry.id),
        ).group_by(AgentRegistry.agent_type).all()
        by_type = {t: c for t, c in type_counts}

        # 按状态统计
        status_counts = db.query(
            AgentRegistry.status,
            func.count(AgentRegistry.id),
        ).group_by(AgentRegistry.status).all()
        by_status = {s: c for s, c in status_counts}

        return {
            "total": total,
            "enabled": enabled,
            "disabled": disabled,
            "by_type": by_type,
            "by_status": by_status,
        }

    # ============================================================
    # 转换
    # ============================================================

    @staticmethod
    def to_spec(record: AgentRegistry) -> AgentSpec:
        """将 DB 记录转换为 AgentSpec"""
        from app.agents.factory.config import AgentSpec, ModelConfig

        model = None
        if record.model_name and record.model_provider:
            model = ModelConfig(
                provider=record.model_provider,
                model_name=record.model_name,
            )

        # 合并 config 到 metadata
        config = json.loads(record.config) if record.config else {}
        metadata = json.loads(record.metadata_json) if record.metadata_json else {}
        if config:
            metadata["config"] = config

        return AgentSpec(
            name=record.agent_name,
            display_name=record.display_name or record.agent_name,
            description=record.description or "",
            agent_type=record.agent_type,
            module_path=record.module_path,
            class_name=record.class_name,
            model=model,
            system_prompt=record.system_prompt or "",
            prompt_template=record.prompt_path or "",
            tools=json.loads(record.tools) if record.tools else [],
            capabilities=json.loads(record.capabilities) if record.capabilities else [],
            enabled=record.enabled,
            metadata=metadata,
        )

    @staticmethod
    def list_to_dicts(records: List[AgentRegistry]) -> List[Dict[str, Any]]:
        """将 DB 记录列表转为字典列表"""
        return [r.to_dict() for r in records]
