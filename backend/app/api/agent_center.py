"""
Agent 管理中心 API

统一管理所有 Agent 的注册、发现、配置、版本管理和生命周期管理。

功能模块:
  1. 注册管理   - POST/DELETE/PUT 动态注册/移除/更新 Agent
  2. 发现查询   - GET 列表/详情/搜索/统计
  3. 配置管理   - GET/PUT 配置热更新
  4. 版本管理   - PUT 版本升级 / GET 版本历史
  5. 生命周期   - POST start/stop/enable/disable
  6. 同步       - POST 内存 Specs ↔ DB 同步

所有 Agent 必须通过此中心管理,禁止业务代码直接实例化 Agent。
"""
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel, Field

from app.db.database import SessionLocal
from app.agents.factory.models import AgentMetadataStore
from app.agents.factory.factory import get_agent_factory
from app.agents.factory.lifecycle import get_lifecycle_manager, AgentLifecycleState
from app.agents.factory.config import AgentSpec, ModelConfig
from app.api.auth import require_auth
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================
# 请求模型
# ============================================================

class AgentCreateRequest(BaseModel):
    """注册 Agent 请求"""
    agent_name: str = Field(..., description="Agent 唯一名称", max_length=64)
    agent_type: str = Field("llm", description="类型: llm/tool/runtime/adapter")
    display_name: str = Field("", description="显示名称")
    description: str = Field("", description="描述")
    module_path: str = Field(..., description="Python 模块路径")
    class_name: str = Field(..., description="类名")
    model_name: Optional[str] = Field(None, description="模型名")
    model_provider: Optional[str] = Field(None, description="模型提供商")
    system_prompt: str = Field("", description="系统提示词")
    tools: List[str] = Field(default_factory=list, description="工具列表")
    capabilities: List[str] = Field(default_factory=list, description="能力列表")
    enabled: bool = Field(True, description="是否启用")
    version: str = Field("1.0.0", description="版本号")
    config: Dict[str, Any] = Field(default_factory=dict, description="配置")


class AgentUpdateRequest(BaseModel):
    """更新 Agent 请求"""
    display_name: Optional[str] = None
    description: Optional[str] = None
    agent_type: Optional[str] = None
    module_path: Optional[str] = None
    class_name: Optional[str] = None
    model_name: Optional[str] = None
    model_provider: Optional[str] = None
    system_prompt: Optional[str] = None
    tools: Optional[List[str]] = None
    capabilities: Optional[List[str]] = None
    enabled: Optional[bool] = None


class ConfigUpdateRequest(BaseModel):
    """配置更新请求"""
    config: Dict[str, Any] = Field(..., description="配置字典")


class VersionUpdateRequest(BaseModel):
    """版本更新请求"""
    version: str = Field(..., description="新版本号", max_length=32)


class ModelUpdateRequest(BaseModel):
    """模型更新请求"""
    model_name: str = Field(..., description="模型名")
    model_provider: str = Field(..., description="模型提供商")


class AgentSyncRequest(BaseModel):
    """同步请求"""
    dry_run: bool = Field(False, description="仅预览不实际写入")


# ============================================================
# 响应工具函数
# ============================================================

def _merge_agent_info(db_record: Optional[dict], factory_spec: Optional[AgentSpec], lifecycle_state: Optional[str]) -> dict:
    """合并 DB 记录、Factory Spec 和生命周期状态"""
    info = {}

    # DB 记录(权威来源)
    if db_record:
        info.update(db_record)

    # Factory Spec (内存中的运行时信息)
    if factory_spec:
        if "agent_name" not in info:
            info["agent_name"] = factory_spec.name
        if not info.get("display_name"):
            info["display_name"] = factory_spec.display_name
        if not info.get("description"):
            info["description"] = factory_spec.description
        # Factory 的 enabled 状态覆盖 DB (运行时可能被 disable)
        info["factory_enabled"] = factory_spec.enabled
        info["in_factory"] = True
    else:
        info["in_factory"] = False
        info["factory_enabled"] = False

    # 生命周期状态
    info["lifecycle_state"] = lifecycle_state or "unknown"

    return info


