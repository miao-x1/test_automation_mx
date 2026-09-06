"""
用例中心 API

AI驱动的测试用例自动生成平台

端点：
  POST /generate         - 创建用例生成任务（SSE流式返回进度）
  POST /generate/sync    - 创建用例生成任务（同步返回）
  GET  /tasks            - 获取用例任务列表
  GET  /tasks/{id}       - 获取用例任务详情
  DELETE /tasks/{id}     - 删除用例任务
  GET  /tasks/{id}/cases - 获取任务下的用例列表
  PUT  /cases/{id}       - 更新单个用例
  DELETE /cases/{id}     - 删除单个用例
  POST /tasks/{id}/export - 导出用例
  GET  /exports/{id}     - 获取导出记录
  GET  /tasks/{id}/mindmap - 获取思维导图数据
  POST /tasks/{id}/mindmap - 生成思维导图
"""
import asyncio
import json
import os
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel as PydanticModel
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.case_task import CaseTask, CaseTaskStatus
from app.models.case_content import CaseContent, CaseType, CasePriority
from app.models.case_mindmap import CaseMindmap
from app.models.case_export import CaseExport, CaseExportStatus
from app.core.logger import log
from app.core.config import settings

router = APIRouter()


# ===== Request/Response Models =====

class GenerateRequest(PydanticModel):
    """用例生成请求"""
    title: str = ""
    source_type: str = "text"  # pdf/doc/image/video/schema/swagger/url/text
    raw_text: str = ""
    url: str = ""
    case_types: List[str] = ["functional", "error", "boundary"]
    max_cases: int = 20


class CaseUpdateRequest(PydanticModel):
    """用例更新请求"""
    title: Optional[str] = None
    case_type: Optional[str] = None
    precondition: Optional[str] = None
    steps: Optional[str] = None
    expected: Optional[str] = None
    priority: Optional[str] = None
    tags: Optional[str] = None


class ExportRequest(PydanticModel):
    """导出请求"""
    export_type: str = "excel"  # excel/markdown/json/csv
    case_ids: Optional[List[int]] = None  # 为空则导出全部


# ===== Helper =====

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _case_agents():
    """使用已有 Case Agent，不走不存在的 agent_selector 工厂名。"""
    from app.agent.case.agent_selector import AgentSelector
    from app.agent.case.case_agent import CaseAgent
    return AgentSelector(), CaseAgent()


def _save_uploaded_file(upload_file: UploadFile) -> str:
    """保存上传文件，返回文件路径"""
    from app.core.upload_security import validate_upload_bytes

    content = upload_file.file.read()
    validated = validate_upload_bytes(
        content,
        upload_file.filename or "unknown",
        upload_file.content_type,
    )
    upload_dir = os.path.join(settings.UPLOAD_DIR, "case")
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, validated.safe_name)
    with open(file_path, "wb") as f:
        f.write(validated.content)
    return file_path


def _determine_source_type(filename: str) -> str:
    """根据文件名判断source_type"""
    ext = os.path.splitext(filename)[1].lower()
    type_map = {
        ".pdf": "pdf",
        ".doc": "doc", ".docx": "docx",
        ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image", ".bmp": "image",
        ".mp4": "video", ".avi": "video", ".mov": "video",
        ".json": "swagger", ".yaml": "swagger", ".yml": "swagger",
    }
    return type_map.get(ext, "text")


# ===== Pipeline =====

