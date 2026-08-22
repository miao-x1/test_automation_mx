"""
Agent Runtime API 路由

提供以下接口：
1. POST /api/v1/task/run              — 提交任务，返回 session_id
2. GET  /api/v1/task/{sid}/logs        — 查询 Agent 执行日志
3. GET  /api/v1/task/{sid}/stream     — SSE 实时推送执行状态
4. GET  /api/v1/task/{sid}/status      — 查询任务状态
5. GET  /api/v1/agents                  — 列出所有已注册 Agent
6. GET  /api/v1/workflows               — 列出所有可用工作流
7. GET  /api/v1/runtime/stats           — 获取运行时统计
8. POST /api/v1/task/one-click          — 一键执行完整测试流程
9. POST /api/v1/task/one-click/stream   — 一键执行（SSE流式）
"""
import json
import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.runtime import get_task_runtime
from app.runtime.agent_factory import AgentFactory

logger = logging.getLogger(__name__)

router = APIRouter()


# ================================================================== #
#  工作流定义（静态，替代 Gen2 list_workflows）                           #
# ================================================================== #

WORKFLOW_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "web_test",
        "display_name": "Web自动化测试",
        "description": "完整的Web UI自动化测试生成与执行流程",
        "task_type": "web",
        "platform": "browser",
        "framework": "playwright",
        "steps": [
            {"name": "需求解析", "agent_name": "requirement_agent", "action": "analyze", "input_key": "", "output_key": "requirement_analysis", "required": True, "timeout": 120.0},
            {"name": "RAG检索", "agent_name": "rag_agent", "action": "retrieve", "input_key": "requirement_analysis", "output_key": "rag_context", "required": False, "timeout": 60.0},
            {"name": "用例生成", "agent_name": "case_agent", "action": "generate", "input_key": "requirement_analysis", "output_key": "test_cases", "required": True, "timeout": 120.0},
            {"name": "脚本生成", "agent_name": "script_generation_agent", "action": "generate", "input_key": "test_cases", "output_key": "test_script", "required": True, "timeout": 180.0},
            {"name": "脚本执行", "agent_name": "execution_agent", "action": "execute_script", "input_key": "test_script", "output_key": "execution_result", "required": False, "timeout": 300.0},
            {"name": "结果分析", "agent_name": "feedback_agent", "action": "analyze_failure", "input_key": "execution_result", "output_key": "analysis_result", "required": False, "timeout": 120.0},
        ],
        "total_steps": 6,
    },
    {
        "name": "api_test",
        "display_name": "接口自动化测试",
        "description": "接口自动化测试用例生成流程",
        "task_type": "api",
        "platform": "server",
        "framework": "pytest",
        "steps": [
            {"name": "需求解析", "agent_name": "requirement_agent", "action": "analyze", "input_key": "", "output_key": "requirement_analysis", "required": True, "timeout": 120.0},
            {"name": "用例生成", "agent_name": "case_agent", "action": "generate", "input_key": "requirement_analysis", "output_key": "test_cases", "required": True, "timeout": 120.0},
            {"name": "用例审查", "agent_name": "review_agent", "action": "review", "input_key": "test_cases", "output_key": "reviewed_cases", "required": False, "timeout": 120.0},
        ],
        "total_steps": 3,
    },
    {
        "name": "android_test",
        "display_name": "Android自动化测试",
        "description": "Android移动端自动化测试生成与执行流程",
        "task_type": "android",
        "platform": "mobile",
        "framework": "appium",
        "steps": [
            {"name": "需求解析", "agent_name": "requirement_agent", "action": "analyze", "input_key": "", "output_key": "requirement_analysis", "required": True, "timeout": 120.0},
            {"name": "Android分析", "agent_name": "android_analyzer_agent", "action": "analyze", "input_key": "requirement_analysis", "output_key": "android_analysis", "required": True, "timeout": 180.0},
            {"name": "Appium脚本生成", "agent_name": "appium_agent", "action": "generate", "input_key": "android_analysis", "output_key": "test_script", "required": True, "timeout": 180.0},
            {"name": "脚本执行", "agent_name": "execution_agent", "action": "execute_script", "input_key": "test_script", "output_key": "execution_result", "required": False, "timeout": 300.0},
        ],
        "total_steps": 4,
    },
    {
        "name": "performance_test",
        "display_name": "性能测试",
        "description": "性能压测场景生成与执行流程",
        "task_type": "performance",
        "platform": "server",
        "framework": "jmeter",
        "steps": [
            {"name": "需求解析", "agent_name": "requirement_agent", "action": "analyze", "input_key": "", "output_key": "requirement_analysis", "required": True, "timeout": 120.0},
            {"name": "性能场景分析", "agent_name": "performance_analyzer_agent", "action": "analyze", "input_key": "requirement_analysis", "output_key": "perf_analysis", "required": True, "timeout": 120.0},
            {"name": "JMeter脚本生成", "agent_name": "jmeter_agent", "action": "generate", "input_key": "perf_analysis", "output_key": "test_script", "required": True, "timeout": 180.0},
            {"name": "脚本执行", "agent_name": "execution_agent", "action": "execute_script", "input_key": "test_script", "output_key": "execution_result", "required": False, "timeout": 300.0},
        ],
        "total_steps": 4,
    },
    {
        "name": "testcase_generation",
        "display_name": "测试用例生成",
        "description": "需求解析→测试点分析→用例生成(含RAG)→用例审核",
        "task_type": "web",
        "platform": "browser",
        "framework": "pytest",
        "steps": [
            {"name": "需求解析", "agent_name": "requirement_analysis_agent", "action": "execute", "input_key": "", "output_key": "requirement_analysis", "required": True, "timeout": 120.0},
            {"name": "测试点分析", "agent_name": "test_point_analysis_agent", "action": "execute", "input_key": "requirement_analysis", "output_key": "test_points", "required": True, "timeout": 120.0},
            {"name": "用例生成", "agent_name": "testcase_generator_agent", "action": "execute", "input_key": "", "output_key": "test_cases", "required": True, "timeout": 180.0},
            {"name": "用例审核", "agent_name": "testcase_review_agent", "action": "execute", "input_key": "", "output_key": "reviews", "required": False, "timeout": 120.0},
        ],
        "total_steps": 4,
    },
]


