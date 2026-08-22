"""
AssetRepository - 资产索引数据访问层

职责:
  1. 封装 AssetRegistry 的 CRUD
  2. JSON 字段(tags / extra_metadata)的序列化
  3. 软删除过滤(is_deleted=False)
  4. 按 keyword/type/status/module/source/tags/ref_type 过滤
  5. 分页查询
  6. asset_code 自动生成(ASSET-YYYY-NNNN)
  7. 复用计数与最近使用时间更新

不做:
  - 业务校验(由 service 层负责)
  - 状态机流转(由 service 层负责)
  - 事务边界(由 service 层或 router 负责提交)
"""
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.models.asset_registry import (
    AssetRegistry,
    AssetRegistryType,
    AssetRegistryStatus,
    AssetRegistrySource,
)
from app.core.exceptions import (
    AssetNotFoundError,
    AssetConflictError,
)

logger = logging.getLogger(__name__)


# ============================================================
# JSON 序列化 helpers (与 ApiEndpointRepository 保持一致)
# ============================================================

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
    """JSON 字符串 → Python 对象(None 返回 default)"""
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError) as e:
        logger.warning(f"JSON 反序列化失败: {e}, raw={value[:100]}")
        return default


def _tags_to_str(tags: Optional[List[str]]) -> Optional[str]:
    """list[str] → 逗号分隔字符串"""
    if not tags:
        return None
    return ",".join(t.strip() for t in tags if t and t.strip())


def _str_to_tags(tags_str: Optional[str]) -> List[str]:
    """逗号分隔字符串 → list[str]"""
    if not tags_str:
        return []
    return [t.strip() for t in tags_str.split(",") if t.strip()]


# ============================================================
# Repository
# ============================================================

