"""
统一测试资产服务（基于 TestAsset）

替代旧的 AssetService（基于 TestAssetV2）。
唯一资产模型：TestAsset。
"""
import json
from typing import Dict, List, Optional, Any
from app.core.logger import log
from app.db.database import SessionLocal
from app.models.test_asset import TestAsset, AssetType, AssetStatus, SourceType
from app.models.session_event import SessionEvent


class AssetService:
    """统一测试资产服务"""

    @staticmethod
    def create_asset(
        title: str,
        asset_type: str = "api",
        source_type: str = "ai",
        session_id: Optional[int] = None,
        requirement_id: Optional[int] = None,
        content_json: Optional[str] = None,
        priority: str = "P1",
        tags: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> TestAsset:
        """创建测试资产"""
        db = SessionLocal()
        try:
            asset = TestAsset(
                title=title,
                asset_type=asset_type,
                source_type=source_type,
                status=AssetStatus.DRAFT.value,
                session_id=session_id,
                requirement_id=requirement_id,
                content_json=content_json,
                published=False,
                priority=priority,
                tags=tags,
                version=1,
                user_id=user_id,
                created_by=user_id,
            )
            if content_json:
                asset.validate_executable()
            db.add(asset)
            db.commit()
            db.refresh(asset)
            return asset
        finally:
            db.close()

    @staticmethod
    def get_asset(asset_id: int, user_id: Optional[int] = None) -> Optional[Dict]:
        """获取资产详情"""
        db = SessionLocal()
        try:
            query = db.query(TestAsset).filter(
                TestAsset.id == asset_id,
                TestAsset.is_deleted == False,
            )
            if user_id:
                query = query.filter(TestAsset.user_id == user_id)
            asset = query.first()
            if not asset:
                return None
            return AssetService._to_dict(asset)
        finally:
            db.close()

    @staticmethod
    def list_assets(
        user_id: Optional[int] = None,
        asset_type: Optional[str] = None,
        status: Optional[str] = None,
        source_type: Optional[str] = None,
        keyword: Optional[str] = None,
        session_id: Optional[int] = None,
        executable: Optional[bool] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> Dict:
        """资产列表"""
        db = SessionLocal()
        try:
            query = db.query(TestAsset).filter(TestAsset.is_deleted == False)
            if user_id:
                query = query.filter(TestAsset.user_id == user_id)
            if asset_type:
                query = query.filter(TestAsset.asset_type == asset_type)
            if status:
                query = query.filter(TestAsset.status == status)
            if source_type:
                query = query.filter(TestAsset.source_type == source_type)
            if keyword:
                query = query.filter(TestAsset.title.contains(keyword))
            if session_id:
                query = query.filter(TestAsset.session_id == session_id)
            if executable is not None:
                query = query.filter(TestAsset.executable == executable)

            total = query.count()
            assets = query.order_by(TestAsset.id.desc()).offset(skip).limit(limit).all()

            return {
                "items": [AssetService._to_summary(a) for a in assets],
                "total": total,
            }
        finally:
            db.close()

    @staticmethod
    def update_asset(
        asset_id: int,
        user_id: int,
        title: Optional[str] = None,
        content_json: Optional[str] = None,
        priority: Optional[str] = None,
        tags: Optional[str] = None,
        asset_type: Optional[str] = None,
    ) -> Optional[Dict]:
        """更新资产"""
        db = SessionLocal()
        try:
            asset = db.query(TestAsset).filter(
                TestAsset.id == asset_id,
                TestAsset.user_id == user_id,
                TestAsset.is_deleted == False,
            ).first()
            if not asset:
                return None

            if title is not None:
                asset.title = title
            if content_json is not None:
                asset.content_json = content_json
                asset.validate_executable()
            if priority is not None:
                asset.priority = priority
            if tags is not None:
                asset.tags = tags
            if asset_type is not None:
                asset.asset_type = asset_type

            db.commit()
            return {"id": asset.id, "status": asset.status, "executable": asset.executable}
        finally:
            db.close()

    @staticmethod
    def delete_asset(asset_id: int, user_id: int) -> bool:
        """软删除资产"""
        db = SessionLocal()
        try:
            asset = db.query(TestAsset).filter(
                TestAsset.id == asset_id,
                TestAsset.user_id == user_id,
            ).first()
            if not asset:
                return False
            asset.is_deleted = True
            db.commit()
            return True
        finally:
            db.close()

    @staticmethod
    def get_stats(user_id: int) -> Dict:
        """资产统计"""
        db = SessionLocal()
        try:
            from sqlalchemy import func

            stats = db.query(
                TestAsset.asset_type,
                TestAsset.status,
                func.count(TestAsset.id),
            ).filter(
                TestAsset.user_id == user_id,
                TestAsset.is_deleted == False,
            ).group_by(TestAsset.asset_type, TestAsset.status).all()

            result = {}
            for atype, status, count in stats:
                if atype not in result:
                    result[atype] = {}
                result[atype][status] = count

            draft_count = db.query(TestAsset).filter(
                TestAsset.user_id == user_id,
                TestAsset.status == AssetStatus.DRAFT.value,
                TestAsset.is_deleted == False,
            ).count()

            executable_count = db.query(TestAsset).filter(
                TestAsset.user_id == user_id,
                TestAsset.executable == True,
                TestAsset.is_deleted == False,
            ).count()

            return {"stats": result, "draft_count": draft_count, "executable_count": executable_count}
        finally:
            db.close()

    @staticmethod
    def get_assets_by_session(session_id: int, user_id: Optional[int] = None) -> List[Dict]:
        """获取会话关联的所有资产"""
        db = SessionLocal()
        try:
            query = db.query(TestAsset).filter(
                TestAsset.session_id == session_id,
                TestAsset.is_deleted == False,
            )
            if user_id:
                query = query.filter(TestAsset.user_id == user_id)
            assets = query.order_by(TestAsset.id).all()
            return [AssetService._to_summary(a) for a in assets]
        finally:
            db.close()

    # ===== 内部方法 =====

    @staticmethod
    def _to_dict(asset: TestAsset) -> Dict:
        """完整资产信息"""
        content = asset.get_content()
        return {
            "id": asset.id,
            "title": asset.title,
            "description": asset.description,
            "asset_type": asset.asset_type,
            "status": asset.status,
            "source_type": asset.source_type,
            "priority": asset.priority,
            "tags": asset.tags.split(",") if asset.tags else [],
            "session_id": asset.session_id,
            "requirement_id": asset.requirement_id,
            "project_id": asset.project_id,
            "executable": asset.executable,
            "published": asset.published,
            "version": asset.version,
            "content_json": content,
            "execution_state": json.loads(asset.execution_state) if asset.execution_state else None,
            "legacy_case_content_id": asset.legacy_case_content_id,
            "legacy_api_case_id": asset.legacy_api_case_id,
            "created_at": str(asset.created_at) if asset.created_at else None,
            "updated_at": str(asset.updated_at) if asset.updated_at else None,
        }

    @staticmethod
    def _to_summary(asset: TestAsset) -> Dict:
        """资产摘要（列表用）"""
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
            "executable": asset.executable,
            "published": asset.published,
            "version": asset.version,
            "steps_count": len(content.get("steps", [])) if content else 0,
            "assertions_count": len(content.get("assertions", [])) if content else 0,
            "created_at": str(asset.created_at) if asset.created_at else None,
            "updated_at": str(asset.updated_at) if asset.updated_at else None,
        }
