"""
TestCaseReviewAgent - 用例审查Agent（消息驱动）

职责：审核测试用例质量，检查步骤完整性、预期明确性、异常覆盖度，
      根据评分决定用例是否通过审查。

输入：TestCaseReviewMessage（含生成的用例列表）
输出：StorageMessage（保存入库的用例）

审查维度：
    1. 步骤完整性：步骤是否覆盖完整测试流程
    2. 预期明确性：每个步骤的预期结果是否可验证
    3. 异常覆盖：是否考虑了异常输入和错误处理
    4. 前置条件：数据准备和环境要求是否充分
    5. 可执行性：步骤是否具体、可操作
    6. 优先级合理性：优先级是否与测试点一致

使用 Prompt：app.prompts.testcase.review_prompt.ReviewPrompt
"""
import json
import time
import logging
import traceback
from typing import Any, Dict, List, Optional

from autogen_core import message_handler, MessageContext, DefaultTopicId, default_subscription

from app.runtime.base_agent import BaseRoutedAgent
from app.agents.messages import StorageMessage
from app.agents.flows.testcase.messages import TestCaseReviewMessage
from app.prompts.testcase.review_prompt import ReviewPrompt

logger = logging.getLogger(__name__)


@default_subscription
class TestCaseReviewAgent(BaseRoutedAgent):
    """用例审查Agent - 审核测试用例质量

    接收 TestCaseReviewMessage（含用例列表），逐个用例调用 LLM 审查质量，
    将通过审查的用例放入 StorageMessage 发布给存储Agent。

    审查流程：逐用例评分 → 过滤不合格 → 发布存储消息
    """

    # 审查通过分数阈值
    PASS_SCORE: int = 80
    # 需修改分数阈值
    NEED_REVISION_SCORE: int = 50

    def __init__(self) -> None:
        super().__init__(
            description="用例审查Agent，审核用例步骤完整性、预期明确性、异常覆盖",
            display_name="TestCaseReviewAgent",
            capabilities=["test_case_review", "testcase_flow"],
        )

    async def execute(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """GraphFlow 入口：构造 TestCaseReviewMessage 并处理"""
        msg = TestCaseReviewMessage(
            task_id=payload.get("task_id", ""),
            session_key=payload.get("session_key", "default"),
            test_cases=payload.get("test_cases", []),
            test_points=payload.get("test_points", []),
            case_count=len(payload.get("test_cases", [])),
            coverage_notes=payload.get("coverage_notes", ""),
            rag_used=payload.get("rag_used", False),
            business_module=payload.get("business_module", ""),
            requirement_id=payload.get("requirement_id"),
        )
        await self.handle_review(msg, ctx)
        return {"status": "success", "step": "testcase_review", "task_id": msg.task_id}

    @message_handler
    async def handle_review(self, message: TestCaseReviewMessage, ctx: MessageContext) -> None:
        """处理用例审查消息，逐个用例审核质量"""
        start = time.time()
        logger.info(f"[TestCaseReviewAgent] 收到审查消息: task={message.task_id}, 用例数={message.case_count}")

        try:
            # 发送开始事件给 CollectorAgent
            await self.emit_start(
                task_id=message.task_id,
                step="testcase_review",
                message=f"{self._display_name} 开始审查用例",
                session_key=message.session_key,
            )

            # 1. 构建测试点映射（便于查找关联的测试点信息）
            point_map = self._build_point_map(message.test_points)

            # 2. 逐个用例审查
            approved_cases: List[Dict[str, Any]] = []
            rejected_cases: List[Dict[str, Any]] = []
            review_details: List[Dict[str, Any]] = []

            for case in message.test_cases:
                # 查找关联的测试点信息
                test_point_info = point_map.get(case.get("test_point_name", ""), {})

                # 调用 LLM 审查单个用例
                review_result = await self._review_single_case(
                    case=case,
                    test_point_info=test_point_info,
                    task_id=message.task_id,
                    session_key=message.session_key,
                )

                review_details.append({
                    "case_name": case.get("case_name", ""),
                    "review_result": review_result,
                })

                # 根据评分决定通过/拒绝
                score = review_result.get("score", 0)
                if score >= self.PASS_SCORE:
                    # 通过的用例补充审查信息
                    case["review_score"] = score
                    case["review_result"] = review_result.get("review_result", "pass")
                    case["review_suggestions"] = review_result.get("suggestions", [])
                    approved_cases.append(case)
                else:
                    case["review_score"] = score
                    case["review_result"] = review_result.get("review_result", "reject")
                    case["review_issues"] = review_result.get("issues", [])
                    rejected_cases.append(case)

            # 3. 构造输出
            output = {
                "approved_cases": approved_cases,
                "rejected_cases": rejected_cases,
                "review_details": review_details,
                "approved_count": len(approved_cases),
                "rejected_count": len(rejected_cases),
                "original_count": message.case_count,
                "avg_score": self._calc_avg_score(review_details),
            }

            duration = time.time() - start

            # 4. 保存结果到数据库
            self._save_result(message, output, duration, "success")

            # 发送结束事件给 CollectorAgent
            await self.emit_end(
                task_id=message.task_id,
                step="testcase_review",
                duration=duration,
                output=output,
                session_key=message.session_key,
            )

            # 5. 发布 StorageMessage 给存储Agent（只存储通过的用例）
            storage_msg = StorageMessage(
                task_id=message.task_id,
                session_key=message.session_key,
                user_id=message.user_id,
                step="testcase_storage",
                storage_type="mysql",
                operation="save",
                table="test_case",
                data={
                    "approved_cases": approved_cases,
                    "test_points": message.test_points,
                    "business_module": message.business_module,
                    "requirement_id": message.requirement_id,
                    "review_details": review_details,
                    "rejected_cases": rejected_cases,
                },
            )
            await self.publish_message(storage_msg, DefaultTopicId())

            logger.info(
                f"[TestCaseReviewAgent] 用例审查完成，发布StorageMessage: "
                f"task={message.task_id}, 通过={len(approved_cases)}, 拒绝={len(rejected_cases)}"
            )

        except Exception as e:
            duration = time.time() - start
            logger.error(f"[TestCaseReviewAgent] 审查失败: {e}", exc_info=True)
            await self.emit_error(
                task_id=message.task_id,
                step="testcase_review",
                error=str(e),
                traceback_str=traceback.format_exc(),
                session_key=message.session_key,
            )
            self._save_result(message, {"error": str(e)}, duration, "error", str(e))

    # ------------------------------------------------------------------ #
    #  LLM 调用与用例审查                                                 #
    # ------------------------------------------------------------------ #

    async def _review_single_case(
        self,
        case: Dict[str, Any],
        test_point_info: Dict[str, Any],
        task_id: str,
        session_key: str,
    ) -> Dict[str, Any]:
        """审查单个测试用例

        Args:
            case: 待审查的用例
            test_point_info: 关联的测试点信息
            task_id: 任务ID
            session_key: 会话标识

        Returns:
            审查结果（score/review_result/suggestions/issues）
        """
        case_name = case.get("case_name", "")
        logger.info(f"[TestCaseReviewAgent] 审查用例: {case_name}")

        # 构建审查提示词
        user_prompt = ReviewPrompt.build(
            case_name=case_name,
            precondition=case.get("precondition", ""),
            steps=case.get("steps", []),
            expected_result=case.get("expected_result", ""),
            priority=case.get("priority", "P1"),
            case_type=case.get("type", "functional"),
            test_point_info=test_point_info,
        )

        # 调用 LLM 审查
        raw_response = await self.call_llm(
            system_prompt=ReviewPrompt.SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.3,
            task_id=task_id,
            step="testcase_review",
            session_key=session_key,
        )

        # 解析审查结果（容错处理）
        result = self._parse_json_response(raw_response)

        if not result:
            # 解析失败，默认需修改
            logger.warning(f"[TestCaseReviewAgent] 审查结果解析失败，默认标记为需修改: {case_name}")
            return {
                "score": 60,
                "review_result": "need_revision",
                "suggestions": ["审查结果解析失败，建议人工复核"],
                "issues": [],
            }

        return result

    # ------------------------------------------------------------------ #
    #  辅助方法                                                           #
    # ------------------------------------------------------------------ #

    def _build_point_map(self, test_points: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """构建测试点名称到测试点信息的映射"""
        point_map: Dict[str, Dict[str, Any]] = {}
        for point in test_points:
            name = point.get("name", "")
            if name:
                point_map[name] = point
        return point_map

    def _calc_avg_score(self, review_details: List[Dict[str, Any]]) -> float:
        """计算所有用例的平均评分"""
        if not review_details:
            return 0.0
        total = sum(
            r.get("review_result", {}).get("score", 0)
            for r in review_details
        )
        return round(total / len(review_details), 1)

    def _parse_json_response(self, response: str) -> Optional[Dict[str, Any]]:
        """解析 LLM 返回的 JSON 响应（容错处理）

        尝试多种方式解析：
        1. 去除 markdown 代码块后直接解析
        2. 从 markdown 代码块中提取
        3. 找到第一个 { 和最后一个 }
        """
        if not response:
            return None

        text = response.strip()

        # 去除 markdown 代码块标记
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        # 方式1：直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 方式2：从 markdown 代码块中提取
        import re
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # 方式3：找到第一个 { 和最后一个 }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

        logger.warning("[TestCaseReviewAgent] JSON解析失败")
        return None

    # ------------------------------------------------------------------ #
    #  数据库保存                                                         #
    # ------------------------------------------------------------------ #

    def _save_result(
        self,
        message: TestCaseReviewMessage,
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
                "step": "testcase_review",
                "agent_name": "TestCaseReviewAgent",
                "status": status,
                "input_json": message.model_dump_json(),
                "output_json": json.dumps(output, ensure_ascii=False),
                "duration": duration,
                "error_message": error,
                "message_type": "TestCaseReviewMessage",
            })
        except Exception as e:
            logger.error(f"[TestCaseReviewAgent] DB保存失败: {e}")