# ================================================================== #
#  辅助函数                                                            #
# ================================================================== #

def _analyze_task_type(requirement: str) -> str:
    """
    根据需求文本关键词自动判断任务类型。

    使用 TestTypeClassifierAgent 的规则引擎进行快速分类，
    将 test_type (web/api/android/performance) 映射为 workflow_name。
    """
    try:
        classifier = AgentFactory.create("test_type_classifier")
        result = classifier.classify_sync(text=requirement)
        test_type = result.get("test_type", "web")

        # test_type → workflow_name 映射
        TYPE_WORKFLOW_MAP = {
            "web": "web_test",
            "api": "api_test",
            "android": "android_test",
            "performance": "performance_test",
        }
        workflow_name = TYPE_WORKFLOW_MAP.get(test_type, "web_test")
        logger.info(f"_analyze_task_type | requirement={requirement[:50]}... → type={test_type}, workflow={workflow_name}")
        return workflow_name
    except Exception as e:
        logger.warning(f"_analyze_task_type fallback | error={e}")
        # 回退到简单关键词匹配
        req_lower = requirement.lower()
        if any(kw in req_lower for kw in ["api", "接口", "rest", "graphql", "swagger"]):
            return "api_test"
        if any(kw in req_lower for kw in ["android", "安卓", "app", "移动"]):
            return "android_test"
        if any(kw in req_lower for kw in ["性能", "performance", "压测", "负载"]):
            return "performance_test"
        return "web_test"


def build_pipeline_steps(workflow_name: str, requirement: str) -> List[Dict[str, Any]]:
    """
    根据工作流名称构建 Gen3 Pipeline 步骤列表。

    每个步骤是一个 dict，包含:
      - agent_type:  Agent 类型字符串
      - action:      执行动作名
      - payload:     输入参数（仅第一步携带用户需求）
      - input_keys:  从上下文中取值的 key 列表（前序步骤的 output_key）
      - output_key:  本步骤输出存入上下文的 key
    """
    if workflow_name == "web_test":
        return [
            {
                "agent_type": "requirement_agent",
                "action": "analyze",
                "payload": {"requirement": requirement},
                "output_key": "requirement_analysis",
            },
            {
                "agent_type": "rag_agent",
                "action": "retrieve",
                "input_keys": ["requirement_analysis"],
                "output_key": "rag_context",
            },
            {
                "agent_type": "relation_agent",
                "action": "discover",
                "input_keys": ["requirement_analysis", "rag_context"],
                "output_key": "relation_context",
            },
            {
                "agent_type": "graph_agent",
                "action": "reason",
                "input_keys": ["requirement_analysis", "rag_context"],
                "output_key": "graph_context",
            },
            {
                "agent_type": "flow_parser",
                "action": "detect",
                "input_keys": ["requirement_analysis", "graph_context"],
                "output_key": "flow_context",
            },
            {
                "agent_type": "case_agent",
                "action": "generate",
                "input_keys": ["requirement_analysis", "rag_context", "relation_context", "graph_context"],
                "output_key": "test_cases",
            },
            {
                "agent_type": "script_generation_agent",
                "action": "execute",
                "input_keys": ["test_cases", "rag_context", "graph_context", "flow_context"],
                "output_key": "test_script",
            },
            {
                "agent_type": "storage_agent",
                "action": "store",
                "input_keys": ["test_script"],
                "defaults": {
                    "requirement": "__meta__.requirement",
                    "task_id": "__meta__.task_id",
                },
                "required": False,
                "output_key": "storage_result",
            },
            {
                "agent_type": "execution_agent",
                "action": "execute_script",
                "input_keys": ["test_script"],
                "param_mapping": {"test_script": "script_content"},
                "extract_fields": {"test_script": "script_content"},
                "defaults": {"task_id": "__meta__.task_id", "execution_id": "__meta__.execution_id"},
                "output_key": "execution_result",
            },
            {
                "agent_type": "report_agent",
                "action": "generate",
                "input_keys": ["execution_result"],
                "defaults": {"task_id": "__meta__.task_id"},
                "required": False,
                "output_key": "report_result",
            },
            {
                "agent_type": "defect_agent",
                "action": "analyze_from_execution",
                "input_keys": ["execution_result"],
                "defaults": {"task_id": "__meta__.task_id"},
                "required": False,
                "condition": {
                    "context_key": "execution_result",
                    "field": "status",
                    "op": "equals",
                    "value": "failed",
                },
                "output_key": "defect_result",
            },
            {
                "agent_type": "feedback_agent",
                "action": "analyze_failure",
                "input_keys": ["execution_result"],
                "param_mapping": {"execution_result": "exec_result"},
                "defaults": {
                    "requirement": "__meta__.requirement",
                    "script_content": "__meta__.script_content",
                },
                "required": False,
                "condition": {
                    "context_key": "execution_result",
                    "field": "status",
                    "op": "equals",
                    "value": "failed",
                },
                "output_key": "analysis_result",
            },
            {
                "agent_type": "flow_export_agent",
                "action": "execute",
                "input_keys": ["report_result", "defect_result", "analysis_result"],
                "defaults": {
                    "task_id": "__meta__.task_id",
                    "session_key": "__meta__.session_id",
                    "scripts": [],
                    "script_language": "python",
                    "framework": "playwright",
                },
                "required": False,
                "output_key": "export_result",
            },
        ]

    if workflow_name == "api_test":
        return [
            {
                "agent_type": "requirement_agent",
                "action": "analyze",
                "payload": {"requirement": requirement},
                "output_key": "requirement_analysis",
            },
            {
                "agent_type": "case_agent",
                "action": "generate",
                "input_keys": ["requirement_analysis"],
                "output_key": "test_cases",
            },
            {
                "agent_type": "review_agent",
                "action": "review",
                "input_keys": ["test_cases"],
                "output_key": "reviewed_cases",
            },
        ]

    if workflow_name == "android_test":
        return [
            {
                "agent_type": "requirement_agent",
                "action": "analyze",
                "payload": {"requirement": requirement},
                "output_key": "requirement_analysis",
            },
            {
                "agent_type": "android_analyzer_agent",
                "action": "analyze",
                "input_keys": ["requirement_analysis"],
                "output_key": "android_analysis",
            },
            {
                "agent_type": "appium_agent",
                "action": "generate",
                "input_keys": ["android_analysis"],
                "output_key": "test_script",
            },
            {
                "agent_type": "execution_agent",
                "action": "execute_script",
                "input_keys": ["test_script"],
                "output_key": "execution_result",
            },
        ]

    if workflow_name == "performance_test":
        return [
            {
                "agent_type": "requirement_agent",
                "action": "analyze",
                "payload": {"requirement": requirement},
                "output_key": "requirement_analysis",
            },
            {
                "agent_type": "performance_analyzer_agent",
                "action": "analyze",
                "input_keys": ["requirement_analysis"],
                "output_key": "perf_analysis",
            },
            {
                "agent_type": "jmeter_agent",
                "action": "generate",
                "input_keys": ["perf_analysis"],
                "output_key": "test_script",
            },
            {
                "agent_type": "execution_agent",
                "action": "execute_script",
                "input_keys": ["test_script"],
                "output_key": "execution_result",
            },
        ]

    if workflow_name == "testcase_generation":
        return [
            {
                "agent_type": "requirement_analysis_agent",
                "action": "execute",
                "payload": {"requirement": requirement},
                "output_key": "requirement_analysis",
            },
            {
                "agent_type": "test_point_analysis_agent",
                "action": "execute",
                "input_keys": ["requirement_analysis"],
                "output_key": "test_points",
            },
            {
                "agent_type": "testcase_generator_agent",
                "action": "execute",
                "input_keys": ["test_points", "requirement_analysis"],
                "output_key": "test_cases",
            },
            {
                "agent_type": "testcase_review_agent",
                "action": "execute",
                "input_keys": ["test_cases"],
                "output_key": "reviews",
            },
        ]

    # 未知工作流，回退到 web_test
    logger.warning(f"未知工作流: {workflow_name}，回退到 web_test")
    return build_pipeline_steps("web_test", requirement)


