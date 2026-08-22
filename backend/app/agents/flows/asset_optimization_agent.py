"""
AssetOptimizationAgent - 测试资产优化 Agent

职责:
  接收 AssetReuseAgent 的复用决策, 用 LLM 基于已有资产优化测试方案,
  输出最终测试方案 (复用清单 + 补充清单 + 执行顺序)。

输入 (AgentRequest.payload):
  requirement:     需求描述 (必填)
  reuse_decision:  复用决策 (来自 AssetReuseAgent, 必填)
  search_results:  搜索结果 (来自 AssetSearchAgent, 可选, 用于上下文)

输出 (AgentResponse.data):
  status:           success / error
  requirement:      原始需求
  optimized_plan:   优化后的测试方案
    - reuse_assets:   直接复用资产清单
    - adapt_assets:   需适配资产清单 (含适配建议)
    - new_assets:     需新建资产清单 (含建议类型)
    - execution_order: 执行顺序
  quality_score:    方案质量评分 0-100
  summary:          方案摘要
"""
import json
import logging
import time
from typing import Any, Dict, List, Optional

from autogen_core import message_handler, MessageContext, default_subscription

from app.runtime.base_agent import BaseRoutedAgent
from app.runtime.messages import AgentRequest, AgentResponse

logger = logging.getLogger(__name__)


