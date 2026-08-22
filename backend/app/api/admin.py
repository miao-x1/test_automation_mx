"""
管理模块 API路由

平台控制层：配置与资源管理
禁止包含任何测试执行逻辑

已实现：
- 用户管理：列表、详情
- 角色权限：列表
- 项目管理：列表
- 环境配置：列表、创建
- 系统配置：获取、更新（持久化到 JSON 文件）
- 数据源管理：列表、创建
- 脚本仓库：列表
"""
import os
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.database import get_db
from app.schemas.response import Response
from app.core.auth import require_auth
from app.models.user import User
from app.core.config import settings as app_settings
from app.core.logger import log

router = APIRouter()

# 系统配置文件路径
_SETTINGS_FILE = os.path.join(app_settings.DATA_DIR, "system_settings.json")


def _load_settings() -> dict:
    """加载系统配置"""
    if os.path.exists(_SETTINGS_FILE):
        try:
            with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_settings(data: dict) -> None:
    """保存系统配置"""
    os.makedirs(os.path.dirname(_SETTINGS_FILE), exist_ok=True)
    with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ==================== 请求模型 ====================

class CreateEnvironmentRequest(BaseModel):
    name: str
    base_url: str = ""
    description: str = ""
    variables: dict = {}


class UpdateSettingsRequest(BaseModel):
    backend_url: Optional[str] = None
    debug_mode: Optional[bool] = None
    qwen_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    extra: Optional[dict] = None


class CreateDatasourceRequest(BaseModel):
    name: str
    type: str = "mysql"
    host: str = ""
    port: int = 3306
    database: str = ""
    username: str = ""
    password: str = ""


# ==================== 用户管理 ====================