async def _run_pipeline(task_id: int, source_type: str, file_path: str = "",
                        url: str = "", raw_text: str = "",
                        case_types: List[str] = None, max_cases: int = 20):
    """执行用例生成Pipeline"""
    db = SessionLocal()
    try:
        task = db.query(CaseTask).filter(CaseTask.id == task_id).first()
        if not task:
            return

        # Step 1: 解析
        task.status = CaseTaskStatus.PARSING
        db.commit()

        selector, generator = _case_agents()
        parse_kwargs = {"file_path": file_path, "url": url, "raw_text": raw_text}
        parse_result = selector.parse(source_type=source_type, task_id=task_id, **parse_kwargs)

        requirement_context = parse_result.get("requirement_context", "")
        structured_data = parse_result.get("structured_data", {})

        task.requirement_context = requirement_context
        db.commit()

        # Step 2: 生成用例
        task.status = CaseTaskStatus.GENERATING
        db.commit()

        gen_result = await asyncio.to_thread(
            generator.generate_rag_cases,
            requirement_context=requirement_context,
            retrieved_context=None,
            case_types=case_types or ["functional", "error", "boundary"],
            max_cases=max_cases,
        )

        cases = gen_result.get("cases", [])

        # Step 3: 保存用例
        for case_data in cases:
            case_content = CaseContent(
                case_task_id=task_id,
                title=case_data.get("title", "未命名用例"),
                case_type=case_data.get("case_type", "functional"),
                precondition=case_data.get("precondition", ""),
                steps=case_data.get("steps", ""),
                expected=case_data.get("expected", ""),
                priority=case_data.get("priority", "medium"),
                tags=case_data.get("tags", ""),
                version=1,
            )
            db.add(case_content)

        task.case_set = json.dumps({"total": len(cases)}, ensure_ascii=False)
        task.status = CaseTaskStatus.COMPLETED
        db.commit()

        log.info(f"Pipeline完成 | task_id={task_id}, cases={len(cases)}")

    except Exception as e:
        log.error(f"Pipeline失败 | task_id={task_id}, error={e}")
        task = db.query(CaseTask).filter(CaseTask.id == task_id).first()
        if task:
            task.status = CaseTaskStatus.FAILED
            task.error_message = str(e)
            db.commit()
    finally:
        db.close()


# ===== Endpoints =====