@default_subscription
class AssetOptimizationAgent(BaseRoutedAgent):
    """测试资产优化 Agent

    基于复用决策, 用 LLM 生成优化的测试方案。

    使用方式:
      直接调用:  await agent.execute({"requirement": "...", "reuse_decision": {...}}, ctx)
      消息驱动:  await self.send_request("asset_optimization_agent", "optimize", payload)
    """

    SYSTEM_PROMPT = """你是一位测试方案优化专家。

任务: 基于已有测试资产的复用决策, 生成优化的测试方案。

输出要求 (JSON 格式):
{
  "reuse_assets": [
    {"asset_id": <int>, "name": "<str>", "reason": "<复用理由>"}
  ],
  "adapt_assets": [
    {
      "asset_id": <int>,
      "name": "<str>",
      "adaptation": "<适配建议>",
      "reason": "<需适配理由>"
    }
  ],
  "new_assets": [
    {
      "asset_type": "<api_endpoint|test_case|script|test_data|...>",
      "name": "<建议资产名>",
      "description": "<资产描述>",
      "priority": "<high|medium|low>"
    }
  ],
  "execution_order": [
    "<执行步骤1>",
    "<执行步骤2>"
  ],
  "quality_score": <0-100>,
  "summary": "<方案摘要>"
}

优化原则:
1. 最大化复用已有资产, 减少重复劳动
2. 适配资产时, 明确需要修改的部分
3. 新建资产仅补充缺失部分, 避免冗余
4. 执行顺序考虑依赖关系 (接口 → 用例 → 脚本 → 数据)
5. quality_score 反映方案完整性与复用率"""

    def __init__(self) -> None:
        super().__init__(
            description="测试资产优化Agent, 用 LLM 生成优化测试方案",
            display_name="AssetOptimizationAgent",
            capabilities=["asset_optimization", "plan_generation"],
        )

    # ------------------------------------------------------------------
    # GraphFlow 入口
    # ------------------------------------------------------------------

    async def execute(
        self, payload: Dict[str, Any], ctx: MessageContext
    ) -> Dict[str, Any]:
        """GraphFlow 入口: 生成优化方案"""
        return await self._do_optimize(payload)

    # ------------------------------------------------------------------
    # 消息处理器: optimize
    # ------------------------------------------------------------------

    @message_handler
    async def handle_optimize(
        self, message: AgentRequest, ctx: MessageContext
    ) -> AgentResponse:
        """处理 optimize 请求

        Args (message.payload):
            requirement:     需求描述 (必填)
            reuse_decision:  复用决策 (来自 AssetReuseAgent, 必填)
            search_results:  搜索结果 (可选, 用于上下文)
        """
        start = time.time()
        request_id = message.request_id
        logger.info(
            f"[AssetOptimizationAgent] 收到优化请求 request_id={request_id}"
        )

        try:
            result = await self._do_optimize(message.payload)
            duration = time.time() - start

            if result.get("status") == "error":
                return AgentResponse(
                    request_id=request_id,
                    sender_type=self._agent_type,
                    status="error",
                    error=result.get("message", "优化失败"),
                    duration=duration,
                )

            return AgentResponse(
                request_id=request_id,
                sender_type=self._agent_type,
                status="success",
                data=result,
                duration=duration,
            )
        except Exception as e:
            duration = time.time() - start
            logger.error(f"[AssetOptimizationAgent] 优化失败: {e}", exc_info=True)
            return AgentResponse(
                request_id=request_id,
                sender_type=self._agent_type,
                status="error",
                error=str(e),
                duration=duration,
            )

    # ------------------------------------------------------------------
    # 核心优化逻辑
    # ------------------------------------------------------------------

    async def _do_optimize(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """执行方案优化

        流程:
          1. 解析需求与复用决策
          2. 用 LLM 生成优化方案
          3. 返回结构化结果
        """
        requirement: str = payload.get("requirement", "").strip()
        reuse_decision: Dict = payload.get("reuse_decision", {})
        search_results: List[Dict] = payload.get("search_results", [])

        if not requirement:
            return {
                "status": "error",
                "message": "requirement 不能为空",
            }
        if not reuse_decision:
            return {
                "status": "error",
                "message": "reuse_decision 不能为空 (需先调用 AssetReuseAgent)",
            }

        # 构建 LLM 输入
        user_prompt = self._build_user_prompt(
            requirement, reuse_decision, search_results
        )

        # 调用 LLM
        try:
            response = await self.call_llm(
                system_prompt=self.SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.4,
                max_tokens=4096,
            )

            # 解析 LLM 返回
            optimized_plan = self._parse_llm_response(response)
            if not optimized_plan:
                logger.warning(
                    "[AssetOptimizationAgent] LLM 返回解析失败, 使用降级方案"
                )
                optimized_plan = self._fallback_plan(reuse_decision)

            return {
                "status": "success",
                "requirement": requirement,
                "optimized_plan": optimized_plan,
                "quality_score": optimized_plan.get("quality_score", 70),
                "summary": optimized_plan.get(
                    "summary", "基于复用决策生成的测试方案"
                ),
            }

        except Exception as e:
            logger.error(f"[AssetOptimizationAgent] LLM 调用失败: {e}", exc_info=True)
            # 降级: 直接基于复用决策生成简单方案
            optimized_plan = self._fallback_plan(reuse_decision)
            return {
                "status": "success",
                "requirement": requirement,
                "optimized_plan": optimized_plan,
                "quality_score": optimized_plan.get("quality_score", 60),
                "summary": f"LLM 调用失败, 使用降级方案: {str(e)[:100]}",
                "degraded": True,
            }

    # ------------------------------------------------------------------
    # LLM 提示词构建
    # ------------------------------------------------------------------

    @staticmethod
    def _build_user_prompt(
        requirement: str,
        reuse_decision: Dict,
        search_results: List[Dict],
    ) -> str:
        """构建 LLM 用户提示词"""
        suggestions = reuse_decision.get("suggestions", [])
        missing_assets = reuse_decision.get("missing_assets", [])
        can_reuse = reuse_decision.get("can_reuse", False)
        reuse_summary = reuse_decision.get("summary", "")

        # 复用建议详情
        reuse_desc = []
        for s in suggestions:
            reuse_desc.append(
                f"- asset_id={s.get('asset_id')}, "
                f"name={s.get('name')}, "
                f"type={s.get('asset_type')}, "
                f"reuse_score={s.get('reuse_score', 0):.2f}, "
                f"coverage={s.get('coverage', 0):.2f}, "
                f"suggestion={s.get('suggestion')}, "
                f"reason={s.get('reason', '')}"
            )
        reuse_text = "\n".join(reuse_desc) if reuse_desc else "无"

        # 搜索结果上下文 (简化, 仅用前 5 条)
        search_desc = []
        for hit in search_results[:5]:
            search_desc.append(
                f"- id={hit.get('asset_id')}, "
                f"name={hit.get('name')}, "
                f"type={hit.get('asset_type')}, "
                f"module={hit.get('module')}, "
                f"summary={hit.get('summary', '')[:100]}"
            )
        search_text = "\n".join(search_desc) if search_desc else "无"

        return f"""需求: {requirement}

复用决策摘要: {reuse_summary}
是否可复用: {can_reuse}
缺失资产类型: {missing_assets if missing_assets else "无"}

复用建议详情:
{reuse_text}

搜索结果上下文 (Top 5):
{search_text}

请基于以上信息, 生成优化的测试方案。"""

    # ------------------------------------------------------------------
    # 降级方案
    # ------------------------------------------------------------------

    @staticmethod
    def _fallback_plan(reuse_decision: Dict) -> Dict[str, Any]:
        """LLM 失败时的降级方案 (基于规则)"""
        suggestions = reuse_decision.get("suggestions", [])
        missing_assets = reuse_decision.get("missing_assets", [])

        reuse_assets = []
        adapt_assets = []
        for s in suggestions:
            if s.get("suggestion") == "reuse":
                reuse_assets.append({
                    "asset_id": s.get("asset_id"),
                    "name": s.get("name", ""),
                    "reason": s.get("reason", "直接复用"),
                })
            elif s.get("suggestion") == "adapt":
                adapt_assets.append({
                    "asset_id": s.get("asset_id"),
                    "name": s.get("name", ""),
                    "adaptation": "需根据需求适配具体字段",
                    "reason": s.get("reason", "部分匹配, 需适配"),
                })

        # 根据 missing_assets 生成新建建议
        new_assets = []
        for asset_type in missing_assets:
            new_assets.append({
                "asset_type": asset_type,
                "name": f"新建{asset_type}",
                "description": f"缺失的 {asset_type} 资产, 需新建",
                "priority": "high",
            })

        # 若无 missing_assets 但无任何可复用, 建议新建全套
        if not reuse_assets and not adapt_assets and not new_assets:
            new_assets = [
                {
                    "asset_type": "api_endpoint",
                    "name": "新建接口资产",
                    "description": "未找到可复用资产, 需新建接口",
                    "priority": "high",
                },
                {
                    "asset_type": "test_case",
                    "name": "新建测试用例",
                    "description": "为新接口生成测试用例",
                    "priority": "high",
                },
            ]

        # 执行顺序 (依赖关系: 接口 → 用例 → 脚本 → 数据)
        execution_order = []
        if reuse_assets or adapt_assets:
            execution_order.append("1. 复用/适配已有资产")
        if any(a["asset_type"] == "api_endpoint" for a in new_assets):
            execution_order.append("2. 新建接口资产")
        if any(a["asset_type"] == "test_case" for a in new_assets):
            execution_order.append("3. 新建测试用例")
        if any(a["asset_type"] == "script" for a in new_assets):
            execution_order.append("4. 生成测试脚本")
        if any(a["asset_type"] == "test_data" for a in new_assets):
            execution_order.append("5. 准备测试数据")

        # 质量评分
        total = len(suggestions)
        reuse_count = len(reuse_assets)
        reuse_rate = reuse_count / total if total > 0 else 0
        quality_score = int(60 + reuse_rate * 30)  # 60-90

        return {
            "reuse_assets": reuse_assets,
            "adapt_assets": adapt_assets,
            "new_assets": new_assets,
            "execution_order": execution_order,
            "quality_score": quality_score,
            "summary": (
                f"降级方案: 复用 {reuse_count} 个, "
                f"适配 {len(adapt_assets)} 个, "
                f"新建 {len(new_assets)} 个"
            ),
        }

    # ------------------------------------------------------------------
    # LLM 响应解析
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_llm_response(response: str) -> Optional[Dict[str, Any]]:
        """解析 LLM 返回的 JSON"""
        if not response:
            return None
        text = response.strip()
        # 尝试提取 JSON 代码块
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end > start:
                text = text[start:end].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            if end > start:
                text = text[start:end].strip()
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"[AssetOptimizationAgent] JSON 解析失败: {e}")
            return None
