"""SwaggerParserAgent - Swagger/OpenAPI文档解析Agent

将Swagger/OpenAPI文档解析为统一的RequirementContext。
直接解析JSON/YAML提取API端点，LLM分析生成测试要点。
"""
import json
import logging
from typing import Any, Dict, List

from autogen_core import message_handler, MessageContext, default_subscription

from app.runtime.base_agent import BaseRoutedAgent
from app.runtime.messages import AgentRequest, AgentResponse
from app.agent.requirement.requirement_context import (
    RequirementContext, PageInfo, ElementInfo, BusinessFlow, TestPoint, Constraint,
)
from app.core.logger import log

logger = logging.getLogger(__name__)

# 合法的HTTP方法
_HTTP_METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH")


@default_subscription
class SwaggerParserAgent(BaseRoutedAgent):
    """Swagger/OpenAPI文档解析Agent - 将API文档解析为RequirementContext"""

    def __init__(self) -> None:
        super().__init__(
            description="Swagger/OpenAPI文档解析Agent，提取API端点和测试要点",
            display_name="SwaggerParserAgent",
            capabilities=["swagger_parse", "api_parse", "requirement_parse"],
        )

    async def execute(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """解析Swagger/OpenAPI文档"""
        swagger_content = payload.get("swagger_content", "")
        file_path = payload.get("file_path", "")
        requirement = payload.get("requirement", "")
        task_id = payload.get("task_id", "")
        session_key = payload.get("session_key", "default")

        log.info(f"[SwaggerParserAgent] 开始解析Swagger: file={file_path or 'inline'}")

        # 若未提供内容但有文件路径，尝试从文件读取
        if not swagger_content and file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    swagger_content = f.read()
            except Exception as e:
                log.error(f"[SwaggerParserAgent] 读取文件失败: {e}")
                return {"status": "error", "error": f"读取Swagger文件失败: {e}"}

        if not swagger_content:
            return {"status": "error", "error": "未提供Swagger内容(swagger_content)或文件路径(file_path)"}

        # Step 1: 解析Swagger内容
        spec: Dict[str, Any] = {}
        try:
            spec = self._parse_spec(swagger_content)
        except Exception as e:
            log.error(f"[SwaggerParserAgent] Swagger解析失败: {e}")
            return {"status": "error", "error": f"Swagger解析失败: {e}"}

        info = spec.get("info", {}) or {}
        title = info.get("title", "Unknown API")
        version = info.get("version", "")
        paths = spec.get("paths", {}) or {}

        # Step 2: 提取API端点
        apis: List[Dict[str, Any]] = []
        for path, methods in paths.items():
            if not isinstance(methods, dict):
                continue
            for method, details in methods.items():
                if method.upper() not in _HTTP_METHODS:
                    continue
                details = details or {}
                parameters = details.get("parameters", []) or []
                responses = details.get("responses", {}) or {}

                api_info: Dict[str, Any] = {
                    "path": path,
                    "method": method.upper(),
                    "summary": details.get("summary", ""),
                    "description": details.get("description", ""),
                    "tags": details.get("tags", []),
                    "parameters": [
                        {
                            "name": p.get("name", ""),
                            "in": p.get("in", "query"),
                            "type": (p.get("schema", {}) or {}).get("type", p.get("type", "string")),
                            "required": p.get("required", False),
                            "description": p.get("description", ""),
                        }
                        for p in parameters if isinstance(p, dict)
                    ],
                    "request_schema": details.get("requestBody", {}),
                    "responses": {
                        code: (resp.get("description", "") if isinstance(resp, dict) else str(resp))
                        for code, resp in responses.items()
                    },
                }
                apis.append(api_info)

        log.info(f"[SwaggerParserAgent] 提取API端点: {len(apis)} 个")

        # Step 3: LLM分析生成测试要点
        apis_text = json.dumps(apis, ensure_ascii=False, default=str)
        if len(apis_text) > 8000:
            apis_text = apis_text[:8000]

        system_prompt = (
            "你是API测试需求分析专家。请分析以下Swagger/OpenAPI提取的API端点，生成测试相关信息。\n"
            "重点关注：参数校验、边界值、错误响应、权限控制等测试场景。\n"
            "返回JSON格式，包含以下字段：\n"
            '{"pages": [{"url":"","title":"接口分组名","page_type":"dashboard","description":"接口描述","elements":[]}],\n'
            '"elements": [{"name":"参数名","element_type":"input","locator":"","text":"","action":"input","required":false}],\n'
            '{"business_flow": [{"flow_name":"流程名","steps":[{"action":"request","target":"METHOD /path","description":""}],"preconditions":[],"postconditions":[]}],\n'
            '"test_points": [{"name":"测试点名","description":"描述","category":"functional/boundary/error/security","priority":"high/medium/low","test_data":{}}],\n'
            '"constraints": [{"type":"business/technical/environmental","description":"约束描述","source":"swagger"}],\n'
            '"summary": "整体摘要","intent": "测试意图"}\n'
            "只返回JSON，不要其他内容。"
        )

        user_prompt = f"API标题: {title} (v{version})\n\nAPI端点:\n{apis_text}"
        if requirement:
            user_prompt = f"附加需求: {requirement}\n\n{user_prompt}"

        try:
            llm_response = await self.call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=4096,
                task_id=task_id,
                step="swagger_llm_analyze",
                session_key=session_key,
            )
            parsed = self._parse_llm_json(llm_response)
        except Exception as e:
            log.error(f"[SwaggerParserAgent] LLM分析失败: {e}")
            parsed = {
                "summary": f"Swagger API: {title}",
                "intent": "api_test",
            }

        # Step 4: 构建RequirementContext
        source_files = [file_path] if file_path else []
        context = RequirementContext(
            task_id=task_id,
            session_key=session_key,
            source_types=["swagger"],
            source_files=source_files,
            raw_requirement=apis_text[:4000],
            summary=parsed.get("summary", f"Swagger API: {title} (v{version})"),
            intent=parsed.get("intent", "api_test"),
            metadata={
                "api_title": title,
                "api_version": version,
                "api_count": len(apis),
                "apis": apis,
            },
        )

        # 填充pages
        for p in parsed.get("pages", []):
            context.pages.append(PageInfo(
                url=p.get("url", ""),
                title=p.get("title", ""),
                page_type=p.get("page_type", ""),
                description=p.get("description", ""),
                elements=p.get("elements", []),
            ))

        # 填充elements
        for e in parsed.get("elements", []):
            context.elements.append(ElementInfo(
                name=e.get("name", ""),
                element_type=e.get("element_type", ""),
                locator=e.get("locator", ""),
                text=e.get("text", ""),
                action=e.get("action", ""),
                required=e.get("required", False),
            ))

        # 填充business_flow
        for f in parsed.get("business_flow", []):
            context.business_flow.append(BusinessFlow(
                flow_name=f.get("flow_name", ""),
                steps=f.get("steps", []),
                preconditions=f.get("preconditions", []),
                postconditions=f.get("postconditions", []),
            ))

        # 填充test_points
        for tp in parsed.get("test_points", []):
            context.test_points.append(TestPoint(
                name=tp.get("name", ""),
                description=tp.get("description", ""),
                category=tp.get("category", "functional"),
                priority=tp.get("priority", "medium"),
                test_data=tp.get("test_data", {}),
            ))

        # 填充constraints
        for c in parsed.get("constraints", []):
            context.constraints.append(Constraint(
                type=c.get("type", "business"),
                description=c.get("description", ""),
                source="swagger",
            ))

        log.info(
            f"[SwaggerParserAgent] 解析完成: "
            f"{len(context.test_points)} test_points, {len(context.business_flow)} flows, "
            f"{len(context.constraints)} constraints"
        )
        return {"status": "success", "context": context.to_dict()}

    def _parse_spec(self, content: str) -> Dict[str, Any]:
        """解析Swagger内容为dict（支持JSON/YAML）"""
        # 优先尝试JSON
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            pass
        # 降级为YAML
        try:
            import yaml
            return yaml.safe_load(content) or {}
        except ImportError:
            log.error("[SwaggerParserAgent] PyYAML not installed, 无法解析YAML")
            raise
        except Exception:
            raise

    def _parse_llm_json(self, raw: str) -> dict:
        """解析LLM返回的JSON"""
        if isinstance(raw, dict):
            return raw
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        try:
            return json.loads(raw)
        except Exception:
            return {"summary": str(raw)[:500]}
