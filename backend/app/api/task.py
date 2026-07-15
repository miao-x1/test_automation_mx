"""
任务管理接口 - 统一入口

支持两种输入模式：
- image: 上传截图 → 统一分析流程
- url: 输入URL → 统一分析流程

数据隔离：所有查询自动过滤 user_id
"""
import os
import uuid
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import PlainTextResponse, FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse
from app.db.database import get_db
from app.schemas.response import Response
from app.schemas.task import TaskResponse, TaskListResponse
from app.services.task_service import TaskService
from app.services.task_service import TaskService as UnifiedTaskService
from app.core.config import settings
from app.core.logger import log
from app.core.auth import get_current_user, require_auth
from app.models.user import User

router = APIRouter()


class CreateTaskRequest(BaseModel):
    """URL模式创建任务请求"""
    url: str = Field(..., description="页面URL")
    task_name: str = Field(default=None, description="任务名称（可选）")


@router.post("/create", summary="创建任务（URL模式）")
async def create_task_url(
    req: CreateTaskRequest,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """输入URL创建任务"""
    task_name = req.task_name or f"测试: {req.url[:50]}"
    task = UnifiedTaskService.create_task(
        db=db,
        task_name=task_name,
        input_mode="url",
        page_url=req.url,
        user_id=user.id,
    )
    return Response(
        code=200,
        message="任务创建成功",
        data=TaskResponse.model_validate(task)
    )


@router.post("/upload", summary="上传图片并创建任务")
async def upload_and_create_task(
    file: UploadFile = File(..., description="UI原型图或页面截图"),
    task_name: str = Form(..., description="任务名称"),
    page_url: str = Form(default=None, description="页面URL（可选，用于同时抓取DOM）"),
    user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """上传UI图片并创建分析任务"""
    # 验证文件类型
    allowed_types = ["image/png", "image/jpeg", "image/jpg", "image/webp"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="不支持的文件类型")

    # 创建上传目录
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)

    # 生成唯一文件名
    ext = Path(file.filename).suffix
    filename = f"{uuid.uuid4().hex}{ext}"
    file_path = upload_dir / filename

    # 保存文件
    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超出限制")

    with open(file_path, "wb") as f:
        f.write(content)

    log.info(f"文件上传成功 | 文件: {filename}")

    # 创建统一任务
    task = UnifiedTaskService.create_task(
        db=db,
        task_name=task_name,
        input_mode="image",
        page_url=page_url,
        file_path=str(file_path),
        original_filename=file.filename,
        file_size=len(content),
        file_type=file.content_type,
        user_id=user.id,
    )

    return Response(
        code=200,
        message="任务创建成功",
        data=TaskResponse.model_validate(task)
    )


@router.get("/images/{image_id}", summary="获取图片")
async def get_image(
    image_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """获取上传的图片文件"""
    from app.models.image_file import ImageFile
    image = db.query(ImageFile).filter(ImageFile.id == image_id, ImageFile.user_id == user.id).first()
    if not image:
        raise HTTPException(status_code=404, detail="图片不存在")
    # 拼接绝对路径
    file_path = image.file_path
    if not os.path.isabs(file_path):
        file_path = os.path.join(settings.UPLOAD_DIR, os.path.basename(file_path))
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"图片文件不存在: {file_path}")
    return FileResponse(
        file_path,
        media_type=image.file_type or "image/jpeg",
        filename=image.original_filename,
    )


@router.get("/{task_id}", summary="获取任务详情")
async def get_task(
    task_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """获取任务详情"""
    task = TaskService.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    # 数据隔离：只能查看自己的任务
    if task.user_id is not None and task.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问该任务")

    return Response(
        code=200,
        message="success",
        data=TaskResponse.model_validate(task)
    )


@router.get("/", summary="获取任务列表")
async def get_task_list(
    skip: int = 0,
    limit: int = 20,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """获取任务列表（自动过滤当前用户）"""
    items, total = TaskService.get_task_list(db, skip, limit, user_id=user.id)

    return Response(
        code=200,
        message="success",
        data=TaskListResponse(
            total=total,
            items=[TaskResponse.model_validate(t) for t in items]
        )
    )


@router.delete("/{task_id}", summary="删除任务")
async def delete_task(
    task_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """删除任务及所有关联数据和文件"""
    task = TaskService.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.user_id is not None and task.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权删除该任务")

    success = TaskService.delete_task(db, task_id)
    if not success:
        raise HTTPException(status_code=404, detail="任务不存在")

    return Response(code=200, message="任务删除成功")


class BatchDeleteRequest(BaseModel):
    """批量删除请求"""
    ids: list[int]


class UpdateScriptRequest(BaseModel):
    """更新脚本请求"""
    script_content: str = Field(..., description="脚本内容")


@router.put("/{task_id}/script", summary="更新脚本内容")
async def update_script(
    task_id: int,
    req: UpdateScriptRequest,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """更新任务的Playwright脚本内容，同步更新关联的需求任务"""
    from app.models.script import Script
    from app.models.requirement_task import RequirementTask
    from app.models.task import Task

    # 数据隔离
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.user_id is not None and task.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权操作")

    script = db.query(Script).filter(Script.task_id == task_id).first()
    if not script:
        raise HTTPException(status_code=404, detail="脚本不存在")
    script.script_content = req.script_content
    # 同步更新关联的需求任务的脚本
    req_task = db.query(RequirementTask).filter(RequirementTask.task_id == task_id).first()
    if req_task:
        req_task.generated_script = req.script_content
    db.commit()
    return Response(code=200, message="脚本更新成功")


@router.post("/batch_delete", summary="批量删除任务")
async def batch_delete_tasks(
    request: BatchDeleteRequest,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """批量删除任务及所有关联数据和文件"""
    if not request.ids:
        raise HTTPException(status_code=400, detail="请选择要删除的任务")
    success_count = 0
    fail_count = 0
    for task_id in request.ids:
        try:
            task = TaskService.get_task(db, task_id)
            if task and (task.user_id is None or task.user_id == user.id):
                if TaskService.delete_task(db, task_id):
                    success_count += 1
                else:
                    fail_count += 1
            else:
                fail_count += 1
        except Exception:
            fail_count += 1
    return Response(code=200, message=f"删除完成: 成功{success_count}个, 失败{fail_count}个")


@router.post("/{task_id}/rerun", summary="重新执行任务")
async def rerun_task(
    task_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """清除旧结果并重新执行分析"""
    task = TaskService.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.user_id is not None and task.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权操作")

    task = TaskService.rerun_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    return Response(
        code=200,
        message="任务已重置，可重新执行分析",
        data=TaskResponse.model_validate(task)
    )


@router.get("/{task_id}/download", summary="下载脚本")
async def download_script(
    task_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """下载生成的Playwright测试脚本"""
    task = TaskService.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.user_id is not None and task.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问")

    script_content = TaskService.get_script_content(db, task_id)
    if not script_content:
        raise HTTPException(status_code=404, detail="脚本不存在，请先执行分析")

    filename = f"test_task_{task_id}.py"
    return PlainTextResponse(
        content=script_content,
        media_type="text/x-python",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )


@router.get("/{task_id}/analyze", summary="启动统一分析（SSE）")
async def analyze_task(
    task_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """
    启动统一分析流程，通过SSE实时推送进度
    根据任务的input_mode自动选择分析路径
    """
    task = TaskService.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.user_id is not None and task.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问")

    return EventSourceResponse(
        UnifiedTaskService.run_unified_analysis(task_id)
    )


@router.post("/{task_id}/auto_fix", summary="自动修复")
async def auto_fix_task(
    task_id: int,
    db: Session = Depends(get_db),
):
    """
    自动修复失败的测试脚本

    分析失败原因，调用 FeedbackAgent 生成修复建议，
    然后尝试自动修复脚本。
    """
    from app.models.task import Task
    from app.models.script import Script
    from app.models.execution_record import ExecutionRecord, ExecutionStatus

    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 获取最近失败的执行记录
    failed_exec = db.query(ExecutionRecord).filter(
        ExecutionRecord.task_id == task_id,
        ExecutionRecord.status == ExecutionStatus.FAILED,
    ).order_by(ExecutionRecord.created_at.desc()).first()

    if not failed_exec:
        return Response(code=200, message="没有失败的执行记录，无需修复", data={
            "task_id": task_id,
            "fixed": False,
            "message": "没有失败的执行记录",
        })

    # 获取脚本
    script = db.query(Script).filter(Script.task_id == task_id).first()
    if not script:
        return Response(code=200, message="没有关联脚本", data={
            "task_id": task_id,
            "fixed": False,
            "message": "没有关联的脚本",
        })

    # 调用 FeedbackAgent 分析失败
    try:
        from app.runtime.agent_factory import AgentFactory
        feedback_agent = AgentFactory.create("feedback_agent")

        analysis = feedback_agent.analyze(
            script_content=script.script_content,
            error_message=failed_exec.error_message or "",
            log_content=failed_exec.log_content or "",
        )

        return Response(code=200, message="分析完成", data={
            "task_id": task_id,
            "fixed": False,
            "analysis": analysis,
            "execution_id": failed_exec.id,
            "message": "已生成修复建议，请查看分析结果",
        })
    except Exception as e:
        log.error(f"自动修复失败: {e}", exc_info=True)
        return Response(code=500, message=f"修复失败: {e}", data={
            "task_id": task_id,
            "fixed": False,
            "error": str(e),
        })


# ==================================================================
# AI 任务理解接口
# ==================================================================

class UnderstandingResponse(BaseModel):
    """AI任务理解结果"""
    goal: str = ""              # 测试目标
    test_object: str = ""       # 测试对象
    test_flow: str = ""         # 测试流程
    risk_points: list = []      # 风险点
    coverage: str = ""          # 预计覆盖范围
    summary: str = ""           # 需求摘要
    confidence: float = 0.0     # 理解置信度


@router.get("/{task_id}/understanding", summary="AI任务理解")
async def get_task_understanding(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_auth),
):
    """AI理解任务，返回结构化的测试目标、流程、风险点等

    用于任务详情页顶部的 AI理解层展示。
    """
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 检查是否已有缓存的理解结果
    if task.analysis_result and task.analysis_result.ai_understanding:
        return Response(code=200, data=task.analysis_result.ai_understanding)

    # 构建理解上下文
    context_parts = []
    if task.task_name:
        context_parts.append(f"任务名称: {task.task_name}")
    if task.page_url:
        context_parts.append(f"测试URL: {task.page_url}")
    if task.task_type:
        context_parts.append(f"测试类型: {task.task_type}")
    if task.input_mode == "image" and task.images:
        context_parts.append(f"上传了{len(task.images)}张页面截图")

    # 查找关联的 RequirementTask
    req_text = ""
    try:
        from app.models.requirement_task import RequirementTask
        req_task = db.query(RequirementTask).filter(
            RequirementTask.task_id == task_id
        ).first()
        if req_task and req_task.requirement:
            req_text = req_task.requirement
            context_parts.append(f"用户需求: {req_text}")
    except Exception:
        pass

    context = "\n".join(context_parts) if context_parts else f"任务#{task_id}"

    # 调用AI生成理解
    try:
        from app.runtime.agent_factory import AgentFactory
        agent = AgentFactory.create("requirement_agent")

        # 使用Agent的LLM能力生成结构化理解
        system_prompt = """你是一个资深测试架构师。请分析用户的测试需求，输出JSON格式的理解结果：
{
  "goal": "一句话描述测试目标",
  "test_object": "测试对象是什么（页面/接口/功能模块）",
  "test_flow": "建议的测试流程，用 → 连接关键步骤",
  "risk_points": ["风险点1", "风险点2", "风险点3"],
  "coverage": "预计覆盖的功能点范围描述",
  "summary": "需求的一句话摘要",
  "confidence": 0.85
}

只输出JSON，不要其他文字。"""

        user_prompt = f"请分析以下测试任务并给出理解：\n\n{context}"

        result_text = await agent.call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        # 解析JSON
        import json
        import re
        json_match = re.search(r'\{[\s\S]*\}', result_text)
        if json_match:
            understanding = json.loads(json_match.group())
        else:
            raise ValueError("AI返回内容无法解析为JSON")

        # 缓存到数据库
        if task.analysis_result:
            task.analysis_result.ai_understanding = understanding
            db.commit()

        return Response(code=200, data=understanding)

    except Exception as e:
        log.warning(f"AI理解失败，降级为规则分析: {e}")
        # 降级：基于关键词的规则分析
        understanding = _generate_local_understanding(context, task)
        return Response(code=200, data=understanding)


def _generate_local_understanding(context: str, task) -> dict:
    """降级：本地规则生成理解"""
    text = context.lower()

    # 测试目标
    goal = "验证核心功能正常工作"
    if "登录" in text:
        goal = "验证用户登录功能的安全性、正确性和边界场景"
    elif "注册" in text:
        goal = "验证用户注册流程的完整性和数据校验"
    elif "搜索" in text:
        goal = "验证搜索功能的准确性和性能"
    elif "购物车" in text:
        goal = "验证购物车操作的正确性和数据一致性"

    # 测试对象
    test_object = "Web页面"
    if task.task_type == "api":
        test_object = "API接口"
    elif task.task_type == "android":
        test_object = "移动APP"
    elif task.page_url:
        test_object = f"页面 {task.page_url}"

    # 测试流程
    flow_parts = ["打开页面"]
    if "登录" in text:
        flow_parts += ["输入用户名密码", "点击登录", "验证跳转", "测试异常输入"]
    elif "搜索" in text:
        flow_parts += ["输入关键词", "点击搜索", "验证结果", "测试空搜索"]
    elif "购物车" in text:
        flow_parts += ["选择商品", "加入购物车", "修改数量", "结算"]
    else:
        flow_parts += ["执行核心操作", "验证结果", "测试边界场景"]
    test_flow = " → ".join(flow_parts)

    # 风险点
    risks = []
    if "登录" in text:
        risks = ["空密码登录", "SQL注入攻击", "暴力破解防护", "会话超时处理"]
    elif "搜索" in text:
        risks = ["特殊字符搜索", "空关键词处理", "搜索结果分页", "性能瓶颈"]
    elif "购物车" in text:
        risks = ["并发添加冲突", "库存超卖", "价格计算精度", "跨设备同步"]
    else:
        risks = ["网络异常处理", "并发操作冲突", "数据边界验证", "错误恢复机制"]

    return {
        "goal": goal,
        "test_object": test_object,
        "test_flow": test_flow,
        "risk_points": risks,
        "coverage": f"覆盖正常流程、异常场景、边界条件约{len(flow_parts)*3+4}个测试点",
        "summary": goal,
        "confidence": 0.6,
    }


# ==================================================================
# AI 脚本优化接口
# ==================================================================

class OptimizeScriptRequest(BaseModel):
    """脚本优化请求"""
    optimization_type: str = "general"  # general / readability / stability / coverage


@router.post("/{task_id}/optimize-script", summary="AI优化测试脚本")
async def optimize_script(
    task_id: int,
    req: OptimizeScriptRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_auth),
):
    """AI优化测试脚本

    根据优化类型（通用/可读性/稳定性/覆盖率）对脚本进行优化。
    """
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if not task.script or not task.script.script_content:
        raise HTTPException(status_code=400, detail="没有关联的脚本")

    old_script = task.script.script_content

    try:
        from app.runtime.agent_factory import AgentFactory
        agent = AgentFactory.create("script_generation_agent")

        type_prompts = {
            "general": "请优化这个测试脚本的代码质量、可读性和稳定性，同时增加必要的注释和异常处理。",
            "readability": "请优化这个测试脚本的可读性：重命名变量、提取公共方法、增加注释，使其更易维护。",
            "stability": "请优化这个测试脚本的稳定性：增加等待策略、重试机制、异常处理，减少flaky测试。",
            "coverage": "请优化这个测试脚本的覆盖率：增加边界场景、异常路径、断言完整性，确保测试更全面。",
        }

        prompt = type_prompts.get(req.optimization_type, type_prompts["general"])

        # 调用AI优化脚本
        system_prompt = f"""你是一个资深测试自动化工程师。请优化以下测试脚本。
要求：
1. 保持原有测试逻辑不变
2. {prompt}
3. 输出完整的优化后脚本代码，不要解释

优化方向: {req.optimization_type}"""

        user_prompt = f"原始脚本:\n```python\n{old_script[:8000]}\n```"

        optimized = await agent.call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        # 清理AI输出中的markdown标记
        if "```" in optimized:
            import re
            code_match = re.search(r'```\w*\n([\s\S]*?)```', optimized)
            if code_match:
                optimized = code_match.group(1)

        # 更新脚本
        task.script.script_content = optimized
        db.commit()

        return Response(code=200, message="脚本优化完成", data={
            "task_id": task_id,
            "optimization_type": req.optimization_type,
            "old_length": len(old_script),
            "new_length": len(optimized),
            "optimized": True,
        })

    except Exception as e:
        log.error(f"脚本优化失败: {e}", exc_info=True)
        return Response(code=500, message=f"优化失败: {e}", data={
            "task_id": task_id,
            "optimized": False,
            "error": str(e),
        })
