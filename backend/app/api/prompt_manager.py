"""
Prompt 管理 API

管理 Agent 内部 Prompt 版本,支持:
1. 版本管理 - 创建/查看/激活/归档/删除
2. A/B 测试 - 启动/停止/统计
3. Prompt 回滚 - 回滚到历史版本
4. 版本比较 - 对比两个版本 diff
5. 同步 - 从 AgentSpec 导入初始 Prompt

权限控制:
- 普通用户: 可查看 ACTIVE 版本和统计
- 开发人员(admin): 可创建/修改/激活/回滚/删除
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, HTTPException, Depends, Body
from pydantic import BaseModel, Field

from app.db.database import SessionLocal
from app.services.prompt_manager import PromptManager
from app.models.prompt_version import PromptStatus
from app.api.auth import require_auth, require_admin
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================
# 请求模型
# ============================================================

class PromptCreateRequest(BaseModel):
    """创建 Prompt 版本"""
    agent_name: str = Field(..., description="Agent 名称", max_length=64)
    prompt_key: str = Field("system_prompt", description="Prompt 标识")
    version: str = Field(..., description="版本号", max_length=32)
    content: str = Field(..., description="Prompt 内容")
    description: str = Field("", description="版本描述")
    status: str = Field("draft", description="初始状态: draft/active")
    tags: List[str] = Field(default_factory=list, description="标签")


class PromptUpdateRequest(BaseModel):
    """更新 Prompt 版本(仅 DRAFT)"""
    content: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None


class ABTestRequest(BaseModel):
    """A/B 测试请求"""
    versions: List[Dict[str, Any]] = Field(
        ...,
        description="版本配置: [{version, group, ratio}]",
    )


class CompareRequest(BaseModel):
    """版本比较请求"""
    version_a: str = Field(..., description="版本 A")
    version_b: str = Field(..., description="版本 B")


class RecordResultRequest(BaseModel):
    """记录执行结果"""
    version: str = Field(..., description="版本号")
    success: bool = Field(..., description="是否成功")


# ============================================================
# 1. 查询
# ============================================================

@router.get("/prompts", summary="查看所有 Agent 的 Prompt 概览")
async def list_prompt_agents(
    user: User = Depends(require_auth),
):
    """列出所有有 Prompt 的 Agent"""
    db = SessionLocal()
    try:
        agents = PromptManager.list_all_agents(db)
        return {"total": len(agents), "agents": agents}
    finally:
        db.close()


@router.get("/prompts/{agent_name}/versions", summary="查看 Agent 的 Prompt 版本列表")
async def list_versions(
    agent_name: str,
    prompt_key: Optional[str] = Query(None, description="按 key 过滤"),
    status: Optional[str] = Query(None, description="按状态过滤: draft/active/archived/testing"),
    user: User = Depends(require_auth),
):
    """查看 Agent 的所有 Prompt 版本"""
    db = SessionLocal()
    try:
        status_enum = PromptStatus(status) if status else None
        versions = PromptManager.list_versions(db, agent_name, prompt_key, status_enum)
        return {
            "total": len(versions),
            "versions": [v.to_dict() for v in versions],
        }
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效状态: {status}")
    finally:
        db.close()


@router.get("/prompts/{agent_name}/active", summary="获取当前活跃 Prompt")
async def get_active_prompt(
    agent_name: str,
    prompt_key: str = Query("system_prompt", description="Prompt 标识"),
    user: User = Depends(require_auth),
):
    """获取 Agent 当前的活跃 Prompt 内容"""
    db = SessionLocal()
    try:
        content = PromptManager.get_prompt(agent_name, prompt_key, db)
        if content is None:
            raise HTTPException(
                status_code=404,
                detail=f"Agent '{agent_name}' 没有活跃的 Prompt (key={prompt_key})",
            )
        # 获取版本详情
        versions = PromptManager.list_versions(db, agent_name, prompt_key, PromptStatus.ACTIVE)
        version_info = versions[0].to_dict() if versions else {}
        return {
            "agent_name": agent_name,
            "prompt_key": prompt_key,
            "content": content,
            "version": version_info.get("version"),
            "content_length": len(content),
        }
    finally:
        db.close()


@router.get("/prompts/{agent_name}/{version}", summary="查看特定版本")
async def get_version_detail(
    agent_name: str,
    version: str,
    prompt_key: str = Query("system_prompt", description="Prompt 标识"),
    user: User = Depends(require_auth),
):
    """查看特定版本的 Prompt"""
    db = SessionLocal()
    try:
        record = PromptManager.get_version(db, agent_name, prompt_key, version)
        if record is None:
            raise HTTPException(status_code=404, detail=f"版本不存在: {version}")
        return record.to_dict()
    finally:
        db.close()


@router.get("/stats", summary="Prompt 管理统计")
async def get_stats(
    user: User = Depends(require_auth),
):
    """获取 Prompt 管理统计信息"""
    db = SessionLocal()
    try:
        return PromptManager.get_stats(db)
    finally:
        db.close()


# ============================================================
# 2. 版本管理 (开发人员权限)
# ============================================================

@router.post("/prompts", summary="创建 Prompt 版本")
async def create_version(
    req: PromptCreateRequest,
    user: User = Depends(require_admin),
):
    """创建新的 Prompt 版本(开发人员权限)

    核心 Prompt 保护:创建后默认 DRAFT 状态,需显式激活才能生效。
    """
    db = SessionLocal()
    try:
        status = PromptStatus.ACTIVE if req.status == "active" else PromptStatus.DRAFT
        record = PromptManager.create_version(
            db,
            agent_name=req.agent_name,
            prompt_key=req.prompt_key,
            version=req.version,
            content=req.content,
            description=req.description,
            status=status,
            tags=req.tags,
        )

        # 如果创建时直接激活
        if status == PromptStatus.ACTIVE:
            record = PromptManager.activate(db, req.agent_name, req.prompt_key, req.version)

        logger.info(f"[PromptAPI] 创建版本: {req.agent_name}/{req.version} by user={user.id}")
        return {
            "message": f"Prompt 版本 '{req.version}' 创建成功",
            "version": record.to_dict(),
        }
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    finally:
        db.close()


@router.put("/prompts/{agent_name}/{version}", summary="更新 Prompt 版本")
async def update_version(
    agent_name: str,
    version: str,
    req: PromptUpdateRequest,
    prompt_key: str = Query("system_prompt"),
    user: User = Depends(require_admin),
):
    """更新 Prompt 版本内容(仅 DRAFT 状态可修改)"""
    db = SessionLocal()
    try:
        record = PromptManager.update_version(
            db,
            agent_name=agent_name,
            prompt_key=prompt_key,
            version=version,
            content=req.content,
            description=req.description,
            tags=req.tags,
        )
        if record is None:
            raise HTTPException(status_code=404, detail=f"版本不存在: {version}")
        return {
            "message": f"版本 '{version}' 更新成功",
            "version": record.to_dict(),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@router.delete("/prompts/{agent_name}/{version}", summary="删除 Prompt 版本")
async def delete_version(
    agent_name: str,
    version: str,
    prompt_key: str = Query("system_prompt"),
    user: User = Depends(require_admin),
):
    """删除 Prompt 版本(仅 DRAFT/ARCHIVED 可删除)"""
    db = SessionLocal()
    try:
        success = PromptManager.delete_version(db, agent_name, prompt_key, version)
        if not success:
            raise HTTPException(status_code=404, detail=f"版本不存在: {version}")
        return {"message": f"版本 '{version}' 已删除"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


# ============================================================
# 3. 激活与归档
# ============================================================

@router.post("/prompts/{agent_name}/{version}/activate", summary="激活 Prompt 版本")
async def activate_version(
    agent_name: str,
    version: str,
    prompt_key: str = Query("system_prompt"),
    user: User = Depends(require_admin),
):
    """激活指定版本(将当前 ACTIVE 归档)"""
    db = SessionLocal()
    try:
        record = PromptManager.activate(db, agent_name, prompt_key, version)
        return {
            "message": f"版本 '{version}' 已激活",
            "version": record.to_dict(),
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        db.close()


@router.post("/prompts/{agent_name}/{version}/archive", summary="归档 Prompt 版本")
async def archive_version(
    agent_name: str,
    version: str,
    prompt_key: str = Query("system_prompt"),
    user: User = Depends(require_admin),
):
    """归档指定版本"""
    db = SessionLocal()
    try:
        record = PromptManager.archive(db, agent_name, prompt_key, version)
        if record is None:
            raise HTTPException(status_code=404, detail=f"版本不存在: {version}")
        return {
            "message": f"版本 '{version}' 已归档",
            "version": record.to_dict(),
        }
    finally:
        db.close()


# ============================================================
# 4. A/B 测试
# ============================================================

@router.post("/prompts/{agent_name}/ab-test/start", summary="启动 A/B 测试")
async def start_ab_test(
    agent_name: str,
    req: ABTestRequest,
    prompt_key: str = Query("system_prompt"),
    user: User = Depends(require_admin),
):
    """启动 A/B 测试

    请求体示例:
    ```json
    {
        "versions": [
            {"version": "v1", "group": "A", "ratio": 0.5},
            {"version": "v2", "group": "B", "ratio": 0.5}
        ]
    }
    ```

    流量比例总和必须为 1.0。
    """
    db = SessionLocal()
    try:
        result = PromptManager.start_ab_test(db, agent_name, prompt_key, req.versions)
        return {
            "message": f"A/B 测试已启动: {len(req.versions)} 个版本",
            "config": result,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@router.post("/prompts/{agent_name}/ab-test/stop", summary="停止 A/B 测试")
async def stop_ab_test(
    agent_name: str,
    prompt_key: str = Query("system_prompt"),
    winner_version: Optional[str] = Query(None, description="获胜版本(将被激活)"),
    user: User = Depends(require_admin),
):
    """停止 A/B 测试,可选择获胜版本"""
    db = SessionLocal()
    try:
        result = PromptManager.stop_ab_test(db, agent_name, prompt_key, winner_version)
        return {
            "message": f"A/B 测试已停止" + (f", 获胜版本: {winner_version}" if winner_version else ""),
            "result": result,
        }
    finally:
        db.close()


@router.get("/prompts/{agent_name}/ab-test/stats", summary="A/B 测试统计")
async def get_ab_test_stats(
    agent_name: str,
    prompt_key: str = Query("system_prompt"),
    user: User = Depends(require_auth),
):
    """获取 A/B 测试统计"""
    db = SessionLocal()
    try:
        stats = PromptManager.get_ab_test_stats(db, agent_name, prompt_key)
        return {
            "agent_name": agent_name,
            "prompt_key": prompt_key,
            "versions": stats,
        }
    finally:
        db.close()


@router.post("/prompts/{agent_name}/record-result", summary="记录 Prompt 执行结果")
async def record_result(
    agent_name: str,
    req: RecordResultRequest,
    prompt_key: str = Query("system_prompt"),
    user: User = Depends(require_auth),
):
    """记录 Prompt 执行结果(用于 A/B 测试统计)"""
    db = SessionLocal()
    try:
        PromptManager.record_result(db, agent_name, prompt_key, req.version, req.success)
        return {"message": "结果已记录"}
    finally:
        db.close()


# ============================================================
# 5. 回滚
# ============================================================

@router.post("/prompts/{agent_name}/rollback", summary="回滚 Prompt 版本")
async def rollback_prompt(
    agent_name: str,
    prompt_key: str = Query("system_prompt"),
    target_version: Optional[str] = Query(None, description="目标版本(为空则回滚到上一版本)"),
    user: User = Depends(require_admin),
):
    """回滚到指定版本或上一活跃版本"""
    db = SessionLocal()
    try:
        record = PromptManager.rollback(db, agent_name, prompt_key, target_version)
        return {
            "message": f"已回滚到版本 '{record.parent_version}'",
            "new_version": record.to_dict(),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


# ============================================================
# 6. 版本比较
# ============================================================

@router.post("/prompts/{agent_name}/compare", summary="比较两个 Prompt 版本")
async def compare_versions(
    agent_name: str,
    req: CompareRequest,
    prompt_key: str = Query("system_prompt"),
    user: User = Depends(require_auth),
):
    """比较两个版本的内容差异

    返回 unified diff 格式的差异、增删行数、相似度。
    """
    db = SessionLocal()
    try:
        result = PromptManager.compare_versions(
            db, agent_name, prompt_key, req.version_a, req.version_b,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        db.close()


# ============================================================
# 7. 同步
# ============================================================

@router.post("/sync", summary="从 AgentSpec 同步初始 Prompt")
async def sync_from_specs(
    user: User = Depends(require_admin),
):
    """将 AgentSpec 中的 system_prompt 同步到 prompt_version 表

    仅同步不存在的,已存在的不覆盖。
    版本号统一为 v1,状态为 ACTIVE。
    """
    db = SessionLocal()
    try:
        from app.agents.factory.factory import get_agent_factory
        factory = get_agent_factory()
        specs = factory.list(enabled_only=False)
        synced = PromptManager.sync_from_specs(db, specs)
        return {
            "message": f"已同步 {synced} 个 Prompt",
            "synced": synced,
        }
    finally:
        db.close()
