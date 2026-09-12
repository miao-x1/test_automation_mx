"""
TestCaseGeneratorAgent - 用例生成Agent（消息驱动）

职责：根据测试点 + RAG上下文，调用 LLM 生成结构化的标准测试用例。

输入：TestCaseMessage（含测试点列表 + RAG上下文）
输出：TestCaseReviewMessage（含生成的用例列表）

注意：此类与 app.agent.testcase.testcase_generator_agent.TestCaseGeneratorAgent 同名但不同路径，
      本类基于 BaseRoutedAgent（AutoGen Core 消息驱动），用于测试用例生成流程。

RAG集成：
    1. 从测试点提取关键词（name + scenario + description + business_module）
    2. 通过 send_request 调用 rag_agent 检索
    3. 过滤低相似度结果
    4. 将过滤后的结果作为上下文发送给 LLM
    5. 生成结构化测试用例

使用 Prompt：app.prompts.testcase.testcase_generate_prompt.TestCaseGeneratePrompt
"""
import json
import time
import logging
import traceback
from typing import Any, Dict, List, Optional

from autogen_core import message_handler, MessageContext, DefaultTopicId, default_subscription

from app.runtime.base_agent import BaseRoutedAgent
from app.agents.flows.testcase.messages import TestCaseMessage, TestCaseReviewMessage
from app.prompts.testcase.testcase_generate_prompt import TestCaseGeneratePrompt

logger = logging.getLogger(__name__)


