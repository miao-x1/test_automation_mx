"""
资产查询服务

统一查询入口，支持多维度筛选
"""
from typing import Dict, List, Optional
from app.core.logger import log
from app.db.database import SessionLocal
from app.models.test_asset import TestAsset, AssetType, AssetStatus
from sqlalchemy import func


class AssetQuery:
    """资产查询服务"""

    @staticmethod
    def query(
        user_id: Optional[int] = None,
        asset_type: Optional[str] = None,
        status: Optional[str] = None,
        source_type: Optional[str] = None,
        keyword: Optional[str] = None,
        session_id: Optional[int] = None,
        requirement_id: Optional[int] = None,
        executable: Optional[bool] = None,
        published: Optional[bool] = None,
        priority: Optional[str] = None,
        tags: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
        order_by: str = "id",
        order_desc: bool = True,
    ) -> Dict:
        """多维度查询"""
        db = SessionLocal()
        try:
            query = db.query(TestAsset).filter(TestAsset.is_deleted == False)

            if user_id:
                query = query.filter(TestAsset.user_id == user_id)
            if asset_type:
                query = query.filter(TestAsset.asset_type == asset_type)
            if status:
                # 支持逗号分隔多状态
                statuses = [s.strip() for s in status.split(",")]
                if len(statuses) > 1:
                    query = query.filter(TestAsset.status.in_(statuses))
                else:
                    query = query.filter(TestAsset.status == status)
            if source_type:
                query = query.filter(TestAsset.source_type == source_type)
            if keyword:
                query = query.filter(TestAsset.title.contains(keyword))
            if session_id:
                query = query.filter(TestAsset.session_id == session_id)
            if requirement_id:
                query = query.filter(TestAsset.requirement_id == requirement_id)
            if executable is not None:
                query = query.filter(TestAsset.executable == executable)
            if published is not None:
                query = query.filter(TestAsset.published == published)
            if priority:
                query = query.filter(TestAsset.priority == priority)
            if tags:
                query = query.filter(TestAsset.tags.contains(tags))

            total = query.count()

            # 排序
            order_col = getattr(TestAsset, order_by, TestAsset.id)
            if order_desc:
                query = query.order_by(order_col.desc())
            else:
                query = query.order_by(order_col.asc())

            assets = query.offset(skip).limit(limit).all()

            return {
                "items": [_to_summary(a) for a in assets],
                "total": total,
                "skip": skip,
                "limit": limit,
            }
        finally:
            db.close()

    @staticmethod
    def count_by_status(user_id: int) -> Dict:
        """按状态统计"""
        db = SessionLocal()
        try:
            stats = db.query(
                TestAsset.status,
                func.count(TestAsset.id),
            ).filter(
                TestAsset.user_id == user_id,
                TestAsset.is_deleted == False,
            ).group_by(TestAsset.status).all()

            return {status: count for status, count in stats}
        finally:
            db.close()

    @staticmethod
    def count_by_type(user_id: int) -> Dict:
        """按类型统计"""
        db = SessionLocal()
        try:
            stats = db.query(
                TestAsset.asset_type,
                func.count(TestAsset.id),
            ).filter(
                TestAsset.user_id == user_id,
                TestAsset.is_deleted == False,
            ).group_by(TestAsset.asset_type).all()

            return {atype: count for atype, count in stats}
        finally:
            db.close()

    @staticmethod
    def get_executable_assets(user_id: int, asset_type: Optional[str] = None) -> List[Dict]:
        """获取可执行资产列表"""
        db = SessionLocal()
        try:
            query = db.query(TestAsset).filter(
                TestAsset.user_id == user_id,
                TestAsset.executable == True,
                TestAsset.is_deleted == False,
            )
            if asset_type:
                query = query.filter(TestAsset.asset_type == asset_type)
            assets = query.order_by(TestAsset.id.desc()).limit(100).all()
            return [_to_summary(a) for a in assets]
        finally:
            db.close()


def _to_summary(asset: TestAsset) -> Dict:
    """资产摘要"""
    content = asset.get_content()
    return {
        "id": asset.id,
        "title": asset.title,
        "asset_type": asset.asset_type,
        "status": asset.status,
        "source_type": asset.source_type,
        "priority": asset.priority,
        "tags": asset.tags.split(",") if asset.tags else [],
        "session_id": asset.session_id,
        "requirement_id": asset.requirement_id,
        "executable": asset.executable,
        "published": asset.published,
        "version": asset.version,
        "steps_count": len(content.get("steps", [])) if content else 0,
        "assertions_count": len(content.get("assertions", [])) if content else 0,
        "created_at": str(asset.created_at) if asset.created_at else None,
        "updated_at": str(asset.updated_at) if asset.updated_at else None,
    }
