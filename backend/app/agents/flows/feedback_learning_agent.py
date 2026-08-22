"""
FeedbackLearningAgent - AI 测试反馈学习 Agent

职责:
  根据历史执行结果优化测试生成能力,收集三类案例并进行 LLM 分析,
  生成三种优化建议:
  1. RAG 优化(rag): 检索参数、索引策略、知识库补充建议
  2. Prompt 优化(prompt): 通过 PromptManager 创建新版本
  3. 策略优化(strategy): temperature、max_tokens、模板调整建议

数据流:
  执行记录(成功/失败) + 审核记录 + 资产版本(人工修改)
        ↓ (collect_cases)
  FeedbackLearningRecord(收集入库)
        ↓ (analyze + LLM)
  FeedbackOptimization(优化建议)
        ↓ (apply)
  RAG / PromptManager / AgentConfig

输入 (AgentRequest.payload):
  optimization_id:  优化任务ID(必填,用于回写结果)
  collect_scope:    收集范围(可选,JSON: {time_range, agent_names, limit})
  user_id:          用户ID(可选)

输出 (AgentResponse.data):
  status / optimization_ids / summary / statistics /
  rag_optimizations / prompt_optimizations / strategy_optimizations
"""
import json
import logging
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from autogen_core import MessageContext, default_subscription, message_handler

from app.runtime.base_agent import BaseRoutedAgent
from app.runtime.messages import AgentRequest, AgentResponse

logger = logging.getLogger(__name__)

# 收集案例的默认数量上限
_DEFAULT_COLLECT_LIMIT = 200

# 置信度阈值
_CONFIDENCE_HIGH = 0.75
_CONFIDENCE_MEDIUM = 0.5


