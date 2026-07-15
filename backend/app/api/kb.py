"""
知识库管理API

数据隔离：所有查询自动过滤 user_id
"""
import json
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from app.schemas.response import Response
from app.services.kb_service import KBService
from app.core.auth import require_auth
from app.models.user import User

router = APIRouter()


# ==================== 请求模型 ====================

class ElementUpdateRequest(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    text: Optional[str] = None
    locator: Optional[str] = None
    xpath: Optional[str] = None
    css_selector: Optional[str] = None


class CaseUpdateRequest(BaseModel):
    case_name: Optional[str] = None
    description: Optional[str] = None
    steps: Optional[list] = None
    assertions: Optional[list] = None


class ScriptUpdateRequest(BaseModel):
    script_content: Optional[str] = None
    script_type: Optional[str] = None


class BatchDeleteRequest(BaseModel):
    ids: list[int]


# ==================== 元素库 ====================

@router.get("/elements", summary="查询元素列表")
async def list_elements(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    name: Optional[str] = None,
    type: Optional[str] = None,
    source: Optional[str] = None,
    page_url: Optional[str] = None,
    kb_status: Optional[str] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    user: User = Depends(require_auth),
):
    data = KBService.list_elements(page, page_size, name, type, source, page_url, kb_status, sort_by, sort_order, user_id=user.id)
    return Response(code=200, data=data)


@router.get("/elements/{element_id}", summary="获取元素详情")
async def get_element(element_id: int, user: User = Depends(require_auth)):
    data = KBService.get_element(element_id, user_id=user.id)
    if not data:
        raise HTTPException(status_code=404, detail="元素不存在")
    return Response(code=200, data=data)


@router.put("/elements/{element_id}", summary="更新元素")
async def update_element(element_id: int, req: ElementUpdateRequest, user: User = Depends(require_auth)):
    data = KBService.update_element(element_id, req.model_dump(exclude_none=True), user_id=user.id)
    if not data:
        raise HTTPException(status_code=404, detail="元素不存在")
    return Response(code=200, data=data, message="更新成功")


@router.delete("/elements/{element_id}", summary="删除元素")
async def delete_element(element_id: int, user: User = Depends(require_auth)):
    if not KBService.delete_element(element_id, user_id=user.id):
        raise HTTPException(status_code=404, detail="元素不存在")
    return Response(code=200, message="删除成功")


@router.post("/elements/batch-delete", summary="批量删除元素")
async def batch_delete_elements(req: BatchDeleteRequest, user: User = Depends(require_auth)):
    data = KBService.batch_delete_elements(req.ids, user_id=user.id)
    return Response(code=200, data=data, message=f"删除完成: 成功{data['success']}个")


@router.post("/elements/{element_id}/reindex", summary="重新向量化元素")
async def reindex_element(element_id: int, user: User = Depends(require_auth)):
    async def generate():
        async for msg in KBService.reindex_element(element_id, user_id=user.id):
            yield {"data": msg}
    return EventSourceResponse(generate())


@router.post("/elements/{element_id}/approve", summary="批准元素")
async def approve_element(element_id: int, user: User = Depends(require_auth)):
    if not KBService.approve_element(element_id, user_id=user.id):
        raise HTTPException(status_code=404, detail="元素不存在")
    return Response(code=200, message="已批准")


@router.post("/elements/{element_id}/reject", summary="拒绝元素")
async def reject_element(element_id: int, user: User = Depends(require_auth)):
    if not KBService.reject_element(element_id, user_id=user.id):
        raise HTTPException(status_code=404, detail="元素不存在")
    return Response(code=200, message="已拒绝")


# ==================== 用例库 ====================

@router.get("/cases", summary="查询用例列表")
async def list_cases(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    case_name: Optional[str] = None,
    kb_status: Optional[str] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    user: User = Depends(require_auth),
):
    data = KBService.list_cases(page, page_size, case_name, kb_status, sort_by, sort_order, user_id=user.id)
    return Response(code=200, data=data)


@router.get("/cases/{case_id}", summary="获取用例详情")
async def get_case(case_id: int, user: User = Depends(require_auth)):
    data = KBService.get_case(case_id, user_id=user.id)
    if not data:
        raise HTTPException(status_code=404, detail="用例不存在")
    return Response(code=200, data=data)


@router.put("/cases/{case_id}", summary="更新用例")
async def update_case(case_id: int, req: CaseUpdateRequest, user: User = Depends(require_auth)):
    data = KBService.update_case(case_id, req.model_dump(exclude_none=True), user_id=user.id)
    if not data:
        raise HTTPException(status_code=404, detail="用例不存在")
    return Response(code=200, data=data, message="更新成功")


@router.delete("/cases/{case_id}", summary="删除用例")
async def delete_case(case_id: int, user: User = Depends(require_auth)):
    if not KBService.delete_case(case_id, user_id=user.id):
        raise HTTPException(status_code=404, detail="用例不存在")
    return Response(code=200, message="删除成功")


@router.post("/cases/batch-delete", summary="批量删除用例")
async def batch_delete_cases(req: BatchDeleteRequest, user: User = Depends(require_auth)):
    data = KBService.batch_delete_cases(req.ids, user_id=user.id)
    return Response(code=200, data=data, message=f"删除完成: 成功{data['success']}个")


@router.post("/cases/{case_id}/reindex", summary="重新向量化用例")
async def reindex_case(case_id: int, user: User = Depends(require_auth)):
    async def generate():
        async for msg in KBService.reindex_case(case_id, user_id=user.id):
            yield {"data": msg}
    return EventSourceResponse(generate())


@router.post("/cases/{case_id}/approve", summary="批准用例")
async def approve_case(case_id: int, user: User = Depends(require_auth)):
    if not KBService.approve_case(case_id, user_id=user.id):
        raise HTTPException(status_code=404, detail="用例不存在")
    return Response(code=200, message="已批准")


@router.post("/cases/{case_id}/reject", summary="拒绝用例")
async def reject_case(case_id: int, user: User = Depends(require_auth)):
    if not KBService.reject_case(case_id, user_id=user.id):
        raise HTTPException(status_code=404, detail="用例不存在")
    return Response(code=200, message="已拒绝")


# ==================== 脚本库 ====================

@router.get("/scripts", summary="查询脚本列表")
async def list_scripts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    script_name: Optional[str] = None,
    kb_status: Optional[str] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    user: User = Depends(require_auth),
):
    data = KBService.list_scripts(page, page_size, script_name, kb_status, sort_by, sort_order, user_id=user.id)
    return Response(code=200, data=data)