@router.post("/generate")
async def generate_cases(
    title: str = Form(""),
    source_type: str = Form("text"),
    raw_text: str = Form(""),
    url: str = Form(""),
    case_types: str = Form("functional,error,boundary"),
    max_cases: int = Form(20),
    file: UploadFile = File(None),
):
    """
    创建用例生成任务（SSE流式返回进度）
    """
    if not (raw_text or "").strip() and not (url or "").strip() and file is None:
        raise HTTPException(status_code=400, detail="请输入需求文本、URL 或上传文件")

    # 处理文件上传
    file_path = ""
    if file:
        file_path = _save_uploaded_file(file)
        if not source_type or source_type == "text":
            source_type = _determine_source_type(file.filename)

    # 创建CaseTask
    db = SessionLocal()
    try:
        task = CaseTask(
            title=title or f"用例生成-{source_type}",
            source_type=source_type,
            source_file=file_path,
            source_url=url,
            raw_input=raw_text,
            status=CaseTaskStatus.WAITING,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        task_id = task.id
    finally:
        db.close()

    types_list = [t.strip() for t in case_types.split(",") if t.strip()]

    # SSE流式返回 - 真实进度
    async def event_stream():
        import asyncio as _asyncio

        yield f"data: {json.dumps({'event': 'start', 'progress': 0, 'message': '开始生成测试用例', 'status': 'start', 'task_id': task_id}, ensure_ascii=False)}\n\n"

        # 用队列传递真实进度
        progress_queue: _asyncio.Queue = _asyncio.Queue()

        async def run_pipeline_with_progress():
            """执行Pipeline，每个阶段完成后推送真实进度"""
            db = SessionLocal()
            try:
                task = db.query(CaseTask).filter(CaseTask.id == task_id).first()
                if not task:
                    await progress_queue.put({"progress": 0, "message": "任务不存在", "status": "failed"})
                    return

                # Step 1: 解析
                await progress_queue.put({"progress": 5, "message": "正在解析输入...", "status": "parsing", "task_id": task_id})
                task.status = CaseTaskStatus.PARSING
                db.commit()

                selector, generator = _case_agents()
                parse_kwargs = {"file_path": file_path, "url": url, "raw_text": raw_text}
                parse_result = await _asyncio.to_thread(
                    selector.parse, source_type=source_type, task_id=task_id, **parse_kwargs
                )

                requirement_context = parse_result.get("requirement_context", "")
                structured_data = parse_result.get("structured_data", {})
                task.requirement_context = requirement_context
                db.commit()

                await progress_queue.put({"progress": 30, "message": "解析完成，开始生成用例...", "status": "generating", "task_id": task_id})

                # Step 2: 生成用例
                task.status = CaseTaskStatus.GENERATING
                db.commit()

                gen_result = await _asyncio.to_thread(
                    generator.generate_rag_cases,
                    requirement_context=requirement_context,
                    retrieved_context=None,
                    case_types=types_list or ["functional", "error", "boundary"],
                    max_cases=max_cases,
                )

                cases = gen_result.get("cases", [])
                await progress_queue.put({"progress": 75, "message": f"已生成 {len(cases)} 条用例，正在保存...", "status": "reviewing", "task_id": task_id})

                # Step 3: 保存用例
                for case_data in cases:
                    case_content = CaseContent(
                        case_task_id=task_id,
                        title=case_data.get("title", "未命名用例"),
                        case_type=case_data.get("case_type", "functional"),
                        precondition=case_data.get("precondition", ""),
                        steps=case_data.get("steps", ""),
                        expected=case_data.get("expected", ""),
                        priority=case_data.get("priority", "medium"),
                        tags=case_data.get("tags", ""),
                        version=1,
                    )
                    db.add(case_content)

                task.case_set = json.dumps({"total": len(cases)}, ensure_ascii=False)
                task.status = CaseTaskStatus.COMPLETED
                db.commit()

                await progress_queue.put({"progress": 100, "message": "用例生成完成", "status": "completed", "task_id": task_id, "case_count": len(cases)})
                log.info(f"Pipeline完成 | task_id={task_id}, cases={len(cases)}")

            except Exception as e:
                log.error(f"Pipeline失败 | task_id={task_id}, error={e}")
                db2 = SessionLocal()
                try:
                    t = db2.query(CaseTask).filter(CaseTask.id == task_id).first()
                    if t:
                        t.status = CaseTaskStatus.FAILED
                        t.error_message = str(e)
                        db2.commit()
                finally:
                    db2.close()
                await progress_queue.put({"progress": -1, "message": f"生成失败: {e}", "status": "failed", "task_id": task_id})
            finally:
                db.close()
                await progress_queue.put(None)  # 结束信号

        # 启动Pipeline
        pipeline_task = _asyncio.create_task(run_pipeline_with_progress())

        # 实时推送进度
        while True:
            try:
                event = await _asyncio.wait_for(progress_queue.get(), timeout=60)
            except _asyncio.TimeoutError:
                yield f"data: {json.dumps({'progress': -1, 'message': '执行超时', 'status': 'failed', 'task_id': task_id}, ensure_ascii=False)}\n\n"
                break

            if event is None:
                break

            status = event.get("status")
            if status == "completed":
                event = {**event, "event": "complete"}
            elif status == "failed":
                event = {**event, "event": "error"}
            else:
                event = {**event, "event": "progress"}
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            if status in ("completed", "failed"):
                break

        # 确保pipeline完成
        try:
            await pipeline_task
        except Exception:
            pass

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/generate/sync")
async def generate_cases_sync(request: GenerateRequest):
    """创建用例生成任务（同步返回）"""
    if not (request.raw_text or "").strip() and not (request.url or "").strip():
        raise HTTPException(status_code=400, detail="请输入需求文本或 URL")
    db = SessionLocal()
    try:
        task = CaseTask(
            title=request.title or f"用例生成-{request.source_type}",
            source_type=request.source_type,
            source_url=request.url,
            raw_input=request.raw_text,
            status=CaseTaskStatus.WAITING,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        task_id = task.id
    finally:
        db.close()

    # 异步执行Pipeline
    asyncio.create_task(
        _run_pipeline(
            task_id=task_id,
            source_type=request.source_type,
            url=request.url,
            raw_text=request.raw_text,
            case_types=request.case_types,
            max_cases=request.max_cases,
        )
    )

    return {"task_id": task_id, "status": "waiting", "message": "任务已创建，正在后台生成"}


@router.get("/tasks")
def list_tasks(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    source_type: Optional[str] = None,
):
    """获取用例任务列表"""
    db = SessionLocal()
    try:
        query = db.query(CaseTask)
        if status:
            query = query.filter(CaseTask.status == status)
        if source_type:
            query = query.filter(CaseTask.source_type == source_type)
        query = query.order_by(CaseTask.id.desc())
        total = query.count()
        tasks = query.offset(skip).limit(limit).all()
        return {
            "items": [
                {
                    "id": t.id,
                    "title": t.title,
                    "source_type": t.source_type,
                    "status": t.status,
                    "case_count": db.query(CaseContent).filter(CaseContent.case_task_id == t.id).count(),
                    "error_message": t.error_message,
                    "created_at": str(t.created_at) if t.created_at else None,
                    "updated_at": str(t.updated_at) if t.updated_at else None,
                }
                for t in tasks
            ],
            "total": total,
        }
    finally:
        db.close()


@router.get("/tasks/{task_id}")
def get_task(task_id: int):
    """获取用例任务详情"""
    db = SessionLocal()
    try:
        task = db.query(CaseTask).filter(CaseTask.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        case_count = db.query(CaseContent).filter(CaseContent.case_task_id == task_id).count()
        return {
            "id": task.id,
            "title": task.title,
            "source_type": task.source_type,
            "source_file": task.source_file,
            "source_url": task.source_url,
            "raw_input": task.raw_input,
            "status": task.status,
            "requirement_context": task.requirement_context,
            "case_set": task.case_set,
            "error_message": task.error_message,
            "version": task.version,
            "case_count": case_count,
            "created_at": str(task.created_at) if task.created_at else None,
            "updated_at": str(task.updated_at) if task.updated_at else None,
        }
    finally:
        db.close()


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int):
    """删除用例任务及其所有用例"""
    db = SessionLocal()
    try:
        task = db.query(CaseTask).filter(CaseTask.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        # 级联删除
        db.query(CaseContent).filter(CaseContent.case_task_id == task_id).delete()
        db.query(CaseMindmap).filter(CaseMindmap.case_task_id == task_id).delete()
        db.query(CaseExport).filter(CaseExport.case_task_id == task_id).delete()
        db.delete(task)
        db.commit()
        return {"message": "删除成功"}
    finally:
        db.close()


@router.get("/tasks/{task_id}/cases")
def list_cases(
    task_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    case_type: Optional[str] = None,
    priority: Optional[str] = None,
):
    """获取任务下的用例列表"""
    db = SessionLocal()
    try:
        task = db.query(CaseTask).filter(CaseTask.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        query = db.query(CaseContent).filter(
            CaseContent.case_task_id == task_id,
            CaseContent.is_deleted == False,
        )
        if case_type:
            query = query.filter(CaseContent.case_type == case_type)
        if priority:
            query = query.filter(CaseContent.priority == priority)

        total = query.count()
        cases = query.order_by(CaseContent.id.asc()).offset(skip).limit(limit).all()

        return {
            "items": [
                {
                    "id": c.id,
                    "case_task_id": c.case_task_id,
                    "title": c.title,
                    "case_type": c.case_type,
                    "precondition": c.precondition,
                    "steps": c.steps,
                    "expected": c.expected,
                    "priority": c.priority,
                    "tags": c.tags,
                    "version": c.version,
                    "created_at": str(c.created_at) if c.created_at else None,
                    "updated_at": str(c.updated_at) if c.updated_at else None,
                }
                for c in cases
            ],
            "total": total,
        }
    finally:
        db.close()


@router.put("/cases/{case_id}")
def update_case(case_id: int, request: CaseUpdateRequest):
    """更新单个用例"""
    db = SessionLocal()
    try:
        case = db.query(CaseContent).filter(CaseContent.id == case_id, CaseContent.is_deleted == False).first()
        if not case:
            raise HTTPException(status_code=404, detail="用例不存在")

        update_data = request.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(case, key, value)
        case.version = (case.version or 1) + 1
        db.commit()
        db.refresh(case)

        return {
            "id": case.id,
            "title": case.title,
            "case_type": case.case_type,
            "precondition": case.precondition,
            "steps": case.steps,
            "expected": case.expected,
            "priority": case.priority,
            "tags": case.tags,
            "version": case.version,
        }
    finally:
        db.close()


@router.delete("/cases/{case_id}")
def delete_case(case_id: int):
    """软删除单个用例"""
    db = SessionLocal()
    try:
        case = db.query(CaseContent).filter(CaseContent.id == case_id).first()
        if not case:
            raise HTTPException(status_code=404, detail="用例不存在")
        case.is_deleted = True
        db.commit()
        return {"message": "删除成功"}
    finally:
        db.close()


@router.post("/tasks/{task_id}/export")
def export_cases(task_id: int, request: ExportRequest):
    """导出用例"""
    db = SessionLocal()
    try:
        task = db.query(CaseTask).filter(CaseTask.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        # 查询用例
        query = db.query(CaseContent).filter(
            CaseContent.case_task_id == task_id,
            CaseContent.is_deleted == False,
        )
        if request.case_ids:
            query = query.filter(CaseContent.id.in_(request.case_ids))
        cases = query.all()

        if not cases:
            raise HTTPException(status_code=400, detail="没有可导出的用例")

        # 生成导出内容
        export_dir = os.path.join(settings.UPLOAD_DIR, "case", "export")
        os.makedirs(export_dir, exist_ok=True)

        export_type = request.export_type
        file_path = ""

        if export_type == "json":
            data = [
                {
                    "title": c.title, "case_type": c.case_type,
                    "precondition": c.precondition, "steps": c.steps,
                    "expected": c.expected, "priority": c.priority, "tags": c.tags,
                }
                for c in cases
            ]
            file_path = os.path.join(export_dir, f"task_{task_id}_cases.json")
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        elif export_type == "markdown":
            lines = [f"# {task.title} - 测试用例\n"]
            for i, c in enumerate(cases, 1):
                lines.append(f"## {i}. {c.title}\n")
                lines.append(f"- **类型**: {c.case_type}")
                lines.append(f"- **优先级**: {c.priority}")
                lines.append(f"- **前置条件**: {c.precondition}")
                lines.append(f"- **测试步骤**:\n{c.steps}")
                lines.append(f"- **预期结果**: {c.expected}")
                if c.tags:
                    lines.append(f"- **标签**: {c.tags}")
                lines.append("")
            file_path = os.path.join(export_dir, f"task_{task_id}_cases.md")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

        elif export_type == "csv":
            import csv
            file_path = os.path.join(export_dir, f"task_{task_id}_cases.csv")
            with open(file_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["标题", "类型", "优先级", "前置条件", "步骤", "预期结果", "标签"])
                for c in cases:
                    writer.writerow([c.title, c.case_type, c.priority, c.precondition, c.steps, c.expected, c.tags])

        else:  # excel
            try:
                import openpyxl
                wb = openpyxl.Workbook()
                ws = wb.active
                ws.title = "测试用例"
                ws.append(["标题", "类型", "优先级", "前置条件", "步骤", "预期结果", "标签"])
                for c in cases:
                    ws.append([c.title, c.case_type, c.priority, c.precondition, c.steps, c.expected, c.tags])
                file_path = os.path.join(export_dir, f"task_{task_id}_cases.xlsx")
                wb.save(file_path)
            except ImportError:
                # fallback to CSV
                import csv
                file_path = os.path.join(export_dir, f"task_{task_id}_cases.csv")
                with open(file_path, "w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(["标题", "类型", "优先级", "前置条件", "步骤", "预期结果", "标签"])
                    for c in cases:
                        writer.writerow([c.title, c.case_type, c.priority, c.precondition, c.steps, c.expected, c.tags])
                export_type = "csv"

        # 保存导出记录
        export_record = CaseExport(
            case_task_id=task_id,
            export_type=export_type,
            file_path=file_path,
            status=CaseExportStatus.COMPLETED,
            config=json.dumps({"case_count": len(cases), "case_ids": request.case_ids}, ensure_ascii=False),
        )
        db.add(export_record)
        db.commit()
        db.refresh(export_record)

        return {
            "export_id": export_record.id,
            "export_type": export_type,
            "file_path": file_path,
            "case_count": len(cases),
            "status": "completed",
        }

    finally:
        db.close()


@router.get("/exports/{export_id}")
def get_export(export_id: int):
    """获取导出记录"""
    db = SessionLocal()
    try:
        export = db.query(CaseExport).filter(CaseExport.id == export_id).first()
        if not export:
            raise HTTPException(status_code=404, detail="导出记录不存在")
        return {
            "id": export.id,
            "case_task_id": export.case_task_id,
            "export_type": export.export_type,
            "file_path": export.file_path,
            "status": export.status,
            "config": export.config,
            "error_message": export.error_message,
            "created_at": str(export.created_at) if export.created_at else None,
        }
    finally:
        db.close()


@router.get("/tasks/{task_id}/mindmap")
def get_mindmap(task_id: int):
    """获取思维导图数据"""
    db = SessionLocal()
    try:
        task = db.query(CaseTask).filter(CaseTask.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        mindmap = db.query(CaseMindmap).filter(CaseMindmap.case_task_id == task_id).first()
        if not mindmap:
            # 自动生成
            cases = db.query(CaseContent).filter(
                CaseContent.case_task_id == task_id,
                CaseContent.is_deleted == False,
            ).all()
            mindmap_data = _build_mindmap_data(task, cases)
            mindmap = CaseMindmap(
                case_task_id=task_id,
                mindmap_data=json.dumps(mindmap_data, ensure_ascii=False),
                format="json",
                version=1,
            )
            db.add(mindmap)
            db.commit()
            db.refresh(mindmap)

        return {
            "id": mindmap.id,
            "task_id": task_id,
            "mindmap_data": json.loads(mindmap.mindmap_data) if mindmap.mindmap_data else {},
            "format": mindmap.format,
        }
    finally:
        db.close()


@router.post("/tasks/{task_id}/mindmap")
def generate_mindmap(task_id: int):
    """生成思维导图"""
    db = SessionLocal()
    try:
        task = db.query(CaseTask).filter(CaseTask.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        cases = db.query(CaseContent).filter(
            CaseContent.case_task_id == task_id,
            CaseContent.is_deleted == False,
        ).all()

        mindmap_data = _build_mindmap_data(task, cases)

        # 更新或创建
        mindmap = db.query(CaseMindmap).filter(CaseMindmap.case_task_id == task_id).first()
        if mindmap:
            mindmap.mindmap_data = json.dumps(mindmap_data, ensure_ascii=False)
            mindmap.version = (mindmap.version or 1) + 1
        else:
            mindmap = CaseMindmap(
                case_task_id=task_id,
                mindmap_data=json.dumps(mindmap_data, ensure_ascii=False),
                format="json",
                version=1,
            )
            db.add(mindmap)
        db.commit()

        return {"task_id": task_id, "mindmap_data": mindmap_data, "message": "思维导图已生成"}
    finally:
        db.close()


def _build_mindmap_data(task: CaseTask, cases: List[CaseContent]) -> dict:
    """构建思维导图数据结构"""
    # 按类型分组
    groups = {}
    for c in cases:
        ct = c.case_type or "functional"
        if ct not in groups:
            groups[ct] = []
        groups[ct].append({"name": c.title, "priority": c.priority})

    type_labels = {"functional": "功能测试", "error": "异常测试", "boundary": "边界测试"}
    children = []
    for ct, items in groups.items():
        children.append({
            "name": type_labels.get(ct, ct),
            "children": items,
        })

    return {
        "name": task.title or "测试用例",
        "children": children,
    }
