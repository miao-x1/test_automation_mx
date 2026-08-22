"""
QualityAnalysisAgent - AI 测试质量分析 Agent

职责:
  接收测试资产、执行记录、缺陷数据,用 LLM 进行四维度质量分析:
  1. 覆盖不足分析(coverage_analysis): 模块覆盖率、未覆盖模块、按类型覆盖率
  2. 高风险模块分析(risk_analysis): 基于缺陷密度、失败率识别高风险模块
  3. 重复测试分析(duplication_analysis): 识别相似/重复的测试用例
  4. 缺陷趋势分析(defect_trend): 缺陷随时间变化趋势、按模块/类型分布

  综合输出:质量分数(0-100) + 改进建议

输入 (AgentRequest.payload):
  report_id:      报告ID (必填,用于回写结果)
  analysis_scope: 分析范围 (可选,JSON: {asset_ids, execution_ids, time_range, modules})
  user_id:        用户ID (可选)

输出 (AgentResponse.data):
  status / report_id / quality_score / summary / coverage_analysis /
  risk_analysis / duplication_analysis / defect_trend / recommendations
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

# 质量分数权重(四维度加权)
_QUALITY_WEIGHTS = {
    "coverage": 0.30,    # 覆盖率权重
    "risk": 0.25,        # 风险权重(越高越安全)
    "duplication": 0.20, # 重复度权重(越高越少重复)
    "defect": 0.25,      # 缺陷权重(越高缺陷越少)
}

# 重复度相似度阈值
_DUPLICATE_THRESHOLD = 0.75  # >= 0.75 视为重复


@default_subscription
class QualityAnalysisAgent(BaseRoutedAgent):
    """AI 测试质量分析 Agent

    使用方式:
      直接调用:  await agent.execute({"report_id": 1, "user_id": 1}, ctx)
      消息驱动:  await self.send_request("quality_analysis_agent", "analyze", payload)
    """

    SYSTEM_PROMPT_COVERAGE = """你是一位测试覆盖率分析专家。

任务: 分析测试资产与模块的覆盖情况,识别覆盖不足的模块和类型。

输出要求 (JSON 格式):
{
  "uncovered_modules": [
    {"module": "模块名", "reason": "未覆盖原因", "severity": "high/medium/low", "suggestion": "建议补充的用例"}
  ],
  "coverage_assessment": "整体覆盖率评估文字描述",
  "risk_areas": ["覆盖薄弱区域1", "覆盖薄弱区域2"],
  "suggestions": ["改进建议1", "改进建议2"]
}"""

    SYSTEM_PROMPT_RISK = """你是一位测试风险评估专家。

任务: 基于缺陷密度、失败率、模块复杂度,识别高风险模块。

输出要求 (JSON 格式):
{
  "high_risk_modules": [
    {"module": "模块名", "risk_score": 0.85, "reasons": ["原因1"], "defect_count": 5, "failure_rate": 0.3}
  ],
  "medium_risk_modules": [...],
  "risk_assessment": "整体风险评估文字描述",
  "suggestions": ["风险缓解建议1", "风险缓解建议2"]
}"""

    SYSTEM_PROMPT_DUPLICATION = """你是一位测试用例重复性分析专家。

任务: 分析测试用例的相似度,识别重复或高度相似的测试用例。

输出要求 (JSON 格式):
{
  "duplicate_groups": [
    {"group_id": "grp_1", "cases": ["用例A", "用例B"], "similarity": 0.9, "suggestion": "merge/remove"}
  ],
  "duplication_assessment": "整体重复度评估文字描述",
  "suggestions": ["去重建议1", "去重建议2"]
}"""

    SYSTEM_PROMPT_DEFECT = """你是一位缺陷趋势分析专家。

任务: 分析缺陷数据的时间趋势、模块分布、类型分布,预测未来趋势。

输出要求 (JSON 格式):
{
  "trend": "increasing/stable/decreasing",
  "trend_assessment": "趋势分析文字描述",
  "by_module": [
    {"module": "模块名", "count": 8, "top_errors": ["错误类型1"]}
  ],
  "by_type": {"assertion": 5, "timeout": 3, "element_not_found": 2},
  "predictions": "未来缺陷趋势预测",
  "suggestions": ["缺陷预防建议1", "缺陷预防建议2"]
}"""

    SYSTEM_PROMPT_SUMMARY = """你是一位测试质量分析专家。

任务: 基于四个维度的分析结果,生成综合质量评估报告。

