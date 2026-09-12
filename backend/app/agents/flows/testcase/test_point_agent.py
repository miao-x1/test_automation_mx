"""
TestPointAgent - 测试点分析Agent（消息驱动）

职责：根据需求解析结果（业务模块、功能点、业务流程、测试范围），
      调用 LLM 分析生成全面的测试点列表。

输入：TestPointMessage（携带 business_module / function_points / business_flow / test_scope）
输出：TestCaseMessage（携带 test_points 列表）

支持5种测试类型：
    - functional: 正常功能流程测试
    - error: 异常流程、错误处理测试
    - boundary: 边界值、极限值测试
    - permission: 权限验证、角色控制测试
    - data_validation: 数据校验、格式验证测试

使用 Prompt：app.prompts.testcase.test_point_prompt.TestPointPrompt
"""
import json
import time
import logging
import traceback
from typing import Any, Dict, List

from autogen_core import message_handler, MessageContext, DefaultTopicId, default_subscription

from app.runtime.base_agent import BaseRoutedAgent
from app.agents.messages import FlowMessage
from app.agents.flows.testcase.messages import TestPointMessage, TestCaseMessage
from app.prompts.testcase.test_point_prompt import TestPointPrompt

logger = logging.getLogger(__name__)


@default_subscription
class TestPointAgent(BaseRoutedAgent):
    """测试点分析Agent - 从需求解析结果中分析测试点

    接收 TestPointMessage，利用 TestPointPrompt 调用 LLM 生成测试点，
    覆盖功能/异常/边界/权限/数据校验5种类型，发布 TestCaseMessage 给用例生成Agent。

    流程：
        TestPointMessage → LLM分析测试点 → 过滤校验 → TestCaseMessage
    """

    # 5种测试类型（用于校验LLM输出）
    SUPPORTED_TEST_TYPES: List[str] = [
        "functional",
        "error",
        "boundary",
        "permission",
        "data_validation",
    ]

    def __init__(self) -> None:
        super().__init__(
            description="测试点分析Agent，根据需求解析结果分析生成测试点列表",
            display_name="TestPointAgent",
            capabilities=["test_point_analysis", "testcase_flow"],
        )

    async def execute(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """GraphFlow 入口：构造 TestPointMessage 并处理"""
        msg = TestPointMessage(
            task_id=payload.get("task_id", ""),
            session_key=payload.get("session_key", "default"),
            business_module=payload.get("business_module", ""),
            function_points=payload.get("function_points", []),
            business_flow=payload.get("business_flow", []),
            test_scope=payload.get("test_scope", {}),
            requirement_id=payload.get("requirement_id"),
        )
        await self.handle_test_point(msg, ctx)
        return {"status": "success", "step": "test_point", "task_id": msg.task_id}

    @message_handler
    async def handle_test_point(self, message: TestPointMessage, ctx: MessageContext) -> None:
        """处理测试点消息，调用LLM生成测试点列表"""
        start = time.time()
        logger.info(f"[TestPointAgent] 收到测试点消息: task={message.task_id}")

        try:
            # 发送开始事件给 CollectorAgent
            await self.emit_start(
                task_id=message.task_id,
                step="test_point",
                message=f"{self._display_name} 开始分析测试点",
                session_key=message.session_key,
            )

            # 1. 构造 LLM 输入（使用 TestPointPrompt）
            from app.knowledge.testing_expert import expert_prompt_for

            user_prompt = TestPointPrompt.build(
                business_module=message.business_module,
                function_points=message.function_points,
                business_flow=message.business_flow,
                test_scope=message.test_scope,
                expert_context=expert_prompt_for(f"{message.business_module} {message.function_points}"),
            )

            # 2. 调用 LLM 生成测试点
            raw_result = await self.call_llm(
                system_prompt=TestPointPrompt.SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.4,
                task_id=message.task_id,
                step="test_point",
                session_key=message.session_key,
            )

            # 3. 解析 LLM 返回的 JSON（容错处理）
            test_points = self._parse_test_points(raw_result)

            # 4. 校验和过滤测试点
            test_points = self._validate_test_points(test_points)

            # 5. 构造输出
            output = {
                "test_points": test_points,
                "point_count": len(test_points),
                "business_module": message.business_module,
                "type_coverage": self._get_type_coverage(test_points),
            }

            duration = time.time() - start

            # 6. 保存结果到数据库
            self._save_result(message, output, duration, "success")

            # 发送结束事件给 CollectorAgent
            await self.emit_end(
                task_id=message.task_id,
                step="test_point",
                duration=duration,
                output=output,
                session_key=message.session_key,
            )

            # 7. 发布 TestCaseMessage 给用例生成Agent
            testcase_msg = TestCaseMessage(
                task_id=message.task_id,
                session_key=message.session_key,
                user_id=message.user_id,
                test_points=test_points,
                business_module=message.business_module,
                requirement_id=message.requirement_id,
                rag_context={},  # 初始为空，由生成Agent按需检索
            )
            await self.publish_message(testcase_msg, DefaultTopicId())

            logger.info(
                f"[TestPointAgent] 测试点分析完成，发布TestCaseMessage: "
                f"task={message.task_id}, 测试点数={len(test_points)}"
            )

        except Exception as e:
            duration = time.time() - start
            logger.error(f"[TestPointAgent] 分析失败: {e}", exc_info=True)
            await self.emit_error(
                task_id=message.task_id,
                step="test_point",
                error=str(e),
                traceback_str=traceback.format_exc(),
                session_key=message.session_key,
            )
            self._save_result(message, {"error": str(e)}, duration, "error", str(e))

    # ------------------------------------------------------------------ #
    #  JSON 解析与校验（容错处理）                                         #
    # ------------------------------------------------------------------ #

    def _parse_test_points(self, raw_response: str) -> List[Dict[str, Any]]:
        """解析 LLM 返回的测试点列表 JSON（容错处理）

        尝试多种方式解析：
        1. 直接 json.loads
        2. 从 markdown 代码块中提取
        3. 找到第一个 [ 和最后一个 ]
        """
        if not raw_response:
            return []

        text = raw_response.strip()

        # 方式1：直接解析
        try:
            result = json.loads(text)
            if isinstance(result, list):
                return result
            if isinstance(result, dict) and "test_points" in result:
                return result["test_points"]
        except json.JSONDecodeError:
            pass

        # 方式2：从 markdown 代码块中提取
        import re
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            try:
                result = json.loads(match.group(1))
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass

        # 方式3：找到第一个 [ 和最后一个 ]
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

        logger.warning("[TestPointAgent] JSON解析失败，返回空列表")
        return []

    def _validate_test_points(self, test_points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """校验和过滤测试点列表

        - 确保每个测试点有 name 和 type 字段
        - 归一化测试类型
        - 补充默认优先级
        """
        validated = []
        for point in test_points:
            if not isinstance(point, dict):
                continue
            name = point.get("name", "").strip()
            if not name:
                continue

            # 归一化测试类型
            point_type = point.get("type", "functional").lower()
            if point_type not in self.SUPPORTED_TEST_TYPES:
                point_type = "functional"

            # 补充默认优先级
            priority = point.get("priority", "P1").upper()
            if priority not in ("P0", "P1", "P2", "P3"):
                priority = "P1"

            validated.append({
                "name": name,
                "type": point_type,
                "priority": priority,
                "scenario": point.get("scenario", ""),
                "description": point.get("description", ""),
                "expected_behavior": point.get("expected_behavior", ""),
            })

        return validated

    def _get_type_coverage(self, test_points: List[Dict[str, Any]]) -> Dict[str, int]:
        """统计各测试类型的测试点数量"""
        coverage: Dict[str, int] = {t: 0 for t in self.SUPPORTED_TEST_TYPES}
        for point in test_points:
            point_type = point.get("type", "functional")
            if point_type in coverage:
                coverage[point_type] += 1
        return coverage

    # ------------------------------------------------------------------ #
    #  数据库保存                                                         #
    # ------------------------------------------------------------------ #

    def _save_result(
        self,
        message: TestPointMessage,
        output: Dict,
        duration: float,
        status: str = "success",
        error: str = None,
    ) -> None:
        """保存结果到数据库（FlowResult 表）"""
        from app.services.context_router.storage_router import get_storage_router

        storage = get_storage_router()
        try:
            storage.mysql_save("FlowResult", {
                "task_id": message.task_id,
                "session_key": message.session_key,
                "user_id": message.user_id,
                "step": "test_point",
                "agent_name": "TestPointAgent",
                "status": status,
                "input_json": message.model_dump_json(),
                "output_json": json.dumps(output, ensure_ascii=False),
                "duration": duration,
                "error_message": error,
                "message_type": "TestPointMessage",
            })
        except Exception as e:
            logger.error(f"[TestPointAgent] DB保存失败: {e}")
