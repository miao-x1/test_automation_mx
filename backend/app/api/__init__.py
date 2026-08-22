"""
API路由模块
"""
from fastapi import APIRouter
from app.api.health import router as health_router
from app.api.auth import router as auth_router
from app.api.task import router as task_router
from app.api.page import router as page_router
from app.api.execution import router as execution_router
from app.api.rag_v2 import router as rag_router
from app.api.requirement import router as requirement_router
from app.api.kb import router as kb_router
from app.api.graph import router as graph_router
from app.api.feedback import router as feedback_router
from app.api.dashboard import router as dashboard_router
from app.api.assets_v2 import router as test_asset_router
from app.api.page_relation import router as page_relation_router
from app.api.multimodal_input import router as multimodal_input_router
from app.api.schedule import router as schedule_router
from app.api.script_upload import router as script_upload_router
from app.api.admin import router as admin_router
from app.api.case import router as case_router
from app.api.knowledge import router as knowledge_router
from app.api.api_test import router as api_test_router
from app.api.upload_task import router as upload_task_router
from app.api.session_v2 import router as session_router
from app.api.workflow import router as workflow_event_router
from app.api.requirement_center import router as requirement_center_router
from app.api.graphflow import router as graphflow_router
from app.api.tri_store import router as tri_store_router
from app.api.page_knowledge import router as page_knowledge_router
from app.api.api_knowledge import router as api_knowledge_router
from app.api.knowledge_center import router as knowledge_center_router
from app.api.agent_runtime import router as agent_runtime_router
from app.api.testcase_generation import router as testcase_generation_router
from app.api.context_api import router as context_api_router
from app.api.requirement_input import router as requirement_input_router
from app.api.context_router import router as context_router_router
from app.api.orchestrator import router as orchestrator_router
from app.api.three_layer import router as three_layer_router

# ===== 新增模块: API 接口管理(与既有 api-test 接口测试、api-knowledge 知识库解耦) =====
from app.api.api_endpoint import router as api_endpoint_router

# ===== 新增模块: 接口测试数据生成 (ApiDataGeneratorAgent + 模板/生成数据管理) =====
from app.api.api_test_data import router as api_test_data_router

# ===== 新增模块: AI 接口调试 (ApiDebugAgent + Postman 风格执行) =====
from app.api.api_debug import router as api_debug_router

# ===== 新增模块: 企业级 Agent Runtime (TaskDispatcher + WorkerPool + SSE/WebSocket) =====
from app.api.runtime_enterprise import router as runtime_enterprise_router

# ===== 新增模块: Agent 管理中心 (注册/发现/配置/版本/生命周期) =====
from app.api.agent_center import router as agent_center_router

# ===== 新增模块: Prompt 版本管理 (版本/AB测试/回滚/比较) =====
from app.api.prompt_manager import router as prompt_manager_router

# ===== 新增模块: 测试资产中心 (Asset Registry / Version / Relation / Search) =====
from app.api.asset_registry import router as asset_registry_router
from app.api.asset_relations import router as asset_relations_router
from app.api.asset_search import router as asset_search_router
from app.api.asset_agents import router as asset_agents_router

# ===== 新增模块: LLM Gateway (统一大模型调用网关) =====
from app.api.llm_gateway import router as llm_gateway_router

# ===== 新增模块: 测试编排系统 (TestPlan + ExecutionFlow + Orchestrator) =====
from app.api.test_orchestration import router as test_orchestration_router

# ===== 新增模块: 测试环境管理 (Environment + Secret + Encryption) =====
from app.api.environment import router as environment_router

# ===== 新增模块: 测试质量分析 (Quality Analysis + LLM) =====
from app.api.quality_analysis import router as quality_analysis_router

# ===== 新增模块: AI 测试反馈学习 (Feedback Learning + LLM) =====
from app.api.feedback_learning import router as feedback_learning_router

# ===== 新增: 企业级安全 (API Key / 脱敏 / 审计日志) =====
from app.api.security import router as security_router

# ===== 新增: Runtime v2 (统一 Agent 运行时) =====
from app.api.runtime_v2 import router as runtime_v2_router

# ===== 新增: Graph 工作流 (UI/API/性能测试流程) =====
from app.api.workflow_api import router as workflow_api_router

# ===== 新增模块: 性能测试 (API/Web性能测试, Locust/JMeter) =====
from app.api.performance import router as performance_router

# ===== 新增模块: 代码执行 (LLM生成代码 + 沙箱隔离执行) =====
from app.api.code import router as code_router

# 主路由
api_router = APIRouter()