# ============================================================
# 1. 发现查询
# ============================================================

@router.get("/agents", summary="查看 Agent 列表")
async def list_agents(
    enabled_only: bool = Query(False, description="仅返回启用的"),
    agent_type: Optional[str] = Query(None, description="按类型过滤: llm/tool/runtime/adapter"),
    status: Optional[str] = Query(None, description="按状态过滤: registered/initialized/running/stopped/error"),
    source: str = Query("all", description="数据源: all/db/factory"),
    user: User = Depends(require_auth),
):
    """查看 Agent 列表(支持过滤和多种数据源)"""
    db = SessionLocal()
    try:
        factory = get_agent_factory()
        lifecycle = get_lifecycle_manager()
        result = []

        if source in ("all", "db"):
            # 从 DB 获取
            records = AgentMetadataStore.list_all(
                db, enabled_only=enabled_only, agent_type=agent_type, status=status,
            )
            for record in records:
                spec = factory.get(record.agent_name) if source == "all" else None
                state = lifecycle.get_state(record.agent_name).value
                result.append(_merge_agent_info(record.to_dict(), spec, state))

        if source in ("all", "factory"):
            # 从 Factory 获取(补充 DB 中没有的)
            db_names = {r.agent_name for r in AgentMetadataStore.list_all(db)}
            for spec in factory.list(enabled_only=enabled_only):
                if spec.name in db_names:
                    continue  # 已从 DB 获取
                if agent_type and spec.agent_type != agent_type:
                    continue
                state = lifecycle.get_state(spec.name).value
                result.append(_merge_agent_info(None, spec, state))

        return {
            "total": len(result),
            "agents": result,
        }
    finally:
        db.close()


@router.get("/agents/{agent_name}", summary="查看 Agent 详情")
async def get_agent_detail(
    agent_name: str,
    user: User = Depends(require_auth),
):
    """查看单个 Agent 的详细信息"""
    db = SessionLocal()
    try:
        record = AgentMetadataStore.get_by_name(db, agent_name)
        if record is None:
            factory = get_agent_factory()
            spec = factory.get(agent_name)
            if spec is None:
                raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' 不存在")

            lifecycle = get_lifecycle_manager()
            state = lifecycle.get_state(agent_name).value
            return _merge_agent_info(None, spec, state)

        factory = get_agent_factory()
        spec = factory.get(agent_name)
        lifecycle = get_lifecycle_manager()
        state = lifecycle.get_state(agent_name).value
        return _merge_agent_info(record.to_dict(), spec, state)
    finally:
        db.close()


@router.get("/search", summary="搜索 Agent")
async def search_agents(
    keyword: str = Query(..., description="搜索关键词"),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(require_auth),
):
    """按名称/显示名/描述模糊搜索 Agent"""
    db = SessionLocal()
    try:
        records = AgentMetadataStore.search(db, keyword, limit)
        return {
            "total": len(records),
            "agents": [r.to_dict() for r in records],
        }
    finally:
        db.close()


@router.get("/stats", summary="获取 Agent 统计")
async def get_agent_stats(
    user: User = Depends(require_auth),
):
    """获取 Agent 注册统计信息"""
    db = SessionLocal()
    try:
        db_stats = AgentMetadataStore.get_stats(db)

        # 合并 Factory 统计
        factory = get_agent_factory()
        factory_stats = factory.get_stats()

        # 合并生命周期统计
        lifecycle = get_lifecycle_manager()
        all_states = lifecycle.get_all_states()

        return {
            "db": db_stats,
            "factory": factory_stats,
            "lifecycle": {
                "total": len(all_states),
                "states": all_states,
            },
        }
    finally:
        db.close()


# ============================================================
# 2. 注册管理 (CRUD)
# ============================================================

