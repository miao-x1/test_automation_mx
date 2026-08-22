"""
AssetRegistryService - 测试资产中心服务层 (资产索引)

职责:
  1. 业务逻辑编排(状态机、校验、版本管理)
  2. 事务边界管理(同事务内多步操作要么全成功要么全回滚)
  3. 委托 Repository 做 CRUD,Service 不直接写 SQL
  4. 数据转换: Model 实例 ↔ dict (通过 repository.to_dict)

不做:
  - HTTP 层逻辑(由 router 负责)
  - SQL 拼接(由 repository 负责)
  - Neo4j 同步(由 AssetRelationService 负责)
  - Milvus 向量同步(由 AssetSearchService 负责)

依赖:
  - AssetRepository (数据访问)
  - AssetVersionRepository (版本管理)
  - SessionLocal (事务管理)
"""
import logging
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import (
    AssetConflictError,
    AssetNotFoundError,
    AssetStateError,
    AssetValidationError,
    AssetVersionNotFoundError,
)
from app.db.database import SessionLocal
from app.models.asset_registry import (
    AssetRegistry,
    AssetRegistryStatus,
    AssetRegistrySource,
)
from app.repositories.asset_repository import AssetRepository
from app.repositories.asset_version_repository import AssetVersionRepository
from app.schemas.asset_registry import (
    AssetCreate,
    AssetUpdate,
    PublishRequest,
    StateTransitionRequest,
)

logger = logging.getLogger(__name__)


# ============================================================
# 状态机定义 (与设计文档一致)
# ============================================================

# 允许的状态流转(从 → 到)
_STATE_TRANSITIONS = {
    AssetRegistryStatus.DRAFT:      {AssetRegistryStatus.ACTIVE, AssetRegistryStatus.ARCHIVED},
    AssetRegistryStatus.ACTIVE:     {AssetRegistryStatus.DEPRECATED, AssetRegistryStatus.ARCHIVED},
    AssetRegistryStatus.DEPRECATED: {AssetRegistryStatus.ACTIVE, AssetRegistryStatus.ARCHIVED},
    AssetRegistryStatus.ARCHIVED:   {AssetRegistryStatus.DRAFT},
}

# 发布操作允许的起始状态 (publish_asset 方法用)
_PUBLISH_ALLOWED_FROM = {
    AssetRegistryStatus.DRAFT,
    AssetRegistryStatus.ACTIVE,      # 重新发布, 生成新版本
    AssetRegistryStatus.DEPRECATED,  # 恢复发布
}