@router.get("/users", summary="获取用户列表")
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = Query(None),
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """获取系统用户列表"""
    query = db.query(User)
    if keyword:
        query = query.filter(User.username.contains(keyword))
    
    total = query.count()
    users = query.order_by(User.id.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()
    
    items = [
        {
            "id": u.id,
            "username": u.username,
            "email": getattr(u, "email", None),
            "role": getattr(u, "role", "user"),
            "is_active": getattr(u, "is_active", True),
            "created_at": str(u.created_at) if hasattr(u, "created_at") and u.created_at else None,
        }
        for u in users
    ]
    return Response(code=200, message="获取成功", data={
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@router.get("/users/{user_id}", summary="获取用户详情")
async def get_user(
    user_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """获取用户详情"""
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    return Response(code=200, message="获取成功", data={
        "id": target.id,
        "username": target.username,
        "email": getattr(target, "email", None),
        "role": getattr(target, "role", "user"),
        "is_active": getattr(target, "is_active", True),
        "created_at": str(target.created_at) if hasattr(target, "created_at") and target.created_at else None,
    })


# ==================== 角色权限 ====================

@router.get("/roles", summary="获取角色列表")
async def list_roles(
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """获取系统角色列表（从用户表聚合）"""
    # 从用户表查询所有不同的角色
    roles_query = db.query(
        User.role.label("role_name"),
        func.count(User.id).label("user_count"),
    ).group_by(User.role).all() if hasattr(User, "role") else []
    
    # 默认角色定义
    default_roles = [
        {"name": "admin", "description": "系统管理员", "permissions": ["*"]},
        {"name": "user", "description": "普通用户", "permissions": ["task:create", "task:execute", "task:view"]},
    ]
    
    role_map = {r.role_name: r.user_count for r in roles_query}
    
    items = []
    for role in default_roles:
        items.append({
            "name": role["name"],
            "description": role["description"],
            "permissions": role["permissions"],
            "user_count": role_map.get(role["name"], 0),
        })
    
    return Response(code=200, message="获取成功", data={
        "items": items,
        "total": len(items),
    })


# ==================== 项目管理 ====================

@router.get("/projects", summary="获取项目列表")
async def list_projects(
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """获取项目列表（从任务表聚合项目名称）"""
    try:
        from app.models.task import Task
        # 查询所有不同的项目名称
        projects = db.query(
            Task.project_name,
            func.count(Task.id),
        ).group_by(Task.project_name).all() if hasattr(Task, "project_name") else []
        
        items = [
            {
                "name": p[0] or "默认项目",
                "task_count": p[1],
            }
            for p in projects
        ]
        
        if not items:
            items = [{"name": "默认项目", "task_count": 0}]
        
        return Response(code=200, message="获取成功", data={
            "items": items,
            "total": len(items),
        })
    except Exception as e:
        log.warning(f"获取项目列表失败: {e}")
        return Response(code=200, message="获取成功", data={
            "items": [{"name": "默认项目", "task_count": 0}],
            "total": 1,
        })


# ==================== 环境配置 ====================

_ENVIRONMENTS_FILE = os.path.join(app_settings.DATA_DIR, "environments.json")


def _load_environments() -> list:
    if os.path.exists(_ENVIRONMENTS_FILE):
        try:
            with open(_ENVIRONMENTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_environments(data: list) -> None:
    os.makedirs(os.path.dirname(_ENVIRONMENTS_FILE), exist_ok=True)
    with open(_ENVIRONMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@router.get("/environments", summary="获取环境列表")
async def list_environments(
    user: User = Depends(require_auth),
):
    """获取测试环境配置列表"""
    envs = _load_environments()
    if not envs:
        # 返回默认环境
        envs = [
            {"id": 1, "name": "测试环境", "base_url": "http://localhost:8080", "description": "默认测试环境"},
            {"id": 2, "name": "开发环境", "base_url": "http://localhost:3000", "description": "开发环境"},
        ]
    return Response(code=200, message="获取成功", data={"items": envs, "total": len(envs)})


@router.post("/environments", summary="创建环境配置")
async def create_environment(
    req: CreateEnvironmentRequest,
    user: User = Depends(require_auth),
):
    """创建测试环境配置"""
    envs = _load_environments()
    new_id = max([e.get("id", 0) for e in envs], default=0) + 1
    new_env = {
        "id": new_id,
        "name": req.name,
        "base_url": req.base_url,
        "description": req.description,
        "variables": req.variables,
        "created_by": user.id,
        "created_at": datetime.now().isoformat(),
    }
    envs.append(new_env)
    _save_environments(envs)
    return Response(code=200, message="创建成功", data=new_env)


# ==================== 系统配置 ====================

@router.get("/settings", summary="获取系统配置")
async def get_settings(
    user: User = Depends(require_auth),
):
    """获取系统全局配置"""
    saved = _load_settings()
    
    # 合并默认配置和已保存配置
    config = {
        "backend_url": saved.get("backend_url", "http://localhost:8000"),
        "debug_mode": saved.get("debug_mode", False),
        "qwen_api_key": saved.get("qwen_api_key", ""),
        "openai_api_key": saved.get("openai_api_key", ""),
        "embedding_provider": getattr(app_settings, "EMBEDDING_PROVIDER", "dashscope"),
        "milvus_host": getattr(app_settings, "MILVUS_HOST", "localhost"),
        "milvus_port": getattr(app_settings, "MILVUS_PORT", 19530),
        "neo4j_uri": getattr(app_settings, "NEO4J_URI", "bolt://localhost:7687"),
        "redis_url": getattr(app_settings, "REDIS_URL", "redis://localhost:6379/0"),
    }
    
    return Response(code=200, message="获取成功", data={"items": [config], "total": 1})


@router.put("/settings", summary="更新系统配置")
async def update_settings(
    req: UpdateSettingsRequest,
    user: User = Depends(require_auth),
):
    """更新系统全局配置（持久化到 JSON 文件）"""
    current = _load_settings()
    
    if req.backend_url is not None:
        current["backend_url"] = req.backend_url
    if req.debug_mode is not None:
        current["debug_mode"] = req.debug_mode
    if req.qwen_api_key is not None:
        current["qwen_api_key"] = req.qwen_api_key
    if req.openai_api_key is not None:
        current["openai_api_key"] = req.openai_api_key
    if req.extra:
        current["extra"] = req.extra
    
    current["updated_by"] = user.id
    current["updated_at"] = datetime.now().isoformat()
    
    _save_settings(current)
    log.info(f"系统配置已更新 | user_id={user.id}")
    
    return Response(code=200, message="更新成功", data=current)


# ==================== 数据源管理 ====================

_DATASOURCES_FILE = os.path.join(app_settings.DATA_DIR, "datasources.json")


def _load_datasources() -> list:
    if os.path.exists(_DATASOURCES_FILE):
        try:
            with open(_DATASOURCES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_datasources(data: list) -> None:
    os.makedirs(os.path.dirname(_DATASOURCES_FILE), exist_ok=True)
    with open(_DATASOURCES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@router.get("/datasources", summary="获取数据源列表")
async def list_datasources(
    user: User = Depends(require_auth),
):
    """获取数据源列表"""
    sources = _load_datasources()
    if not sources:
        # 返回当前系统已配置的数据源
        sources = [
            {
                "id": 1,
                "name": "MySQL 主库",
                "type": "mysql",
                "host": getattr(app_settings, "DB_HOST", "localhost"),
                "port": getattr(app_settings, "DB_PORT", 3306),
                "database": getattr(app_settings, "DB_NAME", "test_automation"),
                "status": "active",
            },
            {
                "id": 2,
                "name": "Milvus 向量库",
                "type": "milvus",
                "host": getattr(app_settings, "MILVUS_HOST", "localhost"),
                "port": getattr(app_settings, "MILVUS_PORT", 19530),
                "status": "active",
            },
            {
                "id": 3,
                "name": "Neo4j 图数据库",
                "type": "neo4j",
                "host": getattr(app_settings, "NEO4J_URI", "bolt://localhost:7687"),
                "port": 7687,
                "status": "active",
            },
            {
                "id": 4,
                "name": "Redis 缓存",
                "type": "redis",
                "host": getattr(app_settings, "REDIS_URL", "redis://localhost:6379/0"),
                "port": 6379,
                "status": "active",
            },
        ]
    return Response(code=200, message="获取成功", data={"items": sources, "total": len(sources)})


@router.post("/datasources", summary="创建数据源")
async def create_datasource(
    req: CreateDatasourceRequest,
    user: User = Depends(require_auth),
):
    """创建数据源"""
    sources = _load_datasources()
    new_id = max([s.get("id", 0) for s in sources], default=4) + 1
    new_source = {
        "id": new_id,
        "name": req.name,
        "type": req.type,
        "host": req.host,
        "port": req.port,
        "database": req.database,
        "username": req.username,
        "status": "inactive",
        "created_by": user.id,
        "created_at": datetime.now().isoformat(),
    }
    sources.append(new_source)
    _save_datasources(sources)
    return Response(code=200, message="创建成功", data=new_source)


# ==================== 脚本仓库 ====================

@router.get("/scripts", summary="获取脚本仓库列表")
async def list_scripts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = Query(None),
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """获取脚本仓库列表"""
    try:
        from app.models.script import Script
        query = db.query(Script)
        if keyword:
            query = query.filter(Script.script_type.contains(keyword))
        
        total = query.count()
        scripts = query.order_by(Script.id.desc()).offset(
            (page - 1) * page_size
        ).limit(page_size).all()
        
        items = [
            {
                "id": s.id,
                "script_name": s.script_type,
                "script_language": s.script_language,
                "framework": s.script_type,
                "task_id": s.task_id,
                "description": s.file_path or "",
                "created_at": str(s.created_at) if hasattr(s, "created_at") and s.created_at else None,
            }
            for s in scripts
        ]
        return Response(code=200, message="获取成功", data={
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        })
    except Exception as e:
        log.warning(f"获取脚本列表失败: {e}")
        return Response(code=200, message="获取成功", data={
            "items": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
        })


@router.post("/scripts", summary="上传脚本到仓库")
async def upload_script(
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """上传脚本到仓库"""
    try:
        from app.models.script import Script
        from fastapi import Request
        
        # 这个端点需要通过 multipart 接收文件
        # 简化实现：接收 JSON body
        return Response(code=200, message="请使用文件上传接口", data={
            "hint": "使用 POST /script-upload 上传脚本文件"
        })
    except Exception as e:
        log.error(f"上传脚本失败: {e}")
        raise HTTPException(status_code=500, detail=f"上传失败: {e}")
