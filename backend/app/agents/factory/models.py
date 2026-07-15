"""
Agent 元数据 DB 操作 - 数据库持久化层

将 AgentSpec 同步到 agent_registry 表，支持运行时动态管理。
"""
import json
import logging
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session

from app.models.agent_registry import AgentRegistry
from app.agents.factory.config import AgentSpec

logger = logging.getLogger(__name__)


class AgentMetadataStore:
    """Agent 元数据数据库存储

    提供 AgentSpec ↔ DB 的双向同步。
    启动时从 DB 加载，运行时变更写回 DB。
    """

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
                # 更新已有记录
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
                )
                db.add(record)

            synced += 1

        db.commit()
        logger.info(f"[AgentMetadataStore] Synced {synced} agent specs to DB")
        return synced

    @staticmethod
    def get_by_name(db: Session, agent_name: str) -> Optional[AgentRegistry]:
        """按名称获取 Agent 注册信息"""
        return db.query(AgentRegistry).filter(
            AgentRegistry.agent_name == agent_name
        ).first()

    @staticmethod
    def list_all(db: Session, enabled_only: bool = False) -> List[AgentRegistry]:
        """列出所有 Agent 注册信息"""
        query = db.query(AgentRegistry)
        if enabled_only:
            query = query.filter(AgentRegistry.enabled == True)
        return query.order_by(AgentRegistry.agent_name).all()

    @staticmethod
    def update_status(db: Session, agent_name: str, status: str) -> bool:
        """更新 Agent 状态"""
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
        )

    @staticmethod
    def list_to_dicts(records: List[AgentRegistry]) -> List[Dict[str, Any]]:
        """将 DB 记录列表转为字典列表"""
        return [r.to_dict() for r in records]