class AssetRegistryService:
    """测试资产中心 — 资产索引服务

    使用方式:
        service = AssetRegistryService()
        result = service.create_asset(asset_create, user_id=1)
    """

    def __init__(self):
        self._repo = AssetRepository()
        self._version_repo = AssetVersionRepository()

    # ------------------------------------------------------------------
    # 会话管理
    # ------------------------------------------------------------------

    @contextmanager
    def _session(self) -> Iterator[Session]:
        """事务会话上下文管理器

        正常退出 → commit
        异常退出 → rollback + 抛出原异常
        """
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
    # 创建资产
    # ------------------------------------------------------------------

    def create_asset(
        self,
        payload: AssetCreate,
        *,
        user_id: Optional[int] = None,
        created_by: Optional[int] = None,
    ) -> Dict[str, Any]:
        """创建资产索引

        业务校验:
          1. source 必须在允许集合内 (schema 已校验, 此处兜底)
          2. status 只能是 draft (首次创建)
          3. asset_code 唯一 (由 repository 检查)
          4. ref_type + ref_id 唯一 (由 repository 检查)
          5. asset_type 与 ref_type 一致性 (schema 已校验)

        创建后:
          - 自动生成版本 v1 (change_type=create, 含初始快照)
        """
        with self._session() as db:
            try:
                asset = self._repo.create(
                    db,
                    name=payload.name,
                    asset_type=payload.asset_type,
                    ref_type=payload.ref_type,
                    ref_id=payload.ref_id,
                    asset_code=payload.asset_code,
                    summary=payload.summary,
                    description=payload.description,
                    module=payload.module,
                    tags=payload.tags,
                    source=payload.source,
                    status=AssetRegistryStatus.DRAFT,
                    extra_metadata=payload.extra_metadata,
                    user_id=user_id,
                    created_by=created_by,
                )
            except AssetConflictError:
                raise

            # 生成初始版本 v1
            snapshot = self._repo.snapshot(asset)
            self._version_repo.create_version(
                db,
                asset_id=asset.id,
                version=1,
                snapshot=snapshot,
                change_log="初始创建",
                change_type="create",
                published_by=created_by,
                user_id=user_id,
            )

            result = self._repo.to_dict(asset)
            result["current_version"] = 1
            logger.info(
                f"[AssetRegSvc] 创建资产成功 id={asset.id} code={asset.asset_code}"
            )
            return result

    # ------------------------------------------------------------------
    # 查询资产详情
    # ------------------------------------------------------------------

    def get_asset(
        self,
        asset_id: int,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """按 ID 获取资产详情"""
        with self._session() as db:
            asset = self._repo.get_by_id(db, asset_id, user_id=user_id)
            result = self._repo.to_dict(asset)
            # 附带当前版本信息
            current_version = self._version_repo.get_current(db, asset_id)
            if current_version:
                result["current_version"] = current_version.version
            return result

    # ------------------------------------------------------------------
    # 查询资产列表
    # ------------------------------------------------------------------

    def list_assets(
        self,
        *,
        user_id: Optional[int] = None,
        keyword: Optional[str] = None,
        asset_type: Optional[str] = None,
        status: Optional[str] = None,
        module: Optional[str] = None,
        source: Optional[str] = None,
        tags: Optional[List[str]] = None,
        ref_type: Optional[str] = None,
        min_quality: Optional[float] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """分页查询资产列表"""
        with self._session() as db:
            items, total = self._repo.list(
                db,
                user_id=user_id,
                keyword=keyword,
                asset_type=asset_type,
                status=status,
                module=module,
                source=source,
                tags=tags,
                ref_type=ref_type,
                min_quality=min_quality,
                page=page,
                page_size=page_size,
            )
            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "items": [self._repo.to_list_item(a) for a in items],
            }

    # ------------------------------------------------------------------
    # 更新资产
    # ------------------------------------------------------------------

    def update_asset(
        self,
        asset_id: int,
        payload: AssetUpdate,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """更新资产 (不生成新版本, 需 publish_asset 才生成版本)

        业务校验:
          1. 资产存在 (由 repository 检查)
          2. 资产状态不能是 archived (归档资产不允许更新, 需先恢复为 draft)
        """
        update_data = payload.model_dump(exclude_unset=True, exclude_none=True)

        with self._session() as db:
            asset = self._repo.get_by_id(db, asset_id, user_id=user_id)

            # 状态约束: archived 不允许更新
            if asset.status == AssetRegistryStatus.ARCHIVED:
                raise AssetStateError(
                    "已归档的资产不能更新, 请先恢复为草稿",
                    asset_id=asset.id,
                    current_status=asset.status,
                )

            self._repo.update(db, asset, **update_data)
            result = self._repo.to_dict(asset)
            logger.info(f"[AssetRegSvc] 更新资产成功 id={asset.id}")
            return result

    # ------------------------------------------------------------------
    # 删除资产 (软删除)
    # ------------------------------------------------------------------

    def delete_asset(
        self,
        asset_id: int,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """软删除资产

        软删除后:
          - 不出现在列表查询中
          - 历史版本与关系保留 (供审计)
        """
        with self._session() as db:
            asset = self._repo.get_by_id(db, asset_id, user_id=user_id)
            self._repo.soft_delete(db, asset)
            logger.info(f"[AssetRegSvc] 软删除资产 id={asset.id}")
            return {
                "id": asset.id,
                "is_deleted": True,
                "asset_code": asset.asset_code,
            }

    # ------------------------------------------------------------------
    # 发布资产 (生成版本快照 + 状态置为 active)
    # ------------------------------------------------------------------

    def publish_asset(
        self,
        asset_id: int,
        payload: PublishRequest,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """发布资产: 生成版本快照 + 状态置为 active

        状态约束:
          - draft → active 允许 (首次发布)
          - active → active 允许 (重新发布, 生成新版本)
          - deprecated → active 允许 (恢复发布)
          - archived → 不允许 (必须先恢复为 draft)

        步骤:
          1. 查资产, 校验状态
          2. 取上一版本快照用于 diff
          3. 生成当前快照
          4. 版本号 +1
          5. 创建新版本记录 (change_type 由 payload 指定)
          6. 状态流转到 active
          7. 更新 asset.version
        """
        with self._session() as db:
            asset = self._repo.get_by_id(db, asset_id, user_id=user_id)

            # 状态约束
            if asset.status not in _PUBLISH_ALLOWED_FROM:
                raise AssetStateError(
                    f"当前状态 {asset.status} 不允许发布, 仅 {_PUBLISH_ALLOWED_FROM} 可发布",
                    asset_id=asset.id,
                    current_status=asset.status,
                    target_status=AssetRegistryStatus.ACTIVE,
                )

            # 取上一版本快照 (用于 diff)
            current_version = self._version_repo.get_current(db, asset.id)
            previous_snapshot = None
            if current_version:
                import json
                try:
                    previous_snapshot = json.loads(current_version.snapshot_json)
                except (json.JSONDecodeError, TypeError):
                    previous_snapshot = None

            # 生成新快照
            new_snapshot = self._repo.snapshot(asset)

            # 计算 diff
            diff_summary = self._version_repo.compute_diff(
                new_snapshot, previous_snapshot
            )

            # 版本号 +1
            new_version = (asset.version or 1) + 1

            # 创建新版本记录
            self._version_repo.create_version(
                db,
                asset_id=asset.id,
                version=new_version,
                snapshot=new_snapshot,
                change_log=payload.change_log,
                change_type=payload.change_type,
                diff_summary=diff_summary,
                published_by=user_id,
                user_id=user_id,
            )

            # 状态流转 + 版本号更新
            self._repo.transition_state(db, asset, AssetRegistryStatus.ACTIVE)
            asset.version = new_version
            db.flush()

            result = self._repo.to_dict(asset)
            result["current_version"] = new_version
            logger.info(
                f"[AssetRegSvc] 发布资产成功 id={asset.id} v{new_version}"
            )
            return result

    # ------------------------------------------------------------------
    # 状态流转 (显式, 不生成版本)
    # ------------------------------------------------------------------

    def change_status(
        self,
        asset_id: int,
        payload: StateTransitionRequest,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """显式状态流转 (不生成版本)

        用于 deprecated / archived 等不涉及内容变更的状态切换
        若 target_status == active, 建议用 publish_asset (会生成版本)
        """
        target = payload.target_status

        with self._session() as db:
            asset = self._repo.get_by_id(db, asset_id, user_id=user_id)

            # 同状态直接返回
            if asset.status == target:
                return self._repo.to_dict(asset)

            # 校验流转合法性
            if not self._can_transition(asset.status, target):
                raise AssetStateError(
                    f"状态流转非法: {asset.status} → {target}",
                    asset_id=asset.id,
                    current_status=asset.status,
                    target_status=target,
                )

            previous_status = asset.status
            self._repo.transition_state(db, asset, target)

            # 状态变更也生成一个轻量版本记录 (无内容快照变更, change_type=status_change)
            # 仅当状态确实变化时
            new_version = (asset.version or 1) + 1
            snapshot = self._repo.snapshot(asset)
            self._version_repo.create_version(
                db,
                asset_id=asset.id,
                version=new_version,
                snapshot=snapshot,
                change_log=payload.reason or f"状态流转: {previous_status} → {target}",
                change_type="status_change",
                published_by=user_id,
                user_id=user_id,
            )
            asset.version = new_version
            db.flush()

            result = self._repo.to_dict(asset)
            result["previous_status"] = previous_status
            result["current_version"] = new_version
            logger.info(
                f"[AssetRegSvc] 状态流转 id={asset.id} {previous_status} → {target}"
            )
            return result

    # ------------------------------------------------------------------
    # 版本管理
    # ------------------------------------------------------------------

    def list_versions(
        self,
        asset_id: int,
        *,
        user_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """列出资产的所有版本"""
        with self._session() as db:
            # 先校验资产存在
            self._repo.get_by_id(db, asset_id, user_id=user_id)
            items, total = self._version_repo.list_versions(
                db, asset_id, page=page, page_size=page_size
            )
            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "items": [self._version_repo.to_list_item(v) for v in items],
            }

    def get_version(
        self,
        asset_id: int,
        version: int,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """获取指定版本详情 (含快照)"""
        with self._session() as db:
            # 先校验资产存在
            self._repo.get_by_id(db, asset_id, user_id=user_id)
            v = self._version_repo.get_by_version(db, asset_id, version)
            return self._version_repo.to_dict(v)

    def rollback_to_version(
        self,
        asset_id: int,
        version: int,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """回滚到指定版本

        步骤:
          1. 校验资产存在 + 状态非 archived
          2. 取目标版本快照
          3. 从快照恢复可变字段 (name, summary, description, module, tags, extra_metadata)
             不可变字段不恢复: asset_code, asset_type, ref_type, ref_id
          4. 版本号 +1
          5. 创建新版本记录 (change_type=rollback)
          6. 状态不变 (保持当前状态)
        """
        with self._session() as db:
            asset = self._repo.get_by_id(db, asset_id, user_id=user_id)

            # 状态约束: archived 不允许回滚
            if asset.status == AssetRegistryStatus.ARCHIVED:
                raise AssetStateError(
                    "已归档的资产不能回滚, 请先恢复为草稿",
                    asset_id=asset.id,
                    current_status=asset.status,
                )

            # 取目标版本
            target_version = self._version_repo.get_by_version(db, asset_id, version)
            import json
            try:
                snapshot = json.loads(target_version.snapshot_json)
            except (json.JSONDecodeError, TypeError):
                raise AssetVersionNotFoundError(
                    f"版本快照解析失败: asset_id={asset_id}, version={version}",
                    asset_id=asset_id,
                    version=version,
                )

            # 从快照恢复可变字段
            self._repo.update(
                db,
                asset,
                name=snapshot.get("name"),
                summary=snapshot.get("summary"),
                description=snapshot.get("description"),
                module=snapshot.get("module"),
                tags=snapshot.get("tags"),
                extra_metadata=snapshot.get("extra_metadata", {}),
                quality_score=snapshot.get("quality_score"),
            )

            # 版本号 +1
            new_version = (asset.version or 1) + 1
            new_snapshot = self._repo.snapshot(asset)
            self._version_repo.create_version(
                db,
                asset_id=asset.id,
                version=new_version,
                snapshot=new_snapshot,
                change_log=f"回滚至 v{version}",
                change_type="rollback",
                published_by=user_id,
                user_id=user_id,
            )
            asset.version = new_version
            db.flush()

            result = self._repo.to_dict(asset)
            result["current_version"] = new_version
            result["rolled_back_from"] = version
            logger.info(
                f"[AssetRegSvc] 回滚成功 id={asset.id} 至 v{version}, 新版本 v{new_version}"
            )
            return result

    # ------------------------------------------------------------------
    # 复用计数
    # ------------------------------------------------------------------

    def mark_used(
        self,
        asset_id: int,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """标记资产被使用 (复用计数 +1, 更新最近使用时间)"""
        with self._session() as db:
            asset = self._repo.get_by_id(db, asset_id, user_id=user_id)
            self._repo.mark_used(db, asset)
            result = self._repo.to_dict(asset)
            logger.info(
                f"[AssetRegSvc] 资产被复用 id={asset.id} count={asset.reuse_count}"
            )
            return result

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def get_stats(
        self,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """资产统计"""
        with self._session() as db:
            return self._repo.stats(db, user_id=user_id)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _can_transition(from_status: str, to_status: str) -> bool:
        """检查状态流转是否合法"""
        if from_status == to_status:
            return True
        allowed = _STATE_TRANSITIONS.get(from_status, set())
        return to_status in allowed