@router.post("/agents", summary="注册 Agent")
async def register_agent(
    req: AgentCreateRequest,
    user: User = Depends(require_auth),
):
    """注册新 Agent 到管理中心

    注册后 Agent 同时存在于 DB 和 AgentFactory 中。
    业务代码通过 factory.create(name) 获取实例,禁止直接 new。
    """
    db = SessionLocal()
    try:
        # 1. 写入 DB
        try:
            record = AgentMetadataStore.create(
                db,
                agent_name=req.agent_name,
                agent_type=req.agent_type,
                display_name=req.display_name,
                description=req.description,
                module_path=req.module_path,
                class_name=req.class_name,
                model_name=req.model_name,
                model_provider=req.model_provider,
                system_prompt=req.system_prompt,
                tools=req.tools,
                capabilities=req.capabilities,
                enabled=req.enabled,
                version=req.version,
                config=req.config,
            )
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))

        # 2. 注册到 AgentFactory (内存)
        factory = get_agent_factory()
        model = None
        if req.model_name and req.model_provider:
            model = ModelConfig(provider=req.model_provider, model_name=req.model_name)

        spec = AgentSpec(
            name=req.agent_name,
            display_name=req.display_name or req.agent_name,
            description=req.description,
            agent_type=req.agent_type,
            module_path=req.module_path,
            class_name=req.class_name,
            model=model,
            system_prompt=req.system_prompt,
            tools=req.tools,
            capabilities=req.capabilities,
            enabled=req.enabled,
        )
        factory.register(spec)

        # 3. 注册到生命周期管理器
        lifecycle = get_lifecycle_manager()
        await lifecycle.register(req.agent_name, spec)

        logger.info(f"[AgentCenter] 注册 Agent: {req.agent_name} v{req.version} by user={user.id}")
        return {
            "message": f"Agent '{req.agent_name}' 注册成功",
            "agent": record.to_dict(),
        }
    finally:
        db.close()


@router.put("/agents/{agent_name}", summary="更新 Agent 信息")
async def update_agent(
    agent_name: str,
    req: AgentUpdateRequest,
    user: User = Depends(require_auth),
):
    """更新 Agent 注册信息"""
    db = SessionLocal()
    try:
        # 过滤 None 值
        updates = {k: v for k, v in req.dict().items() if v is not None}
        if not updates:
            raise HTTPException(status_code=400, detail="没有需要更新的字段")

        record = AgentMetadataStore.update(db, agent_name, **updates)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' 不存在")

        # 同步到 Factory
        factory = get_agent_factory()
        spec = factory.get(agent_name)
        if spec:
            if "display_name" in updates:
                spec.display_name = updates["display_name"]
            if "description" in updates:
                spec.description = updates["description"]
            if "agent_type" in updates:
                spec.agent_type = updates["agent_type"]
            if "enabled" in updates:
                if updates["enabled"]:
                    factory.enable(agent_name)
                else:
                    factory.disable(agent_name)
            if "module_path" in updates:
                spec.module_path = updates["module_path"]
            if "class_name" in updates:
                spec.class_name = updates["class_name"]

        logger.info(f"[AgentCenter] 更新 Agent: {agent_name} by user={user.id}")
        return {
            "message": f"Agent '{agent_name}' 更新成功",
            "agent": record.to_dict(),
        }
    finally:
        db.close()


@router.delete("/agents/{agent_name}", summary="移除 Agent")
async def unregister_agent(
    agent_name: str,
    user: User = Depends(require_auth),
):
    """从管理中心移除 Agent

    会同时清理:
    1. DB 注册记录
    2. AgentFactory 内存规格和实例缓存
    3. 生命周期状态(先 shutdown 再移除)
    """
    db = SessionLocal()
    try:
        # 1. 先 shutdown 生命周期
        lifecycle = get_lifecycle_manager()
        try:
            await lifecycle.shutdown(agent_name)
        except Exception as e:
            logger.warning(f"[AgentCenter] shutdown {agent_name} 时: {e}")

        # 2. 从 Factory 移除
        factory = get_agent_factory()
        factory.unregister(agent_name)

        # 3. 从 DB 删除
        deleted = AgentMetadataStore.delete(db, agent_name)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' 不存在")

        logger.info(f"[AgentCenter] 移除 Agent: {agent_name} by user={user.id}")
        return {"message": f"Agent '{agent_name}' 已移除"}
    finally:
        db.close()


