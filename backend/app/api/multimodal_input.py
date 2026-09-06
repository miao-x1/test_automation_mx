"""
多模态需求输入 API

支持文本/图片/URL/脚本混合输入，自动路由解析和融合
"""
import json
import uuid
from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from pydantic import BaseModel
from app.db.database import SessionLocal
from app.models.requirement_input import RequirementInput, InputMode
from app.models.requirement_task import RequirementTask
from app.runtime.agent_factory import AgentFactory
from app.core.config import settings
from app.core.logger import log
from app.schemas.response import Response
from app.core.auth import require_auth
from app.models.user import User

router = APIRouter()


class MultiModalInputRequest(BaseModel):
    """多模态输入请求"""
    text: Optional[str] = None
    images: Optional[List[str]] = None
    urls: Optional[List[str]] = None
    script_content: Optional[str] = None
    script_language: Optional[str] = "python"
    page_ids: Optional[List[int]] = None


class ParseAndFuseRequest(BaseModel):
    """解析并融合请求"""
    input_id: int


@router.post("/upload_script", summary="上传脚本文件")
async def upload_script(
    file: UploadFile = File(..., description="测试脚本文件"),
    user: User = Depends(require_auth),
):
    """上传脚本文件，返回脚本内容和路径"""
    allowed_ext = {".py", ".js", ".ts", ".yaml", ".yml", ".json"}
    ext = Path(file.filename or "").suffix.lower()
    if ext not in allowed_ext:
        raise HTTPException(status_code=400, detail=f"不支持的脚本类型: {ext}，支持: {', '.join(allowed_ext)}")

    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超出限制")

    # 保存文件
    upload_dir = Path(settings.UPLOAD_DIR) / "requirement_scripts"
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    file_path = upload_dir / filename
    with open(file_path, "wb") as f:
        f.write(content)

    relative_path = f"requirement_scripts/{filename}"

    # 推断脚本语言
    language_map = {".py": "python", ".js": "javascript", ".ts": "typescript", ".yaml": "yaml", ".yml": "yaml", ".json": "json"}
    language = language_map.get(ext, "unknown")

    # 读取脚本内容
    try:
        script_content = content.decode("utf-8")
    except UnicodeDecodeError:
        script_content = content.decode("gbk", errors="replace")

    return Response(code=200, message="上传成功", data={
        "script_path": relative_path,
        "script_content": script_content,
        "script_language": language,
        "filename": file.filename,
    })


@router.post("/upload_images", summary="上传多张图片")
async def upload_images(files: List[UploadFile] = File(..., description="UI截图或原型图")):
    """上传多张图片。与统一 upload_security 同级校验，伪造图片不得落盘。"""
    from app.core.upload_security import validate_upload_file

    upload_dir = Path(settings.UPLOAD_DIR) / "requirement_images"
    upload_dir.mkdir(parents=True, exist_ok=True)

    saved_paths = []
    for file in files:
        validated = await validate_upload_file(file, declared_category="image")
        filename = f"{uuid.uuid4().hex}{validated.ext}"
        file_path = upload_dir / filename
        with open(file_path, "wb") as f:
            f.write(validated.content)
        relative_path = f"requirement_images/{filename}"
        saved_paths.append(relative_path)
        log.info(f"需求图片上传成功 | 文件: {filename}")

    return Response(code=200, message="上传成功", data={"image_paths": saved_paths})


