"""
统一测试资产 API

替代：
  - /test-assets（旧资产中心）
  - /api-test/cases（接口测试用例）
  - /case（用例中心）

所有测试资产统一通过 /assets/v2/ 管理
"""
import json
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel as PydanticModel
from app.core.logger import log
from app.db.database import SessionLocal
from app.models.test_asset import TestAsset as TestAssetV2, AssetType, AssetStatus, AssetSource
from app.core.auth import require_auth
from app.models.user import User

router = APIRouter()


class PublishRequest(PydanticModel):
    """发布请求"""
    asset_ids: List[int]


class UpdateAssetRequest(PydanticModel):
    """更新资产请求"""
    title: Optional[str] = None
    draft_content: Optional[str] = None
    priority: Optional[str] = None
    tags: Optional[str] = None
    asset_type: Optional[str] = None


@router.get("/list")
async def list_assets(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    asset_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    folder_id: Optional[int] = Query(None),
    session_id: Optional[int] = Query(None),
    user: User = Depends(require_auth),
):
    """资产列表（统一）"""
    db = SessionLocal()
    try:
        query = db.query(TestAssetV2).filter(
            TestAssetV2.user_id == user.id,
            TestAssetV2.is_deleted == False,
        )
        if asset_type:
            query = query.filter(TestAssetV2.asset_type == asset_type)
        if status:
            query = query.filter(TestAssetV2.status == status)
        if source:
            query = query.filter(TestAssetV2.source_type == source)
        if keyword:
            query = query.filter(TestAssetV2.title.contains(keyword))
        if folder_id:
            query = query.filter(TestAssetV2.folder_id == folder_id)
        if session_id:
            query = query.filter(TestAssetV2.session_id == session_id)

        total = query.count()
        assets = query.order_by(TestAssetV2.id.desc()).offset(skip).limit(limit).all()

        # 统计
        type_stats = {}
        for t in [AssetType.API, AssetType.WEB, AssetType.ANDROID, AssetType.CASE]:
            count = db.query(TestAssetV2).filter(
                TestAssetV2.user_id == user.id,
                TestAssetV2.asset_type == t.value,
                TestAssetV2.is_deleted == False,
            ).count()
            type_stats[t.value] = count

        draft_count = db.query(TestAssetV2).filter(
            TestAssetV2.user_id == user.id,
            TestAssetV2.status.in_([AssetStatus.CREATED, AssetStatus.GENERATED]),
            TestAssetV2.is_deleted == False,
        ).count()

        return {
            "items": [
                {
                    "id": a.id,
                    "title": a.title,
                    "asset_type": a.asset_type,
                    "status": a.status,
                    "source": a.source,
                    "priority": a.priority,
                    "tags": a.tags.split(",") if a.tags else [],
                    "session_id": a.session_id,
                    "folder_id": a.folder_id,
                    "version": a.version,
                    "has_draft": bool(a.draft_content),
                    "has_published": bool(a.published_content),
                    "created_at": str(a.created_at) if a.created_at else None,
                    "updated_at": str(a.updated_at) if a.updated_at else None,
                }
                for a in assets
            ],
            "total": total,
            "type_stats": type_stats,
            "draft_count": draft_count,
        }
    finally:
        db.close()


@router.get("/{asset_id}")
async def get_asset(
    asset_id: int,
    user: User = Depends(require_auth),
):
    """资产详情"""
    db = SessionLocal()
    try:
        asset = db.query(TestAssetV2).filter(
            TestAssetV2.id == asset_id,
            TestAssetV2.user_id == user.id,
            TestAssetV2.is_deleted == False,
        ).first()
        if not asset:
            raise HTTPException(status_code=404, detail="资产不存在")

        result = {
            "id": asset.id,
            "title": asset.title,
            "description": asset.description,
            "asset_type": asset.asset_type,
            "status": asset.status,
            "source": asset.source,
            "priority": asset.priority,
            "tags": asset.tags.split(",") if asset.tags else [],
            "session_id": asset.session_id,
            "folder_id": asset.folder_id,
            "version": asset.version,
            "draft_content": json.loads(asset.draft_content) if asset.draft_content else None,
            "published_content": json.loads(asset.published_content) if asset.published_content else None,
            "execution_state": json.loads(asset.execution_state) if asset.execution_state else None,
            "created_at": str(asset.created_at) if asset.created_at else None,
            "updated_at": str(asset.updated_at) if asset.updated_at else None,
        }
        return result
    finally:
        db.close()