# ================================================================== #
#  请求/响应模型                                                        #
# ================================================================== #

class TaskRunRequest(BaseModel):
    """提交任务请求"""
    task_id: Optional[str] = Field(default="", description="任务ID")
    requirement: str = Field(..., description="用户需求文本")
    user_id: int = Field(default=0, description="用户ID")
    task_type: Optional[str] = Field(default="", description="测试类型(web/api/android/performance)")
    workflow_name: Optional[str] = Field(default="", description="工作流名称")
    framework: Optional[str] = Field(default="", description="测试框架(playwright/appium/pytest/jmeter)")
    platform: Optional[str] = Field(default="", description="测试平台(browser/mobile/server)")
    confidence: Optional[float] = Field(default=None, description="AI识别置信度")
    auto_classify: bool = Field(default=True, description="是否自动识别测试类型")
    timeout: float = Field(default=600.0, description="超时时间(秒)")


class DegradationInfo(BaseModel):
    """降级信息（用于前端提示用户审查脚本）"""
    level: int = Field(default=0, description="降级级别: 0=未降级(复用), 1=StrategyAgent, 2=FlowScriptGen, 3=RAG增强, 4=纯模板")
    source: str = Field(default="", description="脚本来源: reuse/strategy/flow/rag/template")
    quality: str = Field(default="high", description="质量评估: high/medium/low")
    action_required: bool = Field(default=False, description="是否需要人工审查")
    message: str = Field(default="", description="提示信息")


class TaskRunResponse(BaseModel):
    """提交任务响应"""
    session_id: str
    task_id: str
    status: str
    message: str = ""
    reused: bool = Field(default=False, description="是否复用了历史脚本")
    script_content: Optional[str] = Field(default=None, description="脚本内容（复用时直接返回）")
    script_source: str = Field(default="", description="脚本来源: reused/pipeline")
    similarity: float = Field(default=0, description="复用相似度")
    degradation_info: Optional[DegradationInfo] = Field(default=None, description="降级信息")


# ================================================================== #
#  测试类型分类 请求/响应模型                                            #
# ================================================================== #

class ClassifyRequest(BaseModel):
    """测试类型分类请求"""
    requirement: str = Field(default="", description="需求文本")
    urls: List[str] = Field(default_factory=list, description="URL列表")
    script_content: str = Field(default="", description="脚本内容")
    script_language: str = Field(default="", description="脚本语言")
    images: List[str] = Field(default_factory=list, description="图片路径列表")
    swagger_content: str = Field(default="", description="Swagger/OpenAPI JSON内容")
    db_schema: str = Field(default="", description="数据库结构信息")
    page_info: str = Field(default="", description="页面信息")
    use_llm: bool = Field(default=True, description="是否启用LLM增强")


class ClassifyResponse(BaseModel):
    """测试类型分类响应"""
    test_type: str
    platform: str
    framework: str
    confidence: float
    reason: str = ""
    scores: Dict[str, float] = {}
    detected_signals: List[str] = []


# ================================================================== #
#  核心接口                                                            #
# ================================================================== #