# ============================================================
# 3. 状态查看
# ============================================================

@router.get("/agents/{agent_name}/status", summary="查看 Agent 状态")
async def get_agent_status(
    agent_name: str,
    user: User = Depends(require_auth),
):
    """查看 Agent 的运行状态

    返回:
    - lifecycle_state: registered/initialized/running/stopped/error
    - factory_enabled: Factory 中的启用状态
    - db_enabled: DB 中的启用状态
    - in_factory: 是否在 Factory 内存中
    - in_db: 是否在 DB 中
    - cached_instances: 缓存的实例数
    """
    db = SessionLocal()
    try:
        record = AgentMetadataStore.get_by_name(db, agent_name)

        factory = get_agent_factory()
        spec = factory.get(agent_name)

        lifecycle = get_lifecycle_manager()
        state = lifecycle.get_state(agent_name)

        # 获取缓存实例数
        cached_count = sum(
            1 for k in factory._instances if k[0] == agent_name
        ) if hasattr(factory, "_instances") else 0

        return {
            "agent_name": agent_name,
            "lifecycle_state": state.value,
            "factory_enabled": spec.enabled if spec else False,
            "db_enabled": record.enabled if record else False,
            "in_factory": spec is not None,
            "in_db": record is not None,
            "cached_instances": cached_count,
            "version": record.version if record else (spec.metadata.get("version", "unknown") if spec and spec.metadata else "unknown"),
        }
    finally:
        db.close()


# ============================================================
# 4. 生命周期管理 (启停)
# ============================================================

@router.post("/agents/{agent_name}/start", summary="启动 Agent")
async def start_agent(
    agent_name: str,
    user: User = Depends(require_auth),
):
    """启动/初始化 Agent

    将 Agent 从 registered 状态转为 initialized 状态。
    会调用 AgentFactory.create() 创建实例。
    """
    db = SessionLocal()
    try:
        record = AgentMetadataStore.get_by_name(db, agent_name)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' 不存在")

        if not record.enabled:
            raise HTTPException(status_code=400, detail=f"Agent '{agent_name}' 已禁用,请先启用")

        # 确保在 Factory 中注册
        factory = get_agent_factory()
        if not factory.exists(agent_name):
            spec = AgentMetadataStore.to_spec(record)
            factory.register(spec)

        # 通过生命周期管理器初始化
        lifecycle = get_lifecycle_manager()
        try:
            await lifecycle.initialize(agent_name, runtime=None)
        except Exception as e:
            AgentMetadataStore.update_status(db, agent_name, "error")
            raise HTTPException(status_code=500, detail=f"启动失败: {str(e)}")

        AgentMetadataStore.update_status(db, agent_name, "initialized")
        logger.info(f"[AgentCenter] 启动 Agent: {agent_name} by user={user.id}")

        return {
            "message": f"Agent '{agent_name}' 已启动",
            "lifecycle_state": "initialized",
        }
    finally:
        db.close()


@router.post("/agents/{agent_name}/stop", summary="停止 Agent")
async def stop_agent(
    agent_name: str,
    user: User = Depends(require_auth),
):
    """停止/关闭 Agent

    将 Agent 转为 stopped 状态。
    会调用 Agent 的 cleanup/shutdown 钩子,并清除实例缓存。
    """
    db = SessionLocal()
    try:
        record = AgentMetadataStore.get_by_name(db, agent_name)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' 不存在")

        lifecycle = get_lifecycle_manager()
        try:
            await lifecycle.shutdown(agent_name)
        except Exception as e:
            logger.warning(f"[AgentCenter] stop {agent_name}: {e}")

        AgentMetadataStore.update_status(db, agent_name, "stopped")
        logger.info(f"[AgentCenter] 停止 Agent: {agent_name} by user={user.id}")

        return {
            "message": f"Agent '{agent_name}' 已停止",
            "lifecycle_state": "stopped",
        }
    finally:
        db.close()


