"""
ApiDebugAgent - AI 接口调试分析 Agent

职责:
  接收单次 HTTP 接口执行结果,用 LLM 分析失败原因,
  输出: 问题原因 / 解决方案 / 修复建议

架构:
  Agent → LLM (call_llm_json) → 分析报告
  Agent → 规则引擎 (降级,LLM 失败时使用)

输入 (payload):
  record_id:    执行记录 ID (必填,从 DB 加载完整记录)
  或
  request:      {method, url, headers, body, params}
  response:     {status_code, headers, body, elapsed_ms}
  error:        错误信息
  status:       success/failed/error/timeout
  api_id:       关联接口 ID (可选)

输出:
  status:           success / error / degraded
  problem_cause:    问题原因
  solution:         解决方案
  fix_suggestion:   修复建议 (代码级)
  confidence:       置信度 0-1
  source:           llm / rule_engine
  elapsed_ms:       分析耗时

降级策略:
  LLM 调用失败 → 规则引擎分析 → 返回 degraded
"""
import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from autogen_core import MessageContext, default_subscription

from app.runtime.base_agent import BaseRoutedAgent, action_handler

logger = logging.getLogger(__name__)


# ============================================================
# 规则引擎: 常见错误模式
# ============================================================

_ERROR_PATTERNS: List[Dict[str, Any]] = [
    {
        "id": "CONN_REFUSED",
        "match_keywords": ["connection refused", "connecterror", "connectionerror", "max retries exceeded"],
        "problem_cause": "目标服务未启动或端口不通,连接被拒绝",
        "solution": "1) 检查服务是否运行 2) 确认端口与主机 3) 检查防火墙",
        "fix_suggestion": "确认 base_url 正确,目标服务监听端口可达",
        "confidence": 0.85,
    },
    {
        "id": "DNS_RESOLVE",
        "match_keywords": ["name or service not known", "nodename nor servname", "getaddrinfo", "name resolution"],
        "problem_cause": "域名解析失败,无法解析主机名",
        "solution": "1) 检查 URL 拼写 2) 检查 DNS 配置 3) 使用 IP 直连验证",
        "fix_suggestion": "改用正确域名,或在 hosts 文件添加映射",
        "confidence": 0.8,
    },
    {
        "id": "TIMEOUT",
        "match_keywords": ["timeout", "timed out", "read timeout"],
        "problem_cause": "请求超时,服务端响应过慢或网络延迟",
        "solution": "1) 增加 timeout 参数 2) 检查服务端性能 3) 检查网络延迟",
        "fix_suggestion": "在请求中设置 timeout=30,或检查服务端日志",
        "confidence": 0.8,
    },
    {
        "id": "SSL_ERROR",
        "match_keywords": ["ssl", "certificate", "cert", "ssl: certificate_verify_failed"],
        "problem_cause": "SSL/TLS 证书验证失败",
        "solution": "1) 检查证书有效性 2) 临时跳过 verify(仅测试) 3) 更新 CA 证书",
        "fix_suggestion": "verify=False(仅开发),或更新 cacert.pem",
        "confidence": 0.85,
    },
    {
        "id": "AUTH_401",
        "match_keywords": ["401", "unauthorized", "authentication"],
        "problem_cause": "认证失败,缺少或无效的认证信息",
        "solution": "1) 检查 Authorization 头 2) 确认 token 有效 3) 重新登录获取 token",
        "fix_suggestion": "添加 'Authorization': 'Bearer <token>' 请求头",
        "confidence": 0.9,
    },
    {
        "id": "FORBIDDEN_403",
        "match_keywords": ["403", "forbidden"],
        "problem_cause": "权限不足,账号无访问该资源的权限",
        "solution": "1) 检查账号权限 2) 联系管理员授权 3) 切换有权限的账号",
        "fix_suggestion": "确认当前账号角色有权访问该接口",
        "confidence": 0.85,
    },
    {
        "id": "NOT_FOUND_404",
        "match_keywords": ["404", "not found"],
        "problem_cause": "接口路径不存在或已变更",
        "solution": "1) 检查 URL 拼写 2) 确认接口版本 3) 查阅最新 API 文档",
        "fix_suggestion": "核对接口文档中的 path,检查是否有多余/缺失的斜杠",
        "confidence": 0.9,
    },
    {
        "id": "VALIDATION_422",
        "match_keywords": ["422", "unprocessable entity", "validation"],
        "problem_cause": "请求参数校验失败,字段缺失或格式错误",
        "solution": "1) 检查必填字段 2) 检查字段类型与格式 3) 对照 Schema 校验",
        "fix_suggestion": "对照接口 Schema,补全必填字段,修正类型错误",
        "confidence": 0.85,
    },
    {
        "id": "RATE_LIMIT_429",
        "match_keywords": ["429", "too many requests", "rate limit"],
        "problem_cause": "请求频率超限,被限流",
        "solution": "1) 降低请求频率 2) 增加间隔 3) 申请提升配额",
        "fix_suggestion": "在请求间增加 sleep,或使用指数退避",
        "confidence": 0.9,
    },
    {
        "id": "SERVER_500",
        "match_keywords": ["500", "internal server error"],
        "problem_cause": "服务端内部错误,可能是代码异常或数据库故障",
        "solution": "1) 查看服务端日志 2) 联系后端开发 3) 稍后重试",
        "fix_suggestion": "向服务端反馈 request_id,排查服务端异常堆栈",
        "confidence": 0.75,
    },
    {
        "id": "BAD_GATEWAY_502",
        "match_keywords": ["502", "bad gateway"],
        "problem_cause": "网关错误,上游服务不可用",
        "solution": "1) 检查上游服务 2) 检查网关配置 3) 稍后重试",
        "fix_suggestion": "确认上游服务实例健康,网关路由正确",
        "confidence": 0.8,
    },
    {
        "id": "JSON_PARSE",
        "match_keywords": ["json", "jsondecodeerror", "expecting value"],
        "problem_cause": "响应体非合法 JSON,无法解析",
        "solution": "1) 检查响应内容类型 2) 确认服务端返回 JSON 3) 处理 HTML 错误页",
        "fix_suggestion": "在代码中 try/except json.JSONDecodeError,先检查 content-type",
        "confidence": 0.8,
    },
]