@router.post("/task/run", response_model=TaskRunResponse, summary="提交AI任务")
async def run_task(req: TaskRunRequest):
    """
    提交任务，由 TaskRuntime 自动编排 Agent 执行。

    返回 session_id，可用于查询日志和 SSE 推流。

    流程：
        API → TaskRuntime → execute_pipeline → Agent 执行

    如果 auto_classify=True 且未指定 workflow_name，
    会先调用 TestTypeClassifierAgent 自动识别测试类型。
    """
    task_runtime = get_task_runtime()

    # 自动识别测试类型
    if req.auto_classify and not req.workflow_name:
        try:
            # 通过 TaskDispatcher 提交 (企业级 Runtime)
            from app.runtime.enterprise import get_task_dispatcher, TaskRequest
            dispatcher = get_task_dispatcher()
            classify_task_id = await dispatcher.submit(TaskRequest(
                agent_name="test_type_classifier",
                action="execute",
                payload={"requirement": req.requirement},
                timeout_seconds=60,
                max_retries=1,
            ))
            classify_result_obj = await dispatcher.wait_for_result(classify_task_id, timeout=60)
            if classify_result_obj.status == "success" and classify_result_obj.result:
                classify_result = classify_result_obj.result
                req.task_type = req.task_type or classify_result.get("test_type")
                req.framework = req.framework or classify_result.get("framework")
                req.platform = req.platform or classify_result.get("platform")
                req.confidence = req.confidence or classify_result.get("confidence")
            else:
                raise Exception(classify_result_obj.error or "分类失败")
            logger.info(f"自动识别 | type={req.task_type}, framework={req.framework}, confidence={req.confidence}")
        except Exception as e:
            logger.warning(f"自动识别失败，使用关键词回退 | error: {e}")

    # 确定 workflow_name
    TYPE_WORKFLOW_MAP = {
        "web": "web_test",
        "api": "api_test",
        "android": "android_test",
        "performance": "performance_test",
        # 兼容旧格式
        "web_test": "web_test",
        "api_test": "api_test",
    }
    if req.workflow_name:
        workflow_name = req.workflow_name
    elif req.task_type:
        workflow_name = TYPE_WORKFLOW_MAP.get(req.task_type, "web_test")
    else:
        workflow_name = _analyze_task_type(req.requirement)

    # 生成 session_id
    session_id = str(uuid.uuid4())[:8]

    # ===== Level A: 快速预检（需求解析之前）=====
    try:
        from app.services.reuse_service import ReuseService
        quick_result = ReuseService.quick_check(requirement=req.requirement)
        if quick_result.get("reuse"):
            logger.info(
                f"快速预检命中 | similarity={quick_result['similarity']}, "
                f"script_name={quick_result.get('script_name', '')}"
            )
            deg = quick_result.get("degradation_info", {})
            return TaskRunResponse(
                session_id=session_id,
                task_id=req.task_id,
                status="completed",
                message=f"已复用历史脚本（快速预检）| 相似度: {quick_result['similarity']} | 耗时: 0.1s",
                reused=True,
                script_content=quick_result.get("script_content", ""),
                script_source="reused",
                similarity=quick_result["similarity"],
                degradation_info=DegradationInfo(**deg) if deg else None,
            )
    except Exception as e:
        logger.warning(f"快速预检失败，继续走管道 | error={e}")

    # 构建管道步骤
    steps = build_pipeline_steps(workflow_name, req.requirement)

    # 先执行需求解析步骤（单独执行），获取intent和steps用于精确复用检查
    requirement_analysis = None
    if steps and len(steps) > 0:
        first_step = steps[0]
        if first_step.get("agent_type") == "requirement_agent":
            try:
                req_result = await task_runtime.execute(
                    agent_type="requirement_agent",
                    action=first_step.get("action", "analyze"),
                    payload={"requirement": req.requirement},
                    session_id=session_id,
                    timeout=30,
                )
                if req_result.get("status") in ("completed", "success"):
                    req_data = req_result.get("data", req_result)
                    requirement_analysis = req_data
            except Exception as e:
                logger.warning(f"需求解析步骤失败 | error={e}")

    # ===== Level B: 精确检索（需求解析之后）=====
    if requirement_analysis:
        try:
            reuse_result = ReuseService.check_reuse(
                requirement=req.requirement,
                intent=requirement_analysis.get("intent", ""),
                steps=requirement_analysis.get("steps", []),
            )
            if reuse_result.get("reuse"):
                logger.info(
                    f"精确检索命中 | similarity={reuse_result['similarity']}, "
                    f"intent={requirement_analysis.get('intent', '')}"
                )
                deg = reuse_result.get("degradation_info", {})
                return TaskRunResponse(
                    session_id=session_id,
                    task_id=req.task_id,
                    status="completed",
                    message=f"已复用历史脚本（精确检索）| 相似度: {reuse_result['similarity']} | 耗时: 15s",
                    reused=True,
                    script_content=reuse_result.get("script_content", ""),
                    script_source="reused",
                    similarity=reuse_result["similarity"],
                    degradation_info=DegradationInfo(**deg) if deg else None,
                )
        except Exception as e:
            logger.warning(f"精确检索失败，继续走管道 | error={e}")

    # ===== 未命中复用，执行完整管道 =====
    # 注入管道元数据（供 param_mapping 的 __meta__. 引用）
    if steps and "payload" not in steps[0]:
        steps[0]["payload"] = {"requirement": req.requirement}
    steps[0]["payload"]["__pipeline_meta__"] = {
        "task_id": int(req.task_id) if req.task_id.isdigit() else 0,
        "session_id": session_id,
        "requirement": req.requirement,
        "execution_id": 0,
        "script_content": "",
    }

    start_time = time.time()
    result = await task_runtime.execute_pipeline(
        steps=steps,
        user_id=req.user_id,
        session_id=session_id,
        timeout=req.timeout,
    )
    duration = time.time() - start_time

    status = result.get("status", "unknown")
    if status == "completed":
        message = f"任务完成 | 耗时: {duration:.2f}s"
    else:
        failed_step = result.get("failed_step")
        message = f"任务失败 | 失败步骤: {failed_step}" if failed_step is not None else "任务执行异常"

    # 提取降级信息（如果管道步骤中包含）
    degradation_info = None
    context = result.get("context", {})
    if "test_script" in context and isinstance(context["test_script"], dict):
        script_data = context["test_script"]
        if isinstance(script_data, dict) and "degradation_info" in script_data:
            deg = script_data["degradation_info"]
            degradation_info = DegradationInfo(**deg) if isinstance(deg, dict) else None

    return TaskRunResponse(
        session_id=session_id,
        task_id=req.task_id,
        status=status,
        message=message,
        reused=False,
        script_source="pipeline",
        degradation_info=degradation_info,
    )


@router.get("/task/{session_id}/stream", summary="SSE实时推送执行状态")
async def stream_task(session_id: str):
    """
    SSE 流式推送任务执行状态。

    从数据库（AgentExecutionLog）查询已记录的执行日志并推送。
    """
    from app.db.database import SessionLocal
    from app.models.agent_execution_log import AgentExecutionLog

    db = SessionLocal()
    try:
        logs = db.query(AgentExecutionLog).filter(
            AgentExecutionLog.session_id == session_id
        ).order_by(AgentExecutionLog.id).all()
        events = [log.to_dict() for log in logs]
    finally:
        db.close()

    async def event_generator():
        for event in events:
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.01)
        yield "data: {\"event_type\": \"done\"}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/task/run/stream", summary="SSE流式执行任务")
