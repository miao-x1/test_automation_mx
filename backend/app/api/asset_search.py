"""
测试资产中心 — 资产搜索路由

挂载路径: /api/asset-center/search

接口分组:
  1. 搜索         - POST / (三源融合搜索)
  2. 反查         - GET /by-ref (按 ref_type+ref_id 反查资产)
  3. 批量反查     - GET /by-codes (按 asset_code 列表批量查询)

设计要点:
  1. 使用 Depends(require_auth) 获取当前用户
  2. 搜索结果含命中原因 (可解释性)
  3. Phase 2: Milvus / Neo4j 为 stub, 仅 MySQL 搜索生效
  4. Phase 3: AssetSearchAgent 调用此接口, 补充向量/关系召回
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from app.core.auth import require_auth
from app.models.user import User
from app.schemas.asset_registry import (
    AssetResponse,
    SearchRequest,
    SearchResponse,
)
from app.schemas.response import Response
from app.services.asset_search_service import AssetSearchService

router = APIRouter()

# 服务实例(无状态,可全局复用)
_service = AssetSearchService()


# ============================================================
# 1. 搜索
# ============================================================

@router.post("", response_model=Response[SearchResponse], summary="三源融合搜索")
async def search(
    payload: SearchRequest,
    user: User = Depends(require_auth),
):
    """三源融合搜索测试资产

    融合公式: final_score = 0.5 * mysql + 0.3 * milvus + 0.2 * relation

    Phase 2:
      - MySQL 搜索生效 (关键词匹配 + 评分)
      - Milvus / Neo4j 为 stub (返回空)
    Phase 3:
      - AssetSearchAgent 接入真实 Milvus 向量召回
      - AssetSearchAgent 接入真实 Neo4j 关系扩展
    """
    result = _service.search(payload, user_id=user.id)
    return Response(data=SearchResponse(**result))


# ============================================================
# 2. 反查
# ============================================================

@router.get("/by-ref", response_model=Response[AssetResponse], summary="按 ref 反查资产")
async def find_by_ref(
    ref_type: str = Query(..., description="关联表名"),
    ref_id: int = Query(..., ge=0, description="关联记录 ID, 0 表示纯索引资产"),
    user: User = Depends(require_auth),
):
    """按 ref_type + ref_id 反查资产 (精确匹配)

    用于 Agent 根据既有业务对象 ID 查找对应的资产索引
    """
    result = _service.find_by_ref(ref_type, ref_id, user_id=user.id)
    if result is None:
        return Response(
            code=404,
            message=f"未找到资产: ref_type={ref_type}, ref_id={ref_id}",
            data=None,
        )
    return Response(data=AssetResponse(**result))


@router.get("/by-codes", response_model=Response[List[AssetResponse]], summary="按 asset_code 批量查询")
async def find_by_codes(
    codes: str = Query(..., description="asset_code 列表(逗号分隔)"),
    user: User = Depends(require_auth),
):
    """按 asset_code 列表批量查询资产"""
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    if not code_list:
        return Response(data=[])
    result = _service.find_by_codes(code_list, user_id=user.id)
    return Response(data=[AssetResponse(**r) for r in result])
