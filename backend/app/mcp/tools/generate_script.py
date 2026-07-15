"""
generate_script - 生成测试脚本工具

根据需求文本自动生成可执行的测试脚本。

流程：
  需求 → 类型识别 → 需求解析 → 用例生成 → 脚本生成

支持4种测试类型：
  WEB       → Playwright 脚本
  API       → Pytest + Requests 脚本
  ANDROID   → Appium 脚本
  PERFORMANCE → JMeter 脚本

调用后端 TaskRuntime 管道（根据类型自动选择工作流）。
"""
import json
import time
from typing import Any, Dict

from app.core.logger import log

TOOL_NAME = "generate_script"
TOOL_DESCRIPTION = """生成测试脚本工具。根据需求文本自动生成可执行的测试脚本。

流程：类型识别 → 需求解析 → 用例生成 → 脚本生成。

系统自动识别测试类型并选择对应框架：
- WEB测试 → Playwright 脚本（页面操作、断言）
- API测试 → Pytest + Requests 脚本（接口请求、响应校验）
- ANDROID测试 → Appium 脚本（移动端操作）
- 性能测试 → JMeter 脚本（并发压测）

返回：生成的脚本内容、脚本格式、任务ID、执行步骤。"""

TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "requirement": {
            "type": "string",
            "description": "测试需求描述。如：测试用户登录功能，包括正确密码登录、错误密码提示、空密码验证等场景",
        },
        "test_type": {
            "type": "string",
            "enum": ["web", "api", "android", "performance"],
            "description": "测试类型（可选，留空自动识别）",
        },
        "script_format": {
            "type": "string",
            "enum": ["playwright", "midscene", "yaml", "pytest", "appium", "jmeter"],
            "description": "脚本格式，默认根据测试类型自动选择",
        },
        "additional_info": {
            "type": "string",
            "description": "附加信息（URL/Swagger地址/APK路径等）",
        },
        "execute": {
            "type": "boolean",
            "description": "生成后是否立即执行，默认false",
        },
    },
    "required": ["requirement"],
}


async def execute(**kwargs) -> Dict[str, Any]:
    """
    生成测试脚本

    Args:
        requirement: 需求文本
        test_type: 测试类型 (web/api/android/performance)
        script_format: 脚本格式
        additional_info: 附加信息
        execute: 是否立即执行

    Returns:
        {
            "status": "success" | "error",
            "session_id": str,
            "task_id": str,
            "test_type": str,
            "framework": str,
            "script": str,
            "script_format": str,
            "steps": [...],
            "duration": float,
        }
    """
    start = time.time()

    requirement = kwargs.get("requirement", "")
    if not requirement:
        return {"status": "error", "error": "requirement 参数为必填"}

    test_type = kwargs.get("test_type", "")
    script_format = kwargs.get("script_format", "")
    additional_info = kwargs.get("additional_info", "")
    do_execute = kwargs.get("execute", False)

    log.info(f"[MCP generate_script] 开始 | requirement={requirement[:50]}..., type={test_type}")

    try:
        from app.runtime import get_task_runtime
        from app.agent.requirement.test_type_classifier_agent import TestTypeClassifierAgent

        task_runtime = get_task_runtime()

        # Step 1: 自动识别测试类型（如果未指定）
        framework = ""
        platform = ""
        confidence = 0.0
        if not test_type:
            classifier = TestTypeClassifierAgent()
            classify_result = await classifier.execute(requirement=requirement)
            test_type = classify_result.get("test_type", "web")
            framework = classify_result.get("framework", "playwright")
            platform = classify_result.get("platform", "browser")
            confidence = classify_result.get("confidence", 0.5)
            log.info(f"[MCP generate_script] 自动识别 | type={test_type}, framework={framework}, conf={confidence}")
        else:
            # 根据指定类型映射框架
            TYPE_FRAMEWORK = {
                "web": "playwright",
                "api": "pytest",
                "android": "appium",
                "performance": "jmeter",
            }
            framework = script_format or TYPE_FRAMEWORK.get(test_type, "playwright")

        # Step 2: 构建管道步骤
        # test_type → workflow_name 映射
        TYPE_WORKFLOW = {
            "web": "web_test",
            "api": "api_test",
            "android": "android_test",
            "performance": "performance_test",
        }
        workflow_name = TYPE_WORKFLOW.get(test_type, "web_test")

        # 使用 agent_runtime 的 build_pipeline_steps
        from app.api.agent_runtime import build_pipeline_steps

        # 合并需求文本
        full_requirement = requirement
        if additional_info:
            full_requirement = f"{requirement}\n附加信息: {additional_info}"

        steps = build_pipeline_steps(workflow_name, full_requirement)

        # 如果不执行，去掉执行步骤
        if not do_execute:
            steps = [s for s in steps if s.get("output_key") != "execution_result"]

        # Step 3: 执行管道
        result = await task_runtime.execute_pipeline(
            steps=steps,
            timeout=600,
        )

        duration = round(time.time() - start, 2)

        if result.get("status") in ("completed", "success"):
            context = result.get("context", {})

            # 提取脚本
            script_content = ""
            if "test_script" in context:
                script_data = context["test_script"]
                if isinstance(script_data, dict):
                    script_content = script_data.get("script", script_data.get("content", ""))
                else:
                    script_content = str(script_data)
            elif "test_cases" in context:
                # 如果没有脚本但有用例，返回用例信息
                script_content = json.dumps(context["test_cases"], ensure_ascii=False, indent=2)

            # 提取执行结果（如果执行了）
            execution_result = context.get("execution_result", {})

            log.info(
                f"[MCP generate_script] 完成 | "
                f"type={test_type}, framework={framework}, "
                f"script_len={len(script_content)}, duration={duration}s"
            )

            return {
                "status": "success",
                "session_id": result.get("session_id", ""),
                "test_type": test_type,
                "framework": framework,
                "platform": platform,
                "confidence": round(confidence, 2),
                "script": script_content,
                "script_format": framework,
                "script_length": len(script_content),
                "executed": do_execute,
                "execution_result": execution_result if do_execute else None,
                "steps": [
                    {"agent": s.get("agent_type", ""), "action": s.get("action", ""), "output_key": s.get("output_key", "")}
                    for s in steps
                ],
                "duration": duration,
            }
        else:
            error = result.get("error", "管道执行失败")
            log.error(f"[MCP generate_script] 失败 | error={error}")
            return {
                "status": "error",
                "error": error,
                "test_type": test_type,
                "framework": framework,
                "duration": duration,
            }

    except Exception as e:
        log.error(f"[MCP generate_script] 异常: {e}", exc_info=True)
        return {"status": "error", "error": str(e), "duration": round(time.time() - start, 2)}