@router.post("/agents/{agent_name}/enable", summary="启用 Agent")
async def enable_agent(
    agent_name: str,
    user: User = Depends(require_auth),
):
    """启用 Agent (允许被 factory.create 调用)"""
    db = SessionLocal()
    try:
        record = AgentMetadataStore.get_by_name(db, agent_name)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' 不存在")

        AgentMetadataStore.toggle_enabled(db, agent_name, True)

        factory = get_agent_factory()
        factory.enable(agent_name)

        logger.info(f"[AgentCenter] 启用 Agent: {agent_name} by user={user.id}")
        return {"message": f"Agent '{agent_name}' 已启用", "enabled": True}
    finally:
        db.close()


@router.post("/agents/{agent_name}/disable", summary="禁用 Agent")
async def disable_agent(
    agent_name: str,
    user: User = Depends(require_auth),
):
    """禁用 Agent (禁止被 factory.create 调用,清除实例缓存)"""
    db = SessionLocal()
    try:
        record = AgentMetadataStore.get_by_name(db, agent_name)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' 不存在")

        AgentMetadataStore.toggle_enabled(db, agent_name, False)

        factory = get_agent_factory()
        factory.disable(agent_name)  # 会清除实例缓存

        logger.info(f"[AgentCenter] 禁用 Agent: {agent_name} by user={user.id}")
        return {"message": f"Agent '{agent_name}' 已禁用", "enabled": False}
    finally:
        db.close()


# ============================================================
# 5. 配置管理
# ============================================================

@router.get("/agents/{agent_name}/config", summary="获取 Agent 配置")
async def get_agent_config(
    agent_name: str,
    user: User = Depends(require_auth),
):
    """获取 Agent 的配置(config 字段)"""
    db = SessionLocal()
    try:
        config = AgentMetadataStore.get_config(db, agent_name)
        if config is None:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' 不存在")
        return {"agent_name": agent_name, "config": config}
    finally:
        db.close()


@router.put("/agents/{agent_name}/config", summary="更新 Agent 配置")
async def update_agent_config(
    agent_name: str,
    req: ConfigUpdateRequest,
    user: User = Depends(require_auth),
):
    """更新 Agent 配置(热更新,无需重启)

    config 字段用于存储:
    - 模型参数 (temperature, max_tokens)
    - 超时配置 (timeout_seconds)
    - 重试策略 (max_retries, backoff)
    - 自定义参数
    """
    db = SessionLocal()
    try:
        success = AgentMetadataStore.update_config(db, agent_name, req.config)
        if not success:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' 不存在")

        # 同步到 Factory (清除实例缓存以应用新配置)
        factory = get_agent_factory()
        spec = factory.get(agent_name)
        if spec:
            # 将 config 合并到 spec.metadata
            if spec.metadata is None:
                spec.metadata = {}
            spec.metadata["config"] = req.config
            # 清除缓存,下次 create 时重新实例化
            for key in list(factory._instances.keys()):
                if key[0] == agent_name:
                    del factory._instances[key]

        logger.info(f"[AgentCenter] 更新配置: {agent_name} by user={user.id}")
        return {
            "message": f"Agent '{agent_name}' 配置已更新",
            "config": req.config,
        }
    finally:
        db.close()


@router.put("/agents/{agent_name}/model", summary="更新 Agent 模型")
async def update_agent_model(
    agent_name: str,
    req: ModelUpdateRequest,
    user: User = Depends(require_auth),
):
    """更新 Agent 使用的模型"""
    db = SessionLocal()
    try:
        # 更新 DB
        success = AgentMetadataStore.update_model(db, agent_name, req.model_name, req.model_provider)
        if not success:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' 不存在")

        # 更新 Factory (会清除实例缓存)
        factory = get_agent_factory()
        factory.set_model(agent_name, ModelConfig(
            provider=req.model_provider,
            model_name=req.model_name,
        ))

        logger.info(f"[AgentCenter] 更新模型: {agent_name} → {req.model_provider}/{req.model_name}")
        return {
            "message": f"Agent '{agent_name}' 模型已更新",
            "model_name": req.model_name,
            "model_provider": req.model_provider,
        }
    finally:
        db.close()


