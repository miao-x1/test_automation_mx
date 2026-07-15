"""
发布服务

统一管理：draft → reviewed → published 状态流转
"""
import json
from typing import Dict, List
from app.core.logger import log
from app.db.database import SessionLocal
from app.models.test_asset import TestAsset, AssetStatus
from app.models.session_event import SessionEvent


class PublishService:
    """发布服务"""

    @staticmethod
    def review(asset_ids: List[int], user_id: int) -> Dict:
        """审查：draft → reviewed"""
        db = SessionLocal()
        try:
            reviewed = []
            for aid in asset_ids:
                asset = db.query(TestAsset).filter(
                    TestAsset.id == aid,
                    TestAsset.user_id == user_id,
                    TestAsset.is_deleted == False,
                ).first()
                if asset and asset.status == AssetStatus.DRAFT.value:
                    asset.status = AssetStatus.REVIEWED.value
                    reviewed.append(aid)
                    if asset.session_id:
                        db.add(SessionEvent(
                            session_id=asset.session_id,
                            event_type=SessionEvent.PUBLISH,
                            payload=json.dumps({"asset_id": aid, "action": "review", "title": asset.title}),
                            step_index=0,
                        ))
            db.commit()
            return {"reviewed": reviewed, "count": len(reviewed)}
        finally:
            db.close()

    @staticmethod
    def publish(asset_ids: List[int], user_id: int) -> Dict:
        """发布：draft/reviewed → published"""
        db = SessionLocal()
        try:
            published = []
            for aid in asset_ids:
                asset = db.query(TestAsset).filter(
                    TestAsset.id == aid,
                    TestAsset.user_id == user_id,
                    TestAsset.is_deleted == False,
                ).first()
                if asset and asset.status in (AssetStatus.DRAFT.value, AssetStatus.REVIEWED.value):
                    asset.publish()
                    published.append(aid)
                    if asset.session_id:
                        db.add(SessionEvent(
                            session_id=asset.session_id,
                            event_type=SessionEvent.PUBLISH,
                            payload=json.dumps({"asset_id": aid, "action": "publish", "title": asset.title}),
                            step_index=0,
                        ))
            db.commit()
            return {"published": published, "count": len(published)}
        finally:
            db.close()

    @staticmethod
    def unpublish(asset_ids: List[int], user_id: int) -> Dict:
        """取消发布：published → draft"""
        db = SessionLocal()
        try:
            unpublished = []
            for aid in asset_ids:
                asset = db.query(TestAsset).filter(
                    TestAsset.id == aid,
                    TestAsset.user_id == user_id,
                    TestAsset.is_deleted == False,
                ).first()
                if asset and asset.published:
                    asset.unpublish()
                    unpublished.append(aid)
            db.commit()
            return {"unpublished": unpublished, "count": len(unpublished)}
        finally:
            db.close()