@router.put("/{asset_id}")
async def update_asset(
    asset_id: int,
    request: UpdateAssetRequest,
    user: User = Depends(require_auth),
):
    """更新资产"""
    db = SessionLocal()
    try:
        asset = db.query(TestAssetV2).filter(
            TestAssetV2.id == asset_id,
            TestAssetV2.user_id == user.id,
            TestAssetV2.is_deleted == False,
        ).first()
        if not asset:
            raise HTTPException(status_code=404, detail="资产不存在")

        if request.title is not None:
            asset.title = request.title
        if request.draft_content is not None:
            asset.draft_content = request.draft_content
        if request.priority is not None:
            asset.priority = request.priority
        if request.tags is not None:
            asset.tags = request.tags
        if request.asset_type is not None:
            asset.asset_type = request.asset_type

        db.commit()
        return {"id": asset.id, "status": asset.status}
    finally:
        db.close()


@router.post("/publish")
async def publish_assets(
    request: PublishRequest,
    user: User = Depends(require_auth),
):
    """发布资产（draft → published）"""
    db = SessionLocal()
    try:
        published = []
        for aid in request.asset_ids:
            asset = db.query(TestAssetV2).filter(
                TestAssetV2.id == aid,
                TestAssetV2.user_id == user.id,
                TestAssetV2.is_deleted == False,
            ).first()
            if asset and asset.status in (AssetStatus.GENERATED, AssetStatus.REVIEWED):
                asset.publish()
                published.append(aid)
        db.commit()
        return {"published": published, "count": len(published)}
    finally:
        db.close()


@router.delete("/{asset_id}")
async def delete_asset(
    asset_id: int,
    user: User = Depends(require_auth),
):
    """软删除资产"""
    db = SessionLocal()
    try:
        asset = db.query(TestAssetV2).filter(
            TestAssetV2.id == asset_id,
            TestAssetV2.user_id == user.id,
        ).first()
        if not asset:
            raise HTTPException(status_code=404, detail="资产不存在")
        asset.is_deleted = True
        db.commit()
        return {"id": asset_id, "deleted": True}
    finally:
        db.close()


@router.get("/stats/summary")
async def stats_summary(
    user: User = Depends(require_auth),
):
    """资产统计"""
    db = SessionLocal()
    try:
        from sqlalchemy import func
        stats = db.query(
            TestAssetV2.asset_type,
            TestAssetV2.status,
            func.count(TestAssetV2.id),
        ).filter(
            TestAssetV2.user_id == user.id,
            TestAssetV2.is_deleted == False,
        ).group_by(TestAssetV2.asset_type, TestAssetV2.status).all()

        result = {}
        for asset_type, status, count in stats:
            if asset_type not in result:
                result[asset_type] = {}
            result[asset_type][status] = count

        return {"stats": result}
    finally:
        db.close()


@router.post("/migrate")
async def migrate_legacy_data(
    user: User = Depends(require_auth),
):
    """迁移旧系统数据到统一资产"""
    from app.services.assets.migration_service import MigrationService
    result = MigrationService.migrate_all()
    return {"migration": result}


@router.get("/session/{session_id}")
async def get_session_assets(
    session_id: int,
    user: User = Depends(require_auth),
):
    """获取会话关联的所有资产"""
    from app.services.assets.asset_service import AssetService
    assets = AssetService.get_assets_by_session(session_id, user_id=user.id)
    return {"items": assets, "total": len(assets)}


class ExecuteRequest(PydanticModel):
    """执行请求"""
    asset_ids: List[int]
    env: str = "test"
    base_url: str = "http://localhost:8080"


class RunCaseRequest(PydanticModel):
    """直接执行单条用例（Case First）"""
    case_id: int
    env: str = "test"
    base_url: str = "http://localhost:8080"


class RunSuiteRequest(PydanticModel):
    """执行套件（可选高级功能）"""
    suite_id: int
    env: str = "test"


@router.post("/execute")
async def execute_assets(
    request: ExecuteRequest,
    user: User = Depends(require_auth),
):
    """执行已发布资产"""
    from app.services.execution.dispatcher import ExecutionDispatcher
    result = await ExecutionDispatcher.dispatch_batch(
        asset_ids=request.asset_ids,
        user_id=user.id,
        env=request.env,
        base_url=request.base_url,
    )
    return result