async def run_task_stream(req: TaskRunRequest):
    """
    提交任务并以 SSE 流式返回执行状态。

    实时推送每个 Agent 步骤的执行进度。
    支持自动测试类型识别。
    """
    task_runtime = get_task_runtime()

    # 自动识别测试类型
    if req.auto_classify and not req.workflow_name:
        try:
            classifier = AgentFactory.create("test_type_classifier")
            classify_result = await classifier.execute(requirement=req.requirement)
            req.task_type = req.task_type or classify_result["test_type"]
            req.framework = req.framework or classify_result["framework"]
            req.platform = req.platform or classify_result["platform"]
            req.confidence = req.confidence or classify_result["confidence"]
            logger.info(f"流式自动识别 | type={req.task_type}, confidence={req.confidence}")
        except Exception as e:
            logger.warning(f"流式自动识别失败 | error={e}")

    # 确定 workflow_name
    TYPE_WORKFLOW_MAP = {
        "web": "web_test",
        "api": "api_test",
        "android": "android_test",
        "performance": "performance_test",
        "web_test": "web_test",
        "api_test": "api_test",
    }
    if req.workflow_name:
        workflow_name = req.workflow_name
    elif req.task_type:
        workflow_name = TYPE_WORKFLOW_MAP.get(req.task_type, "web_test")
    else:
        workflow_name = _analyze_task_type(req.requirement)

    # 构建管道步骤
    steps = build_pipeline_steps(workflow_name, req.requirement)

    # 生成 session_id
    session_id = str(uuid.uuid4())[:8]

    async def event_generator():
        try:
            # ===== Level A: 快速预检（需求解析之前）=====
            try:
                from app.services.reuse_service import ReuseService
                quick_result = ReuseService.quick_check(requirement=req.requirement)
                if quick_result.get("reuse"):
                    logger.info(f"流式快速预检命中 | similarity={quick_result['similarity']}")
                    deg = quick_result.get("degradation_info", {})
                    yield f"data: {json.dumps({'event': 'reuse_hit', 'data': {'reused': True, 'similarity': quick_result['similarity'], 'script_name': quick_result.get('script_name', ''), 'script_content': quick_result.get('script_content', ''), 'script_source': 'reused', 'degradation_info': deg, 'check_type': 'quick'}}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'event': 'pipeline_completed', 'data': {'session_id': session_id, 'final_data': {'script_content': quick_result.get('script_content', '')}, 'reused': True}}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'event': 'done', 'data': {}}, ensure_ascii=False)}\n\n"
                    return
                else:
                    yield f"data: {json.dumps({'event': 'reuse_missed', 'data': {'similarity': quick_result.get('similarity', 0), 'message': '快速预检未命中，开始需求解析', 'check_type': 'quick'}}, ensure_ascii=False)}\n\n"
            except Exception as e:
                logger.warning(f"流式快速预检失败 | error={e}")

            # ===== 执行需求解析步骤，获取intent和steps =====
            requirement_analysis = None
            if steps and len(steps) > 0:
                first_step = steps[0]
                if first_step.get("agent_type") == "requirement_agent":
                    try:
                        req_result = await task_runtime.execute(
                            agent_type="requirement_agent",
                            action=first_step.get("action", "analyze"),
                            payload={"requirement": req.requirement},
                            session_id=session_id,
                            timeout=30,
                        )
                        if req_result.get("status") in ("completed", "success"):
                            requirement_analysis = req_result.get("data", req_result)
                    except Exception as e:
                        logger.warning(f"流式需求解析失败 | error={e}")

            # ===== Level B: 精确检索（需求解析之后）=====
            if requirement_analysis:
                try:
                    reuse_result = ReuseService.check_reuse(
                        requirement=req.requirement,
                        intent=requirement_analysis.get("intent", ""),
                        steps=requirement_analysis.get("steps", []),
                    )
                    if reuse_result.get("reuse"):
                        logger.info(f"流式精确检索命中 | similarity={reuse_result['similarity']}")
                        deg = reuse_result.get("degradation_info", {})
                        yield f"data: {json.dumps({'event': 'reuse_hit', 'data': {'reused': True, 'similarity': reuse_result['similarity'], 'script_name': reuse_result.get('script_name', ''), 'script_content': reuse_result.get('script_content', ''), 'script_source': 'reused', 'degradation_info': deg, 'check_type': 'precise'}}, ensure_ascii=False)}\n\n"
                        yield f"data: {json.dumps({'event': 'pipeline_completed', 'data': {'session_id': session_id, 'final_data': {'script_content': reuse_result.get('script_content', '')}, 'reused': True}}, ensure_ascii=False)}\n\n"
                        yield f"data: {json.dumps({'event': 'done', 'data': {}}, ensure_ascii=False)}\n\n"
                        return
                    else:
                        yield f"data: {json.dumps({'event': 'reuse_missed', 'data': {'similarity': reuse_result.get('similarity', 0), 'message': '精确检索未命中，开始执行完整管道', 'check_type': 'precise'}}, ensure_ascii=False)}\n\n"
                except Exception as e:
                    logger.warning(f"流式精确检索失败 | error={e}")

            # ===== 未命中复用，执行完整管道 =====
            # 注入管道元数据
            if steps and "payload" not in steps[0]:
                steps[0]["payload"] = {"requirement": req.requirement}
            steps[0]["payload"]["__pipeline_meta__"] = {
                "task_id": int(req.task_id) if req.task_id.isdigit() else 0,
                "session_id": session_id,
                "requirement": req.requirement,
                "execution_id": 0,
                "script_content": "",
            }

            async for event in task_runtime.execute_pipeline_sse(
                steps=steps,
                user_id=req.user_id,
                session_id=session_id,
                timeout=req.timeout,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            logger.warning(f"SSE 客户端断开 | run/stream | session={session_id}")
            raise
        except Exception as e:
            logger.error(f"SSE 执行异常 | run/stream | session={session_id} | error={e}", exc_info=True)
            yield f"data: {json.dumps({'event': 'error', 'data': {'message': str(e)}}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'event': 'done', 'data': {}}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/task/{session_id}/logs", summary="查询Agent执行日志")
