"""
AssetReuseAgent - 测试资产复用判断 Agent

职责:
  接收 AssetSearchAgent 的搜索结果, 用 LLM 判断哪些资产可以复用,
  计算复用得分, 输出复用决策。

复用得分公式 (与设计文档一致):
  reuse_score = 0.35 * coverage + 0.20 * field_match
              + 0.15 * quality + 0.15 * recency + 0.15 * history

  - coverage:    需求覆盖率 0-1 (LLM 判断资产覆盖需求的程度)
  - field_match: 字段匹配度 0-1 (资产类型/模块/标签与需求的匹配度)
  - quality:     资产质量评分 0-100 (来自 asset.quality_score)
  - recency:     时效性 0-1 (根据 updated_at 计算, 越近越高)
  - history:     历史复用率 0-1 (基于 reuse_count 归一化)

输入 (AgentRequest.payload):
  requirement:    需求描述 (必填)
  search_results: 搜索结果列表 (来自 AssetSearchAgent, 必填)

输出 (AgentResponse.data):
  status:          success / error
  requirement:     原始需求
  can_reuse:       是否建议复用
  suggestions:     复用建议列表 (含 reuse_score 与 suggestion)
  missing_assets:  缺失资产类型 (需新建)
  summary:         决策摘要
"""
import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from autogen_core import message_handler, MessageContext, default_subscription

from app.runtime.base_agent import BaseRoutedAgent
from app.runtime.messages import AgentRequest, AgentResponse

logger = logging.getLogger(__name__)


# 复用得分权重 (与设计文档一致)
_REUSE_WEIGHTS = {
    "coverage": 0.35,
    "field_match": 0.20,
    "quality": 0.15,
    "recency": 0.15,
    "history": 0.15,
}

# 复用建议阈值
_REUSE_THRESHOLD = 0.6   # >= 0.6 建议 reuse
_ADAPT_THRESHOLD = 0.3   # 0.3-0.6 建议 adapt
# < 0.3 建议 skip


