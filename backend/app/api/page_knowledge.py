"""
Page Knowledge API - 页面知识库接口

提供页面截图上传、元素查询、页面搜索等 API。

端点：
  POST   /upload         上传截图（自动OCR+分析+三库存储）
  GET    /pages          页面列表
  GET    /pages/{name}   页面详情
  GET    /elements/{name} 获取页面所有元素（不需要再次OCR）
  GET    /elements/{name}/{type} 按类型获取元素
  GET    /relations/{name} 获取页面关系
  POST   /search         搜索页面（关键词+向量）
  GET    /stats          统计信息
"""
import logging
import os
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile, Query, HTTPException

from app.services.page_knowledge_service import get_page_knowledge_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/upload")
async def upload_screenshot(
    file: UploadFile = File(...),
    page_name: str = Form(""),
    page_url: str = Form(""),
    project_id: str = Form("default"),
    user_id: Optional[int] = Form(None),
):
    """上传页面截图并自动完成完整处理管道

    自动流程：OCR → 页面描述 → 元素提取 → 关系建模 → MySQL + Milvus + Neo4j
    处理完成后，后续查询「登录页面」直接返回所有元素，不需要再次OCR。
    """
    # 保存文件
    from app.core.config import settings
    upload_dir = os.path.join(settings.UPLOAD_DIR, "page_knowledge")
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file.filename)
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # 执行处理管道
    service = get_page_knowledge_service()
    result = await service.upload_screenshot(
        screenshot_path=file_path,
        page_name=page_name,
        page_url=page_url,
        project_id=project_id,
        user_id=user_id,
    )
    return {"code": 0, "message": "页面知识处理完成", "data": result}


@router.get("/pages")
async def list_pages(
    keyword: str = Query(""),
    page_type: str = Query(""),
    module: str = Query(""),
    limit: int = Query(50, le=200),
):
    """页面列表"""
    service = get_page_knowledge_service()
    pages = service.search_pages(
        keyword=keyword,
        page_type=page_type,
        module=module,
        limit=limit,
    )
    return {"code": 0, "message": "success", "data": pages}


@router.get("/pages/{page_name}")
async def get_page(page_name: str):
    """页面详情（含完整元素列表）"""
    service = get_page_knowledge_service()
    page_info = service.get_page_by_name(page_name)
    if page_info is None:
        raise HTTPException(status_code=404, detail=f"页面 '{page_name}' 不存在")
    relations = service.get_page_relations(page_name)
    return {
        "code": 0,
        "message": "success",
        "data": {"page_info": page_info, "relations": relations},
    }


@router.get("/elements/{page_name}")
async def get_elements(page_name: str):
    """获取页面的所有元素（不需要再次OCR）

    CaseAgent 核心查询接口：
      查询「登录页面」→ 返回所有元素（按钮/输入框/菜单等）
    """
    service = get_page_knowledge_service()
    elements = service.get_page_elements(page_name)
    page_info = service.get_page_by_name(page_name)
    return {
        "code": 0,
        "message": "success",
        "data": {
            "page_name": page_name,
            "page_info": page_info,
            "elements": elements,
            "total": len(elements),
        },
    }


@router.get("/elements/{page_name}/{element_type}")
async def get_elements_by_type(page_name: str, element_type: str):
    """按类型获取页面元素

    支持的类型：button / input / link / select / textarea / menu / text / img / other
    """
    service = get_page_knowledge_service()
    elements = service.get_page_elements_by_type(page_name, element_type)
    return {
        "code": 0,
        "message": "success",
        "data": {
            "page_name": page_name,
            "element_type": element_type,
            "elements": elements,
            "total": len(elements),
        },
    }


@router.get("/relations/{page_name}")
async def get_relations(page_name: str):
    """获取页面关系"""
    service = get_page_knowledge_service()
    relations = service.get_page_relations(page_name)
    return {
        "code": 0,
        "message": "success",
        "data": {"page_name": page_name, "relations": relations},
    }


@router.post("/search")
async def search_pages(
    keyword: str = Form(...),
    page_type: str = Form(""),
    module: str = Form(""),
    limit: int = Form(50),
):
    """搜索页面（关键词搜索 + 向量搜索）"""
    service = get_page_knowledge_service()
    # 关键词搜索
    results = service.search_pages(
        keyword=keyword,
        page_type=page_type,
        module=module,
        limit=limit,
    )
    search_method = "keyword"
    # 如果关键词搜索无结果，尝试向量搜索
    if keyword and not results:
        vector_results = await service.search_pages_by_vector(keyword, top_k=limit)
        if vector_results:
            results = vector_results
            search_method = "vector"
    return {
        "code": 0,
        "message": "success",
        "data": {
            "search_method": search_method,
            "results": results,
            "total": len(results),
        },
    }


@router.get("/stats")
async def get_stats():
    """统计信息"""
    service = get_page_knowledge_service()
    stats = service.get_stats()
    return {"code": 0, "message": "success", "data": stats}
