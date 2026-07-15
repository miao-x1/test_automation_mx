"""
API Knowledge API - 接口知识库接口

提供接口文件上传、接口查询、依赖关系查看等 API。

端点：
  POST   /upload                上传接口文件（自动解析+三库存储+依赖检测）
  GET    /apis                  接口列表
  GET    /apis/{api_id}         接口详情
  GET    /apis/by-path           按method+path查询接口
  POST   /search                搜索接口
  GET    /dependencies/{api_id} 获取接口依赖关系
  GET    /related/{api_id}      获取相关接口（依赖图遍历）
  GET    /stats                 统计信息
"""
import logging
import os
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile, Query, HTTPException

from app.services.api_knowledge_service import get_api_knowledge_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/upload")
async def upload_api_file(
    file: UploadFile = File(...),
    source_type: str = Form(""),
    project_id: str = Form("default"),
    user_id: Optional[int] = Form(None),
):
    """上传接口文件并自动完成完整处理管道

    支持：Swagger / OpenAPI / Postman / JMeter / JSON
    自动流程：检测来源 → 解析 → 结构化 → MySQL + Milvus + Neo4j → 依赖检测
    """
    upload_dir = os.path.join(os.getcwd(), "uploads", "api_knowledge")
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file.filename)
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    service = get_api_knowledge_service()
    result = await service.parse_and_store(
        file_path=file_path,
        source_type=source_type,
        project_id=project_id,
        user_id=user_id,
    )
    return {"code": 0, "message": "接口知识处理完成", "data": result}


@router.get("/apis")
async def list_apis(
    keyword: str = Query(""),
    method: str = Query(""),
    module: str = Query(""),
    tags: str = Query(""),
    limit: int = Query(50, le=200),
):
    """接口列表"""
    service = get_api_knowledge_service()
    apis = service.search_apis(
        keyword=keyword,
        method=method,
        module=module,
        tags=tags,
        limit=limit,
    )
    return {"code": 0, "message": "success", "data": apis}


@router.get("/apis/{api_id}")
async def get_api(api_id: int):
    """接口详情（含参数/Header/Body/Response）"""
    service = get_api_knowledge_service()
    api = service.get_api(api_id)
    if api is None:
        raise HTTPException(status_code=404, detail=f"接口 {api_id} 不存在")
    return {"code": 0, "message": "success", "data": api}


@router.get("/apis/by-path")
async def get_api_by_path(
    method: str = Query(..., description="HTTP方法"),
    path: str = Query(..., description="接口路径"),
):
    """按 method + path 查询接口"""
    service = get_api_knowledge_service()
    api = service.get_api_by_method_path(method, path)
    if api is None:
        raise HTTPException(status_code=404, detail=f"接口 {method} {path} 不存在")
    return {"code": 0, "message": "success", "data": api}


@router.post("/search")
async def search_apis(
    keyword: str = Form(""),
    method: str = Form(""),
    module: str = Form(""),
    tags: str = Form(""),
    limit: int = Form(50),
):
    """搜索接口（按关键词/方法/模块/标签）"""
    service = get_api_knowledge_service()
    results = service.search_apis(
        keyword=keyword,
        method=method,
        module=module,
        tags=tags,
        limit=limit,
    )
    return {
        "code": 0,
        "message": "success",
        "data": {"results": results, "total": len(results)},
    }


@router.get("/dependencies/{api_id}")
async def get_dependencies(api_id: int):
    """获取接口的依赖关系

    返回：
      depends_on:  本接口依赖哪些接口
      consumed_by: 哪些接口依赖本接口
    """
    service = get_api_knowledge_service()
    deps = service.get_dependencies(api_id)
    return {"code": 0, "message": "success", "data": deps}


@router.get("/related/{api_id}")
async def get_related_apis(
    api_id: int,
    depth: int = Query(1, ge=1, le=5, description="依赖图遍历深度"),
):
    """获取相关接口（通过依赖关系图遍历）

    API Agent 核心查询接口：
      给定一个接口ID，返回所有相关接口（依赖链路）。
    """
    service = get_api_knowledge_service()
    related = service.get_related_apis(api_id, depth=depth)
    deps = service.get_dependencies(api_id)
    return {
        "code": 0,
        "message": "success",
        "data": {
            "api_id": api_id,
            "depth": depth,
            "related_apis": related,
            "total_related": len(related),
            "dependencies": deps,
        },
    }


@router.get("/stats")
async def get_stats():
    """统计信息"""
    service = get_api_knowledge_service()
    stats = service.get_stats()
    return {"code": 0, "message": "success", "data": stats}