@default_subscription
class AssetReuseAgent(BaseRoutedAgent):
    """测试资产复用判断 Agent

    使用 LLM 分析搜索结果与需求的匹配度, 计算复用得分。

    使用方式:
      直接调用:  await agent.execute({"requirement": "...", "search_results": [...]}, ctx)
      消息驱动:  await self.send_request("asset_reuse_agent", "evaluate", payload)
    """

    # 系统提示词
    SYSTEM_PROMPT = """你是一位测试资产复用分析专家。

任务: 分析已有测试资产与当前需求匹配程度, 判断是否可以复用。

输出要求 (JSON 格式):
{
  "suggestions": [
    {
      "asset_id": <int>,
      "coverage": <0-1>,
      "field_match": <0-1>,
      "reason": "<复用理由>",
      "suggestion": "<reuse|adapt|skip>"
    }
  ],
  "missing_assets": ["<缺失的资产类型>"],
  "summary": "<决策摘要>"
}

评分标准:
- coverage (需求覆盖率): 资产能覆盖需求的百分比
- field_match (字段匹配度): 资产类型/模块/标签与需求的匹配度
- suggestion:
  - reuse: 可直接复用 (coverage >= 0.7)
  - adapt: 需要适配后复用 (0.3 <= coverage < 0.7)
  - skip: 不适合复用 (coverage < 0.3)"""

    def __init__(self) -> None:
        super().__init__(
            description="测试资产复用判断Agent, 用 LLM 评估资产可复用性",
            display_name="AssetReuseAgent",
            capabilities=["asset_reuse", "asset_evaluate"],
        )

    # ------------------------------------------------------------------
    # GraphFlow 入口
    # ------------------------------------------------------------------

    async def execute(
        self, payload: Dict[str, Any], ctx: MessageContext
    ) -> Dict[str, Any]:
        """GraphFlow 入口: 评估资产复用"""
        return await self._do_evaluate(payload)

    # ------------------------------------------------------------------
    # 消息处理器: evaluate
    # ------------------------------------------------------------------

    @message_handler
    async def handle_evaluate(
        self, message: AgentRequest, ctx: MessageContext
    ) -> AgentResponse:
        """处理 evaluate 请求

        Args (message.payload):
            requirement:    需求描述 (必填)
            search_results: 搜索结果列表 (来自 AssetSearchAgent, 必填)
        """
        start = time.time()
        request_id = message.request_id
        logger.info(
            f"[AssetReuseAgent] 收到评估请求 request_id={request_id} "
            f"results_count={len(message.payload.get('search_results', []))}"
        )

        try:
            result = await self._do_evaluate(message.payload)
            duration = time.time() - start

            if result.get("status") == "error":
                return AgentResponse(
                    request_id=request_id,
                    sender_type=self._agent_type,
                    status="error",
                    error=result.get("message", "评估失败"),
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
            logger.error(f"[AssetReuseAgent] 评估失败: {e}", exc_info=True)
            return AgentResponse(
                request_id=request_id,
                sender_type=self._agent_type,
                status="error",
                error=str(e),
                duration=duration,
            )

    # ------------------------------------------------------------------
    # 核心评估逻辑
    # ------------------------------------------------------------------

    async def _do_evaluate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """执行复用评估

        流程:
          1. 解析需求与搜索结果
          2. 对每个搜索结果, 用 LLM 判断 coverage + field_match
          3. 结合资产固有属性 (quality / recency / history) 计算综合 reuse_score
          4. 生成复用建议 (reuse / adapt / skip)
          5. 汇总决策
        """
        requirement: str = payload.get("requirement", "").strip()
        search_results: List[Dict] = payload.get("search_results", [])

        if not requirement:
            return {
                "status": "error",
                "message": "requirement 不能为空",
            }
        if not search_results:
            return {
                "status": "success",
                "requirement": requirement,
                "can_reuse": False,
                "suggestions": [],
                "missing_assets": [],
                "summary": "未找到任何已有资产, 需要全部新建",
            }

        # 1. 用 LLM 评估每个资产的 coverage + field_match
        llm_evaluations = await self._llm_evaluate_assets(
            requirement, search_results
        )

        # 2. 计算综合 reuse_score
        suggestions: List[Dict[str, Any]] = []
        for hit in search_results:
            asset_id = hit.get("asset_id", 0)
            llm_eval = llm_evaluations.get(asset_id, {})

            coverage = llm_eval.get("coverage", 0.0)
            field_match = llm_eval.get("field_match", 0.0)
            quality = hit.get("quality_score", 0.0) / 100.0  # 归一化到 0-1
            recency = self._compute_recency(hit.get("updated_at"))
            history = self._compute_history(hit.get("reuse_count", 0))

            reuse_score = (
                _REUSE_WEIGHTS["coverage"] * coverage
                + _REUSE_WEIGHTS["field_match"] * field_match
                + _REUSE_WEIGHTS["quality"] * quality
                + _REUSE_WEIGHTS["recency"] * recency
                + _REUSE_WEIGHTS["history"] * history
            )

            suggestion = self._decide_suggestion(reuse_score, coverage)

            suggestions.append({
                "asset_id": asset_id,
                "asset_code": hit.get("asset_code", ""),
                "name": hit.get("name", ""),
                "asset_type": hit.get("asset_type", ""),
                "reuse_score": round(reuse_score, 4),
                "coverage": round(coverage, 4),
                "field_match": round(field_match, 4),
                "quality": hit.get("quality_score", 0.0),
                "recency": round(recency, 4),
                "history": round(history, 4),
                "suggestion": suggestion,
                "reason": llm_eval.get("reason", ""),
            })

        # 3. 排序: 按 reuse_score 降序
        suggestions.sort(key=lambda x: x["reuse_score"], reverse=True)

        # 4. 汇总决策
        can_reuse = any(s["suggestion"] == "reuse" for s in suggestions)
        missing_assets = llm_evaluations.get("__missing__", [])

        # 5. 生成摘要
        reuse_count = sum(1 for s in suggestions if s["suggestion"] == "reuse")
        adapt_count = sum(1 for s in suggestions if s["suggestion"] == "adapt")
        skip_count = sum(1 for s in suggestions if s["suggestion"] == "skip")
        summary = (
            f"共评估 {len(suggestions)} 个资产: "
            f"{reuse_count} 个可直接复用, "
            f"{adapt_count} 个需适配, "
            f"{skip_count} 个不适合"
        )
        if missing_assets:
            summary += f"; 缺失资产类型: {', '.join(missing_assets)}"

        return {
            "status": "success",
            "requirement": requirement,
            "can_reuse": can_reuse,
            "suggestions": suggestions,
            "missing_assets": missing_assets,
            "summary": summary,
        }

    # ------------------------------------------------------------------
    # LLM 评估
    # ------------------------------------------------------------------

    async def _llm_evaluate_assets(
        self,
        requirement: str,
        search_results: List[Dict],
    ) -> Dict[str, Any]:
        """用 LLM 评估每个资产的 coverage 和 field_match

        返回:
          {
            <asset_id>: {"coverage": 0.x, "field_match": 0.x, "reason": "..."},
            "__missing__": ["缺失资产类型", ...]
          }
        """
        # 构建用户提示词
        assets_desc = []
        for hit in search_results:
            assets_desc.append(
                f"- asset_id={hit.get('asset_id')}, "
                f"name={hit.get('name')}, "
                f"type={hit.get('asset_type')}, "
                f"module={hit.get('module')}, "
                f"tags={hit.get('tags', [])}, "
                f"summary={hit.get('summary', '')}"
            )
        assets_text = "\n".join(assets_desc)

        user_prompt = f"""需求: {requirement}

已有资产:
{assets_text}

请分析每个资产与需求的匹配程度, 返回 JSON。"""

        try:
            response = await self.call_llm(
                system_prompt=self.SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=2048,
            )

            # 解析 LLM 返回的 JSON
            parsed = self._parse_llm_response(response)
            if not parsed:
                logger.warning("[AssetReuseAgent] LLM 返回解析失败, 使用默认评分")
                return self._default_evaluations(search_results)

            # 构建 asset_id → evaluation 映射
            evaluations: Dict[str, Any] = {}
            for s in parsed.get("suggestions", []):
                asset_id = s.get("asset_id")
                if asset_id is not None:
                    evaluations[asset_id] = {
                        "coverage": float(s.get("coverage", 0.5)),
                        "field_match": float(s.get("field_match", 0.5)),
                        "reason": s.get("reason", ""),
                    }
            evaluations["__missing__"] = parsed.get("missing_assets", [])

            return evaluations

        except Exception as e:
            logger.error(f"[AssetReuseAgent] LLM 评估失败: {e}", exc_info=True)
            return self._default_evaluations(search_results)

    # ------------------------------------------------------------------
    # 辅助计算
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_recency(updated_at: Optional[str]) -> float:
        """计算时效性 0-1

        规则: 30天内=1.0, 90天内=0.7, 180天内=0.4, 更早=0.2
        """
        if not updated_at:
            return 0.0
        try:
            # 兼容 ISO 字符串和 datetime 对象
            if isinstance(updated_at, str):
                dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            else:
                dt = updated_at
            now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
            days = (now - dt).days
            if days <= 30:
                return 1.0
            elif days <= 90:
                return 0.7
            elif days <= 180:
                return 0.4
            else:
                return 0.2
        except Exception:
            return 0.5

    @staticmethod
    def _compute_history(reuse_count: int) -> float:
        """计算历史复用率 0-1

        规则: reuse_count >= 10 → 1.0, 线性归一化
        """
        if reuse_count <= 0:
            return 0.0
        return min(reuse_count / 10.0, 1.0)

    @staticmethod
    def _decide_suggestion(reuse_score: float, coverage: float) -> str:
        """根据 reuse_score 和 coverage 决定建议"""
        if coverage >= 0.7 and reuse_score >= _REUSE_THRESHOLD:
            return "reuse"
        elif coverage >= 0.3 and reuse_score >= _ADAPT_THRESHOLD:
            return "adapt"
        else:
            return "skip"

    @staticmethod
    def _parse_llm_response(response: str) -> Optional[Dict]:
        """解析 LLM 返回的 JSON

        支持:
          - 纯 JSON
          - ```json ... ``` 代码块
        """
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
            logger.warning(f"[AssetReuseAgent] JSON 解析失败: {e}")
            return None

    @staticmethod
    def _default_evaluations(search_results: List[Dict]) -> Dict[str, Any]:
        """LLM 失败时的默认评分 (中性评估)"""
        evaluations: Dict[str, Any] = {}
        for hit in search_results:
            asset_id = hit.get("asset_id", 0)
            evaluations[asset_id] = {
                "coverage": 0.5,
                "field_match": 0.5,
                "reason": "LLM 评估降级, 使用默认中性评分",
            }
        evaluations["__missing__"] = []
        return evaluations
