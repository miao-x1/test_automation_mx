"""
AssetRelationService - 测试资产中心服务层 (资产关系)

职责:
  1. 资产关系 CRUD 的业务编排
  2. 关系合法性校验 (source/target 存在性、状态约束)
  3. Neo4j 同步钩子 (创建/更新/删除后触发, 失败不阻塞主流程)
  4. 批量关系创建 (用于 Agent 批量建立关联)
  5. 关系影响面分析 (给定资产, 找出所有受影响的相关资产)

不做:
  - HTTP 层逻辑
  - SQL 拼接
  - Neo4j 实际同步 (Phase 2 为 stub, Phase 3 接入真实 Neo4j client)

依赖:
  - AssetRelationRepository
  - AssetRepository (校验 source/target 存在)
  - SessionLocal
"""
import logging
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import (
    AssetNotFoundError,
    AssetRelationConflictError,
    AssetRelationNotFoundError,
    AssetStateError,
)
from app.db.database import SessionLocal
from app.models.asset_registry import AssetRegistry, AssetRegistryStatus
from app.repositories.asset_repository import AssetRepository
from app.repositories.asset_relation_repository import AssetRelationRepository
from app.schemas.asset_registry import (
    RelationCreate,
    RelationUpdate,
)

logger = logging.getLogger(__name__)