class AssetRepository:
    """资产索引 Repository

    所有方法接收一个 Session 参数,由调用方负责事务生命周期。
    """

    # ------------------------------------------------------------------
    # asset_code 生成
    # ------------------------------------------------------------------

    def generate_asset_code(self, db: Session) -> str:
        """生成资产编码 ASSET-YYYY-NNNN

        采用 "当前年份 + 当年计数+1" 策略:
          1. 查询当年已存在的最大 asset_code
          2. 序号 + 1, 补零到 4 位
          3. 并发冲突由 service 层捕获 IntegrityError 后重试
        """
        year = datetime.now().year
        prefix = f"ASSET-{year}-"
        # 查询当年最大编号
        last = db.query(AssetRegistry.asset_code).filter(
            AssetRegistry.asset_code.like(f"{prefix}%")
        ).order_by(AssetRegistry.asset_code.desc()).first()
        if last and last[0]:
            try:
                seq = int(last[0].rsplit("-", 1)[-1])
            except ValueError:
                seq = 0
        else:
            seq = 0
        return f"{prefix}{seq + 1:04d}"

    # ------------------------------------------------------------------
    # 创建
    # ------------------------------------------------------------------

    def create(
        self,
        db: Session,
        *,
        name: str,
        asset_type: str,
        ref_type: str,
        ref_id: int = 0,
        asset_code: Optional[str] = None,
        summary: Optional[str] = None,
        description: Optional[str] = None,
        module: Optional[str] = None,
        tags: Optional[List[str]] = None,
        source: str = AssetRegistrySource.MANUAL,
        status: str = AssetRegistryStatus.DRAFT,
        extra_metadata: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
        created_by: Optional[int] = None,
    ) -> AssetRegistry:
        """创建资产索引

        重复检测:
          1. asset_code 重复 → AssetConflictError
          2. 同 user_id + ref_type + ref_id (ref_id>0) 重复 → AssetConflictError
        """
        # 1. 自动生成 asset_code (若未提供)
        if not asset_code:
            asset_code = self.generate_asset_code(db)

        # 2. asset_code 唯一性检查
        existing_code = db.query(AssetRegistry).filter(
            AssetRegistry.asset_code == asset_code,
            AssetRegistry.is_deleted == False,
        ).first()
        if existing_code:
            raise AssetConflictError(
                f"资产编码已存在: {asset_code}",
                asset_id=existing_code.id,
                asset_code=asset_code,
            )

        # 3. ref_type + ref_id 重复检查 (仅 ref_id > 0 时)
        if ref_id > 0:
            existing_ref = db.query(AssetRegistry).filter(
                AssetRegistry.user_id == user_id,
                AssetRegistry.ref_type == ref_type,
                AssetRegistry.ref_id == ref_id,
                AssetRegistry.is_deleted == False,
            ).first()
            if existing_ref:
                raise AssetConflictError(
                    f"资产已索引: ref_type={ref_type}, ref_id={ref_id}",
                    asset_id=existing_ref.id,
                    asset_code=existing_ref.asset_code,
                )

        asset = AssetRegistry(
            asset_code=asset_code,
            name=name,
            asset_type=asset_type,
            ref_type=ref_type,
            ref_id=ref_id,
            summary=summary,
            description=description,
            module=module,
            tags=_tags_to_str(tags),
            source=source,
            status=status,
            version=1,
            quality_score=0.0,
            reuse_count=0,
            extra_metadata=_dump_json(extra_metadata),
            is_deleted=False,
            user_id=user_id,
            created_by=created_by,
        )
        db.add(asset)
        db.flush()  # 取 id,但不 commit
        logger.info(
            f"[AssetRepo] 创建资产 id={asset.id} code={asset.asset_code} "
            f"type={asset.asset_type}"
        )
        return asset

    # ------------------------------------------------------------------
    # 查询(单个)
    # ------------------------------------------------------------------

    def get_by_id(
        self,
        db: Session,
        asset_id: int,
        *,
        user_id: Optional[int] = None,
        include_deleted: bool = False,
    ) -> AssetRegistry:
        """按 ID 查询资产,不存在或软删除则抛 NotFoundError"""
        q = db.query(AssetRegistry).filter(AssetRegistry.id == asset_id)
        if user_id is not None:
            q = q.filter(AssetRegistry.user_id == user_id)
        if not include_deleted:
            q = q.filter(AssetRegistry.is_deleted == False)
        asset = q.first()
        if not asset:
            raise AssetNotFoundError(
                f"资产不存在或已删除: id={asset_id}",
                asset_id=asset_id,
            )
        return asset

    def get_by_code(
        self,
        db: Session,
        asset_code: str,
        *,
        user_id: Optional[int] = None,
        include_deleted: bool = False,
    ) -> AssetRegistry:
        """按 asset_code 查询资产"""
        q = db.query(AssetRegistry).filter(AssetRegistry.asset_code == asset_code)
        if user_id is not None:
            q = q.filter(AssetRegistry.user_id == user_id)
        if not include_deleted:
            q = q.filter(AssetRegistry.is_deleted == False)
        asset = q.first()
        if not asset:
            raise AssetNotFoundError(
                f"资产不存在或已删除: code={asset_code}",
            )
        return asset

    def get_by_ref(
        self,
        db: Session,
        ref_type: str,
        ref_id: int,
        *,
        user_id: Optional[int] = None,
    ) -> Optional[AssetRegistry]:
        """按 ref_type + ref_id 查询资产,不存在返回 None(用于查重)"""
        q = db.query(AssetRegistry).filter(
            AssetRegistry.ref_type == ref_type,
            AssetRegistry.ref_id == ref_id,
            AssetRegistry.is_deleted == False,
        )
        if user_id is not None:
            q = q.filter(AssetRegistry.user_id == user_id)
        return q.first()

    # ------------------------------------------------------------------
    # 查询(列表分页)
    # ------------------------------------------------------------------

    def list(
        self,
        db: Session,
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
    ) -> Tuple[List[AssetRegistry], int]:
        """分页查询资产列表

        返回 (items, total)
        """
        q = db.query(AssetRegistry).filter(AssetRegistry.is_deleted == False)

        if user_id is not None:
            q = q.filter(AssetRegistry.user_id == user_id)
        if keyword:
            kw = f"%{keyword}%"
            q = q.filter(or_(
                AssetRegistry.name.ilike(kw),
                AssetRegistry.asset_code.ilike(kw),
                AssetRegistry.summary.ilike(kw),
            ))
        if asset_type:
            q = q.filter(AssetRegistry.asset_type == asset_type)
        if status:
            q = q.filter(AssetRegistry.status == status)
        if module:
            q = q.filter(AssetRegistry.module == module)
        if source:
            q = q.filter(AssetRegistry.source == source)
        if ref_type:
            q = q.filter(AssetRegistry.ref_type == ref_type)
        if tags:
            # tags 是逗号分隔字符串,任一匹配即返回
            tag_conds = [AssetRegistry.tags.like(f"%{t}%") for t in tags]
            q = q.filter(or_(*tag_conds))
        if min_quality is not None:
            q = q.filter(AssetRegistry.quality_score >= min_quality)

        total = q.count()
        items = (
            q.order_by(AssetRegistry.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    # ------------------------------------------------------------------
    # 更新
    # ------------------------------------------------------------------

    def update(
        self,
        db: Session,
        asset: AssetRegistry,
        **fields,
    ) -> AssetRegistry:
        """部分更新资产

        支持的字段:
          name, summary, description, module, tags(list),
          quality_score, extra_metadata(dict)
        (asset_type / ref_type / ref_id / asset_code 不可变, 由创建时确定)
        (status 由 transition_state 方法流转, 不在此处直接更新)
        """
        field_map = {
            "name": ("name", lambda v: v),
            "summary": ("summary", lambda v: v),
            "description": ("description", lambda v: v),
            "module": ("module", lambda v: v),
            "quality_score": ("quality_score", lambda v: float(v) if v is not None else 0.0),
        }
        json_field_map = {
            "tags": ("tags", _tags_to_str),
            "extra_metadata": ("extra_metadata", _dump_json),
        }

        for key, value in fields.items():
            if value is None and key != "extra_metadata":
                # extra_metadata 允许清空 (传 None 表示删除)
                continue
            if key in field_map:
                col, conv = field_map[key]
                setattr(asset, col, conv(value))
            elif key in json_field_map:
                col, conv = json_field_map[key]
                setattr(asset, col, conv(value))
            else:
                logger.debug(f"[AssetRepo] 跳过未识别字段: {key}")

        db.flush()
        logger.info(f"[AssetRepo] 更新资产 id={asset.id}")
        return asset

    # ------------------------------------------------------------------
    # 状态机流转 (仅更新 status, 业务校验由 service 负责)
    # ------------------------------------------------------------------

    def transition_state(
        self,
        db: Session,
        asset: AssetRegistry,
        target_status: str,
    ) -> AssetRegistry:
        """更新资产状态 (不校验流转合法性, 由 service 层校验)"""
        asset.status = target_status
        db.flush()
        logger.info(
            f"[AssetRepo] 资产状态流转 id={asset.id} → {target_status}"
        )
        return asset

    # ------------------------------------------------------------------
    # 复用计数 / 最近使用时间
    # ------------------------------------------------------------------

    def mark_used(
        self,
        db: Session,
        asset: AssetRegistry,
        *,
        used_at: Optional[datetime] = None,
    ) -> AssetRegistry:
        """更新复用计数与最近使用时间 (复用资产时调用)"""
        asset.reuse_count = (asset.reuse_count or 0) + 1
        asset.last_used_at = used_at or datetime.now()
        db.flush()
        return asset

    # ------------------------------------------------------------------
    # 软删除
    # ------------------------------------------------------------------

    def soft_delete(self, db: Session, asset: AssetRegistry) -> AssetRegistry:
        """软删除 (标记 is_deleted=True, 不真删)

        软删除后:
          - 不出现在列表查询中
          - 历史版本与关系保留 (供审计)
          - 可通过 include_deleted=True 查询
        """
        asset.is_deleted = True
        db.flush()
        logger.info(f"[AssetRepo] 软删除资产 id={asset.id}")
        return asset

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def stats(
        self,
        db: Session,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """资产统计"""
        q = db.query(AssetRegistry).filter(AssetRegistry.is_deleted == False)
        if user_id is not None:
            q = q.filter(AssetRegistry.user_id == user_id)

        total = q.count()

        # 按类型
        by_type_rows = db.query(
            AssetRegistry.asset_type,
            func.count(AssetRegistry.id),
        ).filter(
            AssetRegistry.is_deleted == False,
            *([AssetRegistry.user_id == user_id] if user_id is not None else []),
        ).group_by(AssetRegistry.asset_type).all()
        by_type = {row[0]: row[1] for row in by_type_rows}

        # 按状态
        by_status_rows = db.query(
            AssetRegistry.status,
            func.count(AssetRegistry.id),
        ).filter(
            AssetRegistry.is_deleted == False,
            *([AssetRegistry.user_id == user_id] if user_id is not None else []),
        ).group_by(AssetRegistry.status).all()
        by_status = {row[0]: row[1] for row in by_status_rows}

        # 按模块
        by_module_rows = db.query(
            AssetRegistry.module,
            func.count(AssetRegistry.id),
        ).filter(
            AssetRegistry.is_deleted == False,
            *([AssetRegistry.user_id == user_id] if user_id is not None else []),
        ).group_by(AssetRegistry.module).all()
        by_module = {row[0] or "未分类": row[1] for row in by_module_rows}

        # 按来源
        by_source_rows = db.query(
            AssetRegistry.source,
            func.count(AssetRegistry.id),
        ).filter(
            AssetRegistry.is_deleted == False,
            *([AssetRegistry.user_id == user_id] if user_id is not None else []),
        ).group_by(AssetRegistry.source).all()
        by_source = {row[0]: row[1] for row in by_source_rows}

        # 平均质量评分
        avg_quality = db.query(
            func.avg(AssetRegistry.quality_score)
        ).filter(
            AssetRegistry.is_deleted == False,
            *([AssetRegistry.user_id == user_id] if user_id is not None else []),
        ).scalar() or 0.0

        return {
            "total": total,
            "by_type": by_type,
            "by_status": by_status,
            "by_module": by_module,
            "by_source": by_source,
            "avg_quality_score": float(avg_quality),
        }

    # ------------------------------------------------------------------
    # 序列化 helpers
    # ------------------------------------------------------------------

    def to_dict(self, asset: AssetRegistry) -> Dict[str, Any]:
        """资产完整字段 → dict (响应使用)"""
        return {
            "id": asset.id,
            "asset_code": asset.asset_code,
            "name": asset.name,
            "asset_type": asset.asset_type,
            "ref_type": asset.ref_type,
            "ref_id": asset.ref_id,
            "summary": asset.summary,
            "description": asset.description,
            "module": asset.module,
            "tags": _str_to_tags(asset.tags),
            "status": asset.status,
            "source": asset.source,
            "version": asset.version,
            "quality_score": float(asset.quality_score or 0.0),
            "reuse_count": asset.reuse_count or 0,
            "last_used_at": asset.last_used_at,
            "extra_metadata": _load_json(asset.extra_metadata, default={}) or {},
            "user_id": asset.user_id,
            "created_by": asset.created_by,
            "created_at": asset.created_at,
            "updated_at": asset.updated_at,
        }

    def to_list_item(self, asset: AssetRegistry) -> Dict[str, Any]:
        """资产列表项 (精简字段, 不含 description / extra_metadata)"""
        return {
            "id": asset.id,
            "asset_code": asset.asset_code,
            "name": asset.name,
            "asset_type": asset.asset_type,
            "ref_type": asset.ref_type,
            "ref_id": asset.ref_id,
            "summary": asset.summary,
            "module": asset.module,
            "status": asset.status,
            "source": asset.source,
            "version": asset.version,
            "quality_score": float(asset.quality_score or 0.0),
            "reuse_count": asset.reuse_count or 0,
            "tags": _str_to_tags(asset.tags),
            "last_used_at": asset.last_used_at,
            "created_at": asset.created_at,
            "updated_at": asset.updated_at,
        }

    def snapshot(self, asset: AssetRegistry) -> Dict[str, Any]:
        """生成资产快照 (用于版本表 snapshot_json)

        与 to_dict 的区别: snapshot 包含所有字段 (含 description / extra_metadata),
        并增加 snapshot_at 时间戳, 用于不可变历史记录。
        """
        snap = self.to_dict(asset)
        snap["snapshot_at"] = datetime.now().isoformat()
        return snap