输出要求 (JSON 格式):
{
  "summary": "200字以内的总体质量评估",
  "quality_assessment": "详细质量评估(500字以内)",
  "top_issues": ["最关键问题1", "最关键问题2", "最关键问题3"],
  "recommendations": ["改进建议1", "改进建议2", "改进建议3", "改进建议4", "改进建议5"]
}"""

    def __init__(self) -> None:
        super().__init__(
            description="AI测试质量分析Agent, 基于LLM进行覆盖/风险/重复/缺陷趋势四维度分析",
            display_name="QualityAnalysisAgent",
            capabilities=["quality_analysis", "coverage_analysis", "risk_analysis",
                          "duplication_analysis", "defect_trend_analysis"],
        )

    # ------------------------------------------------------------------
    # GraphFlow 入口(默认 execute action)
    # ------------------------------------------------------------------
    async def execute(
        self, payload: Dict[str, Any], ctx: MessageContext
    ) -> Dict[str, Any]:
        """主入口: 执行完整的质量分析"""
        return await self._do_analysis(payload)

    # ------------------------------------------------------------------
    # 消息处理器: analyze action
    # ------------------------------------------------------------------
    @message_handler
    async def handle_analyze(
        self, message: AgentRequest, ctx: MessageContext
    ) -> AgentResponse:
        """处理 analyze 请求"""
        start = time.time()
        request_id = message.request_id
        try:
            result = await self._do_analysis(message.payload)
            duration = time.time() - start
            if result.get("status") == "error":
                return AgentResponse(
                    request_id=request_id,
                    sender_type=self._agent_type,
                    status="error",
                    error=result.get("message", "分析失败"),
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
            logger.error(f"[QualityAnalysisAgent] 分析失败: {e}", exc_info=True)
            return AgentResponse(
                request_id=request_id,
                sender_type=self._agent_type,
                status="error",
                error=str(e),
                duration=duration,
            )

    # ------------------------------------------------------------------
    # 核心分析逻辑
    # ------------------------------------------------------------------
    async def _do_analysis(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """执行完整的质量分析流程"""
        report_id = payload.get("report_id")
        user_id = payload.get("user_id")
        analysis_scope = payload.get("analysis_scope", {})

        if report_id is None:
            return {"status": "error", "message": "report_id 不能为空"}

        logger.info(f"[QualityAnalysisAgent] 开始分析 report_id={report_id}")

        # 1. 收集输入数据
        input_data = await self._collect_input_data(analysis_scope, user_id)
        logger.info(
            f"[QualityAnalysisAgent] 收集数据: "
            f"assets={input_data['asset_count']}, "
            f"executions={input_data['execution_count']}, "
            f"defects={input_data['defect_count']}"
        )

        # 2. 更新报告状态为 analyzing
        await self._update_report_status(report_id, "analyzing", started=True)

        try:
            # 3. 四维度并行分析(LLM)
            coverage_result = await self._analyze_coverage(input_data)
            risk_result = await self._analyze_risk(input_data)
            duplication_result = await self._analyze_duplication(input_data)
            defect_result = await self._analyze_defect_trend(input_data)

            # 4. 计算分项分数
            coverage_score = self._compute_coverage_score(coverage_result, input_data)
            risk_score = self._compute_risk_score(risk_result)
            duplication_score = self._compute_duplication_score(duplication_result, input_data)
            defect_score = self._compute_defect_score(defect_result, input_data)

            # 5. 综合质量分数
            quality_score = (
                _QUALITY_WEIGHTS["coverage"] * coverage_score
                + _QUALITY_WEIGHTS["risk"] * risk_score
                + _QUALITY_WEIGHTS["duplication"] * duplication_score
                + _QUALITY_WEIGHTS["defect"] * defect_score
            )
            quality_score = round(quality_score, 2)

            # 6. 生成综合摘要
            summary_result = await self._generate_summary(
                coverage_result, risk_result, duplication_result,
                defect_result, quality_score, input_data
            )

            # 7. 保存到数据库
            await self._save_report(
                report_id=report_id,
                quality_score=quality_score,
                coverage_score=coverage_score,
                risk_score=risk_score,
                duplication_score=duplication_score,
                defect_score=defect_score,
                summary=summary_result.get("summary", ""),
                coverage_analysis=coverage_result,
                risk_analysis=risk_result,
                duplication_analysis=duplication_result,
                defect_trend=defect_result,
                recommendations=summary_result.get("recommendations", []),
                input_stats={
                    "asset_count": input_data["asset_count"],
                    "execution_count": input_data["execution_count"],
                    "defect_count": input_data["defect_count"],
                    "time_range": input_data.get("time_range"),
                    "modules": input_data.get("modules", []),
                },
            )

            # 8. 更新状态为 completed
            await self._update_report_status(report_id, "completed", completed=True)

            logger.info(
                f"[QualityAnalysisAgent] 分析完成 report_id={report_id} "
                f"quality_score={quality_score}"
            )

            return {
                "status": "success",
                "report_id": report_id,
                "quality_score": quality_score,
                "coverage_score": coverage_score,
                "risk_score": risk_score,
                "duplication_score": duplication_score,
                "defect_score": defect_score,
                "summary": summary_result.get("summary", ""),
                "coverage_analysis": coverage_result,
                "risk_analysis": risk_result,
                "duplication_analysis": duplication_result,
                "defect_trend": defect_result,
                "recommendations": summary_result.get("recommendations", []),
            }

        except Exception as e:
            logger.error(f"[QualityAnalysisAgent] 分析失败: {e}", exc_info=True)
            await self._update_report_status(
                report_id, "failed", completed=True, error=str(e)
            )
            return {"status": "error", "message": str(e), "report_id": report_id}

    # ------------------------------------------------------------------
    # 数据收集
    # ------------------------------------------------------------------
    async def _collect_input_data(
        self, analysis_scope: Dict[str, Any], user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """从数据库收集测试资产、执行记录、缺陷数据"""
        from app.db.database import SessionLocal
        from app.models.test_asset import TestAsset
        from app.models.execution_record import ExecutionRecord
        from app.models.flow_result import FlowResult

        db = SessionLocal()
        try:
            asset_ids = analysis_scope.get("asset_ids", [])
            execution_ids = analysis_scope.get("execution_ids", [])
            time_range = analysis_scope.get("time_range", {})
            modules = analysis_scope.get("modules", [])
            asset_types = analysis_scope.get("asset_types", [])

            # 1. 收集测试资产
            asset_query = db.query(TestAsset).filter(TestAsset.is_deleted == False)
            if user_id is not None:
                asset_query = asset_query.filter(TestAsset.user_id == user_id)
            if asset_ids:
                asset_query = asset_query.filter(TestAsset.id.in_(asset_ids))
            if asset_types:
                asset_query = asset_query.filter(TestAsset.asset_type.in_(asset_types))

            assets = asset_query.all()
            asset_list = []
            for a in assets:
                content = {}
                if a.content_json:
                    try:
                        content = json.loads(a.content_json)
                    except (json.JSONDecodeError, TypeError):
                        pass
                asset_list.append({
                    "id": a.id,
                    "title": a.title,
                    "asset_type": a.asset_type,
                    "status": a.status,
                    "executable": a.executable,
                    "priority": a.priority,
                    "tags": a.tags,
                    "module": self._extract_module(a, content),
                    "content": content,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                    "updated_at": a.updated_at.isoformat() if a.updated_at else None,
                })

            # 2. 收集执行记录
            exec_query = db.query(ExecutionRecord)
            if user_id is not None:
                exec_query = exec_query.filter(ExecutionRecord.user_id == user_id)
            if execution_ids:
                exec_query = exec_query.filter(ExecutionRecord.id.in_(execution_ids))
            if time_range and time_range.get("start"):
                exec_query = exec_query.filter(
                    ExecutionRecord.created_at >= time_range["start"]
                )
            if time_range and time_range.get("end"):
                exec_query = exec_query.filter(
                    ExecutionRecord.created_at <= time_range["end"]
                )

            executions = exec_query.order_by(ExecutionRecord.created_at.desc()).limit(500).all()
            exec_list = []
            for e in executions:
                exec_list.append({
                    "id": e.id,
                    "status": e.status,
                    "execution_type": e.execution_type,
                    "success_count": e.success_count or 0,
                    "failed_count": e.failed_count or 0,
                    "error_message": e.error_message or "",
                    "log_content": (e.log_content or "")[:2000],  # 截断避免过长
                    "analysis_result": e.analysis_result or "",
                    "duration": e.duration or 0,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                })

            # 3. 收集缺陷数据(从 flow_result 表)
            defect_query = db.query(FlowResult).filter(
                FlowResult.message_type == "DefectMessage"
            )
            if user_id is not None:
                defect_query = defect_query.filter(FlowResult.task_id.isnot(None))

            defects = defect_query.order_by(FlowResult.created_at.desc()).limit(500).all()
            defect_list = []
            for d in defects:
                output = {}
                if d.output_json:
                    try:
                        output = json.loads(d.output_json)
                    except (json.JSONDecodeError, TypeError):
                        pass
                defect_list.append({
                    "id": d.id,
                    "task_id": d.task_id,
                    "output": output,
                    "status": d.status,
                    "error_message": d.error_message or "",
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                })

            # 4. 从执行记录的 error_message / log_content 中提取隐含缺陷
            implied_defects = self._extract_implied_defects(exec_list)

            # 合并显式缺陷和隐含缺陷
            all_defects = defect_list + implied_defects

            return {
                "assets": asset_list,
                "asset_count": len(asset_list),
                "executions": exec_list,
                "execution_count": len(exec_list),
                "defects": all_defects,
                "defect_count": len(all_defects),
                "time_range": time_range,
                "modules": modules or self._extract_all_modules(asset_list),
            }
        finally:
            db.close()

    def _extract_module(self, asset: Any, content: Dict) -> str:
        """从资产中提取模块名"""
        # 优先从 content 中提取
        if content and isinstance(content, dict):
            if content.get("module"):
                return content["module"]
            tags = content.get("tags", [])
            if tags and isinstance(tags, list) and len(tags) > 0:
                return tags[0]
        # 从 asset.tags 提取
        if asset.tags:
            tags_list = asset.tags.split(",")
            if tags_list and tags_list[0].strip():
                return tags_list[0].strip()
        # 从 title 推断
        if asset.title:
            # 简单提取:第一个词或冒号前部分
            title = asset.title.split("：")[0].split(":")[0]
            parts = title.split()
            if parts:
                return parts[0]
        return "default"

    def _extract_all_modules(self, asset_list: List[Dict]) -> List[str]:
        """从资产列表提取所有模块"""
        modules = set()
        for a in asset_list:
            mod = a.get("module", "default")
            modules.add(mod)
        return sorted(list(modules))

    def _extract_implied_defects(self, executions: List[Dict]) -> List[Dict]:
        """从执行记录的 error_message / log_content 中提取隐含缺陷"""
        implied = []
        for e in executions:
            if e.get("status") not in ("failed", "error"):
                continue
            error_msg = e.get("error_message", "")
            log_content = e.get("log_content", "")

            # 从日志中提取 ##TEST_FAIL## 行
            fail_lines = []
            if log_content:
                for line in log_content.split("\n"):
                    if "##TEST_FAIL##" in line or "FAILED" in line.upper():
                        fail_lines.append(line.strip()[:200])

            # 确定错误类型
            error_type = "unknown"
            combined = (error_msg + " " + log_content).lower()
            if "timeout" in combined or "timed out" in combined:
                error_type = "timeout"
            elif "assert" in combined:
                error_type = "assertion"
            elif "element not found" in combined or "no such element" in combined:
                error_type = "element_not_found"
            elif "connection" in combined or "refused" in combined:
                error_type = "connection"
            elif "syntax" in combined or "syntaxerror" in combined:
                error_type = "syntax"

            if error_msg or fail_lines:
                implied.append({
                    "id": None,
                    "task_id": e.get("id"),
                    "output": {
                        "error_type": error_type,
                        "error_message": error_msg[:500] if error_msg else "",
                        "fail_lines": fail_lines[:5],
                        "severity": "high" if error_type in ("assertion", "timeout") else "medium",
                    },
                    "status": "failed",
                    "error_message": error_msg[:500] if error_msg else "",
                    "created_at": e.get("created_at"),
                })

        return implied

    # ------------------------------------------------------------------
    # 四维度分析(LLM 调用)
    # ------------------------------------------------------------------
    async def _analyze_coverage(self, input_data: Dict) -> Dict[str, Any]:
        """覆盖不足分析"""
        assets = input_data["assets"]
        modules = input_data["modules"]

        # 统计覆盖率
        module_coverage = defaultdict(lambda: {"total": 0, "executable": 0})
        type_coverage = defaultdict(lambda: {"total": 0, "executable": 0})

        for a in assets:
            mod = a.get("module", "default")
            module_coverage[mod]["total"] += 1
            if a.get("executable"):
                module_coverage[mod]["executable"] += 1

            atype = a.get("asset_type", "unknown")
            type_coverage[atype]["total"] += 1
            if a.get("executable"):
                type_coverage[atype]["executable"] += 1

        # 计算覆盖率
        covered_modules = sum(1 for m in module_coverage.values() if m["executable"] > 0)
        total_modules = len(module_coverage) if module_coverage else 1
        coverage_rate = covered_modules / total_modules if total_modules > 0 else 0

        # 准备 LLM 输入
        module_summary = []
        for mod, stats in module_coverage.items():
            rate = stats["executable"] / stats["total"] if stats["total"] > 0 else 0
            module_summary.append({
                "module": mod,
                "total_cases": stats["total"],
                "executable_cases": stats["executable"],
                "coverage_rate": round(rate, 4),
            })

        type_summary = {}
        for atype, stats in type_coverage.items():
            rate = stats["executable"] / stats["total"] if stats["total"] > 0 else 0
            type_summary[atype] = round(rate, 4)

        # 调用 LLM 分析
        user_prompt = f"""测试资产数据:
