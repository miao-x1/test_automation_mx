"""
统一执行中心（Execution First）

所有执行入口统一到 /execution，支持：
  - 单资产执行：POST /execution/run/asset
  - 套件执行：POST /execution/run/suite
  - 批量执行：POST /execution/run/batch
  - 取消/重试/SSE/报告/日志/删除

数据隔离：所有查询自动过滤 user_id
"""
import os
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from typing import List, Optional

from app.db.database import get_db
from app.schemas.response import Response
from app.models.execution_record import ExecutionRecord, ExecutionStatus, ExecutionType
from app.models.test_asset import TestAsset
from app.models.test_suite import TestSuite
from app.services.execution.dispatcher import ExecutionDispatcher
from app.services.execution.result_writer import ResultWriter
from app.services.execution.redis_queue import get_execution_queue
from app.services.execution import ExecutionService, ExecutionQueryService
from app.core.config import settings
from app.core.logger import log
from app.core.auth import require_auth
from app.models.user import User

router = APIRouter()


# ===== 请求体 =====

class RunAssetRequest(BaseModel):
    """单资产执行请求"""
    asset_id: int
    env: str = "test"
    base_url: str = "http://localhost:8080"
    async_exec: bool = True


class RunSuiteRequest(BaseModel):
    """套件执行请求"""
    suite_id: int
    env: str = "test"


class RunBatchRequest(BaseModel):
    """批量执行请求"""
    asset_ids: List[int]
    env: str = "test"
    base_url: str = "http://localhost:8080"


class BatchDeleteRequest(BaseModel):
    """批量删除请求体"""
    ids: List[int]


# ===== 辅助函数 =====

