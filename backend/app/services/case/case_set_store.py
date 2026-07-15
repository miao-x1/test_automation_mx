"""
Case Set Store - 分层存储层

从 compiler.py 拆分而来，包含 case_set 的读写、迁移、用例持久化方法。
case_set 分层存储：{L1: {}, L2: {}, L3: {}}，禁止跨层覆盖。
"""
import json
from typing import Any, Dict, List, Optional

from app.core.logger import log
from app.models.case_task import CaseTask
from app.models.case_content import CaseContent


class CaseSetStore:
    """case_set 分层存储（L1/L2/L3），禁止跨层覆盖"""

    @staticmethod
    def read_case_set(db, task_id: int) -> Dict[str, Any]:
        """读取case_set（分层结构）"""
        task = db.query(CaseTask).filter(CaseTask.id == task_id).first()
        if not task or not task.case_set:
            return {"L1": {}, "L2": {}, "L3": {}, "state": "init", "config": {}}
        try:
            data = json.loads(task.case_set)
            # 兼容旧格式：如果没有L1/L2/L3键，自动迁移
            if "L1" not in data and "L2" not in data and "L3" not in data:
                return CaseSetStore.migrate_old_format(data)
            return data
        except json.JSONDecodeError:
            return {"L1": {}, "L2": {}, "L3": {}, "state": "init", "config": {}}

    @staticmethod
    def merge_case_set(db, task_id: int, layer: str, data: Dict[str, Any], state: str = ""):
        """
        merge写入case_set的指定层（禁止覆盖其他层）

        Args:
            layer: "L1" / "L2" / "L3"
            data: 该层的数据
            state: 可选，更新状态机
        """
        task = db.query(CaseTask).filter(CaseTask.id == task_id).first()
        if not task:
            return

        current = CaseSetStore.read_case_set(db, task_id)
        current[layer] = data
        if state:
            current["state"] = state

        task.case_set = json.dumps(current, ensure_ascii=False)
        db.commit()

    @staticmethod
    def migrate_old_format(data: Dict[str, Any]) -> Dict[str, Any]:
        """将旧格式case_set迁移为分层结构"""
        result = {"L1": {}, "L2": {}, "L3": {}, "state": "init", "config": {}}

        level = data.get("level", "")
        if level == "l1" or "features" in data:
            result["L1"] = {
                "features": data.get("features", []),
                "entities": data.get("entities", []),
                "api_candidates": data.get("api_candidates", []),
                "test_strategy": data.get("test_strategy", {}),
                "feature_count": data.get("feature_count", len(data.get("features", []))),
                "feature_titles": data.get("feature_titles", []),
            }
            result["state"] = "l1_done"

        if level == "l2" or "content_count" in data or "case_count" in data:
            result["L2"] = {
                "content_count": data.get("content_count", data.get("case_count", 0)),
                "saved_content_ids": data.get("saved_content_ids", []),
                "feature_titles": data.get("feature_titles", []),
                "draft_count": data.get("draft_count", 0),
                "published_count": data.get("published_count", 0),
            }
            result["state"] = "l2_done"

        if level == "l3" or "scripts" in data or "full_code" in data:
            result["L3"] = {
                "scripts": data.get("scripts", []),
                "full_code": data.get("full_code", ""),
                "run_command": data.get("run_command", ""),
                "entry_file": data.get("entry_file", ""),
            }
            result["state"] = "l3_done"

        return result

    @staticmethod
    def load_cases_from_db(db, task_id: int) -> List[Dict[str, Any]]:
        """从 CaseContent 表读取指定 task_id 关联的用例（草稿层）"""
        contents = db.query(CaseContent).filter(
            CaseContent.case_task_id == task_id,
            CaseContent.is_deleted == False,
        ).all()

        result = []
        for c in contents:
            steps = json.loads(c.steps) if c.steps else []
            assertions = json.loads(c.expected) if c.expected else []
            if isinstance(assertions, dict):
                assertions = [assertions]

            case_dict = {
                "id": c.id,
                "content_id": c.id,
                "title": c.title,
                "priority": c.priority,
                "case_status": c.case_status,
                "api_case_id": c.api_case_id,
                "is_synced": c.api_case_id is not None,
                "tags": c.tags.split(",") if c.tags else [],
            }

            if steps and isinstance(steps, list):
                first = steps[0] if steps else {}
                if isinstance(first, dict):
                    action = first.get("action", "")
                    if action.upper() in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                        case_dict["method"] = action.upper()
                        case_dict["url"] = first.get("url", "")
                        case_dict["request"] = {
                            "method": action.upper(),
                            "url": first.get("url", ""),
                            "headers": first.get("headers", {}),
                            "body": first.get("body", {}),
                            "timeout": first.get("timeout", 5000),
                        }

            case_dict["steps"] = steps
            case_dict["assertions"] = assertions
            case_dict["precondition"] = c.precondition
            result.append(case_dict)
        return result

    @staticmethod
    def save_single_case(
        db,
        task_id: int,
        case_data: Dict[str, Any],
        user_id: Optional[int],
        base_url: str,
    ) -> Optional[int]:
        """保存单条case到CaseContent（草稿层，含L3编译）"""
        try:
            from app.agent.case.test_normalization_agent import TestNormalizationAgent
            normalizer = TestNormalizationAgent()
            norm_result = normalizer.normalize(
                cases=[case_data], base_url=base_url, env="test"
            )
            compiled_cases = norm_result.get("cases", [case_data])
            compiled = compiled_cases[0] if compiled_cases else case_data

            request_obj = compiled.get("request", {})
            pre_steps_list = compiled.get("pre_steps", [])
            assertions_list = compiled.get("assertions", [])
            variables_obj = compiled.get("variables", {})

            steps_list = [{
                "action": request_obj.get("method", "POST"),
                "url": request_obj.get("url", ""),
                "headers": request_obj.get("headers", {}),
                "body": request_obj.get("body", {}),
                "timeout": request_obj.get("timeout", 5000),
            }]

            steps_str = json.dumps(steps_list, ensure_ascii=False)
            assertions_str = json.dumps(assertions_list, ensure_ascii=False)
            pre_steps_str = json.dumps(pre_steps_list, ensure_ascii=False)

            from app.services.case.test_type_router import TestTypeRouter
            test_type = TestTypeRouter.route({
                "method": request_obj.get("method", "POST"),
                "url": request_obj.get("url", ""),
                "steps": steps_list,
                "precondition": pre_steps_str,
            })

            case_content = CaseContent(
                case_task_id=task_id,
                title=compiled.get("title", case_data.get("title", "未命名用例")),
                case_type="api",
                precondition=pre_steps_str,
                steps=steps_str,
                expected=assertions_str,
                priority=compiled.get("priority", case_data.get("priority", "P1")),
                tags=",".join(compiled.get("tags", case_data.get("tags", []))),
                case_status="draft",
                source_type="ai",
                test_type=test_type,
                user_id=user_id,
                created_by=user_id,
                version=1,
            )
            db.add(case_content)
            db.flush()
            return case_content.id

        except Exception as e:
            log.warning(f"CaseSetStore | 保存单条case失败: {e}")
            return None