- 总资产数: {len(assets)}
- 模块数: {total_modules}
- 已覆盖模块: {covered_modules}
- 覆盖率: {coverage_rate:.2%}

模块覆盖明细:
{json.dumps(module_summary, ensure_ascii=False, indent=2)}

按类型覆盖:
{json.dumps(type_summary, ensure_ascii=False, indent=2)}

请分析覆盖不足的模块和类型,返回 JSON。"""

        try:
            response = await self.call_llm(
                system_prompt=self.SYSTEM_PROMPT_COVERAGE,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=2048,
            )
            parsed = self._parse_llm_json(response)
            if parsed:
                parsed["coverage_rate"] = round(coverage_rate, 4)
                parsed["total_modules"] = total_modules
                parsed["covered_modules"] = covered_modules
                parsed["by_type"] = type_summary
                return parsed
        except Exception as e:
            logger.warning(f"[QualityAnalysisAgent] 覆盖分析 LLM 调用失败: {e}")

        # 回退:返回统计结果
        return {
            "coverage_rate": round(coverage_rate, 4),
            "total_modules": total_modules,
            "covered_modules": covered_modules,
            "uncovered_modules": [
                {"module": m, "reason": "无可执行用例", "severity": "medium"}
                for m, s in module_coverage.items() if s["executable"] == 0
            ],
            "by_type": type_summary,
            "suggestions": ["补充未覆盖模块的测试用例"],
        }

    async def _analyze_risk(self, input_data: Dict) -> Dict[str, Any]:
        """高风险模块分析"""
        assets = input_data["assets"]
        defects = input_data["defects"]
        executions = input_data["executions"]

        # 按模块统计缺陷密度
        module_defects = defaultdict(int)
        module_failures = defaultdict(int)
        module_total = defaultdict(int)

        for d in defects:
            output = d.get("output", {})
            mod = output.get("module", "default")
            module_defects[mod] += 1

        for e in executions:
            # 从执行记录提取模块(简化:用 execution_type)
            mod = e.get("execution_type", "unknown")
            module_total[mod] += 1
            if e.get("status") in ("failed", "error"):
                module_failures[mod] += 1

        # 合并所有模块
        all_modules = set(list(module_defects.keys()) + list(module_failures.keys()))
        risk_data = []
        for mod in all_modules:
            defect_count = module_defects.get(mod, 0)
            total = module_total.get(mod, 1)
            failures = module_failures.get(mod, 0)
            failure_rate = failures / total if total > 0 else 0
            # 风险分数 = 缺陷密度 * 0.6 + 失败率 * 0.4
            risk_score = min(1.0, (defect_count / max(total, 1)) * 0.6 + failure_rate * 0.4)
            risk_data.append({
                "module": mod,
                "defect_count": defect_count,
                "failure_count": failures,
                "total_executions": total,
                "failure_rate": round(failure_rate, 4),
                "risk_score": round(risk_score, 4),
            })

        risk_data.sort(key=lambda x: x["risk_score"], reverse=True)

        # 调用 LLM 分析
        user_prompt = f"""模块风险数据:
{json.dumps(risk_data[:20], ensure_ascii=False, indent=2)}

