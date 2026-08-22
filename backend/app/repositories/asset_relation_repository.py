"""
AssetRelationRepository - 资产关系数据访问层

职责:
  1. 封装 AssetRelation 的 CRUD
  2. JSON 字段(metadata_json)的序列化
  3. 软删除过滤
  4. 按 asset_id + direction / relation_type / target_type 过滤
  5. Neo4j 同步状态跟踪 (neo4j_synced / neo4j_synced_at)
  6. 重复关系检测 (source + type + target 唯一)
  7. 自环关系检测 (source_id == target_id)

不做:
  - Neo4j 实际同步 (由 service 层调用 Neo4j client 完成)
  - 关系合法性校验 (如 type 与 asset_type 组合, 由 service 层校验)
"""
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.asset_registry import (
    AssetRelation,
    AssetRegistry,
    AssetRelationType,
)
from app.core.exceptions import (
    AssetRelationNotFoundError,
    AssetRelationConflictError,
)

logger = logging.getLogger(__name__)


def _dump_json(value: Any) -> Optional[str]:
    """Python 对象 → JSON 字符串(None 保持 None)"""
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as e:
        logger.warning(f"JSON 序列化失败: {e}")
        return None


def _load_json(value: Optional[str], default: Any = None) -> Any:
    """JSON 字符串 → Python 对象"""
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError) as e:
        logger.warning(f"JSON 反序列化失败: {e}, raw={value[:100]}")
        return default


