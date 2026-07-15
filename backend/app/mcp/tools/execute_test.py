"""
execute_test - 执行测试工具

执行已有的测试脚本或测试任务。

支持3种执行模式：
1. 按任务ID执行：执行已生成的测试任务
2. 按脚本内容执行：直接提供脚本内容
3. 按资产ID执行：执行测试资产

调用后端能力：
  - ScriptExecutor: 脚本执行器
  - ExecutionDispatcher: 执行分发
  - ExecutionService: 执行服务（SSE流）
"""
import json
import time
from typing import Any, Dict

from app.core.logger import log

TOOL_NAME = "execute_test"
TOOL_DESCRIPTION = """执行测试工具。执行已有的测试脚本或测试任务。

支持3种执行模式：
1. 按任务ID执行：执行已生成的测试任务（通过 task_id）
2. 按脚本内容执行：直接提供脚本代码内容（通过 script_content）
3. 按资产ID执行：执行已发布的测试资产（通过 asset_id）

返回：执行状态、通过/失败数量、执行时长、错误信息、测试报告。"""

TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "task_id": {
            "type": "integer",
            "description": "需求任务ID（模式1）。执行该任务生成的测试脚本",
        },
        "script_content": {
            "type": "string",
            "description": "脚本内容（模式2）。直接提供要执行的脚本代码",
        },
        "script_type": {
            "type": "string",
            "enum": ["playwright", "midscene", "yaml", "pytest", "appium", "jmeter"],
            "description": "脚本类型（模式2必填）。默认playwright",
        },
        "asset_id": {
            "type": "integer",
            "description": "测试资产ID（模式3）。执行已发布的测试资产",
        },
        "base_url": {
            "type": "string",
            "description": "测试目标URL。如：http://localhost:8080",
        },
        "env": {
            "type": "string",
            "enum": ["dev", "test", "staging", "prod"],
            "description": "执行环境，默认test",
        },
        "timeout": {
            "type": "integer",
            "description": "超时时间（秒），默认300",
        },
    },
}


async def execute(**kwargs) -> Dict[str, Any]:
    """
    执行测试

    Args:
        task_id: 需求任务ID
        script_content: 脚本内容
        script_type: 脚本类型
        asset_id: 测试资产ID
        base_url: 目标URL
        env: 执行环境
        timeout: 超时时间

    Returns:
        {
            "status": "success" | "error",
            "execution_id": int,
            "passed": int,
            "failed": int,
            "duration": float,
            "report": dict,
            "error": str,
        }
    """
    start = time.time()

    task_id = kwargs.get("task_id")
    script_content = kwargs.get("script_content", "")
    script_type = kwargs.get("script_type", "playwright")
    asset_id = kwargs.get("asset_id")
    base_url = kwargs.get("base_url", "")
    env = kwargs.get("env", "test")
    timeout = kwargs.get("timeout", 300)

    if not task_id and not script_content and not asset_id:
        return {"status": "error", "error": "必须提供 task_id、script_content 或 asset_id 之一"}

    log.info(f"[MCP execute_test] 开始 | task_id={task_id}, asset_id={asset_id}, script_len={len(script_content)}")

    # 模式1：按任务ID执行
    if task_id:
        try:
            return await _execute_by_task(task_id, env, timeout, start)
        except Exception as e:
            log.error(f"[MCP execute_test] 任务执行失败: {e}", exc_info=True)
            return {"status": "error", "error": f"任务执行失败: {e}", "duration": round(time.time() - start, 2)}

    # 模式2：按脚本内容执行
    if script_content:
        try:
            return await _execute_by_script(script_content, script_type, base_url, timeout, start)
        except Exception as e:
            log.error(f"[MCP execute_test] 脚本执行失败: {e}", exc_info=True)
            return {"status": "error", "error": f"脚本执行失败: {e}", "duration": round(time.time() - start, 2)}

    # 模式3：按资产ID执行
    if asset_id:
        try:
            return await _execute_by_asset(asset_id, env, base_url, start)
        except Exception as e:
            log.error(f"[MCP execute_test] 资产执行失败: {e}", exc_info=True)
            return {"status": "error", "error": f"资产执行失败: {e}", "duration": round(time.time() - start, 2)}

    return {"status": "error", "error": "未知执行模式"}


