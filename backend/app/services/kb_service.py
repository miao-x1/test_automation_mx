"""
知识库管理服务

统一管理元素库、用例库、脚本库的CRUD、审核、去重、重新向量化
"""
import json
from typing import Optional, AsyncGenerator
from sqlalchemy.orm import Session
from app.core.logger import log
from app.db.database import SessionLocal
from app.models.ui_element import UIElement
from app.models.script import Script
from app.models.requirement_task import RequirementTask
from app.agents.factory import AgentRegistry


class KBService:
    """知识库管理服务"""

    # ==================== 元素库 ====================

    @staticmethod
    def list_elements(
        page: int = 1, page_size: int = 20,
        name: Optional[str] = None,
        type: Optional[str] = None,
        source: Optional[str] = None,
        page_url: Optional[str] = None,
        kb_status: Optional[str] = None,
        sort_by: str = "created_at", sort_order: str = "desc",
    ) -> dict:
        """分页查询元素"""
        db = SessionLocal()
        try:
            q = db.query(UIElement)
            if name:
                q = q.filter(UIElement.name.ilike(f"%{name}%"))
            if type:
                q = q.filter(UIElement.type == type)
            if source:
                q = q.filter(UIElement.source == source)
            if page_url:
                q = q.filter(UIElement.page_url.ilike(f"%{page_url}%"))
            if kb_status:
                q = q.filter(UIElement.kb_status == kb_status)

            total = q.count()
            col = getattr(UIElement, sort_by, UIElement.created_at)
            q = q.order_by(col.desc() if sort_order == "desc" else col.asc())
            items = q.offset((page - 1) * page_size).limit(page_size).all()
            return {
                "items": [i.to_dict() for i in items],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        finally:
            db.close()

    @staticmethod
    def get_element(element_id: int) -> Optional[dict]:
        """获取元素详情"""
        db = SessionLocal()
        try:
            elem = db.query(UIElement).filter(UIElement.id == element_id).first()
            return elem.to_dict() if elem else None
        finally:
            db.close()

    @staticmethod
    def update_element(element_id: int, data: dict) -> Optional[dict]:
        """更新元素"""
        db = SessionLocal()
        try:
            elem = db.query(UIElement).filter(UIElement.id == element_id).first()
            if not elem:
                return None
            for field in ["name", "type", "text", "locator", "xpath", "css_selector"]:
                if field in data:
                    setattr(elem, field, data[field])
            db.commit()
            db.refresh(elem)
            # 同步Milvus：删除旧向量+重新索引
            KBService._reindex_element(elem, db)
            return elem.to_dict()
        finally:
            db.close()

    @staticmethod
    def delete_element(element_id: int) -> bool:
        """删除元素（同步删除Milvus向量）"""
        db = SessionLocal()
        try:
            elem = db.query(UIElement).filter(UIElement.id == element_id).first()
            if not elem:
                return False
            task_id = elem.task_id
            db.delete(elem)
            db.commit()
            # 同步删除Milvus向量
            KBService._delete_milvus_by_task_id("ui_element_vector", task_id)
            return True
        finally:
            db.close()

    @staticmethod
    def batch_delete_elements(ids: list[int]) -> dict:
        """批量删除元素"""
        db = SessionLocal()
        try:
            success = 0
            task_ids = []
            for eid in ids:
                elem = db.query(UIElement).filter(UIElement.id == eid).first()
                if elem:
                    task_ids.append(elem.task_id)
                    db.delete(elem)
                    success += 1
            db.commit()
            # 同步删除Milvus向量
            for tid in set(task_ids):
                KBService._delete_milvus_by_task_id("ui_element_vector", tid)
            return {"success": success, "total": len(ids)}
        finally:
            db.close()

    @staticmethod
    def approve_element(element_id: int) -> bool:
        """批准元素"""
        return KBService._set_kb_status(UIElement, element_id, "approved")

    @staticmethod
    def reject_element(element_id: int) -> bool:
        """拒绝元素（同步删除Milvus向量）"""
        db = SessionLocal()
        try:
            elem = db.query(UIElement).filter(UIElement.id == element_id).first()
            if not elem:
                return False
            elem.kb_status = "rejected"
            db.commit()
            KBService._delete_milvus_by_task_id("ui_element_vector", elem.task_id)
            return True
        finally:
            db.close()

    # ==================== 用例库 ====================

    @staticmethod
    def list_cases(
        page: int = 1, page_size: int = 20,
        case_name: Optional[str] = None,
        kb_status: Optional[str] = None,
        sort_by: str = "created_at", sort_order: str = "desc",
    ) -> dict:
        """分页查询用例"""
        db = SessionLocal()
        try:
            q = db.query(RequirementTask).filter(RequirementTask.generated_case.isnot(None))
            if case_name:
                q = q.filter(RequirementTask.generated_case.ilike(f"%{case_name}%"))
            if kb_status:
                q = q.filter(RequirementTask.kb_status == kb_status)

            total = q.count()
            col = getattr(RequirementTask, sort_by, RequirementTask.created_at)
            q = q.order_by(col.desc() if sort_order == "desc" else col.asc())
            items = q.offset((page - 1) * page_size).limit(page_size).all()
            result_items = []
            for rt in items:
                d = rt.to_dict()
                # 解析case_name
                try:
                    case = json.loads(rt.generated_case) if rt.generated_case else {}
                    d["case_name"] = case.get("case_name", "")
                    d["case_description"] = case.get("description", "")
                    d["case_steps"] = case.get("steps", [])
                except (json.JSONDecodeError, TypeError):
                    d["case_name"] = ""
                    d["case_description"] = ""
                    d["case_steps"] = []
                result_items.append(d)
            return {
                "items": result_items,
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        finally:
            db.close()

    @staticmethod
    def get_case(case_id: int) -> Optional[dict]:
        """获取用例详情"""
        db = SessionLocal()
        try:
            rt = db.query(RequirementTask).filter(RequirementTask.id == case_id).first()
            if not rt:
                return None
            d = rt.to_dict()
            try:
                case = json.loads(rt.generated_case) if rt.generated_case else {}
                d["case_name"] = case.get("case_name", "")
                d["case_description"] = case.get("description", "")
                d["case_steps"] = case.get("steps", [])
                d["case_assertions"] = case.get("assertions", [])
            except (json.JSONDecodeError, TypeError):
                d["case_name"] = ""
                d["case_description"] = ""
                d["case_steps"] = []
                d["case_assertions"] = []
            return d
        finally:
            db.close()

    @staticmethod
    def update_case(case_id: int, data: dict) -> Optional[dict]:
        """更新用例"""
        db = SessionLocal()
        try:
            rt = db.query(RequirementTask).filter(RequirementTask.id == case_id).first()
            if not rt:
                return None
            # 更新generated_case字段
            try:
                case = json.loads(rt.generated_case) if rt.generated_case else {}
            except (json.JSONDecodeError, TypeError):
                case = {}
            if "case_name" in data:
                case["case_name"] = data["case_name"]
            if "description" in data:
                case["description"] = data["description"]
            if "steps" in data:
                case["steps"] = data["steps"]
            if "assertions" in data:
                case["assertions"] = data["assertions"]
            rt.generated_case = json.dumps(case, ensure_ascii=False)
            db.commit()
            db.refresh(rt)
            # 同步Milvus
            KBService._reindex_case(rt, db)
            return rt.to_dict()
        finally:
            db.close()

    @staticmethod
    def delete_case(case_id: int) -> bool:
        """删除用例（只删除Milvus向量，不删除RequirementTask本身）"""
        db = SessionLocal()
        try:
            rt = db.query(RequirementTask).filter(RequirementTask.id == case_id).first()
            if not rt:
                return False
            task_id = rt.task_id or 0
            # 清空generated_case
            rt.generated_case = None
            db.commit()
            KBService._delete_milvus_by_task_id("test_case_vector", task_id)
            return True
        finally:
            db.close()

    @staticmethod
    def batch_delete_cases(ids: list[int]) -> dict:
        """批量删除用例"""
        db = SessionLocal()
        try:
            success = 0
            task_ids = []
            for cid in ids:
                rt = db.query(RequirementTask).filter(RequirementTask.id == cid).first()
                if rt and rt.generated_case:
                    task_ids.append(rt.task_id or 0)
                    rt.generated_case = None
                    success += 1
            db.commit()
            for tid in set(task_ids):
                KBService._delete_milvus_by_task_id("test_case_vector", tid)
            return {"success": success, "total": len(ids)}
        finally:
            db.close()

    @staticmethod
    def approve_case(case_id: int) -> bool:
        """批准用例"""
        db = SessionLocal()
        try:
            rt = db.query(RequirementTask).filter(RequirementTask.id == case_id).first()
            if not rt:
                return False
            rt.kb_status = "approved"
            db.commit()
            # 重新索引到Milvus
            KBService._reindex_case(rt, db)
            return True
        finally:
            db.close()

    @staticmethod
    def reject_case(case_id: int) -> bool:
        """拒绝用例"""
        db = SessionLocal()
        try:
            rt = db.query(RequirementTask).filter(RequirementTask.id == case_id).first()
            if not rt:
                return False
            rt.kb_status = "rejected"
            db.commit()
            KBService._delete_milvus_by_task_id("test_case_vector", rt.task_id or 0)
            return True
        finally:
            db.close()

    # ==================== 脚本库 ====================

    @staticmethod
    def list_scripts(
        page: int = 1, page_size: int = 20,
        script_name: Optional[str] = None,
        kb_status: Optional[str] = None,
        sort_by: str = "created_at", sort_order: str = "desc",
    ) -> dict:
        """分页查询脚本"""
        db = SessionLocal()
        try:
            q = db.query(Script)
            if script_name:
                q = q.filter(Script.script_type.ilike(f"%{script_name}%"))
            if kb_status:
                q = q.filter(Script.kb_status == kb_status)

            total = q.count()
            col = getattr(Script, sort_by, Script.created_at)
            q = q.order_by(col.desc() if sort_order == "desc" else col.asc())
            items = q.offset((page - 1) * page_size).limit(page_size).all()
            return {
                "items": [i.to_dict() for i in items],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        finally:
            db.close()

    @staticmethod
    def get_script(script_id: int) -> Optional[dict]:
        """获取脚本详情"""
        db = SessionLocal()
        try:
            s = db.query(Script).filter(Script.id == script_id).first()
            return s.to_dict() if s else None
        finally:
            db.close()

    @staticmethod
    def update_script(script_id: int, data: dict) -> Optional[dict]:
        """更新脚本"""
        db = SessionLocal()
        try:
            s = db.query(Script).filter(Script.id == script_id).first()
            if not s:
                return None
            if "script_content" in data:
                s.script_content = data["script_content"]
            if "script_type" in data:
                s.script_type = data["script_type"]
            db.commit()
            db.refresh(s)
            # 同步Milvus
            KBService._reindex_script(s, db)
            return s.to_dict()
        finally:
            db.close()

    @staticmethod
    def delete_script(script_id: int) -> bool:
        """删除脚本（同步删除Milvus向量）"""
        db = SessionLocal()
        try:
            s = db.query(Script).filter(Script.id == script_id).first()
            if not s:
                return False
            task_id = s.task_id
            db.delete(s)
            db.commit()
            KBService._delete_milvus_by_task_id("script_vector", task_id)
            return True
        finally:
            db.close()

    @staticmethod
    def batch_delete_scripts(ids: list[int]) -> dict:
        """批量删除脚本"""
        db = SessionLocal()
        try:
            success = 0
            task_ids = []
            for sid in ids:
                s = db.query(Script).filter(Script.id == sid).first()
                if s:
                    task_ids.append(s.task_id)
                    db.delete(s)
                    success += 1
            db.commit()
            for tid in set(task_ids):
                KBService._delete_milvus_by_task_id("script_vector", tid)
            return {"success": success, "total": len(ids)}
        finally:
            db.close()

    @staticmethod
    def approve_script(script_id: int) -> bool:
        """批准脚本"""
        db = SessionLocal()
        try:
            s = db.query(Script).filter(Script.id == script_id).first()
            if not s:
                return False
            s.kb_status = "approved"
            db.commit()
            KBService._reindex_script(s, db)
            return True
        finally:
            db.close()

    @staticmethod
    def reject_script(script_id: int) -> bool:
        """拒绝脚本"""
        db = SessionLocal()
        try:
            s = db.query(Script).filter(Script.id == script_id).first()
            if not s:
                return False
            s.kb_status = "rejected"
            db.commit()
            KBService._delete_milvus_by_task_id("script_vector", s.task_id)
            return True
        finally:
            db.close()

    # ==================== 重新向量化 ====================

    @staticmethod
    async def reindex_element(element_id: int) -> AsyncGenerator[str, None]:
        """重新向量化单个元素"""
        db = SessionLocal()
        try:
            elem = db.query(UIElement).filter(UIElement.id == element_id).first()
            if not elem:
                yield json.dumps({"step": "失败", "progress": 100, "message": "元素不存在"}, ensure_ascii=False)
                return
            yield json.dumps({"step": "开始重新向量化", "progress": 10, "message": f"元素: {elem.name}"}, ensure_ascii=False)

            # 删除旧向量
            KBService._delete_milvus_by_task_id("ui_element_vector", elem.task_id)
            yield json.dumps({"step": "删除旧向量", "progress": 40, "message": "已删除旧向量"}, ensure_ascii=False)

            # 重新索引
            KBService._reindex_element(elem, db)
            yield json.dumps({"step": "完成", "progress": 100, "message": "重新向量化完成"}, ensure_ascii=False)
        finally:
            db.close()

    @staticmethod
    async def reindex_case(case_id: int) -> AsyncGenerator[str, None]:
        """重新向量化单个用例"""
        db = SessionLocal()
        try:
            rt = db.query(RequirementTask).filter(RequirementTask.id == case_id).first()
            if not rt:
                yield json.dumps({"step": "失败", "progress": 100, "message": "用例不存在"}, ensure_ascii=False)
                return
            yield json.dumps({"step": "开始重新向量化", "progress": 10, "message": "用例重新向量化"}, ensure_ascii=False)

            KBService._delete_milvus_by_task_id("test_case_vector", rt.task_id or 0)
            yield json.dumps({"step": "删除旧向量", "progress": 40, "message": "已删除旧向量"}, ensure_ascii=False)

            KBService._reindex_case(rt, db)
            yield json.dumps({"step": "完成", "progress": 100, "message": "重新向量化完成"}, ensure_ascii=False)
        finally:
            db.close()

    @staticmethod
    async def reindex_script(script_id: int) -> AsyncGenerator[str, None]:
        """重新向量化单个脚本"""
        db = SessionLocal()
        try:
            s = db.query(Script).filter(Script.id == script_id).first()
            if not s:
                yield json.dumps({"step": "失败", "progress": 100, "message": "脚本不存在"}, ensure_ascii=False)
                return
            yield json.dumps({"step": "开始重新向量化", "progress": 10, "message": "脚本重新向量化"}, ensure_ascii=False)

            KBService._delete_milvus_by_task_id("script_vector", s.task_id)
            yield json.dumps({"step": "删除旧向量", "progress": 40, "message": "已删除旧向量"}, ensure_ascii=False)

            KBService._reindex_script(s, db)
            yield json.dumps({"step": "完成", "progress": 100, "message": "重新向量化完成"}, ensure_ascii=False)
        finally:
            db.close()

    # ==================== 去重 ====================

    @staticmethod
    def detect_duplicates() -> dict:
        """检测重复数据"""
        db = SessionLocal()
        try:
            # 元素去重：name + locator
            from sqlalchemy import func
            elem_dupes = db.query(
                UIElement.name, UIElement.locator, func.count(UIElement.id).label("cnt")
            ).group_by(UIElement.name, UIElement.locator).having(func.count(UIElement.id) > 1).all()
            elem_dupe_list = [{"name": r.name, "locator": r.locator, "count": r.cnt} for r in elem_dupes]

            # 用例去重：case_name
            case_dupes = []
            all_cases = db.query(RequirementTask).filter(RequirementTask.generated_case.isnot(None)).all()
            case_name_map = {}
            for rt in all_cases:
                try:
                    case = json.loads(rt.generated_case)
                    cn = case.get("case_name", "")
                    if cn:
                        case_name_map.setdefault(cn, []).append(rt.id)
                except (json.JSONDecodeError, TypeError):
                    pass
            case_dupe_list = [{"case_name": k, "count": len(v), "ids": v} for k, v in case_name_map.items() if len(v) > 1]

            # 脚本去重：task_id
            script_dupes = db.query(
                Script.task_id, func.count(Script.id).label("cnt")
            ).group_by(Script.task_id).having(func.count(Script.id) > 1).all()
            script_dupe_list = [{"task_id": r.task_id, "count": r.cnt} for r in script_dupes]

            return {
                "elements": {"duplicates": elem_dupe_list, "total": sum(d["count"] - 1 for d in elem_dupe_list)},
                "cases": {"duplicates": case_dupe_list, "total": sum(d["count"] - 1 for d in case_dupe_list)},
                "scripts": {"duplicates": script_dupe_list, "total": sum(d["count"] - 1 for d in script_dupe_list)},
            }
        finally:
            db.close()

    @staticmethod
    async def deduplicate() -> AsyncGenerator[str, None]:
        """一键去重（保留最新，删除旧记录）"""
        db = SessionLocal()
        try:
            total_deleted = 0

            # 元素去重
            yield json.dumps({"step": "元素去重", "progress": 10, "message": "检测元素重复..."}, ensure_ascii=False)
            from sqlalchemy import func
            elem_dupes = db.query(
                UIElement.name, UIElement.locator, func.count(UIElement.id).label("cnt")
            ).group_by(UIElement.name, UIElement.locator).having(func.count(UIElement.id) > 1).all()
            for dupe in elem_dupes:
                items = db.query(UIElement).filter(
                    UIElement.name == dupe.name, UIElement.locator == dupe.locator
                ).order_by(UIElement.id.desc()).all()
                # 保留最新（第一个），删除其余
                for item in items[1:]:
                    db.delete(item)
                    total_deleted += 1
            db.commit()
            yield json.dumps({"step": "元素去重完成", "progress": 40, "message": f"元素去重: 删除{total_deleted}条"}, ensure_ascii=False)

            # 用例去重
            yield json.dumps({"step": "用例去重", "progress": 50, "message": "检测用例重复..."}, ensure_ascii=False)
            case_del = 0
            all_cases = db.query(RequirementTask).filter(RequirementTask.generated_case.isnot(None)).all()
            case_name_map = {}
            for rt in all_cases:
                try:
                    case = json.loads(rt.generated_case)
                    cn = case.get("case_name", "")
                    if cn:
                        case_name_map.setdefault(cn, []).append(rt)
                except (json.JSONDecodeError, TypeError):
                    pass
            for cn, rts in case_name_map.items():
                if len(rts) > 1:
                    # 按id降序，保留最新
                    rts.sort(key=lambda x: x.id, reverse=True)
                    for rt in rts[1:]:
                        rt.generated_case = None
                        case_del += 1
            db.commit()
            total_deleted += case_del
            yield json.dumps({"step": "用例去重完成", "progress": 70, "message": f"用例去重: 清除{case_del}条"}, ensure_ascii=False)

            # 脚本去重
            yield json.dumps({"step": "脚本去重", "progress": 80, "message": "检测脚本重复..."}, ensure_ascii=False)
            script_dupes = db.query(
                Script.task_id, func.count(Script.id).label("cnt")
            ).group_by(Script.task_id).having(func.count(Script.id) > 1).all()
            script_del = 0
            for dupe in script_dupes:
                items = db.query(Script).filter(Script.task_id == dupe.task_id).order_by(Script.id.desc()).all()
                for item in items[1:]:
                    db.delete(item)
                    script_del += 1
            db.commit()
            total_deleted += script_del
            yield json.dumps({"step": "脚本去重完成", "progress": 95, "message": f"脚本去重: 删除{script_del}条"}, ensure_ascii=False)

            yield json.dumps({"step": "去重完成", "progress": 100, "message": f"去重完成，共删除{total_deleted}条重复记录"}, ensure_ascii=False)
        finally:
            db.close()

    # ==================== 统计 ====================

    @staticmethod
    def get_statistics() -> dict:
        """获取知识库统计"""
        db = SessionLocal()
        try:
            from sqlalchemy import func

            elem_total = db.query(func.count(UIElement.id)).scalar() or 0
            elem_approved = db.query(func.count(UIElement.id)).filter(UIElement.kb_status == "approved").scalar() or 0
            elem_draft = db.query(func.count(UIElement.id)).filter(UIElement.kb_status == "draft").scalar() or 0
            elem_rejected = db.query(func.count(UIElement.id)).filter(UIElement.kb_status == "rejected").scalar() or 0

            case_total = db.query(func.count(RequirementTask.id)).filter(RequirementTask.generated_case.isnot(None)).scalar() or 0
            case_approved = db.query(func.count(RequirementTask.id)).filter(
                RequirementTask.generated_case.isnot(None), RequirementTask.kb_status == "approved"
            ).scalar() or 0
            case_draft = db.query(func.count(RequirementTask.id)).filter(
                RequirementTask.generated_case.isnot(None), RequirementTask.kb_status == "draft"
            ).scalar() or 0
            case_rejected = db.query(func.count(RequirementTask.id)).filter(
                RequirementTask.generated_case.isnot(None), RequirementTask.kb_status == "rejected"
            ).scalar() or 0

            script_total = db.query(func.count(Script.id)).scalar() or 0
            script_approved = db.query(func.count(Script.id)).filter(Script.kb_status == "approved").scalar() or 0
            script_draft = db.query(func.count(Script.id)).filter(Script.kb_status == "draft").scalar() or 0
            script_rejected = db.query(func.count(Script.id)).filter(Script.kb_status == "rejected").scalar() or 0

            # 向量总数
            vector_total = 0
            try:
                from app.db.milvus_client import get_milvus_client, COLLECTION_NAME, CASE_COLLECTION_NAME, SCRIPT_COLLECTION_NAME
                client = get_milvus_client()
                for col in [COLLECTION_NAME, CASE_COLLECTION_NAME, SCRIPT_COLLECTION_NAME]:
                    if client.has_collection(col):
                        try:
                            client.load_collection(col)
                            r = client.query(col, filter="id >= 0", output_fields=["id"], limit=1)
                            # 用stats获取行数
                            stats = client.get_collection_stats(col)
                            vector_total += stats.get("row_count", 0)
                        except Exception:
                            pass
            except Exception:
                pass

            # 重复数据
            dupes = KBService.detect_duplicates()
            dupe_total = dupes["elements"]["total"] + dupes["cases"]["total"] + dupes["scripts"]["total"]

            return {
                "elements": {"total": elem_total, "approved": elem_approved, "draft": elem_draft, "rejected": elem_rejected},
                "cases": {"total": case_total, "approved": case_approved, "draft": case_draft, "rejected": case_rejected},
                "scripts": {"total": script_total, "approved": script_approved, "draft": script_draft, "rejected": script_rejected},
                "vector_total": vector_total,
                "duplicate_total": dupe_total,
            }
        finally:
            db.close()

    # ==================== 内部方法 ====================

    @staticmethod
    def _set_kb_status(model, item_id: int, status: str) -> bool:
        """设置审核状态"""
        db = SessionLocal()
        try:
            item = db.query(model).filter(model.id == item_id).first()
            if not item:
                return False
            item.kb_status = status
            db.commit()
            return True
        finally:
            db.close()

    @staticmethod
    def _delete_milvus_by_task_id(collection_name: str, task_id: int):
        """按task_id删除Milvus向量"""
        try:
            from app.db.milvus_client import get_milvus_client
            client = get_milvus_client()
            if client and client.has_collection(collection_name):
                try:
                    client.load_collection(collection_name)
                except Exception:
                    pass
                client.delete(collection_name, filter=f'task_id == {task_id}')
                log.info(f"删除Milvus向量 | collection={collection_name} task_id={task_id}")
        except Exception as e:
            log.warning(f"删除Milvus向量失败: {e}")

    @staticmethod
    def _reindex_element(elem: UIElement, db: Session):
        """重新索引元素到Milvus"""
        try:
            from app.db.milvus_client import get_milvus_client, COLLECTION_NAME, ensure_all_collections

            client = ensure_all_collections()
            embed = AgentRegistry.create("embedding_agent")

            # 删除旧向量
            try:
                client.delete(COLLECTION_NAME, filter=f'task_id == {elem.task_id}')
            except Exception:
                pass

            # 生成新向量
            desc = f"页面: {elem.page_url or ''} | 元素: {elem.name} | 类型: {elem.type} | 定位器: {elem.locator or ''}"
            if desc.strip():
                emb = embed._embed([desc])
                client.insert(collection_name=COLLECTION_NAME, data=[{
                    "task_id": elem.task_id,
                    "page_name": (elem.page_url or "")[:512],
                    "element_name": (elem.name or "")[:255],
                    "element_type": (elem.type or "")[:50],
                    "locator": (elem.locator or "")[:1024],
                    "description": desc[:2048],
                    "embedding": emb[0],
                }])
                log.info(f"重新索引元素 | id={elem.id}")
        except Exception as e:
            log.warning(f"重新索引元素失败: {e}")

    @staticmethod
    def _reindex_case(rt: RequirementTask, db: Session):
        """重新索引用例到Milvus"""
        try:
            from app.db.milvus_client import get_milvus_client, CASE_COLLECTION_NAME, ensure_all_collections

            client = ensure_all_collections()
            embed = AgentRegistry.create("embedding_agent")

            task_id = rt.task_id or 0

            # 删除旧向量
            try:
                client.delete(CASE_COLLECTION_NAME, filter=f'task_id == {task_id}')
            except Exception:
                pass

            if not rt.generated_case:
                return

            try:
                case = json.loads(rt.generated_case)
            except (json.JSONDecodeError, TypeError):
                return

            case_name = case.get("case_name", "")
            description = case.get("description", "")
            steps = case.get("steps", [])

            desc_parts = []
            if case_name:
                desc_parts.append(f"用例: {case_name}")
            if description:
                desc_parts.append(f"描述: {description}")
            if rt.requirement:
                desc_parts.append(f"需求: {rt.requirement}")
            for s in steps[:5]:
                step_desc = s.get("step", s.get("description", "")) if isinstance(s, dict) else str(s)
                if step_desc:
                    desc_parts.append(f"步骤: {step_desc}")
            desc = " | ".join(desc_parts)

            if desc.strip():
                emb = embed._embed([desc])
                steps_json = json.dumps(steps, ensure_ascii=False)
                if len(steps_json) > 4096:
                    steps_json = steps_json[:4096]
                client.insert(collection_name=CASE_COLLECTION_NAME, data=[{
                    "task_id": task_id,
                    "case_name": (case_name or "")[:255],
                    "description": (description or "")[:2048],
                    "steps": steps_json,
                    "embedding": emb[0],
                }])
                log.info(f"重新索引用例 | id={rt.id}")
        except Exception as e:
            log.warning(f"重新索引用例失败: {e}")

    @staticmethod
    def _reindex_script(s: Script, db: Session):
        """重新索引脚本到Milvus"""
        try:
            from app.db.milvus_client import get_milvus_client, SCRIPT_COLLECTION_NAME, ensure_all_collections

            client = ensure_all_collections()
            embed = AgentRegistry.create("embedding_agent")

            # 删除旧向量
            try:
                client.delete(SCRIPT_COLLECTION_NAME, filter=f'task_id == {s.task_id}')
            except Exception:
                pass

            content = s.script_content or ""
            desc = f"脚本类型: {s.script_type} | 语言: {s.script_language} | 内容预览: {content[:500]}"
            if desc.strip():
                emb = embed._embed([desc])
                sc = content[:8192] if len(content) > 8192 else content
                client.insert(collection_name=SCRIPT_COLLECTION_NAME, data=[{
                    "task_id": s.task_id,
                    "script_name": f"task_{s.task_id}_script",
                    "script_content": sc,
                    "description": f"任务{s.task_id}的{s.script_type}脚本",
                    "embedding": emb[0],
                }])
                log.info(f"重新索引脚本 | id={s.id}")
        except Exception as e:
            log.warning(f"重新索引脚本失败: {e}")