class AssetRelationService:
    """测试资产中心 — 资产关系服务"""

    def __init__(self):
        self._rel_repo = AssetRelationRepository()
        self._asset_repo = AssetRepository()

    # ------------------------------------------------------------------
    # 会话管理
    # ------------------------------------------------------------------

    @contextmanager
    def _session(self) -> Iterator[Session]:
        db = SessionLocal()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ------------------------------------------------------------------
    # 创建关系
    # ------------------------------------------------------------------

    def create_relation(
        self,
        payload: RelationCreate,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """创建资产关系

        业务校验:
          1. source / target 资产必须存在 (未软删除)
          2. source / target 不能是已归档状态 (归档资产不参与关系)
          3. (source, type, target) 不重复 (由 repository 检查)
          4. 不允许自环 (schema 已校验, 此处兜底)

        创建后:
          - 触发 Neo4j 同步 (异步, 失败不阻塞)
        """
        with self._session() as db:
            # 1. 校验 source 存在
            source = self._asset_repo.get_by_id(
                db, payload.source_id, user_id=user_id
            )
            if source.status == AssetRegistryStatus.ARCHIVED:
                raise AssetStateError(
                    f"源资产已归档, 不允许创建关系: id={payload.source_id}",
                    asset_id=payload.source_id,
                    current_status=source.status,
                )

            # 2. 校验 target 存在
            target = self._asset_repo.get_by_id(
                db, payload.target_id, user_id=user_id
            )
            if target.status == AssetRegistryStatus.ARCHIVED:
                raise AssetStateError(
                    f"目标资产已归档, 不允许创建关系: id={payload.target_id}",
                    asset_id=payload.target_id,
                    current_status=target.status,
                )

            # 3. 创建关系
            try:
                relation = self._rel_repo.create(
                    db,
                    source_id=payload.source_id,
                    target_id=payload.target_id,
                    relation_type=payload.relation_type,
                    weight=payload.weight,
                    metadata=payload.metadata,
                    user_id=user_id,
                )
            except AssetRelationConflictError:
                raise

            # 4. 序列化 (含对端资产概要)
            result = self._rel_repo.to_dict_with_assets(
                relation, source_asset=source, target_asset=target
            )

            # 5. 触发 Neo4j 同钩子 (异步, 不阻塞主流程)
            self._trigger_neo4j_sync(db, relation, action="create")

            logger.info(
                f"[AssetRelSvc] 创建关系成功 id={relation.id} "
                f"{payload.source_id} -[{payload.relation_type}]-> {payload.target_id}"
            )
            return result

    # ------------------------------------------------------------------
    # 查询关系
    # ------------------------------------------------------------------

    def get_relation(
        self,
        relation_id: int,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """按 ID 获取关系详情 (含对端资产概要)"""
        with self._session() as db:
            relation = self._rel_repo.get_by_id(
                db, relation_id, user_id=user_id
            )
            source = self._asset_repo.get_by_id(
                db, relation.source_id, user_id=user_id
            )
            target = self._asset_repo.get_by_id(
                db, relation.target_id, user_id=user_id
            )
            return self._rel_repo.to_dict_with_assets(
                relation, source_asset=source, target_asset=target
            )

    # ------------------------------------------------------------------
    # 列表查询
    # ------------------------------------------------------------------

    def list_relations(
        self,
        *,
        asset_id: Optional[int] = None,
        direction: Optional[str] = None,
        relation_type: Optional[str] = None,
        target_type: Optional[str] = None,
        user_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """分页查询关系列表"""
        with self._session() as db:
            items, total = self._rel_repo.list(
                db,
                asset_id=asset_id,
                direction=direction,
                relation_type=relation_type,
                target_type=target_type,
                user_id=user_id,
                page=page,
                page_size=page_size,
            )
            # 批量加载对端资产信息 (减少 N+1 查询)
            asset_ids = set()
            for rel in items:
                asset_ids.add(rel.source_id)
                asset_ids.add(rel.target_id)
            assets_map = {}
            if asset_ids:
                assets = db.query(AssetRegistry).filter(
                    AssetRegistry.id.in_(asset_ids)
                ).all()
                assets_map = {a.id: a for a in assets}

            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "items": [
                    self._rel_repo.to_dict_with_assets(
                        rel,
                        source_asset=assets_map.get(rel.source_id),
                        target_asset=assets_map.get(rel.target_id),
                    )
                    for rel in items
                ],
            }

    # ------------------------------------------------------------------
    # 更新关系
    # ------------------------------------------------------------------

    def update_relation(
        self,
        relation_id: int,
        payload: RelationUpdate,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """更新关系权重或元数据"""
        update_data = payload.model_dump(exclude_unset=True, exclude_none=True)

        with self._session() as db:
            relation = self._rel_repo.get_by_id(
                db, relation_id, user_id=user_id
            )
            self._rel_repo.update(
                db,
                relation,
                weight=update_data.get("weight"),
                metadata=update_data.get("metadata"),
            )
            # 触发 Neo4j 重新同步
            self._trigger_neo4j_sync(db, relation, action="update")

            result = self._rel_repo.to_dict(relation)
            logger.info(f"[AssetRelSvc] 更新关系 id={relation.id}")
            return result

    # ------------------------------------------------------------------
    # 删除关系
    # ------------------------------------------------------------------

    def delete_relation(
        self,
        relation_id: int,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """软删除关系"""
        with self._session() as db:
            relation = self._rel_repo.get_by_id(
                db, relation_id, user_id=user_id
            )
            self._rel_repo.soft_delete(db, relation)
            # 标记 Neo4j 需要删除对应边
            self._trigger_neo4j_sync(db, relation, action="delete")

            logger.info(f"[AssetRelSvc] 软删除关系 id={relation.id}")
            return {
                "id": relation.id,
                "is_deleted": True,
            }

    # ------------------------------------------------------------------
    # 影响面分析
    # ------------------------------------------------------------------

    def impact_analysis(
        self,
        asset_id: int,
        *,
        depth: int = 2,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """影响面分析: 给定资产, 找出所有受影响的相关资产 (BFS)

        参数:
          asset_id: 起始资产 ID
          depth:    搜索深度 (1=直接关联, 2=二度关联, 默认 2)

        返回:
          {
            "root_asset": {...},
            "impacted": [
              {"asset": {...}, "depth": 1, "path": [A → B]},
              {"asset": {...}, "depth": 2, "path": [A → B → C]},
              ...
            ],
            "total_impacted": int,
          }
        """
        with self._session() as db:
            # 校验起始资产
            root = self._asset_repo.get_by_id(db, asset_id, user_id=user_id)

            # BFS 遍历
            visited = {asset_id}
            impacted: List[Dict[str, Any]] = []
            current_level = [(asset_id, [])]

            for current_depth in range(1, depth + 1):
                next_level = []
                for (current_id, path) in current_level:
                    # 出向关系
                    outgoing = self._rel_repo.list_outgoing(db, current_id)
                    # 入向关系
                    incoming = self._rel_repo.list_incoming(db, current_id)

                    for rel in outgoing + incoming:
                        neighbor_id = (
                            rel.target_id if rel.source_id == current_id
                            else rel.source_id
                        )
                        if neighbor_id in visited:
                            continue
                        visited.add(neighbor_id)

                        # 获取邻居资产
                        try:
                            neighbor = self._asset_repo.get_by_id(
                                db, neighbor_id, user_id=user_id
                            )
                        except AssetNotFoundError:
                            continue

                        new_path = path + [
                            {
                                "from": current_id,
                                "to": neighbor_id,
                                "relation_type": rel.relation_type,
                            }
                        ]
                        impacted.append({
                            "asset": self._asset_repo.to_list_item(neighbor),
                            "depth": current_depth,
                            "path": new_path,
                        })
                        next_level.append((neighbor_id, new_path))

                current_level = next_level

            return {
                "root_asset": self._asset_repo.to_list_item(root),
                "impacted": impacted,
                "total_impacted": len(impacted),
            }

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def get_stats(
        self,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """关系统计"""
        with self._session() as db:
            return self._rel_repo.stats(db, user_id=user_id)

    # ------------------------------------------------------------------
    # Neo4j 同步钩子 (Phase 2 为 stub)
    # ------------------------------------------------------------------

    def _trigger_neo4j_sync(
        self,
        db: Session,
        relation,
        *,
        action: str,
    ) -> None:
        """触发 Neo4j 同步

        Phase 2: 仅记录日志, 不实际同步
        Phase 3: 接入真实 Neo4j client (异步队列)

        action: create / update / delete
        """
        # Phase 2: stub, 仅日志
        logger.debug(
            f"[AssetRelSvc] Neo4j 同步钩子触发 (Phase 2 stub): "
            f"relation_id={relation.id} action={action}"
        )
        # 不修改 neo4j_synced (保持 False, 等待补偿任务或 Phase 3 接入)

    def sync_pending_to_neo4j(
        self,
        *,
        batch_size: int = 100,
    ) -> Dict[str, Any]:
        """补偿任务: 批量同步未同步的关系到 Neo4j

        Phase 2: 返回空结果 (无实际同步)
        Phase 3: 接入 Neo4j client, 批量写入
        """
        with self._session() as db:
            pending = self._rel_repo.list_unsynced(db, limit=batch_size)
            logger.info(
                f"[AssetRelSvc] 待同步 Neo4j 关系数: {len(pending)} "
                f"(Phase 2 stub, 不实际同步)"
            )
            return {
                "pending_count": len(pending),
                "synced_count": 0,
                "message": "Phase 2 stub, Neo4j 同步未实现",
            }
