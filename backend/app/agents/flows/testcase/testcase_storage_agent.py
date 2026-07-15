"""
TestCaseStorageAgent - 用例存储Agent（消息驱动）

职责：将审查通过的测试用例及测试点持久化到数据库，
      并生成思维导图数据保存到 mind_map 表。

输入：StorageMessage（含 approved_cases + test_points + review_details）
输出：ResultMessage（通知流程结束）

保存的表：
    1. test_case_point:  测试点
    2. test_case:         测试用例
    3. test_case_review:  用例审查结果
    4. mind_map:          思维导图数据

关系：
    TestRequirement (1) → (N) TestCasePoint (1) → (N) TestCase (1) → (N) TestCaseReview
    TestRequirement (1) → (1) MindMap

使用 StorageRouter 统一写入（禁止直接使用 SessionLocal）
"""
import json
import time
import logging
import traceback
from typing import Any, Dict, List, Optional

from autogen_core import message_handler, MessageContext, DefaultTopicId, default_subscription

from app.runtime.base_agent import BaseRoutedAgent
from app.agents.messages import StorageMessage
from app.runtime.messages import ResultMessage

logger = logging.getLogger(__name__)


@default_subscription
class TestCaseStorageAgent(BaseRoutedAgent):
    """用例存储Agent - 持久化测试用例和审查结果

    接收 StorageMessage（含用例数据），将测试点、用例、审查结果保存到数据库，
    生成思维导图数据，完成后发布 ResultMessage 通知流程结束。

    存储流程：
        保存测试点 → 保存用例 → 保存审查结果 → 生成思维导图 → 发布结果
    """

    def __init__(self) -> None:
        super().__init__(
            description="用例存储Agent，将用例、测试点、审查结果持久化到数据库",
            display_name="TestCaseStorageAgent",
            capabilities=["storage", "testcase_flow"],
        )

    async def execute(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """GraphFlow 入口：构造 StorageMessage 并处理"""
        msg = StorageMessage(
            task_id=payload.get("task_id", ""),
            session_key=payload.get("session_key", "default"),
            data=payload.get("data", {}),
        )
        await self.handle_storage(msg, ctx)
        return {"status": "success", "step": "testcase_storage", "task_id": msg.task_id}

    @message_handler
    async def handle_storage(self, message: StorageMessage, ctx: MessageContext) -> None:
        """处理存储消息，将用例数据保存到数据库"""
        start = time.time()
        logger.info(f"[TestCaseStorageAgent] 收到存储消息: task={message.task_id}")

        try:
            # 发送开始事件给 CollectorAgent
            await self.emit_start(
                task_id=message.task_id,
                step="testcase_storage",
                message=f"{self._display_name} 开始存储用例",
                session_key=message.session_key,
            )

            # 解析存储数据
            data = message.data
            approved_cases: List[Dict[str, Any]] = data.get("approved_cases", [])
            test_points: List[Dict[str, Any]] = data.get("test_points", [])
            review_details: List[Dict[str, Any]] = data.get("review_details", [])
            rejected_cases: List[Dict[str, Any]] = data.get("rejected_cases", [])
            business_module: str = data.get("business_module", "")
            requirement_id: Optional[int] = data.get("requirement_id")

            # 1. 保存测试点到数据库
            point_id_map = self._save_test_points(
                test_points=test_points,
                requirement_id=requirement_id,
                user_id=message.user_id,
                task_id=message.task_id,
            )

            # 2. 保存用例到数据库，并关联测试点
            case_id_map = self._save_test_cases(
                approved_cases=approved_cases,
                point_id_map=point_id_map,
                user_id=message.user_id,
                task_id=message.task_id,
            )

            # 3. 保存审查结果到数据库
            self._save_reviews(
                review_details=review_details,
                case_id_map=case_id_map,
            )

            # 4. 生成并保存思维导图数据
            mind_map_content = self._build_mind_map(
                business_module=business_module,
                test_points=test_points,
                approved_cases=approved_cases,
            )
            self._save_mind_map(
                task_id=message.task_id,
                content=mind_map_content,
            )

            # 5. 构造输出
            output = {
                "saved_points": len(point_id_map),
                "saved_cases": len(case_id_map),
                "saved_reviews": len(review_details),
                "mind_map_generated": bool(mind_map_content),
                "requirement_id": requirement_id,
            }

            duration = time.time() - start

            # 6. 保存结果到 FlowResult 表
            self._save_flow_result(message, output, duration, "success")

            # 发送结束事件给 CollectorAgent
            await self.emit_end(
                task_id=message.task_id,
                step="testcase_storage",
                duration=duration,
                output=output,
                session_key=message.session_key,
            )

            # 7. 发布 ResultMessage 通知流程结束
            result_msg = ResultMessage(
                task_id=message.task_id,
                agent_type=self._agent_type,
                agent_key=self._agent_key,
                status="success",
                data={
                    "step": "testcase_storage",
                    "message": "测试用例生成流程完成",
                    "point_count": len(point_id_map),
                    "case_count": len(case_id_map),
                    "review_count": len(review_details),
                    "mind_map_generated": bool(mind_map_content),
                    "approved_cases": approved_cases,
                },
                duration=duration,
                is_final=True,
            )
            await self.publish_message(result_msg, DefaultTopicId())

            logger.info(
                f"[TestCaseStorageAgent] 用例存储完成，发布ResultMessage: "
                f"task={message.task_id}, 测试点={len(point_id_map)}, "
                f"用例={len(case_id_map)}"
            )

        except Exception as e:
            duration = time.time() - start
            logger.error(f"[TestCaseStorageAgent] 存储失败: {e}", exc_info=True)
            await self.emit_error(
                task_id=message.task_id,
                step="testcase_storage",
                error=str(e),
                traceback_str=traceback.format_exc(),
                session_key=message.session_key,
            )
            self._save_flow_result(message, {"error": str(e)}, duration, "error", str(e))

    # ------------------------------------------------------------------ #
    #  数据库保存方法                                                     #
    # ------------------------------------------------------------------ #

    def _save_test_points(
        self,
        test_points: List[Dict[str, Any]],
        requirement_id: Optional[int],
        user_id: Optional[int],
        task_id: str,
    ) -> Dict[str, int]:
        """保存测试点到 test_case_point 表

        Args:
            test_points: 测试点列表
            requirement_id: 关联的测试需求ID
            user_id: 用户ID
            task_id: 任务ID

        Returns:
            测试点名称 → 数据库ID 的映射（用于关联用例）
        """
        from app.services.context_router.storage_router import get_storage_router

        storage = get_storage_router()
        point_id_map: Dict[str, int] = {}

        if not test_points:
            logger.warning("[TestCaseStorageAgent] 无测试点需要保存")
            return point_id_map

        # 如果没有 requirement_id，尝试创建一个最小化的需求记录
        if not requirement_id:
            requirement_id = self._ensure_requirement(task_id, user_id)

        try:
            for point in test_points:
                name = point.get("name", "")
                if not name:
                    continue

                # 检查是否已存在同名测试点
                existing = storage.mysql_query_one("TestCasePoint", {
                    "requirement_id": requirement_id,
                    "name": name,
                    "is_deleted": False,
                })

                if existing:
                    point_id_map[name] = existing["id"]
                    continue

                # 创建新测试点
                point_id = storage.mysql_save("TestCasePoint", {
                    "requirement_id": requirement_id,
                    "name": name,
                    "description": point.get("description", ""),
                    "priority": point.get("priority", "P1"),
                    "type": point.get("type", "functional"),
                    "scenario": point.get("scenario", ""),
                    "expected_behavior": point.get("expected_behavior", ""),
                    "case_count": 0,
                    "user_id": user_id,
                    "created_by": user_id,
                })

                if point_id:
                    point_id_map[name] = point_id
                else:
                    logger.warning(f"[TestCaseStorageAgent] 测试点保存失败: {name}")

            logger.info(f"[TestCaseStorageAgent] 保存测试点 {len(point_id_map)} 个")
        except Exception as e:
            logger.error(f"[TestCaseStorageAgent] 保存测试点失败: {e}")
            raise

        return point_id_map

    def _save_test_cases(
        self,
        approved_cases: List[Dict[str, Any]],
        point_id_map: Dict[str, int],
        user_id: Optional[int],
        task_id: str,
    ) -> Dict[str, str]:
        """保存测试用例到 test_case 表

        Args:
            approved_cases: 通过审查的用例列表
            point_id_map: 测试点名称 → ID 映射
            user_id: 用户ID
            task_id: 任务ID

        Returns:
            用例名称 → 数据库ID 的映射（用于关联审查结果）
        """
        from app.services.context_router.storage_router import get_storage_router

        storage = get_storage_router()
        case_id_map: Dict[str, int] = {}

        if not approved_cases:
            logger.warning("[TestCaseStorageAgent] 无用例需要保存")
            return case_id_map

        try:
            for case in approved_cases:
                case_name = case.get("case_name", "")
                if not case_name:
                    continue

                # 查找关联的测试点ID
                point_name = case.get("test_point_name", "")
                point_id = point_id_map.get(point_name)

                # 如果找不到关联测试点，使用第一个可用的测试点ID
                if not point_id and point_id_map:
                    point_id = list(point_id_map.values())[0]

                if not point_id:
                    logger.warning(f"[TestCaseStorageAgent] 用例 '{case_name}' 无关联测试点，跳过")
                    continue

                # 序列化步骤和RAG引用
                steps_json = json.dumps(case.get("steps", []), ensure_ascii=False)
                rag_refs_json = json.dumps(case.get("rag_references", []), ensure_ascii=False)

                case_id = storage.mysql_save("TestCase", {
                    "task_id": task_id,
                    "point_id": point_id,
                    "case_name": case_name,
                    "precondition": case.get("precondition", ""),
                    "steps": steps_json,
                    "expected_result": case.get("expected_result", ""),
                    "priority": case.get("priority", "P1"),
                    "type": case.get("type", "functional"),
                    "status": "reviewed",
                    "rag_references": rag_refs_json,
                    "version": 1,
                    "user_id": user_id,
                    "created_by": user_id,
                })

                if case_id:
                    case_id_map[case_name] = case_id
                else:
                    logger.warning(f"[TestCaseStorageAgent] 用例保存失败: {case_name}")

            logger.info(f"[TestCaseStorageAgent] 保存用例 {len(case_id_map)} 条")
        except Exception as e:
            logger.error(f"[TestCaseStorageAgent] 保存用例失败: {e}")
            raise

        return case_id_map

    def _save_reviews(
        self,
        review_details: List[Dict[str, Any]],
        case_id_map: Dict[str, int],
    ) -> None:
        """保存审查结果到 test_case_review 表

        Args:
            review_details: 审查详情列表
            case_id_map: 用例名称 → ID 映射
        """
        from app.services.context_router.storage_router import get_storage_router

        storage = get_storage_router()

        if not review_details or not case_id_map:
            return

        try:
            saved_count = 0
            for detail in review_details:
                case_name = detail.get("case_name", "")
                review_result = detail.get("review_result", {})

                case_id = case_id_map.get(case_name)
                if not case_id:
                    continue

                review_id = storage.mysql_save("TestCaseReview", {
                    "case_id": case_id,
                    "score": review_result.get("score", 0),
                    "review_result": review_result.get("review_result", "need_revision"),
                    "suggestion": json.dumps(
                        review_result.get("suggestions", []),
                        ensure_ascii=False,
                    ),
                    "issues": json.dumps(
                        review_result.get("issues", []),
                        ensure_ascii=False,
                    ),
                    "review_comment": f"自动审查 | 评分: {review_result.get('score', 0)}",
                })

                if review_id:
                    saved_count += 1
                else:
                    logger.warning(f"[TestCaseStorageAgent] 审查结果保存失败: case={case_name}")

            logger.info(f"[TestCaseStorageAgent] 保存审查结果 {saved_count} 条")
        except Exception as e:
            logger.error(f"[TestCaseStorageAgent] 保存审查结果失败: {e}")
            raise

    def _save_mind_map(self, task_id: str, content: Dict[str, Any]) -> None:
        """保存思维导图数据到 mind_map 表

        Args:
            task_id: 任务ID
            content: 思维导图内容（JSON树形结构）
        """
        from app.services.context_router.storage_router import get_storage_router

        storage = get_storage_router()

        if not content:
            return

        try:
            content_json = json.dumps(content, ensure_ascii=False)

            # 检查是否已存在
            existing = storage.mysql_query_one("MindMap", {"task_id": task_id})
            if existing:
                storage.mysql_update("MindMap", existing["id"], {
                    "content": content_json,
                    "version": (existing.get("version") or 0) + 1,
                })
            else:
                storage.mysql_save("MindMap", {
                    "task_id": task_id,
                    "content": content_json,
                    "format": "json",
                    "version": 1,
                })

            logger.info(f"[TestCaseStorageAgent] 思维导图已保存: task={task_id}")
        except Exception as e:
            logger.error(f"[TestCaseStorageAgent] 保存思维导图失败: {e}")

    def _ensure_requirement(self, task_id: str, user_id: Optional[int]) -> int:
        """确保存在测试需求记录，不存在则创建最小化记录

        Args:
            task_id: 任务ID
            user_id: 用户ID

        Returns:
            测试需求ID
        """
        from app.services.context_router.storage_router import get_storage_router

        storage = get_storage_router()

        try:
            # 查找已有需求
            existing = storage.mysql_query_one("TestRequirement", {"task_id": task_id})
            if existing:
                return existing["id"]

            # 创建最小化需求记录
            req_id = storage.mysql_save("TestRequirement", {
                "task_id": task_id,
                "content": f"自动生成需求 (task_id={task_id})",
                "source_type": "text",
                "status": "completed",
                "user_id": user_id,
                "created_by": user_id,
            })

            if req_id:
                logger.info(f"[TestCaseStorageAgent] 创建测试需求记录: id={req_id}")
                return req_id
            else:
                raise RuntimeError("创建测试需求记录失败")
        except Exception as e:
            logger.error(f"[TestCaseStorageAgent] 创建测试需求失败: {e}")
            raise

    # ------------------------------------------------------------------ #
    #  思维导图生成                                                       #
    # ------------------------------------------------------------------ #

    def _build_mind_map(
        self,
        business_module: str,
        test_points: List[Dict[str, Any]],
        approved_cases: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """构建思维导图树形结构

        结构：
            根节点（业务模块）
            ├── 测试类型1（functional）
            │   ├── 测试点1
            │   │   ├── 用例1
            │   │   └── 用例2
            │   └── 测试点2
            ├── 测试类型2（error）
            │   └── ...
            └── ...

        Args:
            business_module: 业务模块名称
            test_points: 测试点列表
            approved_cases: 通过审查的用例列表

        Returns:
            思维导图树形结构（Dict）
        """
        if not test_points and not approved_cases:
            return {}

        # 按测试类型分组测试点
        type_groups: Dict[str, List[Dict[str, Any]]] = {}
        for point in test_points:
            point_type = point.get("type", "functional")
            if point_type not in type_groups:
                type_groups[point_type] = []
            type_groups[point_type].append(point)

        # 构建用例名称映射（按测试点名称分组）
        case_map: Dict[str, List[str]] = {}
        for case in approved_cases:
            point_name = case.get("test_point_name", "")
            case_name = case.get("case_name", "")
            if point_name and case_name:
                if point_name not in case_map:
                    case_map[point_name] = []
                case_map[point_name].append(case_name)

        # 构建树形结构
        children = []
        type_labels = {
            "functional": "功能测试",
            "error": "异常测试",
            "boundary": "边界测试",
            "permission": "权限测试",
            "data_validation": "数据校验",
        }

        for point_type, points in type_groups.items():
            type_label = type_labels.get(point_type, point_type)
            type_node = {
                "name": type_label,
                "type": "category",
                "children": [],
            }
            for point in points:
                point_name = point.get("name", "")
                point_node = {
                    "name": point_name,
                    "type": "point",
                    "priority": point.get("priority", ""),
                    "children": [],
                }
                # 添加关联用例
                for case_name in case_map.get(point_name, []):
                    point_node["children"].append({
                        "name": case_name,
                        "type": "case",
                    })
                type_node["children"].append(point_node)
            children.append(type_node)

        return {
            "name": business_module or "测试用例",
            "type": "root",
            "children": children,
        }

    # ------------------------------------------------------------------ #
    #  FlowResult 保存                                                    #
    # ------------------------------------------------------------------ #

    def _save_flow_result(
        self,
        message: StorageMessage,
        output: Dict,
        duration: float,
        status: str = "success",
        error: str = None,
    ) -> None:
        """保存结果到 FlowResult 表"""
        from app.services.context_router.storage_router import get_storage_router

        storage = get_storage_router()
        try:
            storage.mysql_save("FlowResult", {
                "task_id": message.task_id,
                "session_key": message.session_key,
                "user_id": message.user_id,
                "step": "testcase_storage",
                "agent_name": "TestCaseStorageAgent",
                "status": status,
                "input_json": message.model_dump_json(),
                "output_json": json.dumps(output, ensure_ascii=False),
                "duration": duration,
                "error_message": error,
                "message_type": "StorageMessage",
            })
        except Exception as e:
            logger.error(f"[TestCaseStorageAgent] DB保存失败: {e}")