# 注册子路由
api_router.include_router(health_router, tags=["健康检查"])
api_router.include_router(auth_router, prefix="/auth", tags=["认证"])
api_router.include_router(dashboard_router, prefix="/dashboard", tags=["仪表盘"])
api_router.include_router(task_router, prefix="/tasks", tags=["任务管理"])
api_router.include_router(test_asset_router, prefix="/assets/v2", tags=["测试资产管理"])
api_router.include_router(page_router, prefix="/page", tags=["页面抓取(兼容)"])
api_router.include_router(execution_router, prefix="/executions", tags=["执行管理"])
api_router.include_router(rag_router, prefix="/rag", tags=["RAG知识库"])
api_router.include_router(requirement_router, prefix="/requirement", tags=["需求驱动测试"])
api_router.include_router(kb_router, prefix="/kb", tags=["知识库管理"])
api_router.include_router(graph_router, prefix="/graph", tags=["图数据库"])
api_router.include_router(feedback_router, prefix="/feedback", tags=["用户反馈"])
api_router.include_router(page_relation_router, prefix="/page-relation", tags=["页面关联"])
api_router.include_router(multimodal_input_router, prefix="/multimodal-input", tags=["多模态输入"])
api_router.include_router(schedule_router, prefix="/schedule", tags=["定时任务"])
api_router.include_router(script_upload_router, prefix="/script-upload", tags=["脚本上传"])
api_router.include_router(admin_router, prefix="/admin", tags=["管理模块"])
api_router.include_router(case_router, prefix="/case", tags=["用例中心"])
api_router.include_router(knowledge_router, prefix="/knowledge", tags=["知识服务"])
api_router.include_router(api_test_router, prefix="/api-test", tags=["接口测试"])
api_router.include_router(upload_task_router, prefix="/upload/task", tags=["上传任务系统"])
api_router.include_router(session_router, tags=["会话管理"])
api_router.include_router(workflow_event_router, prefix="/workflow", tags=["工作流引擎"])
api_router.include_router(requirement_center_router, tags=["需求中心"])
api_router.include_router(graphflow_router)
api_router.include_router(tri_store_router, prefix="/tri-store", tags=["三库协同"])
api_router.include_router(page_knowledge_router, prefix="/page-knowledge", tags=["页面知识库"])
api_router.include_router(api_knowledge_router, prefix="/api-knowledge", tags=["接口知识库"])
api_router.include_router(knowledge_center_router, prefix="/knowledge-center", tags=["知识中心"])
api_router.include_router(agent_runtime_router, prefix="/api/v1", tags=["Agent Runtime"])
api_router.include_router(testcase_generation_router, prefix="/api/v1", tags=["测试用例生成"])
api_router.include_router(context_api_router, prefix="/api/v1", tags=["三层上下文"])
api_router.include_router(requirement_input_router, prefix="/api/v1/requirement-input", tags=["需求输入"])
api_router.include_router(context_router_router, prefix="/context", tags=["上下文路由"])
api_router.include_router(orchestrator_router, tags=["任务编排"])
api_router.include_router(three_layer_router, prefix="/three-layer", tags=["三层分析"])

# ===== 新增: API 接口管理(独立模块,不依赖既有 api-test / api-knowledge) =====
api_router.include_router(api_endpoint_router, prefix="/endpoints", tags=["API 接口管理"])

# ===== 新增: 接口测试数据生成 (ApiDataGeneratorAgent 暴露 HTTP 接口) =====
api_router.include_router(api_test_data_router, prefix="/api-test-data", tags=["接口测试数据生成"])

# ===== 新增: AI 接口调试 (Postman 风格执行 + 失败原因分析) =====
api_router.include_router(api_debug_router, prefix="/api-debug", tags=["AI 接口调试"])

# ===== 新增: 企业级 Agent Runtime (任务分发 + SSE/WebSocket) =====
api_router.include_router(runtime_enterprise_router, prefix="/runtime", tags=["企业级 Runtime"])

# ===== 新增: Agent 管理中心 (统一管理注册/发现/配置/版本/生命周期) =====
api_router.include_router(agent_center_router, prefix="/agent-center", tags=["Agent 管理中心"])

# ===== 新增: Prompt 版本管理 (版本管理/AB测试/回滚/比较) =====
api_router.include_router(prompt_manager_router, prefix="/prompt-center", tags=["Prompt 管理"])

# ===== 新增: 测试资产中心 (统一资产索引, 支持 CRUD / 版本 / 关系 / 搜索) =====
api_router.include_router(asset_registry_router, prefix="/asset-center/assets", tags=["测试资产中心-资产"])
api_router.include_router(asset_relations_router, prefix="/asset-center/relations", tags=["测试资产中心-关系"])
api_router.include_router(asset_search_router, prefix="/asset-center/search", tags=["测试资产中心-搜索"])
api_router.include_router(asset_agents_router, prefix="/asset-center/agents", tags=["测试资产中心-Agent"])

# ===== 新增: LLM Gateway (统一大模型调用网关) =====
api_router.include_router(llm_gateway_router, tags=["LLM Gateway"])

# ===== 新增: 测试编排系统 (TestPlan + ExecutionFlow + Orchestrator) =====
api_router.include_router(test_orchestration_router, prefix="/test-orchestration", tags=["测试编排"])

# ===== 新增: 测试环境管理 (Environment + Secret + Encryption) =====
api_router.include_router(environment_router, prefix="/environments", tags=["测试环境"])

# ===== 新增: 测试质量分析 (Quality Analysis + LLM) =====
api_router.include_router(quality_analysis_router, prefix="/quality-analysis", tags=["测试质量分析"])

# ===== 新增: AI 测试反馈学习 (Feedback Learning + LLM) =====
api_router.include_router(feedback_learning_router, prefix="/feedback-learning", tags=["AI反馈学习"])

# ===== 新增: 企业级安全 (API Key / 脱敏 / 审计日志) =====
api_router.include_router(security_router, prefix="/security", tags=["企业安全"])

# ===== 新增: Runtime v2 (统一 Agent 运行时 — Dispatcher/Worker/Collector/SSE) =====
api_router.include_router(runtime_v2_router, tags=["Runtime v2"])

# ===== 新增: Graph 工作流 (UI/API/性能测试流程) =====
api_router.include_router(workflow_api_router, tags=["Graph 工作流"])

# ===== 新增: 性能测试 (API/Web性能测试, Locust/JMeter, 实时指标+LLM分析) =====
api_router.include_router(performance_router, prefix="/performance", tags=["性能测试"])

# ===== 新增: 代码执行 (LLM生成代码 + 沙箱隔离执行) =====
api_router.include_router(code_router, prefix="/code", tags=["代码执行"])