def _check_execution_owner(db: Session, execution_id: int, user: User) -> ExecutionRecord:
    """检查执行记录是否属于当前用户"""
    record = db.query(ExecutionRecord).filter(ExecutionRecord.id == execution_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if record.user_id is not None and record.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问")
    return record


def _map_asset_type_to_execution_type(asset_type: str) -> str:
    """将 TestAsset.asset_type 映射为 ExecutionType"""
    mapping = {
        "api": ExecutionType.API,
        "web": ExecutionType.WEB,
        "android": ExecutionType.ANDROID,
        "manual": ExecutionType.API,  # manual 降级为 api 执行
    }
    return mapping.get(asset_type, ExecutionType.API)


# ===== 执行入口 =====

@router.post("/run/asset", summary="执行单个测试资产")
async def run_asset(
    req: RunAssetRequest,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """
    执行单个 TestAsset

    流程：
    1. 加载 TestAsset，验证归属与可执行性
    2. 获取 exec_data
    3. 创建 ExecutionRecord
    4. 异步提交队列 / 同步执行
    """
    # 1. 加载资产，验证归属
    asset = db.query(TestAsset).filter(TestAsset.id == req.asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="测试资产不存在")
    if asset.user_id is not None and asset.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权操作")

    # 2. 验证可执行性
    if not asset.executable:
        raise HTTPException(status_code=400, detail="该资产不可执行（缺少步骤或断言）")

    # 3. 获取执行数据
    exec_data = asset.to_execution_json()
    if not exec_data:
        raise HTTPException(status_code=400, detail="无法生成执行数据")

    # 4. 创建执行记录
    execution_type = _map_asset_type_to_execution_type(asset.asset_type)
    record = ExecutionRecord(
        asset_id=asset.id,
        execution_type=execution_type,
        status=ExecutionStatus.WAITING,
        trigger_source="manual",
        user_id=user.id,
        created_by=user.id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    # 5. 执行
    if req.async_exec:
        # 异步：提交到执行队列
        try:
            queue = get_execution_queue()
            await queue.submit(
                execution_id=record.id,
                cases=[exec_data],
                context_config={
                    "env": req.env,
                    "base_url": req.base_url,
                    "headers": {},
                    "variables": exec_data.get("variables", {}),
                },
            )
        except Exception as e:
            log.warning(f"执行队列提交失败，降级为WAITING状态: {e}")
            record.status = ExecutionStatus.WAITING
            db.commit()

        return Response(
            code=200,
            message="执行任务已提交",
            data={
                "execution_id": record.id,
                "status": record.status,
                "asset_id": asset.id,
            },
        )
    else:
        # 同步：直接执行
        try:
            result = await ExecutionDispatcher.dispatch_batch(
                asset_ids=[asset.id],
                user_id=user.id,
                env=req.env,
                base_url=req.base_url,
            )

            # 更新执行记录
            summary = result.get("summary", {})
            record.status = ExecutionStatus.SUCCESS if summary.get("fail", 0) == 0 and summary.get("error", 0) == 0 else ExecutionStatus.FAILED
            record.success_count = summary.get("pass", 0)
            record.failed_count = summary.get("fail", 0) + summary.get("error", 0)
            record.duration = sum(r.get("duration_ms", 0) for r in result.get("results", [])) / 1000.0
            record.log_content = "\n".join(
                f"[{r.get('status', '?')}] {r.get('title', '')} ({r.get('duration_ms', 0)}ms)"
                + (f" - {r['error']}" if r.get("error") else "")
                for r in result.get("results", [])
            )
            db.commit()
            db.refresh(record)

            return Response(
                code=200,
                message="执行完成",
                data={
                    "execution_id": record.id,
                    "status": record.status,
                    "asset_id": asset.id,
                    "result": result,
                },
            )
        except Exception as e:
            record.status = ExecutionStatus.FAILED
            record.error_message = str(e)
            db.commit()
            raise HTTPException(status_code=500, detail=f"执行失败: {e}")


@router.post("/run/suite", summary="执行测试套件")
async def run_suite(
    req: RunSuiteRequest,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """
    执行 TestSuite

    流程：
    1. 加载 TestSuite，验证归属
    2. 解析 case_ids，加载可执行资产
    3. 创建 ExecutionRecord（execution_type=suite）
    4. 提交到执行队列
    """
    # 1. 加载套件，验证归属
    suite = db.query(TestSuite).filter(TestSuite.id == req.suite_id).first()
    if not suite:
        raise HTTPException(status_code=404, detail="测试套件不存在")
    if suite.user_id is not None and suite.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权操作")

    # 2. 解析 case_ids
    case_ids = []
    if suite.case_ids:
        try:
            case_ids = json.loads(suite.case_ids)
        except json.JSONDecodeError:
            case_ids = []

    if not case_ids:
        raise HTTPException(status_code=400, detail="套件中没有测试用例")

    # 加载可执行资产
    assets = db.query(TestAsset).filter(
        TestAsset.id.in_(case_ids),
        TestAsset.is_deleted == False,
        TestAsset.executable == True,
    ).all()

    if not assets:
        raise HTTPException(status_code=400, detail="套件中没有可执行的测试资产")

    # 3. 创建执行记录
    record = ExecutionRecord(
        suite_id=suite.id,
        execution_type=ExecutionType.SUITE,
        status=ExecutionStatus.WAITING,
        trigger_source="manual",
        user_id=user.id,
        created_by=user.id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    # 4. 构建用例列表并提交到队列
    cases = []
    for asset in assets:
        exec_data = asset.to_execution_json()
        if exec_data:
            cases.append(exec_data)

    base_url = suite.base_url or "http://localhost:8080"
    env = req.env or suite.env or "test"
    suite_headers = {}
    if suite.headers:
        try:
            suite_headers = json.loads(suite.headers)
        except json.JSONDecodeError:
            pass
    suite_variables = {}
    if suite.variables:
        try:
            suite_variables = json.loads(suite.variables)
        except json.JSONDecodeError:
            pass

    try:
        queue = get_execution_queue()
        await queue.submit(
            execution_id=record.id,
            cases=cases,
            context_config={
                "env": env,
                "base_url": base_url,
                "headers": suite_headers,
                "variables": suite_variables,
            },
        )
    except Exception as e:
        log.warning(f"执行队列提交失败，降级为WAITING状态: {e}")
        record.status = ExecutionStatus.WAITING
        db.commit()

    return Response(
        code=200,
        message="套件执行任务已提交",
        data={
            "execution_id": record.id,
            "status": record.status,
            "suite_id": suite.id,
            "case_count": len(cases),
        },
    )


@router.post("/run/batch", summary="批量执行测试资产")
async def run_batch(
    req: RunBatchRequest,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """
    批量执行多个 TestAsset

    流程：
    1. 加载所有 asset_ids 对应的资产
    2. 过滤仅可执行的资产
    3. 创建单条 ExecutionRecord（execution_type=batch）
    4. 提交所有用例到队列
    """
    if not req.asset_ids:
        raise HTTPException(status_code=400, detail="asset_ids 不能为空")

    # 1. 加载资产
    assets = db.query(TestAsset).filter(
        TestAsset.id.in_(req.asset_ids),
        TestAsset.is_deleted == False,
    ).all()

    # 2. 过滤可执行 + 归属校验
    executable_assets = []
    for asset in assets:
        if asset.user_id is not None and asset.user_id != user.id:
            continue
        if asset.executable:
            executable_assets.append(asset)

    if not executable_assets:
        raise HTTPException(status_code=400, detail="没有可执行的测试资产")

    # 3. 创建执行记录
    record = ExecutionRecord(
        execution_type=ExecutionType.BATCH,
        status=ExecutionStatus.WAITING,
        trigger_source="manual",
        user_id=user.id,
        created_by=user.id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    # 4. 构建用例列表并提交到队列
    cases = []
    for asset in executable_assets:
        exec_data = asset.to_execution_json()
        if exec_data:
            cases.append(exec_data)

    if not cases:
        record.status = ExecutionStatus.FAILED
        record.error_message = "无法生成执行数据"
        db.commit()
        raise HTTPException(status_code=400, detail="无法生成执行数据")

    try:
        queue = get_execution_queue()
        await queue.submit(
            execution_id=record.id,
            cases=cases,
            context_config={
                "env": req.env,
                "base_url": req.base_url,
                "headers": {},
                "variables": {},
            },
        )
    except Exception as e:
        log.warning(f"执行队列提交失败，降级为WAITING状态: {e}")
        record.status = ExecutionStatus.WAITING
        db.commit()

    return Response(
        code=200,
        message="批量执行任务已提交",
        data={
            "execution_id": record.id,
            "status": record.status,
            "case_count": len(cases),
        },
    )


# ===== 执行控制 =====

@router.post("/{execution_id}/cancel", summary="取消执行")
async def cancel_execution(
    execution_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """取消正在等待或执行中的任务"""
    record = _check_execution_owner(db, execution_id, user)
    if record.status not in (ExecutionStatus.WAITING, ExecutionStatus.PENDING, ExecutionStatus.RUNNING):
        raise HTTPException(status_code=400, detail=f"当前状态 {record.status} 不可取消")

    try:
        queue = get_execution_queue()
        # 尝试从队列中移除
        if hasattr(queue, 'cancel'):
            cancelled = await queue.cancel(execution_id)
        else:
            cancelled = False
    except Exception:
        cancelled = False

    if not cancelled:
        record.status = ExecutionStatus.CANCELLED
        db.commit()

    return Response(
        code=200,
        message="执行已取消",
        data={"execution_id": execution_id, "status": "cancelled"},
    )


@router.post("/{execution_id}/retry", summary="重试执行")
async def retry_execution(
    execution_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """
    重试执行

    基于原执行记录创建新的 ExecutionRecord，trigger_source="retry"
    """
    record = _check_execution_owner(db, execution_id, user)

    # 创建新的执行记录
    new_record = ExecutionRecord(
        task_id=record.task_id,
        asset_id=record.asset_id,
        suite_id=record.suite_id,
        session_id=record.session_id,
        execution_type=record.execution_type,
        status=ExecutionStatus.WAITING,
        trigger_source="retry",
        user_id=user.id,
        created_by=user.id,
    )
    db.add(new_record)
    db.commit()
    db.refresh(new_record)

    # 如果有关联资产，提交到队列
    if record.asset_id:
        asset = db.query(TestAsset).filter(TestAsset.id == record.asset_id).first()
        if asset and asset.executable:
            exec_data = asset.to_execution_json()
            if exec_data:
                try:
                    queue = get_execution_queue()
                    await queue.submit(
                        execution_id=new_record.id,
                        cases=[exec_data],
                        context_config={
                            "env": "test",
                            "base_url": "http://localhost:8080",
                            "headers": {},
                            "variables": exec_data.get("variables", {}),
                        },
                    )
                except Exception as e:
                    log.warning(f"重试执行队列提交失败: {e}")

    # 如果有关联套件，提交到队列
    elif record.suite_id:
        suite = db.query(TestSuite).filter(TestSuite.id == record.suite_id).first()
        if suite and suite.case_ids:
            try:
                case_ids = json.loads(suite.case_ids)
            except json.JSONDecodeError:
                case_ids = []

            assets = db.query(TestAsset).filter(
                TestAsset.id.in_(case_ids),
                TestAsset.is_deleted == False,
                TestAsset.executable == True,
            ).all()

            cases = [a.to_execution_json() for a in assets if a.to_execution_json()]
            if cases:
                try:
                    queue = get_execution_queue()
                    await queue.submit(
                        execution_id=new_record.id,
                        cases=cases,
                        context_config={
                            "env": suite.env or "test",
                            "base_url": suite.base_url or "http://localhost:8080",
                            "headers": json.loads(suite.headers) if suite.headers else {},
                            "variables": json.loads(suite.variables) if suite.variables else {},
                        },
                    )
                except Exception as e:
                    log.warning(f"重试套件执行队列提交失败: {e}")

    return Response(
        code=200,
        message="重试执行已创建",
        data={
            "execution_id": new_record.id,
            "original_execution_id": execution_id,
            "status": new_record.status,
        },
    )


# ===== SSE 流 =====

@router.get("/{execution_id}/stream", summary="执行进度（SSE）")
async def execution_stream(
    execution_id: int,
    user: User = Depends(require_auth),
):
    """SSE实时推送执行进度

    注意: 不使用 Depends(get_db)，因为 SSE 流期间 DB 连接不会释放，
    会导致连接池耗尽。改为手动管理 session，校验后立即关闭。
    """
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        _check_execution_owner(db, execution_id, user)
    finally:
        db.close()
    return EventSourceResponse(
        ExecutionService.run_execution(execution_id)
    )


# ===== 查询 =====

@router.get("/list", summary="获取执行记录列表")
async def list_executions(
    status: Optional[str] = None,
    execution_type: Optional[str] = None,
    asset_id: Optional[int] = None,
    suite_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """获取当前用户的执行记录（分页，支持多维度过滤）"""
    query = db.query(ExecutionRecord).filter(ExecutionRecord.user_id == user.id)

    if status:
        query = query.filter(ExecutionRecord.status == status)
    if execution_type:
        query = query.filter(ExecutionRecord.execution_type == execution_type)
    if asset_id:
        query = query.filter(ExecutionRecord.asset_id == asset_id)
    if suite_id:
        query = query.filter(ExecutionRecord.suite_id == suite_id)

    query = query.order_by(ExecutionRecord.created_at.desc())

    total = query.count()
    records = query.offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for r in records:
        item = r.to_dict()
        # 解析分析结果
        if r.analysis_result:
            try:
                item["analysis"] = json.loads(r.analysis_result)
            except json.JSONDecodeError:
                item["analysis"] = None
        else:
            item["analysis"] = None
        items.append(item)

    return Response(code=200, message="success", data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    })


@router.get("/{execution_id}", summary="查询执行详情")
async def get_execution(
    execution_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """查询执行记录详情"""
    record = _check_execution_owner(db, execution_id, user)
    data = record.to_dict()
    # 解析分析结果
    if record.analysis_result:
        try:
            data["analysis"] = json.loads(record.analysis_result)
        except json.JSONDecodeError:
            data["analysis"] = None
    else:
        data["analysis"] = None
    return Response(code=200, message="success", data=data)


# ===== 报告 =====

@router.get("/{execution_id}/report", summary="查看测试报告")
async def get_execution_report(
    execution_id: int,
    format: str = Query("html", description="报告格式: html/json/excel"),
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """获取测试报告，支持 html/json/excel 格式"""
    record = _check_execution_owner(db, execution_id, user)

    if format == "json":
        # JSON 格式：直接返回 analysis_result 中的结构化数据
        report_data = {
            "execution_id": record.id,
            "execution_type": record.execution_type,
            "status": record.status,
            "success_count": record.success_count,
            "failed_count": record.failed_count,
            "duration": record.duration,
            "start_time": record.start_time,
            "end_time": record.end_time,
        }
        if record.analysis_result:
            try:
                report_data["detail"] = json.loads(record.analysis_result)
            except json.JSONDecodeError:
                report_data["detail"] = None
        return Response(code=200, message="success", data=report_data)

    # HTML / Excel：返回文件
    report_path = ExecutionQueryService.get_execution_report(db, execution_id)
    if not report_path:
        raise HTTPException(status_code=404, detail="测试报告不存在")
    if not os.path.isabs(report_path):
        report_path = os.path.join(os.getcwd(), report_path)
    if not os.path.exists(report_path):
        raise HTTPException(status_code=404, detail="报告文件不存在")

    if format == "excel":
        return FileResponse(report_path, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=f"report_{execution_id}.xlsx")
    else:
        return FileResponse(report_path, media_type="text/html", filename=f"report_{execution_id}.html")


# ===== 日志 =====

@router.get("/{execution_id}/logs", summary="查看执行日志")
async def get_execution_logs(
    execution_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """获取执行日志内容"""
    _check_execution_owner(db, execution_id, user)
    log_content = ExecutionQueryService.get_execution_log(db, execution_id)
    if log_content is None:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    return PlainTextResponse(content=log_content, media_type="text/plain; charset=utf-8")


# ===== 删除 =====

@router.delete("/{execution_id}", summary="删除执行记录")
async def delete_execution(
    execution_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """删除指定的执行记录"""
    record = _check_execution_owner(db, execution_id, user)

    # 清理关联文件
    if record.report_path:
        try:
            report_full = os.path.join(settings.REPORT_DIR, record.report_path) if not os.path.isabs(record.report_path) else record.report_path
            if os.path.exists(report_full):
                os.remove(report_full)
        except Exception as e:
            log.warning(f"删除报告文件失败: {e}")

    if record.screenshot_path:
        try:
            screenshot_full = os.path.join(settings.SCREENSHOT_DIR, record.screenshot_path) if not os.path.isabs(record.screenshot_path) else record.screenshot_path
            if os.path.exists(screenshot_full):
                os.remove(screenshot_full)
        except Exception as e:
            log.warning(f"删除截图文件失败: {e}")

    db.delete(record)
    db.commit()
    log.info(f"已删除执行记录 | execution_id={execution_id}")
    return Response(code=200, message="删除成功")


@router.delete("/batch", summary="批量删除执行记录")
async def batch_delete_executions(
    req: BatchDeleteRequest,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """批量删除指定的执行记录（仅当前用户）"""
    deleted_count = 0
    for eid in req.ids:
        record = db.query(ExecutionRecord).filter(
            ExecutionRecord.id == eid,
            ExecutionRecord.user_id == user.id,
        ).first()
        if record:
            # 清理关联文件
            if record.report_path:
                try:
                    report_full = os.path.join(settings.REPORT_DIR, record.report_path) if not os.path.isabs(record.report_path) else record.report_path
                    if os.path.exists(report_full):
                        os.remove(report_full)
                except Exception:
                    pass
            if record.screenshot_path:
                try:
                    screenshot_full = os.path.join(settings.SCREENSHOT_DIR, record.screenshot_path) if not os.path.isabs(record.screenshot_path) else record.screenshot_path
                    if os.path.exists(screenshot_full):
                        os.remove(screenshot_full)
                except Exception:
                    pass
            db.delete(record)
            deleted_count += 1

    db.commit()
    log.info(f"批量删除执行记录 | count={deleted_count}")
    return Response(code=200, message=f"已删除 {deleted_count} 条记录", data={"deleted_count": deleted_count})


# ===== 执行分析 =====

@router.post("/{execution_id}/analyze", summary="AI智能分析执行结果")
async def analyze_execution(
    execution_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """AI智能分析执行结果

    失败时自动调用AI分析：
    - 错误原因
    - 影响范围
    - 修复方案
    - 是否可自动修复
    """
    record = _check_execution_owner(db, execution_id, user)

    # 如果已有分析结果，直接返回
    if record.analysis_result:
        try:
            existing = json.loads(record.analysis_result)
            # 如果已有AI分析，直接返回
            if existing.get("ai_analyzed"):
                return Response(code=200, message="分析结果已存在", data={
                    "execution_id": execution_id,
                    "analysis": existing,
                    "analyzed": True,
                })
        except json.JSONDecodeError:
            pass

    # 基础分析数据
    analysis = {
        "execution_id": execution_id,
        "status": record.status,
        "success_count": record.success_count or 0,
        "failed_count": record.failed_count or 0,
        "duration": record.duration or 0,
        "suggestions": [],
    }

    # 失败时调用AI进行智能分析
    if record.status == "failed" or (record.failed_count and record.failed_count > 0):
        try:
            from app.runtime.agent_factory import AgentFactory

            # 获取脚本内容
            script_content = ""
            if record.task_id:
                from app.models.script import Script
                script = db.query(Script).filter(Script.task_id == record.task_id).first()
                if script:
                    script_content = script.script_content or ""

            # 调用 FeedbackAgent AI分析
            feedback_agent = AgentFactory.create("feedback_agent")
            ai_analysis = feedback_agent.analyze(
                script_content=script_content[:8000],
                error_message=record.error_message or "",
                log_content=(record.log_content or "")[:8000],
            )

            # 结构化AI分析结果
            if isinstance(ai_analysis, dict):
                analysis["error_cause"] = ai_analysis.get("error_cause", ai_analysis.get("root_cause", record.error_message or "未知错误"))
                analysis["impact_scope"] = ai_analysis.get("impact_scope", "当前测试用例")
                analysis["fix_suggestion"] = ai_analysis.get("fix_suggestion", ai_analysis.get("suggestion", "检查脚本逻辑和定位器"))
                analysis["auto_fixable"] = ai_analysis.get("auto_fixable", False)
                analysis["ai_analyzed"] = True
            else:
                analysis["error_cause"] = str(ai_analysis)
                analysis["fix_suggestion"] = "检查脚本逻辑"
                analysis["ai_analyzed"] = True

            analysis["suggestions"] = [
                {
                    "type": "ai_analysis",
                    "error_cause": analysis.get("error_cause", ""),
                    "impact_scope": analysis.get("impact_scope", ""),
                    "fix_suggestion": analysis.get("fix_suggestion", ""),
                    "auto_fixable": analysis.get("auto_fixable", False),
                },
            ]
        except Exception as e:
            log.warning(f"AI分析失败，降级为规则分析: {e}")
            # 降级为规则分析
            if record.error_message:
                analysis["error_cause"] = record.error_message
                analysis["impact_scope"] = "当前测试用例"
                analysis["fix_suggestion"] = "检查脚本逻辑和定位器是否正确"
                analysis["auto_fixable"] = False
                analysis["ai_analyzed"] = False

            analysis["suggestions"] = [
                {
                    "type": "rule_based",
                    "error_cause": record.error_message or "执行失败",
                    "fix_suggestion": "检查脚本逻辑和定位器是否正确",
                    "auto_fixable": False,
                },
            ]
    else:
        analysis["suggestions"] = [
            {"type": "info", "message": "执行成功，无异常"},
        ]

    # 保存分析结果
    record.analysis_result = json.dumps(analysis, ensure_ascii=False, default=str)
    db.commit()

    return Response(code=200, message="分析完成", data={
        "execution_id": execution_id,
        "analysis": analysis,
        "analyzed": True,
    })


@router.get("/{execution_id}/analysis", summary="获取执行分析")
async def get_execution_analysis(
    execution_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """获取执行结果的分析数据"""
    record = _check_execution_owner(db, execution_id, user)

    if record.analysis_result:
        try:
            analysis = json.loads(record.analysis_result)
            return Response(code=200, message="success", data={
                "execution_id": execution_id,
                "analysis": analysis,
                "analyzed": True,
            })
        except json.JSONDecodeError:
            pass

    return Response(code=200, message="尚未分析", data={
        "execution_id": execution_id,
        "analysis": None,
        "analyzed": False,
    })


@router.get("/analysis/list", summary="分析结果列表")
async def list_analysis(
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """获取有分析结果的执行记录列表"""
    query = db.query(ExecutionRecord).filter(
        ExecutionRecord.user_id == user.id,
        ExecutionRecord.analysis_result.isnot(None),
    )
    if status:
        query = query.filter(ExecutionRecord.status == status)

    total = query.count()
    records = query.order_by(ExecutionRecord.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    items = []
    for r in records:
        item = r.to_dict()
        if r.analysis_result:
            try:
                item["analysis"] = json.loads(r.analysis_result)
            except json.JSONDecodeError:
                item["analysis"] = None
        items.append(item)

    return Response(code=200, message="success", data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    })


@router.delete("/analysis/batch", summary="批量删除分析结果")
async def batch_delete_analysis(
    req: BatchDeleteRequest,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """批量删除分析结果"""
    deleted = 0
    for eid in req.ids:
        record = db.query(ExecutionRecord).filter(
            ExecutionRecord.id == eid,
            ExecutionRecord.user_id == user.id,
        ).first()
        if record and record.analysis_result:
            record.analysis_result = None
            deleted += 1
    db.commit()
    return Response(code=200, message=f"已删除 {deleted} 条分析结果", data={"deleted_count": deleted})


@router.delete("/analysis/{execution_id}", summary="删除分析结果")
async def delete_analysis(
    execution_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """删除指定执行记录的分析结果"""
    record = _check_execution_owner(db, execution_id, user)
    record.analysis_result = None
    db.commit()
    return Response(code=200, message="分析结果已删除")


# ===== 按任务执行 =====

@router.post("/{task_id}/execute", summary="按任务执行脚本")
async def execute_by_task(
    task_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """按任务ID执行脚本：查找任务关联的脚本并执行"""
    from app.models.task import Task
    from app.models.script import Script

    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 查找脚本
    script = db.query(Script).filter(Script.task_id == task_id).first()
    if not script:
        raise HTTPException(status_code=404, detail="任务没有关联的脚本")

    # 查找关联的TestAsset
    asset = db.query(TestAsset).filter(TestAsset.task_id == task_id).first()

    # 创建执行记录
    record = ExecutionRecord(
        task_id=task_id,
        asset_id=asset.id if asset else None,
        execution_type=ExecutionType.WEB,
        status=ExecutionStatus.WAITING,
        trigger_source="manual",
        user_id=user.id,
        created_by=user.id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    # 如果有asset，提交到队列
    if asset and asset.executable:
        exec_data = asset.to_execution_json()
        if exec_data:
            try:
                queue = get_execution_queue()
                await queue.submit(
                    execution_id=record.id,
                    cases=[exec_data],
                    context_config={
                        "env": "test",
                        "base_url": task.page_url or "http://localhost:8080",
                        "headers": {},
                        "variables": {},
                    },
                )
            except Exception as e:
                log.warning(f"执行队列提交失败: {e}")

    return Response(code=200, message="执行任务已提交", data={
        "execution_id": record.id,
        "task_id": task_id,
        "status": record.status,
    })


@router.get("/task/{task_id}/list", summary="按任务查询执行记录")
async def list_by_task(
    task_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """按任务ID查询关联的执行记录"""
    query = db.query(ExecutionRecord).filter(
        ExecutionRecord.task_id == task_id,
        ExecutionRecord.user_id == user.id,
    )

    total = query.count()
    records = query.order_by(ExecutionRecord.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    items = [r.to_dict() for r in records]

    return Response(code=200, message="success", data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "task_id": task_id,
        "items": items,
    })


# ===== 截图 =====

@router.get("/{execution_id}/screenshot", summary="获取执行截图")
async def get_screenshot(
    execution_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """获取执行记录的截图"""
    record = _check_execution_owner(db, execution_id, user)

    if not record.screenshot_path:
        raise HTTPException(status_code=404, detail="无截图")

    screenshot_path = record.screenshot_path
    if not os.path.isabs(screenshot_path):
        screenshot_path = os.path.join(settings.SCREENSHOT_DIR, screenshot_path)

    if not os.path.exists(screenshot_path):
        raise HTTPException(status_code=404, detail="截图文件不存在")

    return FileResponse(screenshot_path, media_type="image/png")