@router.post("/execute/stream")
async def execute_assets_stream(
    request: ExecuteRequest,
    user: User = Depends(require_auth),
):
    """SSE流式执行"""
    import asyncio
    from app.services.execution.dispatcher import ExecutionDispatcher

    progress_queue = asyncio.Queue()

    async def _background():
        await ExecutionDispatcher.dispatch_batch(
            asset_ids=request.asset_ids,
            user_id=user.id,
            env=request.env,
            base_url=request.base_url,
        )

    background_task = asyncio.create_task(_background())

    async def event_generator():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(progress_queue.get(), timeout=300.0)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    if event.get("type") in ("completed", "error"):
                        break
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'heartbeat'}, ensure_ascii=False)}\n\n"
        finally:
            if not background_task.done():
                background_task.cancel()

    from fastapi.responses import StreamingResponse
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/execution/run/case", deprecated=True)
async def run_case(
    request: RunCaseRequest,
    user: User = Depends(require_auth),
):
    """
    ⚠ 废弃：请使用 POST /execution/run/asset

    保留兼容，内部转发到统一执行入口
    """
    # 转发到统一执行接口
    from app.services.execution.dispatcher import ExecutionDispatcher
    result = await ExecutionDispatcher.dispatch_by_asset(
        asset_id=request.case_id,
        user_id=user.id,
        env=request.env,
        base_url=request.base_url,
    )
    return {
        "execution_id": result.get("execution_id"),
        "case_id": request.case_id,
        "status": result.get("status", "queued"),
        "message": "⚠ 此接口已废弃，请使用 POST /execution/run/asset",
    }


@router.post("/execution/run/suite", deprecated=True)
async def run_suite(
    request: RunSuiteRequest,
    user: User = Depends(require_auth),
):
    """
    ⚠ 废弃：请使用 POST /execution/run/suite（统一执行中心）

    保留兼容，内部转发到统一执行入口
    """
    from app.models.test_suite import TestSuite
    db = SessionLocal()
    try:
        suite = db.query(TestSuite).filter(
            TestSuite.id == request.suite_id,
            TestSuite.user_id == user.id,
            TestSuite.is_deleted == False,
        ).first()
        if not suite:
            raise HTTPException(status_code=404, detail="套件不存在")

        case_ids = json.loads(suite.case_ids) if suite.case_ids else []
        if not case_ids:
            raise HTTPException(status_code=400, detail="套件中没有用例")

        # 通过统一执行入口批量执行
        from app.services.execution.dispatcher import ExecutionDispatcher
        result = await ExecutionDispatcher.dispatch_batch(
            asset_ids=case_ids,
            user_id=user.id,
            env=request.env or suite.env or "test",
            base_url=suite.base_url or "http://localhost:8080",
        )

        # 更新套件状态
        suite.status = "running"
        suite.run_count = (suite.run_count or 0) + 1
        db.commit()

        return {
            "execution_id": result.get("execution_id"),
            "suite_id": request.suite_id,
            "case_count": len(case_ids),
            "status": result.get("status", "queued"),
            "message": "⚠ 此接口已废弃，请使用 POST /execution/run/suite（统一执行中心）",
        }
    finally:
        db.close()


# ===== Provider 管理 =====

@router.get("/providers", summary="获取所有Provider")
async def list_providers(
    user: User = Depends(require_auth),
):
    """获取所有支持的测试类型Provider"""
    providers = [
        {
            "type": "web",
            "name": "Web UI 测试",
            "config_schema": {
                "base_url": {"type": "string", "required": True, "description": "目标网站URL"},
                "browser": {"type": "string", "required": False, "default": "chromium", "description": "浏览器类型"},
                "headless": {"type": "boolean", "required": False, "default": True},
            },
            "default_config": {"base_url": "", "browser": "chromium", "headless": True},
        },
        {
            "type": "api",
            "name": "API 接口测试",
            "config_schema": {
                "base_url": {"type": "string", "required": True, "description": "API基础URL"},
                "auth_type": {"type": "string", "required": False, "default": "bearer"},
                "token": {"type": "string", "required": False},
            },
            "default_config": {"base_url": "", "auth_type": "bearer", "token": ""},
        },
        {
            "type": "performance",
            "name": "性能测试",
            "config_schema": {
                "target_url": {"type": "string", "required": True},
                "concurrent_users": {"type": "integer", "required": False, "default": 10},
                "duration": {"type": "integer", "required": False, "default": 60},
            },
            "default_config": {"target_url": "", "concurrent_users": 10, "duration": 60},
        },
        {
            "type": "android",
            "name": "Android 测试",
            "config_schema": {
                "app_package": {"type": "string", "required": True},
                "device_id": {"type": "string", "required": False},
                "app_activity": {"type": "string", "required": False},
            },
            "default_config": {"app_package": "", "device_id": "", "app_activity": ""},
        },
    ]
    return {"code": 200, "message": "success", "data": providers}