缺陷总数: {len(defects)}
执行记录总数: {len(executions)}

请识别高风险模块,返回 JSON。"""

        try:
            response = await self.call_llm(
                system_prompt=self.SYSTEM_PROMPT_RISK,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=2048,
            )
            parsed = self._parse_llm_json(response)
            if parsed:
                parsed["risk_distribution"] = {
                    "high": sum(1 for r in risk_data if r["risk_score"] >= 0.7),
                    "medium": sum(1 for r in risk_data if 0.3 <= r["risk_score"] < 0.7),
                    "low": sum(1 for r in risk_data if r["risk_score"] < 0.3),
                }
                return parsed
        except Exception as e:
            logger.warning(f"[QualityAnalysisAgent] 风险分析 LLM 调用失败: {e}")

        # 回退
        return {
            "high_risk_modules": [r for r in risk_data if r["risk_score"] >= 0.7][:5],
            "medium_risk_modules": [r for r in risk_data if 0.3 <= r["risk_score"] < 0.7][:10],
            "risk_distribution": {
                "high": sum(1 for r in risk_data if r["risk_score"] >= 0.7),
                "medium": sum(1 for r in risk_data if 0.3 <= r["risk_score"] < 0.7),
                "low": sum(1 for r in risk_data if r["risk_score"] < 0.3),
            },
            "suggestions": ["关注高风险模块,增加测试覆盖"],
        }

    async def _analyze_duplication(self, input_data: Dict) -> Dict[str, Any]:
        """重复测试分析"""
        assets = input_data["assets"]

        # 基于标题和模块计算相似度
        groups = []
        used_indices = set()

        for i, a in enumerate(assets):
            if i in used_indices:
                continue
            group = [a]
            used_indices.add(i)
            for j in range(i + 1, len(assets)):
                if j in used_indices:
                    continue
                b = assets[j]
                sim = self._compute_similarity(a, b)
                if sim >= _DUPLICATE_THRESHOLD:
                    group.append(b)
                    used_indices.add(j)
            if len(group) > 1:
                groups.append({
                    "group_id": f"grp_{len(groups) + 1}",
                    "cases": [g["title"] for g in group],
                    "similarity": round(
                        sum(self._compute_similarity(group[0], g) for g in group[1:]) / max(len(group) - 1, 1), 4
                    ),
                    "suggestion": "merge",
                })

        duplication_rate = len(sum([g["cases"] for g in groups], [])) / max(len(assets), 1)

        # 调用 LLM 分析
        user_prompt = f"""测试用例总数: {len(assets)}
