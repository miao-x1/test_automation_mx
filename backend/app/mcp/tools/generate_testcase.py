"""
generate_testcase - 生成测试用例工具

根据需求文本自动生成测试用例。

流程：
  需求文本 → 需求解析 → 测试点分析 → 用例生成 → 用例审核

调用后端 TaskRuntime 管道：
  requirement_analysis_agent → test_point_analysis_agent
  → testcase_generator_agent → testcase_review_agent
"""
import json
import time
from typing import Any, Dict

from app.core.logger import log

TOOL_NAME = "generate_testcase"
TOOL_DESCRIPTION = """生成测试用例工具。根据需求文本自动生成结构化测试用例。

流程：需求解析 → 测试点分析 → 用例生成 → 用例审核（RAG增强）。

输入需求文本，系统自动：
1. 解析需求，提取测试意图和场景
2. 生成测试点（功能/边界/异常/安全等分类）
3. 为每个测试点生成详细测试用例（含前置条件、步骤、预期结果）
4. AI审核用例质量并打分

返回：测试点列表、测试用例列表（含步骤、预期结果、优先级）、用例审核结果。"""

TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "requirement": {
            "type": "string",
            "description": "测试需求描述。如：测试电商系统的用户注册登录流程，包括手机号注册、密码登录、第三方登录等场景",
        },
        "source_type": {
            "type": "string",
            "enum": ["text", "image", "pdf", "word", "api_doc", "db_schema"],
            "description": "需求来源类型，默认text",
        },
        "document_context": {
            "type": "string",
            "description": "文档解析结果（当source_type非text时，提供文档解析后的文本内容）",
        },
        "image_description": {
            "type": "string",
            "description": "图片描述信息（当source_type为image时）",
        },
        "priority_filter": {
            "type": "string",
            "enum": ["all", "high", "medium", "low"],
            "description": "用例优先级过滤，默认all返回全部",
        },
    },
    "required": ["requirement"],
}


async def execute(**kwargs) -> Dict[str, Any]:
    """
    生成测试用例

    Args:
        requirement: 需求文本
        source_type: 来源类型
        document_context: 文档解析结果
        image_description: 图片描述
        priority_filter: 优先级过滤

    Returns:
        {
            "status": "success" | "error",
            "session_id": str,
            "task_id": str,
            "requirement_id": int,
            "total_points": int,
            "total_cases": int,
            "avg_score": float,
            "test_points": [...],
            "test_cases": [...],
            "duration": float,
        }
    """
    start = time.time()

    requirement = kwargs.get("requirement", "")
    if not requirement:
        return {"status": "error", "error": "requirement 参数为必填"}

    source_type = kwargs.get("source_type", "text")
    document_context = kwargs.get("document_context", "")
    image_description = kwargs.get("image_description", "")
    priority_filter = kwargs.get("priority_filter", "all")

    log.info(f"[MCP generate_testcase] 开始 | requirement={requirement[:50]}...")

    try:
        from app.runtime import get_task_runtime

        task_runtime = get_task_runtime()

        # 构建管道步骤（与 testcase_generation API 一致）
        steps = [
            {
                "agent_type": "requirement_analysis_agent",
                "action": "execute",
                "payload": {"requirement": requirement},
                "output_key": "requirement_analysis",
            },
            {
                "agent_type": "test_point_analysis_agent",
                "action": "execute",
                "input_keys": ["requirement_analysis"],
                "output_key": "test_points",
            },
            {
                "agent_type": "testcase_generator_agent",
                "action": "execute",
                "input_keys": ["requirement_analysis", "test_points"],
                "output_key": "test_cases",
            },
            {
                "agent_type": "testcase_review_agent",
                "action": "execute",
                "input_keys": ["test_cases"],
                "output_key": "reviews",
            },
        ]

        result = await task_runtime.execute_pipeline(
            steps=steps,
            timeout=600,
        )

        duration = round(time.time() - start, 2)

        if result.get("status") in ("completed", "success"):
            context = result.get("context", {})

            # 提取测试点
            test_points = context.get("test_points", [])
            # 提取测试用例
            test_cases = context.get("test_cases", [])
            # 提取审核结果
            reviews = context.get("reviews", [])

            # 优先级过滤
            if priority_filter != "all" and test_cases:
                test_cases = [c for c in test_cases if c.get("priority", "").lower() == priority_filter]

            # 计算平均分
            avg_score = 0.0
            if reviews:
                scores = [r.get("score", 0) for r in reviews if isinstance(r, dict)]
                avg_score = round(sum(scores) / len(scores), 2) if scores else 0.0

            log.info(
                f"[MCP generate_testcase] 完成 | "
                f"points={len(test_points)}, cases={len(test_cases)}, "
                f"avg_score={avg_score}, duration={duration}s"
            )

            return {
                "status": "success",
                "session_id": result.get("session_id", ""),
                "total_points": len(test_points),
                "total_cases": len(test_cases),
                "avg_score": avg_score,
                "test_points": test_points[:20],   # 限制返回数量
                "test_cases": test_cases[:50],
                "reviews_count": len(reviews),
                "duration": duration,
            }
        else:
            error = result.get("error", "管道执行失败")
            log.error(f"[MCP generate_testcase] 失败 | error={error}")
            return {
                "status": "error",
                "error": error,
                "duration": duration,
            }

    except Exception as e:
        log.error(f"[MCP generate_testcase] 异常: {e}", exc_info=True)
        return {"status": "error", "error": str(e), "duration": round(time.time() - start, 2)}