async def _execute_by_task(task_id: int, env: str, timeout: int, start: float) -> Dict[str, Any]:
    """按任务ID执行"""
    from app.services.requirement_flow_service import RequirementFlowService

    results = []
    final_data = None

    for chunk in RequirementFlowService.execute_only(requirement_id=task_id):
        try:
            data = json.loads(chunk)
            step = data.get("step", "")
            if step in ("执行完成", "任务完成"):
                final_data = data.get("data", {})
            results.append({
                "step": step,
                "progress": data.get("progress", 0),
                "message": data.get("message", ""),
            })
        except (json.JSONDecodeError, TypeError):
            continue

    duration = round(time.time() - start, 2)
    log.info(f"[MCP execute_test] 任务执行完成 | task_id={task_id}, duration={duration}s")

    return {
        "status": "success",
        "mode": "task",
        "task_id": task_id,
        "steps": results,
        "final": final_data,
        "duration": duration,
    }


async def _execute_by_script(
    script_content: str, script_type: str, base_url: str, timeout: int, start: float
) -> Dict[str, Any]:
    """按脚本内容执行"""
    from app.agent.script.script_executor import ScriptExecutor

    executor = ScriptExecutor()

    result = executor.execute(
        content=script_content,
        script_type=script_type,
        task_id=None,
        timeout=timeout,
    )

    duration = round(time.time() - start, 2)
    log.info(f"[MCP execute_test] 脚本执行完成 | type={script_type}, duration={duration}s")

    return {
        "status": result.get("status", "unknown"),
        "mode": "script",
        "script_type": script_type,
        "passed": result.get("passed", 0),
        "failed": result.get("failed", 0),
        "total": result.get("total", 0),
        "duration": result.get("duration", duration),
        "logs": result.get("logs", [])[:20],  # 限制返回
        "error": result.get("error", ""),
    }


async def _execute_by_asset(asset_id: int, env: str, base_url: str, start: float) -> Dict[str, Any]:
    """按资产ID执行"""
    from app.services.execution_service import ExecutionDispatcher
    from app.db.database import SessionLocal
    from app.models.execution_record import ExecutionRecord

    # 分发执行
    execution_ids = ExecutionDispatcher.dispatch(
        asset_ids=[asset_id],
        user_id=None,
        env=env,
        base_url=base_url or "http://localhost:8080",
    )

    if not execution_ids:
        return {"status": "error", "error": "执行分发失败，未创建执行记录"}

    execution_id = execution_ids[0]

    # 等待执行完成（简单轮询）
    db = SessionLocal()
    try:
        max_wait = 300  # 5分钟
        waited = 0
        while waited < max_wait:
            record = db.query(ExecutionRecord).filter(ExecutionRecord.id == execution_id).first()
            if record and record.status.value in ("success", "failed", "cancelled"):
                break
            import asyncio
            await asyncio.sleep(3)
            waited += 3
            db.expire_all()

        record = db.query(ExecutionRecord).filter(ExecutionRecord.id == execution_id).first()
        duration = round(time.time() - start, 2)

        if record:
            log.info(f"[MCP execute_test] 资产执行完成 | asset_id={asset_id}, exec_id={execution_id}, duration={duration}s")
            return {
                "status": record.status.value if record.status else "unknown",
                "mode": "asset",
                "asset_id": asset_id,
                "execution_id": execution_id,
                "passed": record.success_count or 0,
                "failed": record.failed_count or 0,
                "total": (record.success_count or 0) + (record.failed_count or 0),
                "duration": record.duration or duration,
                "error_message": record.error_message or "",
            }
        else:
            return {"status": "error", "error": "执行记录未找到", "duration": duration}
    finally:
        db.close()