@default_subscription
class FeedbackLearningAgent(BaseRoutedAgent):
    """AI 测试反馈学习 Agent

    使用方式:
      直接调用:  await agent.execute({"optimization_id": 1, "user_id": 1}, ctx)
      消息驱动:  await self.send_request("feedback_learning_agent", "learn", payload)
    """

    # ================================================================
    # System Prompts
    # ================================================================

    SYSTEM_PROMPT_SUCCESS = """你是一位测试质量分析专家。

任务: 分析成功的测试执行案例,提取成功模式和最佳实践。

输出要求 (JSON 格式):
{
  "success_patterns": ["成功模式1", "成功模式2"],
  "best_practices": ["最佳实践1", "最佳实践2"],
  "key_factors": ["关键成功因素1", "关键成功因素2"],
  "reusable_strategies": ["可复用策略1", "可复用策略2"]
}"""

    SYSTEM_PROMPT_FAILURE = """你是一位测试失败分析专家。

任务: 分析失败的测试执行案例,识别常见失败模式和根因。

输出要求 (JSON 格式):
{
  "common_failures": [
    {"pattern": "失败模式", "frequency": "high/medium/low", "root_cause": "根因", "affected_agents": ["agent名"]}
  ],
  "failure_trends": "失败趋势描述",
  "high_risk_areas": ["高风险区域1", "高风险区域2"],
  "prevention_suggestions": ["预防建议1", "预防建议2"]
}"""

    SYSTEM_PROMPT_MODIFICATION = """你是一位测试用例审查和人工修改分析专家。

任务: 分析人工修改记录,识别AI生成内容的常见问题和改进方向。

输出要求 (JSON 格式):
{
  "common_issues": [
    {"issue": "问题类型", "frequency": "high/medium/low", "example": "示例", "fix_pattern": "修复模式"}
  ],
  "quality_gaps": ["质量差距1", "质量差距2"],
  "improvement_areas": ["改进方向1", "改进方向2"],
  "human_preferences": ["人工偏好1", "人工偏好2"]
}"""

    SYSTEM_PROMPT_RAG_OPT = """你是一位 RAG(检索增强生成)优化专家。

任务: 基于成功/失败/修改案例的分析结果,提出 RAG 检索优化建议。

输出要求 (JSON 格式):
{
  "optimizations": [
    {
      "title": "优化建议标题",
      "description": "详细描述",
      "retrieval_params": {"top_k": 5, "score_threshold": 0.7, "rerank": true},
      "index_suggestions": ["索引补充建议1"],
      "knowledge_gaps": ["知识库缺口1"],
      "confidence": 0.8,
      "reasoning": "优化理由"
    }
  ]
}"""

    SYSTEM_PROMPT_PROMPT_OPT = """你是一位 Prompt 工程优化专家。

任务: 基于案例分析结果,提出 Prompt 优化建议(创建新版本或修改现有版本)。

输出要求 (JSON 格式):
{
  "optimizations": [
    {
      "title": "优化建议标题",
      "description": "详细描述",
      "agent_name": "目标Agent名",
      "prompt_key": "system_prompt",
      "suggested_content": "建议的Prompt内容",
      "change_summary": "变更摘要",
      "confidence": 0.8,
      "reasoning": "优化理由"
    }
  ]
}"""

    SYSTEM_PROMPT_STRATEGY_OPT = """你是一位测试生成策略优化专家。

任务: 基于案例分析结果,提出 Agent 配置策略优化建议(temperature、max_tokens等)。

输出要求 (JSON 格式):
{
  "optimizations": [
    {
      "title": "优化建议标题",
      "description": "详细描述",
      "agent_name": "目标Agent名",
      "current_config": {"temperature": 0.3, "max_tokens": 4096},
      "suggested_config": {"temperature": 0.2, "max_tokens": 8192},
      "reasoning": "优化理由",
      "confidence": 0.8
    }
  ]
}"""

    SYSTEM_PROMPT_SUMMARY = """你是一位测试反馈学习总结专家。

任务: 综合所有分析结果,生成反馈学习总结报告。

输出要求 (JSON 格式):
{
  "summary": "200字以内的总结",
  "key_insights": ["关键洞察1", "关键洞察2", "关键洞察3"],
  "top_recommendations": ["首要建议1", "首要建议2", "首要建议3"],
  "expected_improvements": "预期改进效果描述"
}"""

    def __init__(self) -> None:
        super().__init__(
            description="AI测试反馈学习Agent, 收集成功/失败/修改案例并生成RAG/Prompt/策略优化建议",
            display_name="FeedbackLearningAgent",
            capabilities=[
                "feedback_learning", "case_collection",
                "rag_optimization", "prompt_optimization", "strategy_optimization",
            ],
        )

    # ------------------------------------------------------------------
    # GraphFlow 入口(默认 execute action)
    # ------------------------------------------------------------------
    async def execute(
        self, payload: Dict[str, Any], ctx: MessageContext
    ) -> Dict[str, Any]:
        """主入口: 执行完整的反馈学习流程"""
        return await self._do_learning(payload)

    # ------------------------------------------------------------------
    # 消息处理器: learn action
    # ------------------------------------------------------------------
    @message_handler
    async def handle_learn(
        self, message: AgentRequest, ctx: MessageContext
    ) -> AgentResponse:
        """处理 learn 请求"""
        start = time.time()
        request_id = message.request_id
        try:
            result = await self._do_learning(message.payload)
            duration = time.time() - start
            if result.get("status") == "error":
                return AgentResponse(
                    request_id=request_id,
                    sender_type=self._agent_type,
                    status="error",
                    error=result.get("message", "学习失败"),
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
            logger.error(f"[FeedbackLearningAgent] 学习失败: {e}", exc_info=True)
            return AgentResponse(
                request_id=request_id,
                sender_type=self._agent_type,
                status="error",
                error=str(e),
                duration=duration,
            )

    # ------------------------------------------------------------------
    # 核心学习逻辑
    # ------------------------------------------------------------------
    async def _do_learning(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """执行完整的反馈学习流程"""
        optimization_id = payload.get("optimization_id")
        user_id = payload.get("user_id")
        collect_scope = payload.get("collect_scope", {})

        if optimization_id is None:
            return {"status": "error", "message": "optimization_id 不能为空"}

        logger.info(f"[FeedbackLearningAgent] 开始学习 optimization_id={optimization_id}")

        # 1. 收集案例
        cases = await self._collect_cases(collect_scope, user_id)
        logger.info(
            f"[FeedbackLearningAgent] 收集案例: "
            f"success={cases['success_count']}, "
            f"failure={cases['failure_count']}, "
            f"modification={cases['modification_count']}"
        )

        # 2. 保存学习记录
        record_ids = await self._save_learning_records(cases, user_id)

        # 3. 更新任务状态为 analyzing
        await self._update_optimization_status(optimization_id, "analyzing")

        try:
            # 4. 三维度分析(LLM)
            success_analysis = await self._analyze_success(cases["success"])
            failure_analysis = await self._analyze_failure(cases["failure"])
            modification_analysis = await self._analyze_modification(cases["modification"])

            # 5. 生成三类优化建议
            rag_opts = await self._generate_rag_optimizations(
                success_analysis, failure_analysis, modification_analysis, record_ids, user_id
            )
            prompt_opts = await self._generate_prompt_optimizations(
                success_analysis, failure_analysis, modification_analysis, record_ids, user_id
            )
            strategy_opts = await self._generate_strategy_optimizations(
                success_analysis, failure_analysis, modification_analysis, record_ids, user_id
            )

            # 6. 生成总结
            summary_result = await self._generate_summary(
                success_analysis, failure_analysis, modification_analysis,
                rag_opts, prompt_opts, strategy_opts, cases
            )

            # 7. 更新任务状态为 completed
            all_opt_ids = rag_opts["ids"] + prompt_opts["ids"] + strategy_opts["ids"]
            await self._update_optimization_status(
                optimization_id, "completed",
                summary=summary_result.get("summary", ""),
                optimization_ids=all_opt_ids,
            )

            logger.info(
                f"[FeedbackLearningAgent] 学习完成 optimization_id={optimization_id} "
                f"rag={len(rag_opts['ids'])}, prompt={len(prompt_opts['ids'])}, "
                f"strategy={len(strategy_opts['ids'])}"
            )

            return {
                "status": "success",
                "optimization_id": optimization_id,
                "optimization_ids": all_opt_ids,
                "summary": summary_result.get("summary", ""),
                "key_insights": summary_result.get("key_insights", []),
                "top_recommendations": summary_result.get("top_recommendations", []),
                "statistics": {
                    "success_count": cases["success_count"],
                    "failure_count": cases["failure_count"],
                    "modification_count": cases["modification_count"],
                    "total_records": len(record_ids),
                    "rag_optimizations": len(rag_opts["ids"]),
                    "prompt_optimizations": len(prompt_opts["ids"]),
                    "strategy_optimizations": len(strategy_opts["ids"]),
                },
                "rag_optimizations": rag_opts["data"],
                "prompt_optimizations": prompt_opts["data"],
                "strategy_optimizations": strategy_opts["data"],
            }

        except Exception as e:
            logger.error(f"[FeedbackLearningAgent] 学习失败: {e}", exc_info=True)
            await self._update_optimization_status(
                optimization_id, "failed", error=str(e)
            )
            return {"status": "error", "message": str(e), "optimization_id": optimization_id}

    # ------------------------------------------------------------------
    # 案例收集
    # ------------------------------------------------------------------
    async def _collect_cases(
        self, collect_scope: Dict[str, Any], user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """从数据库收集三类案例"""
        from app.db.database import SessionLocal
        from app.models.execution_record import ExecutionRecord
        from app.models.asset_registry import AssetVersion
        from app.models.test_case_review import TestCaseReview

        db = SessionLocal()
        try:
            time_range = collect_scope.get("time_range", {})
            agent_names = collect_scope.get("agent_names", [])
            limit = collect_scope.get("limit", _DEFAULT_COLLECT_LIMIT)

            # 1. 收集成功案例
            success_query = db.query(ExecutionRecord).filter(
                ExecutionRecord.status == "success"
            )
            if user_id is not None:
                success_query = success_query.filter(ExecutionRecord.user_id == user_id)
            if time_range and time_range.get("start"):
                success_query = success_query.filter(
                    ExecutionRecord.created_at >= time_range["start"]
                )
            if time_range and time_range.get("end"):
                success_query = success_query.filter(
                    ExecutionRecord.created_at <= time_range["end"]
                )

            success_execs = success_query.order_by(
                ExecutionRecord.created_at.desc()
            ).limit(limit).all()

            success_cases = []
            for e in success_execs:
                success_cases.append({
                    "execution_id": e.id,
                    "asset_id": e.asset_id,
                    "execution_type": e.execution_type,
                    "success_count": e.success_count or 0,
                    "duration": e.duration or 0,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                    "agent_name": self._infer_agent_name(e.execution_type),
                })

            # 2. 收集失败案例
            failure_query = db.query(ExecutionRecord).filter(
                ExecutionRecord.status.in_(["failed", "error"])
            )
            if user_id is not None:
                failure_query = failure_query.filter(ExecutionRecord.user_id == user_id)
            if time_range and time_range.get("start"):
                failure_query = failure_query.filter(
                    ExecutionRecord.created_at >= time_range["start"]
                )
            if time_range and time_range.get("end"):
                failure_query = failure_query.filter(
                    ExecutionRecord.created_at <= time_range["end"]
                )

            failure_execs = failure_query.order_by(
                ExecutionRecord.created_at.desc()
            ).limit(limit).all()

            failure_cases = []
            for e in failure_execs:
                analysis = {}
                if e.analysis_result:
                    try:
                        analysis = json.loads(e.analysis_result)
                    except (json.JSONDecodeError, TypeError):
                        pass
                failure_cases.append({
                    "execution_id": e.id,
                    "asset_id": e.asset_id,
                    "execution_type": e.execution_type,
                    "failed_count": e.failed_count or 0,
                    "error_message": (e.error_message or "")[:500],
                    "log_content": (e.log_content or "")[:2000],
                    "analysis_result": analysis,
                    "duration": e.duration or 0,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                    "agent_name": self._infer_agent_name(e.execution_type),
                    "error_type": self._classify_error(e.error_message or "", e.log_content or ""),
                })

            # 3. 收集人工修改记录
            # 3a. 从 AssetVersion 收集
            version_query = db.query(AssetVersion).filter(
                AssetVersion.change_type.in_(["update", "rollback"])
            )
            versions = version_query.order_by(
                AssetVersion.created_at.desc()
            ).limit(limit).all()

            # 3b. 从 TestCaseReview 收集
            review_query = db.query(TestCaseReview).filter(
                TestCaseReview.review_result.in_(["need_revision", "reject"])
            )
            reviews = review_query.order_by(
                TestCaseReview.created_at.desc()
            ).limit(limit).all()

            modification_cases = []
            for v in versions:
                diff = {}
                if v.diff_summary:
                    try:
                        diff = json.loads(v.diff_summary) if isinstance(v.diff_summary, str) else v.diff_summary
                    except (json.JSONDecodeError, TypeError):
                        pass
                modification_cases.append({
                    "source": "asset_version",
                    "source_id": v.id,
                    "asset_id": v.asset_id,
                    "change_type": v.change_type,
                    "diff_summary": diff,
                    "change_log": v.change_log or "",
                    "created_at": v.created_at.isoformat() if v.created_at else None,
                })

            for r in reviews:
                modification_cases.append({
                    "source": "test_case_review",
                    "source_id": r.id,
                    "case_id": r.case_id,
                    "review_score": r.score,
                    "review_result": r.review_result,
                    "suggestion": r.suggestion or "",
                    "issues": r.issues or "",
                    "review_comment": r.review_comment or "",
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                })

            return {
                "success": success_cases,
                "success_count": len(success_cases),
                "failure": failure_cases,
                "failure_count": len(failure_cases),
                "modification": modification_cases,
                "modification_count": len(modification_cases),
            }
        finally:
            db.close()

    def _infer_agent_name(self, execution_type: Optional[str]) -> str:
        """从执行类型推断关联 Agent"""
        mapping = {
            "api": "api_case_agent",
            "web": "script_generation_agent",
            "android": "script_generation_agent",
            "suite": "execution_agent",
            "batch": "execution_agent",
        }
        return mapping.get(execution_type or "", "unknown")

    def _classify_error(self, error_message: str, log_content: str) -> str:
        """分类错误类型"""
        combined = (error_message + " " + log_content).lower()
        if "timeout" in combined or "timed out" in combined:
            return "timeout"
        elif "assert" in combined:
            return "assertion"
        elif "element not found" in combined or "no such element" in combined:
            return "element_not_found"
        elif "connection" in combined or "refused" in combined:
            return "connection"
        elif "syntax" in combined or "syntaxerror" in combined:
            return "syntax"
        elif "import" in combined or "module" in combined:
            return "import_error"
        return "unknown"

    # ------------------------------------------------------------------
    # 保存学习记录
    # ------------------------------------------------------------------
    async def _save_learning_records(
        self, cases: Dict[str, Any], user_id: Optional[int] = None
    ) -> List[int]:
        """将收集的案例保存到 FeedbackLearningRecord 表"""
        from app.db.database import SessionLocal
        from app.models.feedback_learning import FeedbackLearningRecord

        record_ids = []
        db = SessionLocal()
        try:
            # 保存成功案例
            for case in cases["success"]:
                record = FeedbackLearningRecord(
                    record_type="success",
                    source="execution",
                    source_id=case.get("execution_id"),
                    agent_name=case.get("agent_name"),
                    content_json=json.dumps(case, ensure_ascii=False),
                    module=case.get("execution_type"),
                    status="analyzed",
                    user_id=user_id,
                    created_by=user_id,
                    is_deleted=False,
                )
                db.add(record)
                db.flush()
                record_ids.append(record.id)

            # 保存失败案例
            for case in cases["failure"]:
                record = FeedbackLearningRecord(
                    record_type="failure",
                    source="execution",
                    source_id=case.get("execution_id"),
                    agent_name=case.get("agent_name"),
                    content_json=json.dumps(case, ensure_ascii=False),
                    tags=case.get("error_type"),
                    module=case.get("execution_type"),
                    status="analyzed",
                    user_id=user_id,
                    created_by=user_id,
                    is_deleted=False,
                )
                db.add(record)
                db.flush()
                record_ids.append(record.id)

            # 保存修改记录
            for case in cases["modification"]:
                record = FeedbackLearningRecord(
                    record_type="modification",
                    source=case.get("source", "asset_version"),
                    source_id=case.get("source_id"),
                    content_json=json.dumps(case, ensure_ascii=False),
                    status="analyzed",
                    user_id=user_id,
                    created_by=user_id,
                    is_deleted=False,
                )
                db.add(record)
                db.flush()
                record_ids.append(record.id)

            db.commit()
            logger.info(
                f"[FeedbackLearningAgent] 保存学习记录 {len(record_ids)} 条"
            )
        except Exception as e:
            db.rollback()
            logger.error(f"[FeedbackLearningAgent] 保存学习记录失败: {e}")
        finally:
            db.close()

        return record_ids

    # ------------------------------------------------------------------
    # 三维度分析(LLM 调用)
    # ------------------------------------------------------------------
    async def _analyze_success(self, success_cases: List[Dict]) -> Dict[str, Any]:
        """分析成功案例"""
        if not success_cases:
            return {
                "success_patterns": [],
                "best_practices": [],
                "key_factors": [],
                "reusable_strategies": [],
            }

        # 统计成功模式
        type_dist = Counter(c.get("execution_type", "unknown") for c in success_cases)
        agent_dist = Counter(c.get("agent_name", "unknown") for c in success_cases)
        avg_duration = (
            sum(c.get("duration", 0) for c in success_cases) / len(success_cases)
            if success_cases else 0
        )

        user_prompt = f"""成功案例统计:
- 总数: {len(success_cases)}
- 按执行类型: {dict(type_dist)}
- 按Agent: {dict(agent_dist)}
- 平均耗时: {avg_duration:.2f}秒

案例详情(前10条):
{json.dumps(success_cases[:10], ensure_ascii=False, indent=2)}

请分析成功模式,返回 JSON。"""

        try:
            response = await self.call_llm(
                system_prompt=self.SYSTEM_PROMPT_SUCCESS,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=2048,
            )
            parsed = self._parse_llm_json(response)
            if parsed:
                parsed["total_count"] = len(success_cases)
                parsed["type_distribution"] = dict(type_dist)
                parsed["agent_distribution"] = dict(agent_dist)
                return parsed
        except Exception as e:
            logger.warning(f"[FeedbackLearningAgent] 成功分析 LLM 调用失败: {e}")

        # 回退
        return {
            "success_patterns": [f"{t}类型执行成功率高" for t in list(type_dist.keys())[:3]],
            "best_practices": ["保持当前执行策略"],
            "key_factors": ["执行类型匹配", "Agent选择合理"],
            "reusable_strategies": [f"复用{a}的执行策略" for a in list(agent_dist.keys())[:3]],
            "total_count": len(success_cases),
            "type_distribution": dict(type_dist),
            "agent_distribution": dict(agent_dist),
        }

    async def _analyze_failure(self, failure_cases: List[Dict]) -> Dict[str, Any]:
        """分析失败案例"""
        if not failure_cases:
            return {
                "common_failures": [],
                "failure_trends": "无失败案例",
                "high_risk_areas": [],
                "prevention_suggestions": [],
            }

        # 统计失败模式
        error_type_dist = Counter(c.get("error_type", "unknown") for c in failure_cases)
        agent_dist = Counter(c.get("agent_name", "unknown") for c in failure_cases)
        type_dist = Counter(c.get("execution_type", "unknown") for c in failure_cases)

        # 按错误类型聚合
        by_error_type = defaultdict(list)
        for c in failure_cases:
            by_error_type[c.get("error_type", "unknown")].append(c)

        common_failures = []
        for error_type, cases in sorted(
            by_error_type.items(), key=lambda x: len(x[1]), reverse=True
        ):
            frequency = "high" if len(cases) >= 5 else "medium" if len(cases) >= 2 else "low"
            affected = list(set(c.get("agent_name", "unknown") for c in cases))[:3]
            common_failures.append({
                "pattern": f"{error_type} 错误",
                "frequency": frequency,
                "root_cause": cases[0].get("error_message", "")[:200] if cases else "",
                "affected_agents": affected,
                "count": len(cases),
            })

        user_prompt = f"""失败案例统计:
- 总数: {len(failure_cases)}
- 按错误类型: {dict(error_type_dist)}
- 按Agent: {dict(agent_dist)}
- 按执行类型: {dict(type_dist)}

常见失败模式:
{json.dumps(common_failures[:10], ensure_ascii=False, indent=2)}

请分析失败模式,返回 JSON。"""

        try:
            response = await self.call_llm(
                system_prompt=self.SYSTEM_PROMPT_FAILURE,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=2048,
            )
            parsed = self._parse_llm_json(response)
            if parsed:
                parsed["total_count"] = len(failure_cases)
                parsed["error_type_distribution"] = dict(error_type_dist)
                return parsed
        except Exception as e:
            logger.warning(f"[FeedbackLearningAgent] 失败分析 LLM 调用失败: {e}")

        # 回退
        return {
            "common_failures": common_failures,
            "failure_trends": f"共{len(failure_cases)}个失败案例,主要错误类型: {list(error_type_dist.keys())[:3]}",
            "high_risk_areas": list(error_type_dist.keys())[:3],
            "prevention_suggestions": [f"减少{t}类型错误" for t in list(error_type_dist.keys())[:3]],
            "total_count": len(failure_cases),
            "error_type_distribution": dict(error_type_dist),
        }

    async def _analyze_modification(self, modification_cases: List[Dict]) -> Dict[str, Any]:
        """分析人工修改记录"""
        if not modification_cases:
            return {
                "common_issues": [],
                "quality_gaps": [],
                "improvement_areas": [],
                "human_preferences": [],
            }

        # 统计修改来源
        source_dist = Counter(c.get("source", "unknown") for c in modification_cases)
        change_type_dist = Counter(
            c.get("change_type", "unknown") for c in modification_cases
            if c.get("change_type")
        )
        review_result_dist = Counter(
            c.get("review_result", "unknown") for c in modification_cases
            if c.get("review_result")
        )

        # 提取常见问题
        common_issues = []
        for source, cases in [
            ("asset_version", [c for c in modification_cases if c.get("source") == "asset_version"]),
            ("test_case_review", [c for c in modification_cases if c.get("source") == "test_case_review"]),
        ]:
            if not cases:
                continue
            if source == "test_case_review":
                avg_score = sum(c.get("review_score", 0) for c in cases) / len(cases)
                reject_count = sum(1 for c in cases if c.get("review_result") == "reject")
                common_issues.append({
                    "issue": "用例质量不达标",
                    "frequency": "high" if reject_count > len(cases) * 0.3 else "medium",
                    "example": cases[0].get("suggestion", "")[:200] if cases else "",
                    "fix_pattern": "加强用例完整性和准确性",
                    "avg_score": round(avg_score, 2),
                    "count": len(cases),
                })
            else:
                common_issues.append({
                    "issue": "资产需人工修改",
                    "frequency": "medium",
                    "example": cases[0].get("change_log", "")[:200] if cases else "",
                    "fix_pattern": "提升生成质量减少修改",
                    "count": len(cases),
                })

        user_prompt = f"""人工修改记录统计:
- 总数: {len(modification_cases)}
- 按来源: {dict(source_dist)}
- 按变更类型: {dict(change_type_dist)}
- 按审核结果: {dict(review_result_dist)}

常见问题:
{json.dumps(common_issues[:10], ensure_ascii=False, indent=2)}

案例详情(前10条):
{json.dumps(modification_cases[:10], ensure_ascii=False, indent=2)}

请分析人工修改记录,返回 JSON。"""

        try:
            response = await self.call_llm(
                system_prompt=self.SYSTEM_PROMPT_MODIFICATION,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=2048,
            )
            parsed = self._parse_llm_json(response)
            if parsed:
                parsed["total_count"] = len(modification_cases)
                parsed["source_distribution"] = dict(source_dist)
                return parsed
        except Exception as e:
            logger.warning(f"[FeedbackLearningAgent] 修改分析 LLM 调用失败: {e}")

        # 回退
        return {
            "common_issues": common_issues,
            "quality_gaps": ["生成内容需人工修正"],
            "improvement_areas": ["提升生成准确性"],
            "human_preferences": ["更完整的断言", "更清晰的步骤描述"],
            "total_count": len(modification_cases),
            "source_distribution": dict(source_dist),
        }

    # ------------------------------------------------------------------
    # 生成三类优化建议
    # ------------------------------------------------------------------
    async def _generate_rag_optimizations(
        self,
        success_analysis: Dict,
        failure_analysis: Dict,
        modification_analysis: Dict,
        record_ids: List[int],
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """生成 RAG 优化建议"""
        user_prompt = f"""基于以下分析结果,提出 RAG 检索优化建议:

1. 成功案例分析:
{json.dumps(success_analysis, ensure_ascii=False, indent=2)}

2. 失败案例分析:
{json.dumps(failure_analysis, ensure_ascii=False, indent=2)}

3. 人工修改分析:
{json.dumps(modification_analysis, ensure_ascii=False, indent=2)}

请提出 RAG 优化建议(检索参数、索引策略、知识库补充),返回 JSON。"""

        try:
            response = await self.call_llm(
                system_prompt=self.SYSTEM_PROMPT_RAG_OPT,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=2048,
            )
            parsed = self._parse_llm_json(response)
            if parsed and parsed.get("optimizations"):
                opts = parsed["optimizations"]
                saved_ids = await self._save_optimizations(
                    opts, "rag", record_ids, user_id
                )
                return {"ids": saved_ids, "data": opts}
        except Exception as e:
            logger.warning(f"[FeedbackLearningAgent] RAG优化 LLM 调用失败: {e}")

        # 回退: 基于失败分析生成统计型建议
        fallback_opts = self._generate_rag_fallback(failure_analysis, modification_analysis)
        saved_ids = await self._save_optimizations(
            fallback_opts, "rag", record_ids, user_id
        )
        return {"ids": saved_ids, "data": fallback_opts}

    async def _generate_prompt_optimizations(
        self,
        success_analysis: Dict,
        failure_analysis: Dict,
        modification_analysis: Dict,
        record_ids: List[int],
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """生成 Prompt 优化建议"""
        user_prompt = f"""基于以下分析结果,提出 Prompt 优化建议:

1. 成功案例分析:
{json.dumps(success_analysis, ensure_ascii=False, indent=2)}

2. 失败案例分析:
{json.dumps(failure_analysis, ensure_ascii=False, indent=2)}

3. 人工修改分析:
{json.dumps(modification_analysis, ensure_ascii=False, indent=2)}

请提出 Prompt 优化建议(针对具体Agent的system_prompt改进),返回 JSON。"""

        try:
            response = await self.call_llm(
                system_prompt=self.SYSTEM_PROMPT_PROMPT_OPT,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=2048,
            )
            parsed = self._parse_llm_json(response)
            if parsed and parsed.get("optimizations"):
                opts = parsed["optimizations"]
                saved_ids = await self._save_optimizations(
                    opts, "prompt", record_ids, user_id
                )
                return {"ids": saved_ids, "data": opts}
        except Exception as e:
            logger.warning(f"[FeedbackLearningAgent] Prompt优化 LLM 调用失败: {e}")

        # 回退
        fallback_opts = self._generate_prompt_fallback(
            failure_analysis, modification_analysis
        )
        saved_ids = await self._save_optimizations(
            fallback_opts, "prompt", record_ids, user_id
        )
        return {"ids": saved_ids, "data": fallback_opts}

    async def _generate_strategy_optimizations(
        self,
        success_analysis: Dict,
        failure_analysis: Dict,
        modification_analysis: Dict,
        record_ids: List[int],
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """生成策略优化建议"""
        user_prompt = f"""基于以下分析结果,提出 Agent 配置策略优化建议:

1. 成功案例分析:
{json.dumps(success_analysis, ensure_ascii=False, indent=2)}

2. 失败案例分析:
{json.dumps(failure_analysis, ensure_ascii=False, indent=2)}

3. 人工修改分析:
{json.dumps(modification_analysis, ensure_ascii=False, indent=2)}

请提出 Agent 配置优化建议(temperature、max_tokens等),返回 JSON。"""

        try:
            response = await self.call_llm(
                system_prompt=self.SYSTEM_PROMPT_STRATEGY_OPT,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=2048,
            )
            parsed = self._parse_llm_json(response)
            if parsed and parsed.get("optimizations"):
                opts = parsed["optimizations"]
                saved_ids = await self._save_optimizations(
                    opts, "strategy", record_ids, user_id
                )
                return {"ids": saved_ids, "data": opts}
        except Exception as e:
            logger.warning(f"[FeedbackLearningAgent] 策略优化 LLM 调用失败: {e}")

        # 回退
        fallback_opts = self._generate_strategy_fallback(failure_analysis)
        saved_ids = await self._save_optimizations(
            fallback_opts, "strategy", record_ids, user_id
        )
        return {"ids": saved_ids, "data": fallback_opts}

    # ------------------------------------------------------------------
    # 回退优化生成(无 LLM 时)
    # ------------------------------------------------------------------
    def _generate_rag_fallback(
        self, failure_analysis: Dict, modification_analysis: Dict
    ) -> List[Dict[str, Any]]:
        """基于失败分析生成 RAG 回退建议"""
        opts = []
        error_dist = failure_analysis.get("error_type_distribution", {})

        if error_dist:
            top_error = max(error_dist, key=error_dist.get)
            opts.append({
                "title": f"补充{top_error}错误相关知识",
                "description": f"检测到{top_error}类型错误频发,建议补充相关检索知识",
                "retrieval_params": {"top_k": 5, "score_threshold": 0.7, "rerank": True},
                "index_suggestions": [f"增加{top_error}错误的索引覆盖"],
                "knowledge_gaps": [f"{top_error}错误处理知识不足"],
                "confidence": _CONFIDENCE_MEDIUM,
                "reasoning": f"{top_error}错误占比最高,需加强相关知识检索",
            })

        if modification_analysis.get("total_count", 0) > 0:
            opts.append({
                "title": "优化用例生成相关知识检索",
                "description": "人工修改频繁,说明生成时检索的知识不够准确",
                "retrieval_params": {"top_k": 8, "score_threshold": 0.65, "rerank": True},
                "index_suggestions": ["增加用例模板索引"],
                "knowledge_gaps": ["用例最佳实践知识不足"],
                "confidence": _CONFIDENCE_MEDIUM,
                "reasoning": "人工修改记录多,反映检索质量需提升",
            })

        if not opts:
            opts.append({
                "title": "维持当前RAG检索参数",
                "description": "当前检索参数基本满足需求",
                "retrieval_params": {"top_k": 5, "score_threshold": 0.7, "rerank": False},
                "index_suggestions": [],
                "knowledge_gaps": [],
                "confidence": _CONFIDENCE_MEDIUM,
                "reasoning": "无明显优化方向,维持现状",
            })

        return opts

    def _generate_prompt_fallback(
        self, failure_analysis: Dict, modification_analysis: Dict
    ) -> List[Dict[str, Any]]:
        """基于失败分析生成 Prompt 回退建议"""
        opts = []
        agent_dist = failure_analysis.get("error_type_distribution", {})

        if agent_dist:
            opts.append({
                "title": "增强错误处理Prompt指引",
                "description": "在生成Prompt中增加常见错误的处理指引",
                "agent_name": "script_generation_agent",
                "prompt_key": "system_prompt",
                "suggested_content": "生成脚本时请增加异常处理和重试机制,特别注意timeout和element_not_found错误的处理。",
                "change_summary": "增加错误处理指引",
                "confidence": _CONFIDENCE_MEDIUM,
                "reasoning": "失败案例中错误处理不足",
            })

        if modification_analysis.get("common_issues"):
            opts.append({
                "title": "强化用例完整性Prompt",
                "description": "人工修改反映用例完整性不足,需在Prompt中强化",
                "agent_name": "case_agent",
                "prompt_key": "system_prompt",
                "suggested_content": "生成用例时请确保每个步骤都有明确的预期结果和验证点,包含正常流程、异常流程和边界条件。",
                "change_summary": "强化完整性要求",
                "confidence": _CONFIDENCE_MEDIUM,
                "reasoning": "人工修改多与用例不完整相关",
            })

        if not opts:
            opts.append({
                "title": "微调生成Prompt",
                "description": "根据反馈微调现有Prompt",
                "agent_name": "case_agent",
                "prompt_key": "system_prompt",
                "suggested_content": "请保持高质量的测试用例生成,注重用例的准确性和可执行性。",
                "change_summary": "微调措辞",
                "confidence": _CONFIDENCE_MEDIUM,
                "reasoning": "无明确优化方向,做轻微调整",
            })

        return opts

    def _generate_strategy_fallback(self, failure_analysis: Dict) -> List[Dict[str, Any]]:
        """基于失败分析生成策略回退建议"""
        opts = []
        total = failure_analysis.get("total_count", 0)

        if total > 10:
            opts.append({
                "title": "降低生成temperature提升稳定性",
                "description": "失败案例较多,降低temperature提升生成稳定性",
                "agent_name": "script_generation_agent",
                "current_config": {"temperature": 0.2, "max_tokens": 8192},
                "suggested_config": {"temperature": 0.1, "max_tokens": 8192},
                "reasoning": "失败率高,需更确定性的生成",
                "confidence": _CONFIDENCE_HIGH,
            })
        elif total > 0:
            opts.append({
                "title": "微调生成参数",
                "description": "根据失败案例微调生成参数",
                "agent_name": "script_generation_agent",
                "current_config": {"temperature": 0.2, "max_tokens": 8192},
                "suggested_config": {"temperature": 0.15, "max_tokens": 8192},
                "reasoning": "适度降低随机性",
                "confidence": _CONFIDENCE_MEDIUM,
            })
        else:
            opts.append({
                "title": "维持当前策略配置",
                "description": "无失败案例,维持当前配置",
                "agent_name": "script_generation_agent",
                "current_config": {"temperature": 0.2, "max_tokens": 8192},
                "suggested_config": {"temperature": 0.2, "max_tokens": 8192},
                "reasoning": "当前配置运行良好",
                "confidence": _CONFIDENCE_MEDIUM,
            })

        return opts

    # ------------------------------------------------------------------
    # 生成总结
    # ------------------------------------------------------------------
    async def _generate_summary(
        self,
        success_analysis: Dict,
        failure_analysis: Dict,
        modification_analysis: Dict,
        rag_opts: Dict,
        prompt_opts: Dict,
        strategy_opts: Dict,
        cases: Dict,
    ) -> Dict[str, Any]:
        """生成反馈学习总结"""
        user_prompt = f"""反馈学习分析汇总:

1. 成功案例: {cases['success_count']} 条
   - 成功模式: {success_analysis.get('success_patterns', [])[:3]}

2. 失败案例: {cases['failure_count']} 条
   - 常见失败: {[f['pattern'] for f in failure_analysis.get('common_failures', [])[:3]]}

3. 人工修改: {cases['modification_count']} 条
   - 常见问题: {[i['issue'] for i in modification_analysis.get('common_issues', [])[:3]]}

4. RAG优化建议: {len(rag_opts.get('ids', []))} 条
5. Prompt优化建议: {len(prompt_opts.get('ids', []))} 条
6. 策略优化建议: {len(strategy_opts.get('ids', []))} 条

请生成总结报告,返回 JSON。"""

        try:
            response = await self.call_llm(
                system_prompt=self.SYSTEM_PROMPT_SUMMARY,
                user_prompt=user_prompt,
                temperature=0.4,
                max_tokens=2048,
            )
            parsed = self._parse_llm_json(response)
            if parsed:
                return parsed
        except Exception as e:
            logger.warning(f"[FeedbackLearningAgent] 总结生成 LLM 调用失败: {e}")

        # 回退
        return {
            "summary": (
                f"反馈学习完成: 成功{cases['success_count']}例, "
                f"失败{cases['failure_count']}例, "
                f"修改{cases['modification_count']}例。"
                f"生成RAG优化{len(rag_opts.get('ids', []))}条, "
                f"Prompt优化{len(prompt_opts.get('ids', []))}条, "
                f"策略优化{len(strategy_opts.get('ids', []))}条。"
            ),
            "key_insights": [
                f"成功案例主要来自{', '.join(list(success_analysis.get('type_distribution', {}).keys())[:3])}",
                f"主要失败原因为{', '.join(list(failure_analysis.get('error_type_distribution', {}).keys())[:3])}",
                f"人工修改主要集中在{', '.join(list(modification_analysis.get('source_distribution', {}).keys())[:3])}",
            ],
            "top_recommendations": [
                "应用RAG优化建议提升检索质量",
                "应用Prompt优化建议提升生成质量",
                "应用策略优化建议提升稳定性",
            ],
            "expected_improvements": "预计可提升生成成功率和减少人工修改",
        }

    # ------------------------------------------------------------------
    # 保存优化建议
    # ------------------------------------------------------------------
    async def _save_optimizations(
        self,
        optimizations: List[Dict[str, Any]],
        opt_type: str,
        record_ids: List[int],
        user_id: Optional[int] = None,
    ) -> List[int]:
        """保存优化建议到数据库"""
        from app.db.database import SessionLocal
        from app.models.feedback_learning import FeedbackOptimization

        saved_ids = []
        db = SessionLocal()
        try:
            for opt in optimizations:
                title = opt.get("title", f"{opt_type}优化建议")
                description = opt.get("description", "")
                agent_name = opt.get("agent_name")
                confidence = opt.get("confidence")

                # 构造 optimization_json(去掉已存为独立字段的)
                opt_json = {k: v for k, v in opt.items()
                            if k not in ("title", "description", "agent_name", "confidence")}
                summary = opt.get("reasoning", opt.get("change_summary", ""))

                optimization = FeedbackOptimization(
                    title=title,
                    description=description,
                    optimization_type=opt_type,
                    agent_name=agent_name,
                    optimization_json=json.dumps(opt_json, ensure_ascii=False),
                    source_record_ids=json.dumps(record_ids[:50], ensure_ascii=False),
                    summary=summary,
                    confidence=confidence,
                    status="pending",
                    user_id=user_id,
                    created_by=user_id,
                    is_deleted=False,
                )
                db.add(optimization)
                db.flush()
                saved_ids.append(optimization.id)

            db.commit()
            logger.info(
                f"[FeedbackLearningAgent] 保存{opt_type}优化建议 {len(saved_ids)} 条"
            )
        except Exception as e:
            db.rollback()
            logger.error(f"[FeedbackLearningAgent] 保存优化建议失败: {e}")
        finally:
            db.close()

        return saved_ids

    # ------------------------------------------------------------------
    # 更新任务状态
    # ------------------------------------------------------------------
    async def _update_optimization_status(
        self,
        optimization_id: int,
        status: str,
        summary: Optional[str] = None,
        optimization_ids: Optional[List[int]] = None,
        error: Optional[str] = None,
    ) -> None:
        """更新优化任务状态

        注: optimization_id 对应 FeedbackOptimization 表中的一条汇总记录,
        该记录在 service 层创建,agent 更新其状态和关联的优化建议ID列表。
        """
        from app.db.database import SessionLocal
        from app.models.feedback_learning import FeedbackOptimization

        db = SessionLocal()
        try:
            opt = db.query(FeedbackOptimization).filter(
                FeedbackOptimization.id == optimization_id
            ).first()
            if opt:
                opt.status = status
                if summary:
                    opt.summary = summary
                if optimization_ids is not None:
                    opt.applied_result = json.dumps(
                        {"optimization_ids": optimization_ids}, ensure_ascii=False
                    )
                if error:
                    opt.description = (opt.description or "") + f"\n错误: {error}"
                db.commit()
        except Exception as e:
            logger.error(f"[FeedbackLearningAgent] 更新任务状态失败: {e}")
            db.rollback()
        finally:
            db.close()

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_llm_json(response: str) -> Optional[Dict[str, Any]]:
        """解析 LLM 返回的 JSON"""
        if not response:
            return None
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass
        import re
        match = re.search(r'\{[\s\S]*\}', response)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return None
