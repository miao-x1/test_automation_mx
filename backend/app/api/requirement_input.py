"""
需求输入统一API路由

提供以下接口：
1. POST /api/v1/requirement-input/parse   — 解析多模态需求输入，返回RequirementContext
2. POST /api/v1/requirement-input/upload   — 上传文件（图片/PDF/Word/视频/Schema）
3. POST /api/v1/requirement-input/generate  — 解析需求并直接发送给TestCaseGenerator
"""
import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, UploadFile, File, Form, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

# 上传文件存储目录
UPLOAD_DIR = os.path.join(settings.UPLOAD_DIR, "requirement_input")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 文件类型分类
FILE_TYPE_MAP = {
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image",
    ".gif": "image", ".bmp": "image",
    ".pdf": "pdf",
    ".doc": "word", ".docx": "word",
    ".mp4": "video", ".avi": "video", ".mov": "video", ".mkv": "video",
    ".sql": "schema", ".ddl": "schema",
    ".json": "swagger", ".yaml": "swagger", ".yml": "swagger",
}


# ================================================================== #
#  请求/响应模型                                                       #
# ================================================================== #

class RequirementInputRequest(BaseModel):
    """多模态需求输入请求"""
    text: str = Field(default="", description="需求文本")
    image_paths: List[str] = Field(default_factory=list, description="图片文件路径列表")
    pdf_paths: List[str] = Field(default_factory=list, description="PDF文件路径列表")
    word_paths: List[str] = Field(default_factory=list, description="Word文件路径列表")
    video_paths: List[str] = Field(default_factory=list, description="视频文件路径列表")
    swagger_content: str = Field(default="", description="Swagger/OpenAPI JSON内容")
    schema_content: str = Field(default="", description="数据库DDL SQL内容")
    urls: List[str] = Field(default_factory=list, description="URL列表")
    context: Dict[str, Any] = Field(default_factory=dict, description="附加上下文")
    task_id: str = Field(default="", description="任务ID")
    user_id: Optional[int] = Field(default=None, description="用户ID")
    # 是否直接发送给TestCaseGenerator
    auto_generate: bool = Field(default=False, description="解析后是否自动发送给用例生成Agent")


class RequirementContextResponse(BaseModel):
    """需求上下文响应"""
    status: str
    context: Dict[str, Any] = Field(default_factory=dict)
    source_types: List[str] = Field(default_factory=list)
    summary: str = ""
    intent: str = ""
    pages_count: int = 0
    elements_count: int = 0
    test_points_count: int = 0
    business_flows_count: int = 0
    constraints_count: int = 0
    duration: float = 0.0
    error: str = ""


class UploadResponse(BaseModel):
    """文件上传响应"""
    status: str
    file_path: str = ""
    file_type: str = ""
    file_name: str = ""
    file_size: int = 0
    error: str = ""


# ================================================================== #
#  API 端点                                                           #
# ================================================================== #

@router.post("/parse", response_model=RequirementContextResponse, summary="解析多模态需求输入")
async def parse_requirement_input(req: RequirementInputRequest):
    """
    解析多模态需求输入，返回统一的RequirementContext。

    支持的输入类型：
    - 文本需求
    - 图片（UI截图）
    - PDF文档
    - Word文档
    - 视频（操作录屏）
    - Swagger/OpenAPI JSON
    - 数据库Schema DDL
    - URL列表
    - 附加上下文

    返回统一的RequirementContext格式：
    {
        pages: [],
        elements: [],
        business_flow: [],
        test_points: [],
        constraints: []
    }
    """
    import time as _time
    start = _time.time()

    # 使用 TaskRuntime 调用 InputRouterAgent
    from app.runtime import get_task_runtime

    task_runtime = get_task_runtime()
    session_key = f"req_input_{uuid.uuid4().hex[:8]}"
    task_id = req.task_id or f"task_{uuid.uuid4().hex[:8]}"

    payload = {
        "text": req.text,
        "image_paths": req.image_paths,
        "pdf_paths": req.pdf_paths,
        "word_paths": req.word_paths,
        "video_paths": req.video_paths,
        "swagger_content": req.swagger_content,
        "schema_content": req.schema_content,
        "urls": req.urls,
        "context": req.context,
        "task_id": task_id,
        "session_key": session_key,
        "user_id": req.user_id,
    }

    try:
        result = await task_runtime.execute(
            agent_type="input_router_agent",
            action="execute",
            payload=payload,
            task_id=task_id,
            user_id=req.user_id,
            timeout=300,
        )

        if result and result.get("status") in ("completed", "success"):
            # 兼容两种返回格式
            data = result.get("data", result)
            ctx_data = data.get("context", {}) if isinstance(data, dict) else {}

            # 如果需要自动发送给TestCaseGenerator
            if req.auto_generate and ctx_data:
                try:
                    from app.agents.messages import RequirementContextMessage
                    from autogen_core import DefaultTopicId
                    # 发布 RequirementContextMessage
                    msg = RequirementContextMessage(
                        task_id=task_id,
                        session_key=session_key,
                        user_id=req.user_id,
                        source_types=ctx_data.get("source_types", []),
                        context=ctx_data,
                    )
                    # 通过 runtime 广播
                    await task_runtime.publish_message(msg, topic_id=DefaultTopicId())
                    logger.info(f"RequirementContextMessage 已发布给TestCaseGenerator | task_id={task_id}")
                except Exception as e:
                    logger.warning(f"发布RequirementContextMessage失败: {e}")

            duration = _time.time() - start
            return RequirementContextResponse(
                status="success",
                context=ctx_data,
                source_types=ctx_data.get("source_types", []),
                summary=ctx_data.get("summary", ""),
                intent=ctx_data.get("intent", ""),
                pages_count=len(ctx_data.get("pages", [])),
                elements_count=len(ctx_data.get("elements", [])),
                test_points_count=len(ctx_data.get("test_points", [])),
                business_flows_count=len(ctx_data.get("business_flow", [])),
                constraints_count=len(ctx_data.get("constraints", [])),
                duration=round(duration, 2),
            )
        else:
            return RequirementContextResponse(
                status="error",
                error=result.get("error", "解析失败") if result else "无返回结果",
                duration=round(_time.time() - start, 2),
            )

    except Exception as e:
        logger.error(f"parse_requirement_input 失败: {e}", exc_info=True)
        return RequirementContextResponse(
            status="error",
            error=str(e),
            duration=round(_time.time() - start, 2),
        )