@router.post("/parse", summary="解析多模态输入")
async def parse_input(request: MultiModalInputRequest, user: User = Depends(require_auth)):
    """
    解析多模态输入

    根据输入类型自动路由到对应的Parser，返回解析结果和推荐模式
    """
    # 验证至少有一种输入
    has_input = any([
        request.text and request.text.strip(),
        request.images and len(request.images) > 0,
        request.urls and len(request.urls) > 0,
        request.script_content and request.script_content.strip(),
    ])
    if not has_input:
        raise HTTPException(status_code=400, detail="至少提供一种输入（文本/图片/URL/脚本）")

    # 路由解析
    router_agent = AgentFactory.create("input_router")
    input_data = {
        "text": request.text or "",
        "images": request.images or [],
        "urls": request.urls or [],
        "script_content": request.script_content or "",
        "script_language": request.script_language or "python",
        "page_ids": request.page_ids or [],
    }
    route_result = router_agent.route(input_data)

    # 保存到数据库
    db = SessionLocal()
    try:
        req_input = RequirementInput(
            mode=route_result["mode"],
            text=request.text,
            images=json.dumps(request.images or [], ensure_ascii=False) if request.images else None,
            urls=json.dumps(request.urls or [], ensure_ascii=False) if request.urls else None,
            script_content=request.script_content,
            script_language=request.script_language,
            page_ids=json.dumps(request.page_ids or [], ensure_ascii=False) if request.page_ids else None,
            recommended_mode=route_result["recommended_mode"],
            recommended_reason=route_result["recommended_reason"],
            parsed_result=json.dumps(route_result["parse_results"], ensure_ascii=False),
            user_id=user.id,
            created_by=user.id,
        )
        db.add(req_input)
        db.commit()
        db.refresh(req_input)
    finally:
        db.close()

    return Response(code=200, message="解析成功", data={
        "input_id": req_input.id,
        "mode": route_result["mode"],
        "recommended_mode": route_result["recommended_mode"],
        "recommended_reason": route_result["recommended_reason"],
        "parse_results": route_result["parse_results"],
        "active_modes": route_result["active_modes"],
    })


@router.post("/fuse", summary="融合多模态解析结果")
async def fuse_input(request: ParseAndFuseRequest, user: User = Depends(require_auth)):
    """
    融合多模态解析结果为UnifiedRequirement

    将各Parser的解析结果通过FusionAgent融合为统一需求
    """
    db = SessionLocal()
    try:
        req_input = db.query(RequirementInput).filter(
            RequirementInput.id == request.input_id,
            RequirementInput.user_id == user.id,
        ).first()
        if not req_input:
            raise HTTPException(status_code=404, detail="输入记录不存在")

        # 获取解析结果
        parse_results = []
        if req_input.parsed_result:
            try:
                parse_results = json.loads(req_input.parsed_result)
            except json.JSONDecodeError:
                parse_results = []

        if not parse_results:
            raise HTTPException(status_code=400, detail="没有可融合的解析结果，请先解析输入")

        # 融合
        fusion_agent = AgentFactory.create("fusion_agent")
        fused = fusion_agent.fuse(parse_results, req_input.mode)

        # 更新数据库
        req_input.fused_result = json.dumps(fused, ensure_ascii=False)
        req_input.unified_requirement = fused.get("unified_requirement", "")
        db.commit()

        return Response(code=200, message="融合成功", data=fused)
    finally:
        db.close()


@router.post("/parse_and_fuse", summary="一键解析并融合")
async def parse_and_fuse(request: MultiModalInputRequest, user: User = Depends(require_auth)):
    """
    一键解析并融合多模态输入

    自动完成：路由 → 解析 → 融合，返回UnifiedRequirement
    """
    has_input = any([
        request.text and request.text.strip(),
        request.images and len(request.images) > 0,
        request.urls and len(request.urls) > 0,
        request.script_content and request.script_content.strip(),
    ])
    if not has_input:
        raise HTTPException(status_code=400, detail="至少提供一种输入（文本/图片/URL/脚本）")

    # 1. 路由解析
    router_agent = AgentFactory.create("input_router")
    input_data = {
        "text": request.text or "",
        "images": request.images or [],
        "urls": request.urls or [],
        "script_content": request.script_content or "",
        "script_language": request.script_language or "python",
        "page_ids": request.page_ids or [],
    }
    route_result = router_agent.route(input_data)

    # 2. 融合
    fusion_agent = AgentFactory.create("fusion_agent")
    fused = fusion_agent.fuse(route_result["parse_results"], route_result["mode"])

    # 3. 保存到数据库
    db = SessionLocal()
    try:
        req_input = RequirementInput(
            mode=route_result["mode"],
            text=request.text,
            images=json.dumps(request.images or [], ensure_ascii=False) if request.images else None,
            urls=json.dumps(request.urls or [], ensure_ascii=False) if request.urls else None,
            script_content=request.script_content,
            script_language=request.script_language,
            page_ids=json.dumps(request.page_ids or [], ensure_ascii=False) if request.page_ids else None,
            recommended_mode=route_result["recommended_mode"],
            recommended_reason=route_result["recommended_reason"],
            parsed_result=json.dumps(route_result["parse_results"], ensure_ascii=False),
            fused_result=json.dumps(fused, ensure_ascii=False),
            unified_requirement=fused.get("unified_requirement", ""),
            user_id=user.id,
            created_by=user.id,
        )
        db.add(req_input)
        db.commit()
        db.refresh(req_input)
    finally:
        db.close()

    return Response(code=200, message="解析融合成功", data={
        "input_id": req_input.id,
        "mode": route_result["mode"],
        "recommended_mode": route_result["recommended_mode"],
        "recommended_reason": route_result["recommended_reason"],
        "active_modes": route_result["active_modes"],
        "fused": fused,
        "unified_requirement": fused.get("unified_requirement", ""),
    })