class AssetRelationRepository:
    """资产关系 Repository"""

    # ------------------------------------------------------------------
    # 创建
    # ------------------------------------------------------------------

    def create(
        self,
        db: Session,
        *,
        source_id: int,
        target_id: int,
        relation_type: str,
        weight: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
    ) -> AssetRelation:
        """创建资产关系

        重复检测:
          1. source_id == target_id → AssetRelationConflictError (自环)
          2. (source, type, target) 已存在 → AssetRelationConflictError
        """
        # 1. 自环检查
        if source_id == target_id:
            raise AssetRelationConflictError(
                f"不允许自环关系: source_id == target_id == {source_id}",
                source_id=source_id,
                target_id=target_id,
                relation_type=relation_type,
            )

        # 2. 重复检查 (软删除的也算冲突? 这里采用"软删除的允许重建"策略,
        #    仅查未软删除的)
        existing = db.query(AssetRelation).filter(
            AssetRelation.source_id == source_id,
            AssetRelation.target_id == target_id,
            AssetRelation.relation_type == relation_type,
            AssetRelation.is_deleted == False,  # noqa: E712
        ).first()
        if existing:
            raise AssetRelationConflictError(
                f"关系已存在: {source_id} -[{relation_type}]-> {target_id}",
                relation_id=existing.id,
                source_id=source_id,
                target_id=target_id,
                relation_type=relation_type,
            )

        relation = AssetRelation(
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            weight=weight,
            metadata_json=_dump_json(metadata),
            neo4j_synced=False,
            is_deleted=False,
            user_id=user_id,
        )
        db.add(relation)
        db.flush()
        logger.info(
            f"[AssetRelRepo] 创建关系 id={relation.id} "
            f"{source_id} -[{relation_type}]-> {target_id}"
        )
        return relation

    # ------------------------------------------------------------------
    # 查询(单个)
    # ------------------------------------------------------------------

    def get_by_id(
        self,
        db: Session,
        relation_id: int,
        *,
        user_id: Optional[int] = None,
        include_deleted: bool = False,
    ) -> AssetRelation:
        """按 ID 查询关系,不存在或软删除则抛 NotFoundError"""
        q = db.query(AssetRelation).filter(AssetRelation.id == relation_id)
        if user_id is not None:
            q = q.filter(AssetRelation.user_id == user_id)
        if not include_deleted:
            q = q.filter(AssetRelation.is_deleted == False)  # noqa: E712
        relation = q.first()
        if not relation:
            raise AssetRelationNotFoundError(
                f"关系不存在或已删除: id={relation_id}",
                relation_id=relation_id,
            )
        return relation

    # ------------------------------------------------------------------
    # 查询(列表)
    # ------------------------------------------------------------------

    def list(
        self,
        db: Session,
        *,
        asset_id: Optional[int] = None,
        direction: Optional[str] = None,
        relation_type: Optional[str] = None,
        target_type: Optional[str] = None,
        user_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[AssetRelation], int]:
        """分页查询关系列表

        参数:
          asset_id:    查询该资产的出入关系
          direction:   'outgoing' (source_id=asset_id)
                       'incoming' (target_id=asset_id)
                       None       (两者都查)
          target_type: 对端资产的 asset_type 过滤
        """
        q = db.query(AssetRelation).filter(
            AssetRelation.is_deleted == False  # noqa: E712
        )

        if user_id is not None:
            q = q.filter(AssetRelation.user_id == user_id)

        if asset_id is not None:
            if direction == "outgoing":
                q = q.filter(AssetRelation.source_id == asset_id)
            elif direction == "incoming":
                q = q.filter(AssetRelation.target_id == asset_id)
            else:
                # 两者都查
                q = q.filter(or_(
                    AssetRelation.source_id == asset_id,
                    AssetRelation.target_id == asset_id,
                ))

        if relation_type:
            q = q.filter(AssetRelation.relation_type == relation_type)

        if target_type:
            # 子查询: 对端资产 asset_type 过滤
            # outgoing: target_id 对应的 asset.asset_type
            # incoming: source_id 对应的 asset.asset_type
            if direction == "outgoing":
                q = q.join(
                    AssetRegistry,
                    AssetRelation.target_id == AssetRegistry.id,
                ).filter(AssetRegistry.asset_type == target_type)
            elif direction == "incoming":
                q = q.join(
                    AssetRegistry,
                    AssetRelation.source_id == AssetRegistry.id,
                ).filter(AssetRegistry.asset_type == target_type)
            else:
                # 两者都查: 需要分别 join 再合并
                # 简化: 先 outgoing 再 incoming, 合并结果
                # 此处采用子查询 union 策略
                outgoing_q = q.join(
                    AssetRegistry,
                    AssetRelation.target_id == AssetRegistry.id,
                ).filter(AssetRegistry.asset_type == target_type)
                incoming_q = q.join(
                    AssetRegistry,
                    AssetRelation.source_id == AssetRegistry.id,
                ).filter(AssetRegistry.asset_type == target_type)
                q = outgoing_q.union(incoming_q)

        total = q.count()
        items = (
            q.order_by(AssetRelation.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    def list_outgoing(
        self,
        db: Session,
        asset_id: int,
        *,
        relation_type: Optional[str] = None,
    ) -> List[AssetRelation]:
        """获取资产的所有出向关系 (source_id=asset_id)"""
        q = db.query(AssetRelation).filter(
            AssetRelation.source_id == asset_id,
            AssetRelation.is_deleted == False,  # noqa: E712
        )
        if relation_type:
            q = q.filter(AssetRelation.relation_type == relation_type)
        return q.all()

    def list_incoming(
        self,
        db: Session,
        asset_id: int,
        *,
        relation_type: Optional[str] = None,
    ) -> List[AssetRelation]:
        """获取资产的所有入向关系 (target_id=asset_id)"""
        q = db.query(AssetRelation).filter(
            AssetRelation.target_id == asset_id,
            AssetRelation.is_deleted == False,  # noqa: E712
        )
        if relation_type:
            q = q.filter(AssetRelation.relation_type == relation_type)
        return q.all()

    # ------------------------------------------------------------------
    # 更新
    # ------------------------------------------------------------------

    def update(
        self,
        db: Session,
        relation: AssetRelation,
        *,
        weight: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AssetRelation:
        """更新关系权重或元数据

        更新后 neo4j_synced 重置为 False (需要重新同步)
        """
        if weight is not None:
            relation.weight = weight
        if metadata is not None:
            relation.metadata_json = _dump_json(metadata)
        # 关系内容变更, 需要重新同步 Neo4j
        if weight is not None or metadata is not None:
            relation.neo4j_synced = False
            relation.neo4j_synced_at = None
        db.flush()
        logger.info(f"[AssetRelRepo] 更新关系 id={relation.id}")
        return relation

    # ------------------------------------------------------------------
    # Neo4j 同步状态
    # ------------------------------------------------------------------

    def mark_neo4j_synced(
        self,
        db: Session,
        relation: AssetRelation,
        *,
        synced_at: Optional[datetime] = None,
    ) -> AssetRelation:
        """标记关系已同步到 Neo4j"""
        relation.neo4j_synced = True
        relation.neo4j_synced_at = synced_at or datetime.now()
        db.flush()
        return relation

    def list_unsynced(
        self,
        db: Session,
        *,
        limit: int = 100,
    ) -> List[AssetRelation]:
        """查询未同步 Neo4j 的关系 (用于补偿任务)"""
        return db.query(AssetRelation).filter(
            AssetRelation.neo4j_synced == False,  # noqa: E712
            AssetRelation.is_deleted == False,  # noqa: E712
        ).limit(limit).all()

    # ------------------------------------------------------------------
    # 软删除
    # ------------------------------------------------------------------

    def soft_delete(self, db: Session, relation: AssetRelation) -> AssetRelation:
        """软删除关系

        软删除后:
          - 不出现在列表查询中
          - Neo4j 中的对应边由 service 层负责删除 (标记 neo4j_synced=False)
        """
        relation.is_deleted = True
        relation.neo4j_synced = False  # 需要在 Neo4j 中删除对应边
        db.flush()
        logger.info(f"[AssetRelRepo] 软删除关系 id={relation.id}")
        return relation

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def stats(
        self,
        db: Session,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """关系统计"""
        q = db.query(AssetRelation).filter(
            AssetRelation.is_deleted == False  # noqa: E712
        )
        if user_id is not None:
            q = q.filter(AssetRelation.user_id == user_id)

        total = q.count()
        pending_sync = db.query(AssetRelation).filter(
            AssetRelation.neo4j_synced == False,  # noqa: E712
            AssetRelation.is_deleted == False,  # noqa: E712
            *([AssetRelation.user_id == user_id] if user_id is not None else []),
        ).count()

        return {
            "total_relations": total,
            "pending_neo4j_sync": pending_sync,
        }

    # ------------------------------------------------------------------
    # 序列化 helpers
    # ------------------------------------------------------------------

    def to_dict(self, relation: AssetRelation) -> Dict[str, Any]:
        """关系完整字段 → dict"""
        return {
            "id": relation.id,
            "source_id": relation.source_id,
            "target_id": relation.target_id,
            "relation_type": relation.relation_type,
            "weight": float(relation.weight or 1.0),
            "metadata": _load_json(relation.metadata_json, default={}) or {},
            "neo4j_synced": relation.neo4j_synced,
            "neo4j_synced_at": relation.neo4j_synced_at,
            "user_id": relation.user_id,
            "created_at": relation.created_at,
            "updated_at": relation.updated_at,
        }

    def to_dict_with_assets(
        self,
        relation: AssetRelation,
        source_asset: Optional[AssetRegistry] = None,
        target_asset: Optional[AssetRegistry] = None,
    ) -> Dict[str, Any]:
        """关系字段 → dict (含对端资产概要, 用于列表展示)"""
        result = self.to_dict(relation)
        if source_asset:
            result["source_asset"] = {
                "asset_id": source_asset.id,
                "asset_code": source_asset.asset_code,
                "name": source_asset.name,
                "ref_type": source_asset.ref_type,
                "ref_id": source_asset.ref_id,
            }
        if target_asset:
            result["target_asset"] = {
                "asset_id": target_asset.id,
                "asset_code": target_asset.asset_code,
                "name": target_asset.name,
                "ref_type": target_asset.ref_type,
                "ref_id": target_asset.ref_id,
            }
        return result
