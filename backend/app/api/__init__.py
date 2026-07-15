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
from app.api.workflow import router as workflow_router
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
api_router.include_router(workflow_router, prefix="/workflow", tags=["工作流引擎"])
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