@default_subscription
class TestCaseGeneratorAgent(BaseRoutedAgent):
    """用例生成Agent - RAG上下文增强版（消息驱动）

    接收 TestCaseMessage（含测试点 + RAG上下文），
    为每个测试点调用 LLM 生成结构化用例，发布 TestCaseReviewMessage。

    RAG集成流程：检索 → TopK过滤 → 生成
    """

    # RAG 配置
    RAG_TOP_K: int = 10           # 每类检索最大数量
    RAG_MIN_SCORE: float = 0.3    # 最低相似度阈值
    RAG_MAX_CASES: int = 5        # 发送给LLM的历史用例最大数
    RAG_MAX_ELEMENTS: int = 10    # 发送给LLM的元素最大数

    def __init__(self) -> None:
        super().__init__(
            description="用例生成Agent（RAG上下文增强），根据测试点+RAG上下文生成结构化用例",
            display_name="TestCaseGeneratorAgent",
            capabilities=["case_generate", "rag", "testcase_flow"],
        )

    async def execute(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """GraphFlow 入口：构造 TestCaseMessage 并处理"""
        msg = TestCaseMessage(
            task_id=payload.get("task_id", ""),
            session_key=payload.get("session_key", "default"),
            test_points=payload.get("test_points", []),
            rag_context=payload.get("rag_context", {}),
            business_module=payload.get("business_module", ""),
            requirement_id=payload.get("requirement_id"),
        )
        await self.handle_testcase_generate(msg, ctx)
        return {"status": "success", "step": "testcase_generate", "task_id": msg.task_id}

    @message_handler
    async def handle_testcase_generate(self, message: TestCaseMessage, ctx: MessageContext) -> None:
        """处理用例生成消息，为每个测试点生成结构化用例"""
        start = time.time()
        logger.info(f"[TestCaseGeneratorAgent] 收到用例生成消息: task={message.task_id}")

        try:
            # 发送开始事件给 CollectorAgent
            await self.emit_start(
                task_id=message.task_id,
                step="testcase_generate",
                message=f"{self._display_name} 开始生成用例",
                session_key=message.session_key,
            )

            # 1. 逐个测试点生成用例（含RAG检索）
            test_cases: List[Dict[str, Any]] = []
            rag_used = False

            for point in message.test_points:
                # 1.1 RAG检索：从测试点提取关键词检索
                rag_context = message.rag_context
                if not rag_context and message.business_module:
                    # 消息中未携带RAG上下文时，自动检索
                    rag_context = await self._retrieve_rag(point, message.business_module)
                    if rag_context:
                        rag_used = True

                # 1.2 过滤RAG结果
                filtered_context = self._filter_rag_context(rag_context) if rag_context else None

                # 1.3 调用LLM生成用例
                case = await self._generate_single_case(
                    test_point=point,
                    rag_context=filtered_context,
                    task_id=message.task_id,
                    session_key=message.session_key,
                )

                if case:
                    # 补充RAG引用信息
                    case["rag_references"] = self._extract_rag_refs(filtered_context)
                    # 关联测试点信息
                    case["test_point_name"] = point.get("name", "")
                    case["test_point_type"] = point.get("type", "")
                    test_cases.append(case)

            # 2. 构造输出
            output = {
                "test_cases": test_cases,
                "case_count": len(test_cases),
                "rag_used": rag_used or bool(message.rag_context),
                "business_module": message.business_module,
            }

            duration = time.time() - start

            # 3. 保存结果到数据库
            self._save_result(message, output, duration, "success")

            # 发送结束事件给 CollectorAgent
            await self.emit_end(
                task_id=message.task_id,
                step="testcase_generate",
                duration=duration,
                output=output,
                session_key=message.session_key,
            )

            # 4. 发布 TestCaseReviewMessage 给用例审查Agent
            review_msg = TestCaseReviewMessage(
                task_id=message.task_id,
                session_key=message.session_key,
                user_id=message.user_id,
                test_cases=test_cases,
                test_points=message.test_points,
                case_count=len(test_cases),
                coverage_notes=f"共生成 {len(test_cases)} 条用例，RAG增强: {output['rag_used']}",
                rag_used=output["rag_used"],
                business_module=message.business_module,
                requirement_id=message.requirement_id,
            )
            await self.publish_message(review_msg, DefaultTopicId())

            logger.info(
                f"[TestCaseGeneratorAgent] 用例生成完成，发布TestCaseReviewMessage: "
                f"task={message.task_id}, 用例数={len(test_cases)}"
            )

        except Exception as e:
            duration = time.time() - start
            logger.error(f"[TestCaseGeneratorAgent] 生成失败: {e}", exc_info=True)
            await self.emit_error(
                task_id=message.task_id,
                step="testcase_generate",
                error=str(e),
                traceback_str=traceback.format_exc(),
                session_key=message.session_key,
            )
            self._save_result(message, {"error": str(e)}, duration, "error", str(e))

    # ------------------------------------------------------------------ #
    #  RAG 检索集成                                                       #
    # ------------------------------------------------------------------ #

    async def _retrieve_rag(
        self,
        test_point: Dict[str, Any],
        business_module: str = "",
    ) -> Optional[Dict[str, Any]]:
        """RAG检索集成：通过 send_request 调用 rag_agent 检索

        流程：提取关键词 → send_request → 返回检索结果

        Args:
            test_point: 测试点信息
            business_module: 业务模块名称

        Returns:
            RAG检索结果（含 cases/elements/scripts），失败时返回 None
        """
        try:
            # 构建查询文本：从测试点提取关键词
            query_parts = [
                test_point.get("name", ""),
                business_module,
                test_point.get("scenario", ""),
                test_point.get("description", ""),
            ]
            query = " ".join(p for p in query_parts if p).strip()

            if not query:
                return None

            # 通过 send_request 调用 rag_agent
            response = await self.send_request(
                target_agent_type="rag_agent",
                action="retrieve",
                payload={
                    "query": query,
                    "top_k": self.RAG_TOP_K,
                },
            )

            if response.status != "success":
                logger.warning(f"[TestCaseGeneratorAgent] RAG检索失败: {response.error}")
                return None

            rag_data = response.data
            logger.info(
                f"[TestCaseGeneratorAgent] RAG检索完成 | 查询: {query[:50]} | "
                f"用例: {len(rag_data.get('cases', []))} | "
                f"元素: {len(rag_data.get('elements', []))}"
            )
            return rag_data

        except Exception as e:
            logger.warning(f"[TestCaseGeneratorAgent] RAG检索异常: {e}")
            return None

    def _filter_rag_context(self, rag_context: Dict[str, Any]) -> Dict[str, Any]:
        """过滤RAG检索结果

        - 去除相似度低于阈值的结果
        - 限制每类结果数量（TopK过滤）

        Args:
            rag_context: 原始RAG检索结果

        Returns:
            过滤后的RAG上下文
        """
        if not rag_context:
            return {}

        # 过滤历史用例
        filtered_cases = []
        for case in rag_context.get("cases", []):
            score = case.get("score", 0)
            if score >= self.RAG_MIN_SCORE:
                filtered_cases.append(case)
        filtered_cases = filtered_cases[:self.RAG_MAX_CASES]

        # 过滤页面元素
        filtered_elements = []
        for elem in rag_context.get("elements", []):
            score = elem.get("score", 0)
            if score >= self.RAG_MIN_SCORE:
                filtered_elements.append(elem)
        filtered_elements = filtered_elements[:self.RAG_MAX_ELEMENTS]

        # 脚本参考（取前3个）
        filtered_scripts = rag_context.get("scripts", [])[:3]

        return {
            "cases": filtered_cases,
            "elements": filtered_elements,
            "scripts": filtered_scripts,
        }

    def _extract_rag_refs(self, rag_context: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """从RAG上下文中提取引用信息（id + case_name + score）"""
        if not rag_context:
            return []
        refs = []
        for c in rag_context.get("cases", [])[:3]:
            refs.append({
                "id": c.get("id"),
                "case_name": c.get("case_name", c.get("title", "")),
                "score": c.get("score", 0),
            })
        return refs

    # ------------------------------------------------------------------ #
    #  LLM 调用与用例生成                                                 #
    # ------------------------------------------------------------------ #

    async def _generate_single_case(
        self,
        test_point: Dict[str, Any],
        rag_context: Optional[Dict[str, Any]],
        task_id: str,
        session_key: str,
    ) -> Optional[Dict[str, Any]]:
        """为单个测试点生成结构化用例

        Args:
            test_point: 测试点信息
            rag_context: 已过滤的RAG上下文
            task_id: 任务ID（用于事件追踪）
            session_key: 会话标识

        Returns:
            生成的用例字典，失败时返回 None
        """
        point_name = test_point.get("name", "")
        logger.info(f"[TestCaseGeneratorAgent] 开始生成用例 | 测试点: {point_name}")

        # 构建提示词
        from app.knowledge.testing_expert import expert_prompt_for

        user_prompt = TestCaseGeneratePrompt.build(
            test_point=test_point,
            rag_context=rag_context,
            expert_context=expert_prompt_for(
                f"{test_point.get('name', '')} {test_point.get('scenario', '')}"
            ),
        )

        # 调用 LLM 生成用例
        raw_response = await self.call_llm(
            system_prompt=TestCaseGeneratePrompt.SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.4,
            task_id=task_id,
            step="testcase_generate",
            session_key=session_key,
        )

        # 解析 JSON 响应（容错处理）
        case = self._parse_json_response(raw_response)

        if not case:
            logger.warning(f"[TestCaseGeneratorAgent] 用例解析失败，跳过测试点: {point_name}")
            return None

        logger.info(
            f"[TestCaseGeneratorAgent] 用例生成完成 | 用例: {case.get('case_name', '')} | "
            f"步骤数: {len(case.get('steps', []))}"
        )
        return case

    # ------------------------------------------------------------------ #
    #  JSON 解析（容错处理）                                              #
    # ------------------------------------------------------------------ #

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

        logger.warning("[TestCaseGeneratorAgent] JSON解析失败")
        return None

    # ------------------------------------------------------------------ #
    #  数据库保存                                                         #
    # ------------------------------------------------------------------ #

    def _save_result(
        self,
        message: TestCaseMessage,
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
                "step": "testcase_generate",
                "agent_name": "TestCaseGeneratorAgent",
                "status": status,
                "input_json": message.model_dump_json(),
                "output_json": json.dumps(output, ensure_ascii=False),
                "duration": duration,
                "error_message": error,
                "message_type": "TestCaseMessage",
            })
        except Exception as e:
            logger.error(f"[TestCaseGeneratorAgent] DB保存失败: {e}")