@router.get("/providers/{provider_type}/schema", summary="获取Provider配置Schema")
async def get_provider_schema(
    provider_type: str,
    user: User = Depends(require_auth),
):
    """获取指定Provider类型的配置Schema"""
    schemas = {
        "web": {
            "type": "web",
            "name": "Web UI 测试",
            "config_schema": {
                "base_url": {"type": "string", "required": True, "description": "目标网站URL"},
                "browser": {"type": "string", "required": False, "default": "chromium"},
                "headless": {"type": "boolean", "required": False, "default": True},
            },
            "default_config": {"base_url": "", "browser": "chromium", "headless": True},
        },
        "api": {
            "type": "api",
            "name": "API 接口测试",
            "config_schema": {
                "base_url": {"type": "string", "required": True},
                "auth_type": {"type": "string", "required": False, "default": "bearer"},
                "token": {"type": "string", "required": False},
            },
            "default_config": {"base_url": "", "auth_type": "bearer", "token": ""},
        },
        "performance": {
            "type": "performance",
            "name": "性能测试",
            "config_schema": {
                "target_url": {"type": "string", "required": True},
                "concurrent_users": {"type": "integer", "required": False, "default": 10},
                "duration": {"type": "integer", "required": False, "default": 60},
            },
            "default_config": {"target_url": "", "concurrent_users": 10, "duration": 60},
        },
        "android": {
            "type": "android",
            "name": "Android 测试",
            "config_schema": {
                "app_package": {"type": "string", "required": True},
                "device_id": {"type": "string", "required": False},
                "app_activity": {"type": "string", "required": False},
            },
            "default_config": {"app_package": "", "device_id": "", "app_activity": ""},
        },
    }
    if provider_type not in schemas:
        raise HTTPException(status_code=404, detail=f"Provider类型 '{provider_type}' 不存在")
    return {"code": 200, "message": "success", "data": schemas[provider_type]}


# ===== 资产创建 =====

class CreateAssetRequest(PydanticModel):
    """创建资产请求"""
    title: str
    asset_type: str = "web"
    description: Optional[str] = None
    draft_content: Optional[str] = None
    priority: Optional[str] = None
    tags: Optional[str] = None
    source: str = "manual"
    session_id: Optional[int] = None
    folder_id: Optional[int] = None


@router.post("/", summary="创建测试资产")
async def create_asset(
    request: CreateAssetRequest,
    user: User = Depends(require_auth),
):
    """创建新的测试资产"""
    db = SessionLocal()
    try:
        asset = TestAssetV2(
            title=request.title,
            asset_type=request.asset_type,
            description=request.description or "",
            draft_content=request.draft_content or "",
            priority=request.priority or "normal",
            tags=request.tags or "",
            source=request.source,
            source_type=request.source,
            session_id=request.session_id,
            folder_id=request.folder_id,
            user_id=user.id,
            created_by=user.id,
            status=AssetStatus.CREATED,
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        return {
            "code": 200,
            "message": "创建成功",
            "data": {
                "id": asset.id,
                "title": asset.title,
                "asset_type": asset.asset_type,
                "status": asset.status,
            },
        }
    finally:
        db.close()


# ===== 批量删除 =====

class BatchDeleteAssetsRequest(PydanticModel):
    """批量删除资产请求"""
    ids: List[int]


@router.post("/batch-delete", summary="批量删除测试资产")
async def batch_delete_assets(
    request: BatchDeleteAssetsRequest,
    user: User = Depends(require_auth),
):
    """批量软删除测试资产"""
    db = SessionLocal()
    try:
        deleted = 0
        for aid in request.ids:
            asset = db.query(TestAssetV2).filter(
                TestAssetV2.id == aid,
                TestAssetV2.user_id == user.id,
            ).first()
            if asset:
                asset.is_deleted = True
                deleted += 1
        db.commit()
        return {"code": 200, "message": f"已删除 {deleted} 个资产", "data": {"deleted_count": deleted}}
    finally:
        db.close()