@router.post("/upload", response_model=UploadResponse, summary="上传需求文件")
async def upload_requirement_file(
    file: UploadFile = File(...),
    file_category: str = Form(default="auto", description="文件类别: image/pdf/word/video/swagger/schema/auto"),
):
    """
    上传需求文件（图片/PDF/Word/视频/Schema/Swagger）。

    返回文件路径，后续可用于 /parse 接口。
    """
    from app.core.upload_security import UploadRejected, validate_upload_file

    try:
        validated = await validate_upload_file(file, declared_category=file_category or "auto")
    except UploadRejected:
        raise
    except Exception as e:
        logger.error(f"文件上传失败: {e}", exc_info=True)
        raise

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    save_name = f"{validated.category}_{uuid.uuid4().hex[:8]}{os.path.splitext(validated.safe_name)[1]}"
    save_path = os.path.join(UPLOAD_DIR, save_name)
    with open(save_path, "wb") as f:
        f.write(validated.content)

    logger.info(
        f"文件上传成功 | category={validated.category}, path={save_path}, size={validated.size}"
    )

    return UploadResponse(
        status="success",
        file_path=save_path,
        file_type=validated.category,
        file_name=validated.original_name,
        file_size=validated.size,
    )


@router.post("/generate", summary="解析需求并直接生成测试用例(SSE流式)")
async def parse_and_generate(req: RequirementInputRequest):
    """
    解析多模态需求输入，并直接发送给TestCaseGenerator生成测试用例。

    以SSE流式返回执行进度。
    """
    task_id = req.task_id or f"task_{uuid.uuid4().hex[:8]}"
    session_key = f"req_gen_{uuid.uuid4().hex[:8]}"

    async def event_stream():
        import json as _json

        # Step 1: 解析需求
        yield f"data: {_json.dumps({'event': 'step_start', 'step': 'parse_requirement', 'message': '开始解析需求输入...'})}\n\n"

        from app.runtime import get_task_runtime
        task_runtime = get_task_runtime()

        payload = {
            "text": req.text,
            "image_paths": req.image_paths,
            "pdf_paths": req.pdf_paths,
            "word_paths": req.word_paths,
            "video_paths": req.video_paths,
            "swagger_content": req.swagger_content,
            "schema_content": req.schema_content,
            "urls": req.urls,
            "context": req.context,
            "task_id": task_id,
            "session_key": session_key,
            "user_id": req.user_id,
        }

        try:
            result = await task_runtime.execute(
                agent_type="input_router_agent",
                action="execute",
                payload=payload,
                task_id=task_id,
                user_id=req.user_id,
                timeout=300,
            )

            if result and result.get("status") in ("completed", "success"):
                data = result.get("data", result)
                ctx_data = data.get("context", {}) if isinstance(data, dict) else {}

                yield f"data: {_json.dumps({'event': 'step_completed', 'step': 'parse_requirement', 'message': '需求解析完成', 'context': ctx_data})}\n\n"

                # Step 2: 发布给TestCaseGenerator
                yield f"data: {_json.dumps({'event': 'step_start', 'step': 'generate_cases', 'message': '开始生成测试用例...'})}\n\n"

                try:
                    from app.agents.messages import RequirementContextMessage
                    from autogen_core import DefaultTopicId

                    msg = RequirementContextMessage(
                        task_id=task_id,
                        session_key=session_key,
                        user_id=req.user_id,
                        source_types=ctx_data.get("source_types", []),
                        context=ctx_data,
                    )
                    await task_runtime.publish_message(msg, topic_id=DefaultTopicId())

                    yield f"data: {_json.dumps({'event': 'step_completed', 'step': 'generate_cases', 'message': '已发送给用例生成Agent'})}\n\n"
                except Exception as e:
                    yield f"data: {_json.dumps({'event': 'step_failed', 'step': 'generate_cases', 'error': str(e)})}\n\n"

                # Done
                yield f"data: {_json.dumps({'event': 'done', 'task_id': task_id, 'session_key': session_key})}\n\n"

            else:
                error = result.get("error", "解析失败") if result else "无返回结果"
                yield f"data: {_json.dumps({'event': 'error', 'error': error})}\n\n"

        except Exception as e:
            logger.error(f"parse_and_generate 失败: {e}", exc_info=True)
            yield f"data: {_json.dumps({'event': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