@router.get("/scripts/{script_id}", summary="获取脚本详情")
async def get_script(script_id: int, user: User = Depends(require_auth)):
    data = KBService.get_script(script_id, user_id=user.id)
    if not data:
        raise HTTPException(status_code=404, detail="脚本不存在")
    return Response(code=200, data=data)


@router.put("/scripts/{script_id}", summary="更新脚本")
async def update_script(script_id: int, req: ScriptUpdateRequest, user: User = Depends(require_auth)):
    data = KBService.update_script(script_id, req.model_dump(exclude_none=True), user_id=user.id)
    if not data:
        raise HTTPException(status_code=404, detail="脚本不存在")
    return Response(code=200, data=data, message="更新成功")


@router.delete("/scripts/{script_id}", summary="删除脚本")
async def delete_script(script_id: int, user: User = Depends(require_auth)):
    if not KBService.delete_script(script_id, user_id=user.id):
        raise HTTPException(status_code=404, detail="脚本不存在")
    return Response(code=200, message="删除成功")


@router.post("/scripts/batch-delete", summary="批量删除脚本")
async def batch_delete_scripts(req: BatchDeleteRequest, user: User = Depends(require_auth)):
    data = KBService.batch_delete_scripts(req.ids, user_id=user.id)
    return Response(code=200, data=data, message=f"删除完成: 成功{data['success']}个")


@router.post("/scripts/{script_id}/reindex", summary="重新向量化脚本")
async def reindex_script(script_id: int, user: User = Depends(require_auth)):
    async def generate():
        async for msg in KBService.reindex_script(script_id, user_id=user.id):
            yield {"data": msg}
    return EventSourceResponse(generate())


@router.post("/scripts/{script_id}/approve", summary="批准脚本")
async def approve_script(script_id: int, user: User = Depends(require_auth)):
    if not KBService.approve_script(script_id, user_id=user.id):
        raise HTTPException(status_code=404, detail="脚本不存在")
    return Response(code=200, message="已批准")


@router.post("/scripts/{script_id}/reject", summary="拒绝脚本")
async def reject_script(script_id: int, user: User = Depends(require_auth)):
    if not KBService.reject_script(script_id, user_id=user.id):
        raise HTTPException(status_code=404, detail="脚本不存在")
    return Response(code=200, message="已拒绝")


# ==================== 统计 ====================

@router.get("/statistics", summary="知识库统计")
async def get_statistics(user: User = Depends(require_auth)):
    data = KBService.get_statistics(user_id=user.id)
    return Response(code=200, data=data)


# ==================== 去重 ====================

@router.post("/detect-duplicates", summary="检测重复数据")
async def detect_duplicates(user: User = Depends(require_auth)):
    data = KBService.detect_duplicates(user_id=user.id)
    return Response(code=200, data=data)


@router.post("/deduplicate", summary="一键去重")
async def deduplicate(user: User = Depends(require_auth)):
    async def generate():
        async for msg in KBService.deduplicate(user_id=user.id):
            yield {"data": msg}
    return EventSourceResponse(generate())