async def get_task_logs(
    session_id: str,
    agent_name: Optional[str] = Query(None, description="按Agent名称过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    limit: int = Query(50, description="返回数量限制"),
):
    """
    查询 Agent 执行过程日志。

    从 agent_execution_log 表查询，
    包含每个 Agent 的输入、输出、状态、耗时。
    """
    from app.db.database import SessionLocal
    from app.models.agent_execution_log import AgentExecutionLog
    from sqlalchemy import desc

    db = SessionLocal()
    try:
        query = db.query(AgentExecutionLog).filter(
            AgentExecutionLog.session_id == session_id
        )
        if agent_name:
            query = query.filter(AgentExecutionLog.agent_name == agent_name)
        if status:
            query = query.filter(AgentExecutionLog.status == status)

        logs = query.order_by(desc(AgentExecutionLog.id)).limit(limit).all()

        return {
            "session_id": session_id,
            "total": len(logs),
            "logs": [log.to_dict() for log in logs],
        }
    finally:
        db.close()


@router.get("/task/{session_id}/status", summary="查询任务状态")
async def get_task_status(session_id: str):
    """查询任务执行状态和 Agent 执行进度（从数据库 AgentExecutionLog 查询）"""
    from app.db.database import SessionLocal
    from app.models.agent_execution_log import AgentExecutionLog

    db = SessionLocal()
    try:
        logs = db.query(AgentExecutionLog).filter(
            AgentExecutionLog.session_id == session_id
        ).order_by(AgentExecutionLog.id).all()

        if not logs:
            return {"error": "会话不存在", "session_id": session_id}

        return {
            "session_id": session_id,
            "status": "completed" if all(l.status == "success" for l in logs) else "failed",
            "agents": [log.to_dict() for log in logs],
            "total_steps": len(logs),
        }
    finally:
        db.close()


# ================================================================== #
#  任务级查询接口（按 task_id 查询，区别于按 session_id 的接口）           #
# ================================================================== #

@router.get("/tasks/{task_id}/workflow", summary="获取任务工作流")
async def get_task_workflow(task_id: int):
    """获取任务的 Agent 执行链路（工作流）

    从 AgentExecutionLog 按 task_id 查询，构建执行链路 Timeline。
    """
    from app.db.database import SessionLocal
    from app.models.agent_execution_log import AgentExecutionLog
    from sqlalchemy import desc

    db = SessionLocal()
    try:
        logs = db.query(AgentExecutionLog).filter(
            AgentExecutionLog.task_id == task_id
        ).order_by(AgentExecutionLog.id).all()

        if not logs:
            return {
                "task_id": task_id,
                "total_steps": 0,
                "steps": [],
                "message": "无执行记录",
            }

        steps = []
        for i, log in enumerate(logs, 1):
            steps.append({
                "step": i,
                "agent_name": log.agent_name,
                "step_name": log.step or "",
                "status": log.status,
                "duration": log.duration,
                "start_time": str(log.start_time) if log.start_time else None,
                "end_time": str(log.end_time) if log.end_time else None,
                "model_name": log.model_name,
                "tokens_used": log.tokens_used,
                "error": log.error,
            })

        # 统计
        total = len(steps)
        success = sum(1 for s in steps if s["status"] == "success")
        failed = sum(1 for s in steps if s["status"] == "error")
        running = sum(1 for s in steps if s["status"] == "running")
        total_duration = sum(s["duration"] or 0 for s in steps)

        return {
            "task_id": task_id,
            "total_steps": total,
            "success_count": success,
            "failed_count": failed,
            "running_count": running,
            "total_duration": round(total_duration, 2),
            "steps": steps,
        }
    finally:
        db.close()


@router.get("/tasks/{task_id}/agent-log", summary="获取任务Agent日志")
async def get_task_agent_log(
    task_id: int,
    agent_name: Optional[str] = Query(None, description="按 Agent 名称过滤"),
    status: Optional[str] = Query(None, description="按状态过滤(success/error/running)"),
    limit: int = Query(100, ge=1, le=500, description="返回数量"),
):
    """获取任务中每个 Agent 的执行日志（含输入输出）

    按 task_id 查询，返回详细的 Agent 执行记录。
    """
    from app.db.database import SessionLocal
    from app.models.agent_execution_log import AgentExecutionLog
    from sqlalchemy import desc

    db = SessionLocal()
    try:
        query = db.query(AgentExecutionLog).filter(
            AgentExecutionLog.task_id == task_id
        )
        if agent_name:
            query = query.filter(AgentExecutionLog.agent_name == agent_name)
        if status:
            query = query.filter(AgentExecutionLog.status == status)

        logs = query.order_by(desc(AgentExecutionLog.id)).limit(limit).all()

        return {
            "task_id": task_id,
            "total": len(logs),
            "logs": [log.to_dict() for log in logs],
        }
    finally:
        db.close()


@router.get("/agents/registry", summary="获取Agent注册表(DB持久化)")
async def get_agent_registry():
    """从数据库获取 Agent 注册信息（包含状态、版本等元数据）"""
    from app.db.database import SessionLocal
    from app.models.agent_registry import AgentRegistry

    db = SessionLocal()
    try:
        records = db.query(AgentRegistry).order_by(AgentRegistry.agent_name).all()
        return {
            "total": len(records),
            "agents": [r.to_dict() for r in records],
        }
    finally:
        db.close()


@router.put("/agents/{agent_name}/model", summary="更新Agent模型")
async def update_agent_model(agent_name: str, model_name: str = Query(...), provider: str = Query(...)):
    """动态更新 Agent 使用的模型"""
    from app.db.database import SessionLocal
    from app.agents.factory.models import AgentMetadataStore

    db = SessionLocal()
    try:
        success = AgentMetadataStore.update_model(db, agent_name, model_name, provider)
        if not success:
            return {"error": f"Agent '{agent_name}' not found in registry"}
        return {"agent_name": agent_name, "model_name": model_name, "provider": provider}
    finally:
        db.close()


@router.put("/agents/{agent_name}/toggle", summary="启用/禁用Agent")
async def toggle_agent(agent_name: str, enabled: bool = Query(...)):
    """启用或禁用 Agent"""
    from app.db.database import SessionLocal
    from app.agents.factory.models import AgentMetadataStore

    db = SessionLocal()
    try:
        success = AgentMetadataStore.toggle_enabled(db, agent_name, enabled)
        if not success:
            return {"error": f"Agent '{agent_name}' not found in registry"}
        return {"agent_name": agent_name, "enabled": enabled}
    finally:
        db.close()


@router.get("/lifecycle/stats", summary="获取Agent生命周期统计")
async def get_lifecycle_stats():
    """获取 Agent 生命周期状态统计"""
    from app.agents.factory import get_lifecycle_manager

    manager = get_lifecycle_manager()
    return manager.get_stats()

@router.get("/agents", summary="列出所有已注册Agent")
async def list_agents():
    """列出所有已注册的 Agent"""
    task_runtime = get_task_runtime()
    agents = await task_runtime.list_agents()
    return {
        "total": len(agents),
        "agents": agents,
    }


@router.get("/workflows", summary="列出所有可用工作流")
async def get_workflows():
    """列出所有可用的工作流"""
    return {
        "total": len(WORKFLOW_DEFINITIONS),
        "workflows": WORKFLOW_DEFINITIONS,
    }


@router.get("/runtime/stats", summary="获取运行时统计")
async def get_runtime_stats():
    """获取运行时统计信息"""
    task_runtime = get_task_runtime()
    return task_runtime.get_stats()


@router.get("/sessions", summary="列出所有会话")
async def list_sessions(user_id: Optional[int] = Query(None)):
    """列出所有活跃会话"""
    task_runtime = get_task_runtime()
    sessions = await task_runtime.list_sessions(user_id)
    return {
        "total": len(sessions),
        "sessions": sessions,
    }


@router.get("/sessions/{session_id}/events", summary="获取会话事件")
async def get_session_events(session_id: str):
    """获取会话的所有执行事件（从数据库 AgentExecutionLog 查询）"""
    from app.db.database import SessionLocal
    from app.models.agent_execution_log import AgentExecutionLog

    db = SessionLocal()
    try:
        logs = db.query(AgentExecutionLog).filter(
            AgentExecutionLog.session_id == session_id
        ).order_by(AgentExecutionLog.id).all()
        events = [log.to_dict() for log in logs]
        return {
            "session_id": session_id,
            "total": len(events),
            "events": events,
        }
    finally:
        db.close()


# ================================================================== #
#  测试类型智能识别接口                                                  #
# ================================================================== #

@router.post("/classify", response_model=ClassifyResponse, summary="AI智能识别测试类型")
async def classify_test_type(req: ClassifyRequest):
    """
    分析用户需求，自动判断测试类型、平台、框架。

    输入：
        - requirement: 需求文本
        - urls: URL列表
        - images: 图片路径
        - swagger_content: Swagger/OpenAPI内容
        - db_schema: 数据库结构
        - page_info: 页面信息
        - use_llm: 是否启用LLM增强

    输出：
        {
            test_type:  web | api | android | performance
            platform:   browser | mobile | server
            framework:  playwright | appium | pytest | jmeter
            confidence: 0-1
        }
    """
    classifier = AgentFactory.create("test_type_classifier")

    if req.use_llm:
        result = await classifier.execute(
            requirement=req.requirement,
            urls=req.urls,
            script_content=req.script_content,
            script_language=req.script_language,
            images=req.images,
            swagger_content=req.swagger_content,
            db_schema=req.db_schema,
            page_info=req.page_info,
        )
    else:
        result = classifier.classify_sync(
            text=req.requirement,
            urls=req.urls,
            script_content=req.script_content,
            script_language=req.script_language,
            images=req.images,
            swagger_content=req.swagger_content,
            db_schema=req.db_schema,
            page_info=req.page_info,
        )

    return ClassifyResponse(
        test_type=result["test_type"],
        platform=result["platform"],
        framework=result["framework"],
        confidence=result["confidence"],
        reason=result.get("reason", ""),
        scores=result.get("scores", {}),
        detected_signals=result.get("detected_signals", []),
    )


# ================================================================== #
#  一键执行接口                                                          #
# ================================================================== #

class OneClickRequest(BaseModel):
    """一键执行请求 - 用户只需输入需求"""
    requirement: str = Field(..., description="自然语言测试需求")
    task_id: Optional[str] = Field(default="", description="任务ID（可选）")


class OneClickResponse(BaseModel):
    """一键执行响应 - 包含全链路结果"""
    status: str = Field(description="整体状态: completed | failed")
    session_id: str = Field(description="会话ID")
    requirement_analysis: Optional[Dict[str, Any]] = Field(default=None, description="需求分析: business_flow, test_points, risk_points")
    test_cases: Optional[Dict[str, Any]] = Field(default=None, description="测试用例")
    script_content: Optional[str] = Field(default=None, description="生成的脚本内容")
    execution_result: Optional[Dict[str, Any]] = Field(default=None, description="执行结果: status, screenshots, logs, report")
    failure_analysis: Optional[Dict[str, Any]] = Field(default=None, description="失败分析: root_cause, failure_reasons, fix_suggestions")
    report_url: Optional[str] = Field(default=None, description="报告URL")
    screenshot_url: Optional[str] = Field(default=None, description="截图URL")
    duration: float = Field(default=0, description="总耗时(秒)")
    message: str = Field(default="", description="汇总消息")


def _extract_one_click_results(context: Dict[str, Any], session_id: str, duration: float) -> OneClickResponse:
    """从 pipeline context 中提取一键执行的结果"""
    req_analysis = context.get("requirement_analysis", {})
    test_cases = context.get("test_cases", {})
    test_script = context.get("test_script", {})
    execution_result = context.get("execution_result", {})
    analysis_result = context.get("analysis_result", {})

    # 提取脚本内容
    script_content = ""
    if isinstance(test_script, dict):
        script_content = test_script.get("script_content", "") or test_script.get("script", "")
    elif isinstance(test_script, str):
        script_content = test_script

    # 提取执行结果摘要
    exec_summary = None
    if isinstance(execution_result, dict):
        exec_summary = {
            "status": execution_result.get("status", "unknown"),
            "success_count": execution_result.get("success_count", 0),
            "failed_count": execution_result.get("failed_count", 0),
            "duration": execution_result.get("duration", 0),
            "error_message": execution_result.get("error_message", ""),
            "report_path": execution_result.get("report_path", ""),
            "screenshot_path": execution_result.get("screenshot_path", ""),
            "log_content": (execution_result.get("log_content", "") or "")[-2000:],
        }

    # 提取失败分析（仅执行失败时存在）
    failure_analysis = None
    if isinstance(analysis_result, dict) and analysis_result.get("failure_reasons"):
        failure_analysis = {
            "root_cause": analysis_result.get("root_cause", ""),
            "failure_reasons": analysis_result.get("failure_reasons", []),
            "fix_suggestions": analysis_result.get("fix_suggestions", []),
            "failed_steps": analysis_result.get("failed_steps", []),
            "severity": analysis_result.get("severity", "medium"),
        }

    # 构建报告和截图URL
    report_url = None
    screenshot_url = None
    if exec_summary:
        if exec_summary.get("report_path"):
            report_url = f"/api/v1/task/{session_id}/report"
        if exec_summary.get("screenshot_path"):
            screenshot_url = f"/api/v1/task/{session_id}/screenshot"

    # 整体状态
    overall_status = "completed"
    if exec_summary and exec_summary.get("status") == "failed":
        overall_status = "failed"

    # 汇总消息
    if overall_status == "completed":
        msg = f"测试完成 | 成功: {exec_summary.get('success_count', 0)}, 失败: {exec_summary.get('failed_count', 0)} | 耗时: {duration:.1f}s"
    else:
        msg = f"测试失败 | 失败步骤: {exec_summary.get('failed_count', 0) if exec_summary else 0} | 耗时: {duration:.1f}s"

    return OneClickResponse(
        status=overall_status,
        session_id=session_id,
        requirement_analysis=req_analysis if isinstance(req_analysis, dict) else None,
        test_cases=test_cases if isinstance(test_cases, dict) else None,
        script_content=script_content or None,
        execution_result=exec_summary,
        failure_analysis=failure_analysis,
        report_url=report_url,
        screenshot_url=screenshot_url,
        duration=duration,
        message=msg,
    )


@router.post("/task/one-click", response_model=OneClickResponse, summary="一键执行完整测试流程")
async def one_click_run(req: OneClickRequest):
    """
    一键执行完整自动化测试流程。

    用户只需输入自然语言需求，系统自动完成：
    1. 需求理解 → 输出 business_flow, test_points, risk_points
    2. 知识检索 → MySQL页面元素 + Milvus历史案例 + Neo4j页面关系
    3. 生成测试用例
    4. 生成 Playwright 脚本
    5. 执行脚本
    6. 保存执行记录、截图、日志、报告
    7. 失败时自动调用分析Agent，输出失败原因和修复建议
    """
    task_runtime = get_task_runtime()

    # 自动识别测试类型
    workflow_name = _analyze_task_type(req.requirement)

    session_id = str(uuid.uuid4())[:8]

    # 快速预检
    try:
        from app.services.reuse_service import ReuseService
        quick_result = ReuseService.quick_check(requirement=req.requirement)
        if quick_result.get("reuse"):
            logger.info(f"一键执行 | 快速预检命中 | similarity={quick_result['similarity']}")
            return OneClickResponse(
                status="completed",
                session_id=session_id,
                script_content=quick_result.get("script_content", ""),
                execution_result={"status": "reused", "success_count": 0, "failed_count": 0},
                message=f"已复用历史脚本 | 相似度: {quick_result['similarity']} | 耗时: 0.1s",
                duration=0.1,
            )
    except Exception as e:
        logger.warning(f"一键执行 | 快速预检失败 | error={e}")

    # 构建管道步骤
    steps = build_pipeline_steps(workflow_name, req.requirement)

    # 注入管道元数据
    if steps and "payload" not in steps[0]:
        steps[0]["payload"] = {"requirement": req.requirement}
    steps[0]["payload"]["__pipeline_meta__"] = {
        "task_id": int(req.task_id) if req.task_id.isdigit() else 0,
        "session_id": session_id,
        "requirement": req.requirement,
        "execution_id": 0,
        "script_content": "",
    }

    start_time = time.time()
    result = await task_runtime.execute_pipeline(
        steps=steps,
        user_id=0,
        session_id=session_id,
        timeout=600,
    )
    duration = time.time() - start_time

    context = result.get("context", {})
    return _extract_one_click_results(context, session_id, duration)


@router.post("/task/one-click/stream", summary="一键执行（SSE流式）")
async def one_click_run_stream(req: OneClickRequest):
    """
    一键执行完整测试流程（SSE流式版）。

    实时推送执行进度，最终返回完整结果。
    """
    task_runtime = get_task_runtime()
    workflow_name = _analyze_task_type(req.requirement)
    session_id = str(uuid.uuid4())[:8]

    async def event_generator():
        try:
            # 快速预检
            try:
                from app.services.reuse_service import ReuseService
                quick_result = ReuseService.quick_check(requirement=req.requirement)
                if quick_result.get("reuse"):
                    yield f"data: {json.dumps({'event': 'reuse_hit', 'data': {'similarity': quick_result['similarity']}}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'event': 'pipeline_completed', 'data': {'status': 'completed', 'reused': True, 'script_content': quick_result.get('script_content', '')}}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'event': 'done', 'data': {}}, ensure_ascii=False)}\n\n"
                    return
            except Exception as e:
                logger.warning(f"一键SSE | 快速预检失败 | error={e}")

            steps = build_pipeline_steps(workflow_name, req.requirement)
            if steps and "payload" not in steps[0]:
                steps[0]["payload"] = {"requirement": req.requirement}
            steps[0]["payload"]["__pipeline_meta__"] = {
                "task_id": int(req.task_id) if req.task_id.isdigit() else 0,
                "session_id": session_id,
                "requirement": req.requirement,
                "execution_id": 0,
                "script_content": "",
            }

            start_time = time.time()
            final_context = {}

            async for event in task_runtime.execute_pipeline_sse(steps=steps, user_id=0, session_id=session_id, timeout=600):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

                # 捕获最终上下文
                if event.get("event") == "pipeline_completed":
                    final_context = event.get("data", {}).get("context", {})

            duration = time.time() - start_time
            response = _extract_one_click_results(final_context, session_id, duration)

            # 发送最终汇总结果
            yield f"data: {json.dumps({'event': 'one_click_result', 'data': response.model_dump()}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'event': 'done', 'data': {}}, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            logger.warning(f"SSE 客户端断开 | one-click/stream | session={session_id}")
            raise
        except Exception as e:
            logger.error(f"SSE 执行异常 | one-click/stream | session={session_id} | error={e}", exc_info=True)
            yield f"data: {json.dumps({'event': 'error', 'data': {'message': str(e)}}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'event': 'done', 'data': {}}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
