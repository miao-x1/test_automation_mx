"""
TaskExecutor - 定时任务执行器

负责执行定时任务，支持重试逻辑
"""
import json
from datetime import datetime
from typing import Dict, Any, Optional
from app.core.logger import log
from app.models.requirement_task import RequirementStatus
from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability


class TaskExecutor(NewBaseAgent):
    """定时任务执行器"""

    agent_name = "task_executor"
    display_name = "Task Executor"
    description = "定时任务执行器 - 负责执行定时任务，支持重试逻辑"
    capabilities = [AgentCapability.SCHEDULE]

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)

    async def execute(self, task, run_log=None, db=None) -> Dict[str, Any]:
        """
        执行定时任务

        Note: task 可以是 dict 或 ORM 对象；run_log 和 db 参数保留用于向后兼容。

        Returns:
            {
                status: "success" | "failed" | "timeout",
                summary: str,
                error: str,
                task_id: int | None,
                retry_count: int,
            }
        """
        if not isinstance(task, dict):
            task = task.to_dict() if hasattr(task, "to_dict") else dict(task)

        config = {}
        task_config = task.get("task_config")
        if task_config:
            try:
                config = json.loads(task_config)
            except json.JSONDecodeError:
                config = {}

        requirement_text = config.get("requirement", "")
        target_url = config.get("target_url", "")
        script_format = config.get("script_format", "playwright")

        if not requirement_text:
            return {
                "status": "failed",
                "summary": "任务配置中无需求文本",
                "error": "task_config.requirement为空",
                "task_id": None,
                "retry_count": 0,
            }

        # 带重试的执行
        max_retries = task.get("max_retries") or 3
        retry_interval = task.get("retry_interval") or 60
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                result = await self._run_requirement_flow(
                    requirement=requirement_text,
                    target_url=target_url,
                    script_format=script_format,
                    user_id=task.get("user_id"),
                    timeout=task.get("timeout") or 3600,
                )

                if result.get("success"):
                    return {
                        "status": "success",
                        "summary": result.get("summary", "执行成功"),
                        "error": "",
                        "task_id": result.get("task_id"),
                        "retry_count": attempt,
                    }
                else:
                    last_error = result.get("error", "未知错误")
                    if attempt < max_retries:
                        import asyncio
                        await asyncio.sleep(min(retry_interval, 10))  # 限制等待时间
                        log.info(f"定时任务重试 | task_id={task.id}, attempt={attempt + 1}/{max_retries}")

            except Exception as e:
                last_error = str(e)
                if attempt < max_retries:
                    import asyncio
                    await asyncio.sleep(min(retry_interval, 10))

        return {
            "status": "failed",
            "summary": f"执行失败（重试{max_retries}次后）",
            "error": last_error or "未知错误",
            "task_id": None,
            "retry_count": max_retries,
        }

    async def _run_requirement_flow(
        self,
        requirement: str,
        target_url: str = "",
        script_format: str = "playwright",
        user_id: int = None,
        timeout: int = 3600,
    ) -> Dict[str, Any]:
        """
        执行需求驱动的测试流程

        创建RequirementTask → 触发分析 → 返回结果
        """
        from app.services.context_router.storage_router import get_storage_router

        storage = get_storage_router()
        try:
            # 创建需求任务（通过 StorageRouter）
            image_paths = json.dumps([target_url], ensure_ascii=False) if target_url else None
            req_id = storage.mysql_save("RequirementTask", {
                "requirement": requirement,
                "status": RequirementStatus.PENDING,
                "user_id": user_id,
                "created_by": user_id,
                "image_paths": image_paths,
            })

            log.info(f"定时任务创建需求 | req_id={req_id}")

            # 触发分析流程（同步调用）
            from app.services.requirement_flow_service import RequirementFlowService

            task_id = None
            success = False
            summary = ""

            async for event_str in RequirementFlowService.generate(
                requirement=requirement,
                execute=False,
                additional_info=target_url or None,
                script_format=script_format,
            ):
                import json as _json
                try:
                    event = _json.loads(event_str)
                    step = event.get("step", "")

                    if step == "任务完成" and event.get("data", {}).get("task_id"):
                        task_id = event["data"]["task_id"]
                        success = True
                        summary = f"任务#{task_id}创建成功"
                    elif step == "任务失败":
                        success = False
                        summary = event.get("message", "任务失败")
                except Exception:
                    pass

            return {
                "success": success,
                "summary": summary,
                "task_id": task_id,
                "error": "" if success else summary,
            }

        except Exception as e:
            log.error(f"定时任务执行需求流程异常: {e}", exc_info=True)
            return {
                "success": False,
                "summary": f"执行异常: {str(e)[:100]}",
                "task_id": None,
                "error": str(e),
            }