初步识别重复组: {len(groups)}
重复用例数: {sum(len(g['cases']) for g in groups)}
重复率: {duplication_rate:.2%}

重复组明细:
{json.dumps(groups[:10], ensure_ascii=False, indent=2)}

请分析重复测试情况,返回 JSON。"""

        try:
            response = await self.call_llm(
                system_prompt=self.SYSTEM_PROMPT_DUPLICATION,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=2048,
            )
            parsed = self._parse_llm_json(response)
            if parsed:
                parsed["total_cases"] = len(assets)
                parsed["duplicate_count"] = sum(len(g["cases"]) for g in groups)
                parsed["duplication_rate"] = round(duplication_rate, 4)
                return parsed
        except Exception as e:
            logger.warning(f"[QualityAnalysisAgent] 重复分析 LLM 调用失败: {e}")

        return {
            "duplicate_groups": groups,
            "total_cases": len(assets),
            "duplicate_count": sum(len(g["cases"]) for g in groups),
            "duplication_rate": round(duplication_rate, 4),
            "suggestions": ["合并重复用例,减少维护成本"],
        }

    async def _analyze_defect_trend(self, input_data: Dict) -> Dict[str, Any]:
        """缺陷趋势分析"""
        defects = input_data["defects"]

        # 按时间分组(按月)
        by_period = defaultdict(lambda: {"count": 0, "high": 0, "medium": 0, "low": 0})
        by_type = defaultdict(int)
        by_module = defaultdict(lambda: {"count": 0, "errors": []})

        for d in defects:
            created = d.get("created_at")
            if created:
                try:
                    dt = datetime.fromisoformat(created.replace("Z", ""))
                    period = dt.strftime("%Y-%m")
                except (ValueError, TypeError):
                    period = "unknown"
            else:
                period = "unknown"

            output = d.get("output", {})
            severity = output.get("severity", "medium")
            error_type = output.get("error_type", "unknown")
            module = output.get("module", "default")

            by_period[period]["count"] += 1
            if severity in by_period[period]:
                by_period[period][severity] += 1

            by_type[error_type] += 1
            by_module[module]["count"] += 1
            if error_type not in by_module[module]["errors"]:
                by_module[module]["errors"].append(error_type)

        # 趋势判断
        periods = sorted([p for p in by_period.keys() if p != "unknown"])
        if len(periods) >= 2:
            recent = by_period[periods[-1]]["count"]
            previous = by_period[periods[-2]]["count"]
            if recent > previous * 1.2:
                trend = "increasing"
            elif recent < previous * 0.8:
                trend = "decreasing"
            else:
                trend = "stable"
        else:
            trend = "stable"

        # 调用 LLM 分析
        period_data = [{"period": p, **stats} for p, stats in sorted(by_period.items())]
        module_data = [
            {"module": m, "count": v["count"], "top_errors": v["errors"][:3]}
            for m, v in sorted(by_module.items(), key=lambda x: x[1]["count"], reverse=True)
        ]

        user_prompt = f"""缺陷数据统计:
- 缺陷总数: {len(defects)}
- 趋势: {trend}

按月分布:
{json.dumps(period_data, ensure_ascii=False, indent=2)}

按模块分布:
{json.dumps(module_data, ensure_ascii=False, indent=2)}

按类型分布:
{json.dumps(dict(by_type), ensure_ascii=False, indent=2)}

请分析缺陷趋势,返回 JSON。"""

        try:
            response = await self.call_llm(
                system_prompt=self.SYSTEM_PROMPT_DEFECT,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=2048,
            )
            parsed = self._parse_llm_json(response)
            if parsed:
                parsed["trend"] = trend
                parsed["by_type"] = dict(by_type)
                return parsed
        except Exception as e:
            logger.warning(f"[QualityAnalysisAgent] 缺陷趋势 LLM 调用失败: {e}")

        return {
            "trend": trend,
            "by_period": period_data,
            "by_module": module_data,
            "by_type": dict(by_type),
            "suggestions": ["持续监控缺陷趋势"],
        }

    async def _generate_summary(
        self, coverage: Dict, risk: Dict, duplication: Dict,
        defect: Dict, quality_score: float, input_data: Dict
    ) -> Dict[str, Any]:
        """生成综合摘要"""
        user_prompt = f"""质量分析结果汇总:

1. 覆盖率分析:
   - 总模块数: {coverage.get('total_modules', 0)}
   - 已覆盖: {coverage.get('covered_modules', 0)}
   - 覆盖率: {coverage.get('coverage_rate', 0):.2%}
   - 未覆盖模块: {len(coverage.get('uncovered_modules', []))}

