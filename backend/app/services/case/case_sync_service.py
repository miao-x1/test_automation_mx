"""
CaseSyncService - 用例同步服务

职责：将 test-case（草稿层）的用例同步到 api-test（发布层）

数据流：
  AI生成 → CaseContent(DRAFT) → 用户确认 → CaseSyncService → ApiCase(PUBLISHED)

去重规则：
  - source_content_id 唯一映射
  - title + method + url hash 去重
"""
import json
import hashlib
from typing import Dict, Optional, Tuple
from app.core.logger import log
from app.db.database import SessionLocal
from app.models.case_content import CaseContent
from app.models.api_case import ApiCase, ApiCaseStatus


class CaseSyncService:
    """用例同步服务：test-case → api-test"""

    @staticmethod
    def sync_single(content_id: int, user_id: Optional[int] = None, folder_id: Optional[int] = None) -> Dict:
        """
        同步单条用例：CaseContent → ApiCase

        Args:
            content_id: CaseContent ID
            user_id: 操作用户ID
            folder_id: 目标目录ID

        Returns:
            {"api_case_id": int, "action": "created"/"updated", "canonical_case_id": str}
        """
        db = SessionLocal()
        try:
            content = db.query(CaseContent).filter(CaseContent.id == content_id, CaseContent.is_deleted == False).first()
            if not content:
                return {"error": f"CaseContent不存在: {content_id}"}

            # 检查是否已同步
            existing = db.query(ApiCase).filter(
                ApiCase.source_content_id == content_id,
                ApiCase.is_deleted == False,
            ).first()

            # 解析steps获取method/url
            steps = json.loads(content.steps) if content.steps else []
            method = ""
            url = ""
            headers = {}
            body = {}
            timeout = 5000

            if steps and isinstance(steps, list):
                first = steps[0] if steps else {}
                if isinstance(first, dict):
                    action = first.get("action", "")
                    if action.upper() in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                        method = action.upper()
                        url = first.get("url", "")
                        headers = first.get("headers", {})
                        body = first.get("body", {})
                        timeout = first.get("timeout", 5000)

            # 解析assertions
            assertions = json.loads(content.expected) if content.expected else []
            if isinstance(assertions, dict):
                assertions = [assertions]

            # 生成canonical_case_id
            canonical_id = content.case_type.upper()[:2] + f"_{content.id:04d}"

            if existing:
                # 更新已有记录
                existing.title = content.title
                existing.priority = content.priority
                existing.steps = content.steps
                existing.assertions = json.dumps(assertions, ensure_ascii=False) if assertions else None
                existing.method = method
                existing.url = url
                existing.precondition = content.precondition
                existing.tags = content.tags
                existing.status = ApiCaseStatus.PUBLISHED
                existing.version = (existing.version or 0) + 1
                db.commit()

                # 更新CaseContent状态
                content.case_status = "published"
                content.api_case_id = existing.id
                db.commit()

                log.info(f"CaseSyncService | 更新用例 | content_id={content_id} → api_case_id={existing.id}")
                return {
                    "api_case_id": existing.id,
                    "action": "updated",
                    "canonical_case_id": existing.canonical_case_id or canonical_id,
                }
            else:
                # 推断测试类型
                from app.services.case.test_type_router import TestTypeRouter
                case_data_for_route = {
                    "method": method,
                    "url": url,
                    "steps": steps,
                    "precondition": content.precondition,
                }
                test_type = TestTypeRouter.route(case_data_for_route)

                # 创建新记录
                api_case = ApiCase(
                    title=content.title,
                    case_id=canonical_id,
                    canonical_case_id=canonical_id,
                    description=f"由AI生成同步入库（source_content_id={content_id}）",
                    priority=content.priority,
                    status=ApiCaseStatus.PUBLISHED,
                    method=method,
                    url=url,
                    steps=content.steps,
                    assertions=json.dumps(assertions, ensure_ascii=False) if assertions else None,
                    precondition=content.precondition,
                    tags=content.tags,
                    folder_id=folder_id,
                    source="ai",
                    source_content_id=content_id,
                    user_id=user_id or content.user_id,
                    created_by=user_id or content.user_id,
                    version=1,
                    test_type=test_type,
                )
                db.add(api_case)
                db.flush()

                # 更新CaseContent状态和映射
                content.case_status = "published"
                content.api_case_id = api_case.id
                db.commit()

                log.info(f"CaseSyncService | 创建用例 | content_id={content_id} → api_case_id={api_case.id}")
                return {
                    "api_case_id": api_case.id,
                    "action": "created",
                    "canonical_case_id": canonical_id,
                }

        except Exception as e:
            log.error(f"CaseSyncService | 同步失败: {e}")
            return {"error": str(e)}
        finally:
            db.close()

    @staticmethod
    def sync_batch(task_id: int, user_id: Optional[int] = None, folder_id: Optional[int] = None) -> Dict:
        """
        批量同步：将一个task下所有DRAFT用例同步到api-test

        Args:
            task_id: CaseTask ID
            user_id: 操作用户ID
            folder_id: 目标目录ID

        Returns:
            {"synced": int, "created": int, "updated": int, "errors": int, "details": [...]}
        """
        db = SessionLocal()
        try:
            contents = db.query(CaseContent).filter(
                CaseContent.case_task_id == task_id,
                CaseContent.is_deleted == False,
                CaseContent.case_status.in_(["draft", "review"]),
            ).all()

            if not contents:
                return {"synced": 0, "created": 0, "updated": 0, "errors": 0, "details": []}

            results = []
            created = 0
            updated = 0
            errors = 0

            for content in contents:
                result = CaseSyncService.sync_single(
                    content_id=content.id,
                    user_id=user_id,
                    folder_id=folder_id,
                )
                if "error" in result:
                    errors += 1
                elif result["action"] == "created":
                    created += 1
                elif result["action"] == "updated":
                    updated += 1
                results.append(result)

            return {
                "synced": created + updated,
                "created": created,
                "updated": updated,
                "errors": errors,
                "details": results,
            }

        except Exception as e:
            log.error(f"CaseSyncService | 批量同步失败: {e}")
            return {"synced": 0, "created": 0, "updated": 0, "errors": 1, "details": [{"error": str(e)}]}

    @staticmethod
    def get_draft_count(task_id: int) -> int:
        """获取指定task下待同步的用例数量"""
        db = SessionLocal()
        try:
            return db.query(CaseContent).filter(
                CaseContent.case_task_id == task_id,
                CaseContent.is_deleted == False,
                CaseContent.case_status.in_(["draft", "review"]),
            ).count()
        finally:
            db.close()

    @staticmethod
    def get_sync_status(content_id: int) -> Dict:
        """获取用例同步状态"""
        db = SessionLocal()
        try:
            content = db.query(CaseContent).filter(CaseContent.id == content_id).first()
            if not content:
                return {"status": "not_found"}

            return {
                "content_id": content.id,
                "case_status": content.case_status,
                "api_case_id": content.api_case_id,
                "is_synced": content.api_case_id is not None,
            }
        finally:
            db.close()

    @staticmethod
    def sync_single_or_batch(source: str, content_id: Optional[int] = None, task_id: Optional[int] = None, user_id: Optional[int] = None, folder_id: Optional[int] = None) -> Dict:
        """统一同步入口"""
        if source == "content":
            if not content_id:
                return {"error": "source=content时content_id必填"}
            return CaseSyncService.sync_single(content_id=content_id, user_id=user_id, folder_id=folder_id)
        elif source == "task":
            if not task_id:
                return {"error": "source=task时task_id必填"}
            return CaseSyncService.sync_batch(task_id=task_id, user_id=user_id, folder_id=folder_id)
        else:
            return {"error": "source必须是content或task"}