@default_subscription
class ApiDebugAgent(BaseRoutedAgent):
    """AI 接口调试 Agent

    分析单次 HTTP 接口执行结果,输出问题原因 / 解决方案 / 修复建议

    使用方式:
      直接调用:  await agent.execute({"record_id": 123}, ctx)
      消息驱动:  await self.send_request("api_debug_agent", "analyze", payload)
      持久化:    分析结果自动回写到 api_execution_record.analysis_result
    """

    def __init__(self) -> None:
        super().__init__(
            description="AI 接口调试 Agent - 分析 HTTP 执行结果,输出问题原因/解决方案/修复建议",
            display_name="ApiDebugAgent",
            capabilities=["debug", "failure_analysis", "llm_reasoning"],
        )

    # ------------------------------------------------------------------
    # GraphFlow 入口
    # ------------------------------------------------------------------

    async def execute(
        self, payload: Dict[str, Any], ctx: MessageContext
    ) -> Dict[str, Any]:
        """GraphFlow 入口: 按 action 分派"""
        action = payload.get("action", "analyze")
        if action == "analyze":
            return await self._do_analyze(payload)
        elif action == "health":
            return await self._do_health()
        elif action == "list_patterns":
            return self._do_list_patterns()
        else:
            return {"status": "error", "message": f"未知 action: {action}"}

    # ------------------------------------------------------------------
    # action handlers (供其他 Agent 通过 send_request 调用)
    # ------------------------------------------------------------------

    @action_handler("analyze")
    async def handle_analyze(
        self, payload: Dict[str, Any], ctx: MessageContext
    ) -> Dict[str, Any]:
        """分析执行结果"""
        return await self._do_analyze(payload)

    @action_handler("health")
    async def handle_health(
        self, payload: Dict[str, Any], ctx: MessageContext
    ) -> Dict[str, Any]:
        return await self._do_health()

    # ------------------------------------------------------------------
    # 核心分析逻辑
    # ------------------------------------------------------------------

    async def _do_analyze(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """执行分析

        步骤:
          1. 加载执行记录 (从 record_id 或直接使用 payload)
          2. 判断是否需要分析 (success 可选分析,failed/error/timeout 必分析)
          3. 调用 LLM 分析,失败则降级到规则引擎
          4. 持久化结果到 api_execution_record
        """
        start = time.time()
        record_id = payload.get("record_id")
        force = payload.get("force", False)

        # 1. 加载执行记录
        record = await self._load_record(record_id, payload)
        if not record:
            return {
                "status": "error",
                "message": f"执行记录不存在: record_id={record_id}",
            }

        status = record.get("status", "failed")
        # 成功的请求默认不分析(除非 force)
        if status == "success" and not force:
            return {
                "status": "skipped",
                "message": "请求成功,无需分析(可设置 force=true 强制分析)",
                "record_id": record_id,
            }

        # 2. 标记分析中
        if record_id:
            await self._update_analysis_status(record_id, "analyzing")

        # 3. 优先 LLM 分析,失败降级到规则引擎
        try:
            result = await self._analyze_with_llm(record)
            source = "llm"
        except Exception as e:
            logger.warning(f"[ApiDebugAgent] LLM 分析失败,降级到规则引擎: {e}")
            result = self._analyze_with_rules(record)
            source = "rule_engine"

        elapsed_ms = int((time.time() - start) * 1000)
        result["record_id"] = record_id
        result["source"] = source
        result["elapsed_ms"] = elapsed_ms
        result["status"] = "success" if source == "llm" else "degraded"

        # 4. 持久化分析结果
        if record_id:
            try:
                await self._persist_analysis(record_id, result)
            except Exception as e:
                logger.error(f"[ApiDebugAgent] 持久化分析结果失败: {e}")

        logger.info(
            f"[ApiDebugAgent] 分析完成 record_id={record_id} "
            f"source={source} confidence={result.get('confidence')} "
            f"elapsed_ms={elapsed_ms}"
        )
        return result

    # ------------------------------------------------------------------
    # LLM 分析
    # ------------------------------------------------------------------

    async def _analyze_with_llm(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """使用 LLM 分析执行结果"""
        system_prompt = (
            "你是接口测试调试专家。根据 HTTP 接口执行结果,分析失败原因并给出修复建议。\n"
            "输出严格的 JSON 格式,包含以下字段:\n"
            "{\n"
            '  "problem_cause": "问题原因,2-3句话说明根本原因",\n'
            '  "solution": "解决方案,分步骤说明如何解决(用1. 2. 3.)",\n'
            '  "fix_suggestion": "修复建议,具体的代码或配置修改(如可行)",\n'
            '  "confidence": 0.0-1.0 的置信度,\n'
            '  "category": "错误分类: network/auth/validation/server/logic/other"\n'
            "}\n"
            "只输出 JSON,不要额外说明。"
        )

        # 构造用户提示词 (截断过长内容)
        user_prompt = self._build_user_prompt(record)

        result = await self.call_llm_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.3,
        )

        # 校验输出
        if not isinstance(result, dict):
            raise ValueError(f"LLM 返回非 dict: {type(result)}")

        return {
            "problem_cause": result.get("problem_cause", "未能确定原因"),
            "solution": result.get("solution", "无解决方案"),
            "fix_suggestion": result.get("fix_suggestion", "无修复建议"),
            "confidence": float(result.get("confidence", 0.5)),
            "category": result.get("category", "other"),
        }

    def _build_user_prompt(self, record: Dict[str, Any]) -> str:
        """构造 LLM 提示词"""
        request = record.get("request", {}) or {}
        response = record.get("response", {}) or {}

        def _truncate(obj: Any, max_len: int = 500) -> str:
            s = json.dumps(obj, ensure_ascii=False, default=str) if not isinstance(obj, str) else obj
            return s[:max_len] + "..." if len(s) > max_len else s

        parts = [
            f"## 请求信息",
            f"方法: {request.get('method', record.get('method', 'UNKNOWN'))}",
            f"URL: {request.get('url', record.get('url', ''))}",
            f"请求头: {_truncate(request.get('headers', {}))}",
            f"请求体: {_truncate(request.get('body', record.get('body')))}",
            "",
            f"## 响应信息",
            f"状态码: {response.get('status_code', record.get('status_code'))}",
            f"响应头: {_truncate(response.get('headers', {}))}",
            f"响应体: {_truncate(response.get('body', record.get('response_body')))}",
            f"耗时(毫秒): {record.get('duration', 0)}",
            "",
            f"## 执行状态",
            f"状态: {record.get('status', 'unknown')}",
            f"错误: {_truncate(record.get('error', ''), 800)}",
        ]
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # 规则引擎分析 (降级)
    # ------------------------------------------------------------------

    def _analyze_with_rules(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """使用规则引擎分析 (LLM 不可用时的降级方案)"""
        error_text = str(record.get("error", "") or "").lower()
        status_code = record.get("status_code")
        response_body = str(record.get("response_body", "") or "").lower()
        status = record.get("status", "")

        # 拼接匹配文本
        match_text = f"{error_text} {status_code} {response_body} {status}".lower()

        # 匹配错误模式
        for pattern in _ERROR_PATTERNS:
            for kw in pattern["match_keywords"]:
                if kw.lower() in match_text:
                    return {
                        "problem_cause": pattern["problem_cause"],
                        "solution": pattern["solution"],
                        "fix_suggestion": pattern["fix_suggestion"],
                        "confidence": pattern["confidence"],
                        "category": pattern["id"].lower(),
                        "matched_pattern": pattern["id"],
                    }

        # 通用失败分析
        if status_code and 500 <= status_code < 600:
            return {
                "problem_cause": f"服务端返回 {status_code} 错误,可能是服务端内部异常",
                "solution": "1) 查看服务端日志 2) 联系后端开发 3) 稍后重试",
                "fix_suggestion": "向服务端反馈完整请求信息,排查服务端异常",
                "confidence": 0.6,
                "category": "server",
            }
        if status_code and 400 <= status_code < 500:
            return {
                "problem_cause": f"客户端请求错误 {status_code},可能是参数或权限问题",
                "solution": "1) 检查请求参数 2) 确认权限 3) 对照接口文档",
                "fix_suggestion": "核对接口文档,确认请求格式与必填字段",
                "confidence": 0.6,
                "category": "client",
            }
        if status in ("timeout",):
            return {
                "problem_cause": "请求超时,服务端响应过慢或网络延迟",
                "solution": "1) 增加 timeout 参数 2) 检查服务端性能 3) 检查网络",
                "fix_suggestion": "设置 timeout=30,或检查服务端响应时间",
                "confidence": 0.7,
                "category": "timeout",
            }
        if status in ("error",):
            return {
                "problem_cause": "请求发生异常,可能是网络或配置问题",
                "solution": "1) 检查网络连通性 2) 检查 URL 拼写 3) 查看错误堆栈",
                "fix_suggestion": "确认目标服务可达,URL 格式正确",
                "confidence": 0.5,
                "category": "network",
            }

        # 兜底
        return {
            "problem_cause": "无法确定具体原因,建议人工排查",
            "solution": "1) 查看完整请求与响应 2) 对比预期结果 3) 联系开发",
            "fix_suggestion": "人工检查请求与响应,对比接口文档",
            "confidence": 0.3,
            "category": "unknown",
        }

    # ------------------------------------------------------------------
    # 数据访问
    # ------------------------------------------------------------------

    async def _load_record(
        self, record_id: Optional[int], payload: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """加载执行记录"""
        # 1. 直接传入完整记录
        if "request" in payload or "response" in payload:
            return {
                "record_id": record_id,
                "request": payload.get("request", {}),
                "response": payload.get("response", {}),
                "method": payload.get("method"),
                "url": payload.get("url"),
                "status_code": payload.get("status_code"),
                "response_body": payload.get("response_body"),
                "duration": payload.get("duration", 0),
                "error": payload.get("error"),
                "status": payload.get("status", "failed"),
            }

        # 2. 从 DB 加载
        if not record_id:
            return None

        from app.db.database import SessionLocal
        from app.models.api_execution_record import ApiExecutionRecord
        import json as _json

        db = SessionLocal()
        try:
            rec = db.query(ApiExecutionRecord).filter(
                ApiExecutionRecord.id == record_id,
                ApiExecutionRecord.is_deleted == False,
            ).first()
            if not rec:
                return None

            def _safe_load(s):
                if not s:
                    return None
                try:
                    return _json.loads(s)
                except Exception:
                    return s

            return {
                "record_id": rec.id,
                "api_id": rec.api_id,
                "case_id": rec.case_id,
                "method": rec.method,
                "url": rec.url,
                "request": {
                    "method": rec.method,
                    "url": rec.url,
                    "headers": _safe_load(rec.headers_json) or {},
                    "params": _safe_load(rec.params_json) or {},
                    "body": _safe_load(rec.body_json),
                },
                "response": {
                    "status_code": rec.status_code,
                    "headers": _safe_load(rec.response_headers_json) or {},
                    "body": _safe_load(rec.response_body),
                },
                "status_code": rec.status_code,
                "response_body": rec.response_body,
                "duration": rec.duration,
                "error": rec.error,
                "status": rec.status.value if hasattr(rec.status, "value") else rec.status,
            }
        finally:
            db.close()

    async def _update_analysis_status(self, record_id: int, status: str) -> None:
        """更新分析状态"""
        from app.db.database import SessionLocal
        from app.models.api_execution_record import ApiExecutionRecord, AnalysisStatus

        db = SessionLocal()
        try:
            rec = db.query(ApiExecutionRecord).filter(
                ApiExecutionRecord.id == record_id
            ).first()
            if rec:
                try:
                    rec.analysis_status = AnalysisStatus(status)
                except ValueError:
                    pass
                db.commit()
        except Exception as e:
            logger.warning(f"[ApiDebugAgent] 更新分析状态失败: {e}")
            db.rollback()
        finally:
            db.close()

    async def _persist_analysis(self, record_id: int, result: Dict[str, Any]) -> None:
        """持久化分析结果"""
        from app.db.database import SessionLocal
        from app.models.api_execution_record import ApiExecutionRecord, AnalysisStatus

        db = SessionLocal()
        try:
            rec = db.query(ApiExecutionRecord).filter(
                ApiExecutionRecord.id == record_id
            ).first()
            if rec:
                rec.analysis_result = json.dumps(result, ensure_ascii=False, default=str)
                rec.analysis_status = AnalysisStatus.DONE
                rec.analyzed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                db.commit()
        except Exception as e:
            logger.error(f"[ApiDebugAgent] 持久化失败: {e}")
            db.rollback()
        finally:
            db.close()

    # ------------------------------------------------------------------
    # 健康检查
    # ------------------------------------------------------------------

    async def _do_health(self) -> Dict[str, Any]:
        """健康检查"""
        return {
            "status": "healthy",
            "agent": "ApiDebugAgent",
            "capabilities": ["debug", "failure_analysis", "llm_reasoning"],
            "patterns_count": len(_ERROR_PATTERNS),
            "llm_available": True,
            "supported_actions": ["analyze", "health", "list_patterns"],
        }

    def _do_list_patterns(self) -> Dict[str, Any]:
        """列出所有错误模式"""
        return {
            "status": "success",
            "total": len(_ERROR_PATTERNS),
            "patterns": [
                {
                    "id": p["id"],
                    "keywords": p["match_keywords"],
                    "problem_cause": p["problem_cause"],
                    "confidence": p["confidence"],
                }
                for p in _ERROR_PATTERNS
            ],
        }
