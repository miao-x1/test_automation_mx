"""
接口测试统一 API

路由前缀：/api-test

子模块：
  - case_controller: 用例管理 + 目录管理
  - suite_controller: 测试套件
  - execution_controller: 执行引擎
  - report_controller: 报告
  - import_controller: 用例导入（AI/Swagger）
"""
from fastapi import APIRouter

from app.api.api_test.case_controller import router as case_router
from app.api.api_test.suite_controller import router as suite_router
from app.api.api_test.execution_controller import router as execution_router
from app.api.api_test.report_controller import router as report_router
from app.api.api_test.import_controller import router as import_router

router = APIRouter()

router.include_router(case_router)
router.include_router(suite_router)
router.include_router(execution_router)
router.include_router(report_router)
router.include_router(import_router)