2. 风险分析:
   - 高风险模块: {len(risk.get('high_risk_modules', []))}
   - 中风险模块: {len(risk.get('medium_risk_modules', []))}

3. 重复测试:
   - 总用例数: {duplication.get('total_cases', 0)}
   - 重复用例: {duplication.get('duplicate_count', 0)}
   - 重复率: {duplication.get('duplication_rate', 0):.2%}

4. 缺陷趋势:
   - 趋势: {defect.get('trend', 'stable')}
   - 缺陷类型: {defect.get('by_type', {})}

综合质量分数: {quality_score}/100

输入数据: 资产 {input_data['asset_count']} 条, 执行记录 {input_data['execution_count']} 条, 缺陷 {input_data['defect_count']} 条

请生成综合质量评估报告,返回 JSON。"""

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
            logger.warning(f"[QualityAnalysisAgent] 摘要生成 LLM 调用失败: {e}")

        # 回退
        level = "优秀" if quality_score >= 80 else "良好" if quality_score >= 60 else "一般" if quality_score >= 40 else "需改进"
        return {
            "summary": f"质量评估: {level}({quality_score}/100)。覆盖率 {coverage.get('coverage_rate', 0):.2%},重复率 {duplication.get('duplication_rate', 0):.2%},缺陷趋势 {defect.get('trend', 'stable')}。",
            "quality_assessment": f"综合质量分数 {quality_score}/100,评级 {level}。",
            "top_issues": [],
            "recommendations": [
                "补充未覆盖模块的测试用例",
                "关注高风险模块的稳定性",
                "合并重复测试用例",
                "持续监控缺陷趋势",
            ],
        }

    # ------------------------------------------------------------------
    # 分数计算
    # ------------------------------------------------------------------
    def _compute_coverage_score(self, coverage: Dict, input_data: Dict) -> float:
        """计算覆盖率分数(0-100)"""
        rate = coverage.get("coverage_rate", 0)
        return round(rate * 100, 2)

    def _compute_risk_score(self, risk: Dict) -> float:
        """计算风险分数(0-100,越高越安全)"""
        distribution = risk.get("risk_distribution", {})
        high = distribution.get("high", 0)
        medium = distribution.get("medium", 0)
        low = distribution.get("low", 0)
        total = high + medium + low
        if total == 0:
            return 80.0  # 无风险数据,默认较高
        # 风险分数 = (低风险占比 * 100 + 中风险占比 * 60 + 高风险占比 * 20)
        score = (low * 100 + medium * 60 + high * 20) / total
        return round(score, 2)

    def _compute_duplication_score(self, duplication: Dict, input_data: Dict) -> float:
        """计算重复度分数(0-100,越高越少重复)"""
        rate = duplication.get("duplication_rate", 0)
        # 重复率越高,分数越低
        return round(max(0, 100 - rate * 200), 2)

    def _compute_defect_score(self, defect: Dict, input_data: Dict) -> float:
        """计算缺陷分数(0-100,越高缺陷越少)"""
        trend = defect.get("trend", "stable")
        defect_count = input_data.get("defect_count", 0)
        execution_count = input_data.get("execution_count", 1)

        # 基础分:缺陷率越低越高
        defect_rate = defect_count / max(execution_count, 1)
        base_score = max(0, 100 - defect_rate * 100)

        # 趋势调整
        if trend == "decreasing":
            base_score = min(100, base_score + 10)
        elif trend == "increasing":
            base_score = max(0, base_score - 10)

        return round(base_score, 2)

    # ------------------------------------------------------------------
    # 相似度计算
    # ------------------------------------------------------------------
    def _compute_similarity(self, a: Dict, b: Dict) -> float:
        """计算两个测试用例的相似度(0-1)"""
        # 标题相似度(简单词重叠)
        title_a = set(a.get("title", "").lower().split())
        title_b = set(b.get("title", "").lower().split())
        if title_a and title_b:
            title_sim = len(title_a & title_b) / max(len(title_a | title_b), 1)
        else:
            title_sim = 0

        # 模块相似度
        mod_a = a.get("module", "")
        mod_b = b.get("module", "")
        mod_sim = 1.0 if mod_a == mod_b and mod_a else 0.0

        # 类型相似度
        type_a = a.get("asset_type", "")
        type_b = b.get("asset_type", "")
        type_sim = 1.0 if type_a == type_b and type_a else 0.0

        # 加权:标题 0.5 + 模块 0.3 + 类型 0.2
        return title_sim * 0.5 + mod_sim * 0.3 + type_sim * 0.2

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_llm_json(response: str) -> Optional[Dict[str, Any]]:
        """解析 LLM 返回的 JSON"""
        if not response:
            return None
        # 尝试直接解析
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass
        # 尝试提取 JSON 块
        import re
        match = re.search(r'\{[\s\S]*\}', response)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return None

    async def _update_report_status(
        self, report_id: int, status: str,
        started: bool = False, completed: bool = False,
        error: Optional[str] = None
    ) -> None:
        """更新报告状态"""
        from app.db.database import SessionLocal
        from app.models.quality_report import QualityReport
        from datetime import datetime

        db = SessionLocal()
        try:
            report = db.query(QualityReport).filter(QualityReport.id == report_id).first()
            if report:
                report.status = status
                if started:
                    report.started_at = datetime.now()
                if completed:
                    report.completed_at = datetime.now()
                if error:
                    report.error_message = error
                db.commit()
        except Exception as e:
            logger.error(f"[QualityAnalysisAgent] 更新报告状态失败: {e}")
            db.rollback()
        finally:
            db.close()

    async def _save_report(
        self, report_id: int, quality_score: float,
        coverage_score: float, risk_score: float,
        duplication_score: float, defect_score: float,
        summary: str, coverage_analysis: Dict, risk_analysis: Dict,
        duplication_analysis: Dict, defect_trend: Dict,
        recommendations: List[str], input_stats: Dict
    ) -> None:
        """保存分析结果到数据库"""
        from app.db.database import SessionLocal
        from app.models.quality_report import QualityReport

        db = SessionLocal()
        try:
            report = db.query(QualityReport).filter(QualityReport.id == report_id).first()
            if report:
                report.quality_score = quality_score
                report.coverage_score = coverage_score
                report.risk_score = risk_score
                report.duplication_score = duplication_score
                report.defect_score = defect_score
                report.summary = summary
                report.coverage_analysis = json.dumps(coverage_analysis, ensure_ascii=False)
                report.risk_analysis = json.dumps(risk_analysis, ensure_ascii=False)
                report.duplication_analysis = json.dumps(duplication_analysis, ensure_ascii=False)
                report.defect_trend = json.dumps(defect_trend, ensure_ascii=False)
                report.recommendations = json.dumps(recommendations, ensure_ascii=False)
                report.input_stats = json.dumps(input_stats, ensure_ascii=False)
                db.commit()
                logger.info(f"[QualityAnalysisAgent] 报告已保存 report_id={report_id}")
        except Exception as e:
            logger.error(f"[QualityAnalysisAgent] 保存报告失败: {e}")
            db.rollback()
        finally:
            db.close()
