"""
数据迁移服务

将旧系统数据迁移到统一 TestAssetV2：
  - CaseContent → TestAssetV2 (draft)
  - ApiCase → TestAssetV2 (published)
  - 旧 TestAsset → TestAssetV2

迁移原则：
  - 保留旧数据（不删除）
  - 自动迁移
  - 兼容旧接口
  - 禁止白屏
  - 禁止删除用户数据
"""
import json
from typing import Dict, Optional
from app.core.logger import log
from app.db.database import SessionLocal
from app.models.test_asset import TestAsset as TestAssetV2, AssetType, AssetStatus, AssetSource


class MigrationService:
    """数据迁移服务"""

    @staticmethod
    def migrate_all() -> Dict:
        """执行全部迁移"""
        results = {}
        results["case_content"] = MigrationService.migrate_case_content()
        results["api_case"] = MigrationService.migrate_api_case()
        log.info(f"MigrationService | 迁移完成 | {results}")
        return results

    @staticmethod
    def migrate_case_content() -> Dict:
        """CaseContent → TestAssetV2"""
        db = SessionLocal()
        try:
            from app.models.case_content import CaseContent

            # 只迁移未迁移的
            migrated_ids = set(
                row[0] for row in db.query(TestAssetV2.legacy_case_content_id)
                .filter(TestAssetV2.legacy_case_content_id.isnot(None))
                .all()
            )

            contents = db.query(CaseContent).filter(
                CaseContent.is_deleted == False,
                ~CaseContent.id.in_(migrated_ids) if migrated_ids else True,
            ).all()

            created = 0
            skipped = 0
            errors = 0

            for content in contents:
                try:
                    # 推断asset_type
                    asset_type = MigrationService._infer_asset_type(content.test_type)

                    # 推断status
                    status = MigrationService._infer_status_from_content(content.case_status)

                    # 构建draft_content
                    steps = json.loads(content.steps) if content.steps else []
                    method = ""
                    url = ""
                    headers = {}
                    body = {}
                    timeout = 5000

                    if steps and isinstance(steps, list) and isinstance(steps[0], dict):
                        first = steps[0]
                        action = first.get("action", "")
                        if action.upper() in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                            method = action.upper()
                            url = first.get("url", "")
                            headers = first.get("headers", {})
                            body = first.get("body", {})
                            timeout = first.get("timeout", 5000)

                    assertions = json.loads(content.expected) if content.expected else []
                    if isinstance(assertions, dict):
                        assertions = [assertions]

                    draft_content = json.dumps({
                        "method": method,
                        "url": url,
                        "headers": headers,
                        "body": body,
                        "timeout": timeout,
                        "pre_steps": [],
                        "assertions": assertions,
                        "variables": {},
                        "runtime": {"retry": 0, "env": "test"},
                    }, ensure_ascii=False)

                    asset = TestAssetV2(
                        title=content.title,
                        asset_type=asset_type,
                        status=status,
                        source=AssetSource.AI if content.source_type == "ai" else AssetSource.MANUAL,
                        session_id=None,  # CaseContent没有session_id
                        draft_content=draft_content,
                        priority=content.priority or "P1",
                        tags=content.tags,
                        user_id=content.user_id,
                        created_by=content.user_id,
                        legacy_case_content_id=content.id,
                        legacy_api_case_id=content.api_case_id,
                    )
                    db.add(asset)
                    created += 1
                except Exception as e:
                    errors += 1
                    log.warning(f"MigrationService | CaseContent迁移失败 id={content.id}: {e}")

            db.commit()
            return {"created": created, "skipped": skipped, "errors": errors}
        except Exception as e:
            log.error(f"MigrationService | CaseContent迁移异常: {e}")
            return {"created": 0, "skipped": 0, "errors": 1, "error": str(e)}
        finally:
            db.close()

    @staticmethod
    def migrate_api_case() -> Dict:
        """ApiCase → TestAssetV2"""
        db = SessionLocal()
        try:
            from app.models.api_case import ApiCase

            # 只迁移未迁移的
            migrated_ids = set(
                row[0] for row in db.query(TestAssetV2.legacy_api_case_id)
                .filter(TestAssetV2.legacy_api_case_id.isnot(None))
                .all()
            )

            cases = db.query(ApiCase).filter(
                ApiCase.is_deleted == False,
                ~ApiCase.id.in_(migrated_ids) if migrated_ids else True,
            ).all()

            created = 0
            updated = 0
            errors = 0

            for case in cases:
                try:
                    # 检查是否已通过CaseContent迁移
                    existing = db.query(TestAssetV2).filter(
                        TestAssetV2.legacy_case_content_id == case.source_content_id,
                    ).first() if case.source_content_id else None

                    asset_type = MigrationService._infer_asset_type(case.test_type)

                    # 构建published_content
                    steps = json.loads(case.steps) if case.steps else []
                    assertions = json.loads(case.assertions) if case.assertions else []

                    published_content = json.dumps({
                        "method": case.method or "",
                        "url": case.url or "",
                        "headers": {},
                        "body": {},
                        "timeout": 5000,
                        "pre_steps": [],
                        "assertions": assertions,
                        "variables": {},
                        "runtime": {"retry": 0, "env": "test"},
                    }, ensure_ascii=False)

                    if existing:
                        # 补充published_content
                        existing.published_content = published_content
                        existing.status = AssetStatus.PUBLISHED
                        existing.legacy_api_case_id = case.id
                        updated += 1
                    else:
                        asset = TestAssetV2(
                            title=case.title,
                            asset_type=asset_type,
                            status=AssetStatus.PUBLISHED,
                            source_type=AssetSource.AI if case.source == "ai" else AssetSource.MANUAL,
                            session_id=None,
                            draft_content=published_content,
                            published_content=published_content,
                            priority=case.priority or "P1",
                            tags=case.tags,
                            folder_id=case.folder_id,
                            user_id=case.user_id,
                            created_by=case.user_id,
                            legacy_api_case_id=case.id,
                        )
                        db.add(asset)
                        created += 1
                except Exception as e:
                    errors += 1
                    log.warning(f"MigrationService | ApiCase迁移失败 id={case.id}: {e}")

            db.commit()
            return {"created": created, "updated": updated, "errors": errors}
        except Exception as e:
            log.error(f"MigrationService | ApiCase迁移异常: {e}")
            return {"created": 0, "updated": 0, "errors": 1, "error": str(e)}
        finally:
            db.close()

    @staticmethod
    def _infer_asset_type(test_type: Optional[str]) -> str:
        """推断资产类型"""
        if not test_type:
            return AssetType.API
        t = test_type.upper()
        if t in ("UI",):
            return AssetType.WEB
        if t in ("WEB",):
            return AssetType.WEB
        if t in ("ANDROID",):
            return AssetType.ANDROID
        return AssetType.API

    @staticmethod
    def _infer_status_from_content(case_status: Optional[str]) -> str:
        """从CaseContent状态推断TestAssetV2状态"""
        if not case_status:
            return AssetStatus.CREATED
        if case_status == "draft":
            return AssetStatus.GENERATED
        if case_status == "review":
            return AssetStatus.REVIEWED
        if case_status == "published":
            return AssetStatus.PUBLISHED
        return AssetStatus.CREATED