@router.get("/recommend", summary="获取输入推荐模式")
async def get_recommendation(
    text: Optional[str] = None,
    has_images: bool = False,
    has_urls: bool = False,
    has_script: bool = False,
):
    """
    根据输入内容推荐处理模式

    不执行实际解析，仅返回推荐
    """
    recommended_mode = "text"
    recommended_reason = "纯文本输入，使用标准文本解析模式"

    if has_images and not text:
        recommended_mode = "vision"
        recommended_reason = "检测到图片输入，推荐使用Vision模式进行UI元素识别和需求提取"
    elif has_images and text:
        recommended_mode = "vision"
        recommended_reason = "检测到图片+文本混合输入，Vision模式可增强图片中的UI元素理解"
    elif has_urls and not text:
        recommended_mode = "dom"
        recommended_reason = "检测到URL输入，推荐使用DOM模式自动抓取页面结构和元素"
    elif has_urls and text:
        recommended_mode = "dom"
        recommended_reason = "检测到URL+文本输入，DOM模式可自动提取页面元素辅助测试"
    elif has_script:
        recommended_mode = "reuse"
        recommended_reason = "检测到脚本输入，推荐使用复用模式，基于已有脚本逻辑生成测试"

    return Response(code=200, message="获取成功", data={
        "recommended_mode": recommended_mode,
        "recommended_reason": recommended_reason,
    })


@router.get("/{input_id}", summary="获取输入详情")
async def get_input(input_id: int, user: User = Depends(require_auth)):
    """获取多模态输入详情"""
    db = SessionLocal()
    try:
        req_input = db.query(RequirementInput).filter(
            RequirementInput.id == input_id,
            RequirementInput.user_id == user.id,
        ).first()
        if not req_input:
            raise HTTPException(status_code=404, detail="输入记录不存在")

        # 解析JSON字段
        images = json.loads(req_input.images) if req_input.images else []
        urls = json.loads(req_input.urls) if req_input.urls else []
        page_ids = json.loads(req_input.page_ids) if req_input.page_ids else []
        parsed_result = json.loads(req_input.parsed_result) if req_input.parsed_result else []
        fused_result = json.loads(req_input.fused_result) if req_input.fused_result else None

        return Response(code=200, message="获取成功", data={
            "id": req_input.id,
            "requirement_id": req_input.requirement_id,
            "mode": req_input.mode,
            "text": req_input.text,
            "images": images,
            "urls": urls,
            "script_path": req_input.script_path,
            "script_content": req_input.script_content,
            "script_language": req_input.script_language,
            "page_ids": page_ids,
            "recommended_mode": req_input.recommended_mode,
            "recommended_reason": req_input.recommended_reason,
            "parsed_result": parsed_result,
            "fused_result": fused_result,
            "unified_requirement": req_input.unified_requirement,
            "created_at": str(req_input.created_at) if req_input.created_at else None,
        })
    finally:
        db.close()
