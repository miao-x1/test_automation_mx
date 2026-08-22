"""
AssetVersionRepository - 资产版本数据访问层

职责:
  1. 封装 AssetVersion 的 CRUD
  2. 版本快照存储 (snapshot_json 序列化)
  3. is_current 标记管理 (同一资产仅一个 current)
  4. 版本回滚 (从快照恢复 + 生成新版本记录)
  5. diff_summary 计算 (与上一版本的字段级差异)

不做:
  - 实际资产字段恢复 (由 AssetService 调用 AssetRepository.update 完成)
  - 事务边界
"""
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.asset_registry import AssetVersion
from app.core.exceptions import AssetVersionNotFoundError

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


class AssetVersionRepository:
    """资产版本 Repository"""

    # ------------------------------------------------------------------
    # 创建版本
    # ------------------------------------------------------------------

    def create_version(
        self,
        db: Session,
        *,
        asset_id: int,
        version: int,
        snapshot: Dict[str, Any],
        change_log: str = "",
        change_type: str = "update",
        diff_summary: Optional[Dict[str, Any]] = None,
        published_by: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> AssetVersion:
        """创建新版本

        步骤:
          1. 取消该资产之前的 is_current 标记
          2. 插入新版本记录, is_current=True
          3. flush 返回新记录

        注意: version 由调用方 (service) 决定 (通常 = asset.version + 1)
        """
        # 1. 取消之前的 is_current
        db.query(AssetVersion).filter(
            AssetVersion.asset_id == asset_id,
            AssetVersion.is_current == True,  # noqa: E712
        ).update({AssetVersion.is_current: False}, synchronize_session=False)

        # 2. 插入新版本
        record = AssetVersion(
            asset_id=asset_id,
            version=version,
            snapshot_json=_dump_json(snapshot),
            change_log=change_log,
            change_type=change_type,
            diff_summary=_dump_json(diff_summary),
            is_current=True,
            published_by=published_by,
            user_id=user_id,
        )
        db.add(record)
        db.flush()
        logger.info(
            f"[AssetVerRepo] 创建版本 asset_id={asset_id} version={version} "
            f"type={change_type}"
        )
        return record

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_by_id(
        self,
        db: Session,
        version_id: int,
        *,
        user_id: Optional[int] = None,
    ) -> AssetVersion:
        """按版本记录 ID 查询"""
        q = db.query(AssetVersion).filter(AssetVersion.id == version_id)
        if user_id is not None:
            q = q.filter(AssetVersion.user_id == user_id)
        record = q.first()
        if not record:
            raise AssetVersionNotFoundError(
                f"版本记录不存在: id={version_id}",
            )
        return record

    def get_by_version(
        self,
        db: Session,
        asset_id: int,
        version: int,
    ) -> AssetVersion:
        """按 asset_id + version 查询"""
        record = db.query(AssetVersion).filter(
            AssetVersion.asset_id == asset_id,
            AssetVersion.version == version,
        ).first()
        if not record:
            raise AssetVersionNotFoundError(
                f"版本不存在: asset_id={asset_id}, version={version}",
                asset_id=asset_id,
                version=version,
            )
        return record

    def get_current(
        self,
        db: Session,
        asset_id: int,
    ) -> Optional[AssetVersion]:
        """获取当前版本 (is_current=True), 不存在返回 None"""
        return db.query(AssetVersion).filter(
            AssetVersion.asset_id == asset_id,
            AssetVersion.is_current == True,  # noqa: E712
        ).first()

    def list_versions(
        self,
        db: Session,
        asset_id: int,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[AssetVersion], int]:
        """分页查询资产版本列表 (按 version 倒序)"""
        q = db.query(AssetVersion).filter(AssetVersion.asset_id == asset_id)
        total = q.count()
        items = (
            q.order_by(AssetVersion.version.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    def get_latest_version_number(
        self,
        db: Session,
        asset_id: int,
    ) -> int:
        """获取资产最新版本号 (用于计算下一个版本)"""
        record = db.query(AssetVersion.version).filter(
            AssetVersion.asset_id == asset_id,
        ).order_by(AssetVersion.version.desc()).first()
        return record[0] if record else 0

    # ------------------------------------------------------------------
    # 差异计算
    # ------------------------------------------------------------------

    def compute_diff(
        self,
        current: Dict[str, Any],
        previous: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """计算两个快照之间的字段级差异

        返回结构:
          {
            "added":    {"field": value, ...},     # previous 无, current 有
            "removed":  {"field": value, ...},    # previous 有, current 无
            "modified": {"field": [old, new], ...}  # 都有, 值不同
          }
        """
        if previous is None:
            return {"added": current, "removed": {}, "modified": {}}

        added = {}
        removed = {}
        modified = {}

        all_keys = set(current.keys()) | set(previous.keys())
        for key in all_keys:
            if key in current and key not in previous:
                added[key] = current[key]
            elif key not in current and key in previous:
                removed[key] = previous[key]
            elif current[key] != previous[key]:
                modified[key] = [previous[key], current[key]]

        return {"added": added, "removed": removed, "modified": modified}

    # ------------------------------------------------------------------
    # 序列化 helpers
    # ------------------------------------------------------------------

    def to_dict(self, record: AssetVersion) -> Dict[str, Any]:
        """版本完整字段 → dict (含快照)"""
        return {
            "id": record.id,
            "asset_id": record.asset_id,
            "version": record.version,
            "snapshot": _load_json(record.snapshot_json, default={}) or {},
            "change_log": record.change_log,
            "change_type": record.change_type,
            "diff_summary": _load_json(record.diff_summary),
            "is_current": record.is_current,
            "published_by": record.published_by,
            "user_id": record.user_id,
            "created_by": record.created_by,
            "created_at": record.created_at,
        }

    def to_list_item(self, record: AssetVersion) -> Dict[str, Any]:
        """版本列表项 (不含 snapshot, 仅元信息)"""
        return {
            "id": record.id,
            "asset_id": record.asset_id,
            "version": record.version,
            "change_log": record.change_log,
            "change_type": record.change_type,
            "is_current": record.is_current,
            "published_by": record.published_by,
            "created_by": record.created_by,
            "created_at": record.created_at,
        }