# ============================================================
# 6. 版本管理
# ============================================================

@router.put("/agents/{agent_name}/version", summary="更新 Agent 版本")
async def update_agent_version(
    agent_name: str,
    req: VersionUpdateRequest,
    user: User = Depends(require_auth),
):
    """更新 Agent 版本号

    自动记录版本历史到 metadata.version_history。
    """
    db = SessionLocal()
    try:
        success = AgentMetadataStore.update_version(db, agent_name, req.version)
        if not success:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' 不存在")

        logger.info(f"[AgentCenter] 版本更新: {agent_name} → v{req.version} by user={user.id}")
        return {
            "message": f"Agent '{agent_name}' 版本已更新",
            "version": req.version,
        }
    finally:
        db.close()


@router.get("/agents/{agent_name}/version/history", summary="查看版本历史")
async def get_version_history(
    agent_name: str,
    user: User = Depends(require_auth),
):
    """查看 Agent 的版本变更历史"""
    db = SessionLocal()
    try:
        history = AgentMetadataStore.get_version_history(db, agent_name)
        record = AgentMetadataStore.get_by_name(db, agent_name)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' 不存在")

        return {
            "agent_name": agent_name,
            "current_version": record.version,
            "history": history,
        }
    finally:
        db.close()


# ============================================================
# 7. 同步
# ============================================================

@router.post("/sync", summary="同步 Agent Specs 到 DB")
async def sync_agents_to_db(
    user: User = Depends(require_auth),
):
    """将 AgentFactory 内存中的 AgentSpecs 同步到数据库

    用于启动后将代码中定义的 DEFAULT_AGENT_SPECS 持久化到 DB。
    已存在的记录更新,不存在的插入,不会删除 DB 中额外的记录。
    """
    db = SessionLocal()
    try:
        factory = get_agent_factory()
        specs = factory.list(enabled_only=False)
        synced = AgentMetadataStore.sync_from_specs(db, specs)

        logger.info(f"[AgentCenter] 同步 {synced} 个 Agent Specs 到 DB by user={user.id}")
        return {
            "message": f"已同步 {synced} 个 Agent",
            "synced": synced,
        }
    finally:
        db.close()


# ============================================================
# 8. Factory 信息 (验证 factory.create 支持)
# ============================================================

@router.get("/factory/info", summary="获取 AgentFactory 信息")
async def get_factory_info(
    user: User = Depends(require_auth),
):
    """获取 AgentFactory 的运行时信息

    返回所有已注册 Agent 的规格信息,用于验证 factory.create(name) 的可用性。
    """
    factory = get_agent_factory()
    return {
        "stats": factory.get_stats(),
        "agents": factory.get_info(),
    }


@router.post("/factory/test-create", summary="测试 Agent 创建")
async def test_create_agent(
    agent_name: str = Query(..., description="要测试创建的 Agent 名称"),
    user: User = Depends(require_auth),
):
    """测试 factory.create(name) 是否可用

    验证 Agent 能否被成功实例化(不实际执行)。
    """
    factory = get_agent_factory()

    if not factory.exists(agent_name):
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' 不在 Factory 中")

    if not factory.is_enabled(agent_name):
        raise HTTPException(status_code=400, detail=f"Agent '{agent_name}' 已禁用")

    try:
        instance = await factory.create(agent_name)
        if instance is not None:
            class_name = instance.__class__.__name__
            module = instance.__class__.__module__
            return {
                "message": f"Agent '{agent_name}' 创建成功",
                "class": class_name,
                "module": module,
                "agent_type": type(instance).__mro__[1].__name__ if len(type(instance).__mro__) > 1 else "unknown",
            }
        else:
            raise HTTPException(status_code=500, detail="创建返回 None")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建失败: {str(e)}")
