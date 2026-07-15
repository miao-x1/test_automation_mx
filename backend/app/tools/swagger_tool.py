"""Swagger 工具 - 接口文档解析"""
import json
import logging
from typing import Any, Dict, List
from app.tools.base import BaseTool, ToolResult, ToolContext

logger = logging.getLogger(__name__)


class SwaggerParseTool(BaseTool):
    """Swagger/OpenAPI 解析工具

    解析 Swagger/OpenAPI 文档，提取接口信息。
    """

    def __init__(self):
        super().__init__(name="swagger_parse", description="解析Swagger/OpenAPI文档，提取接口信息")

    async def execute(self, ctx: ToolContext, **kwargs) -> ToolResult:
        file_path = kwargs.get("file_path", "")
        content = kwargs.get("content", "")
        source_type = kwargs.get("source_type", "swagger")

        if not file_path and not content:
            return ToolResult(success=False, error="file_path或content不能为空")

        try:
            if file_path:
                with open(file_path, "r", encoding="utf-8") as f:
                    raw = f.read()
            else:
                raw = content

            # 解析 JSON 或 YAML
            try:
                spec = json.loads(raw)
            except json.JSONDecodeError:
                try:
                    import yaml
                    spec = yaml.safe_load(raw)
                except Exception:
                    return ToolResult(success=False, error="无法解析为JSON或YAML")

            # 判断是否是 Swagger/OpenAPI
            if "swagger" not in spec and "openapi" not in spec:
                return ToolResult(success=False, error="不是有效的Swagger/OpenAPI文档")

            # 提取接口
            apis = []
            paths = spec.get("paths", {})
            for path, methods in paths.items():
                for method, details in methods.items():
                    if method.upper() not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                        continue

                    # 提取参数
                    parameters = []
                    for p in details.get("parameters", []):
                        parameters.append({
                            "name": p.get("name", ""),
                            "in": p.get("in", ""),
                            "required": p.get("required", False),
                            "type": p.get("schema", {}).get("type", ""),
                            "description": p.get("description", ""),
                        })

                    # 提取请求体
                    request_body = details.get("requestBody", {})
                    body_content = request_body.get("content", {})
                    body_schema = {}
                    body_example = {}
                    if "application/json" in body_content:
                        schema = body_content["application/json"].get("schema", {})
                        body_schema = schema
                        body_example = body_content["application/json"].get("example", {})

                    # 提取响应
                    responses = []
                    for code, resp in details.get("responses", {}).items():
                        responses.append({
                            "code": code,
                            "description": resp.get("description", ""),
                        })

                    # 提取认证
                    security = details.get("security", [])

                    apis.append({
                        "method": method.upper(),
                        "path": path,
                        "summary": details.get("summary", ""),
                        "description": details.get("description", ""),
                        "tags": details.get("tags", []),
                        "parameters": parameters,
                        "request_body_schema": body_schema,
                        "request_body_example": body_example,
                        "responses": responses,
                        "security": security,
                    })

            return ToolResult(
                success=True,
                data={
                    "title": spec.get("info", {}).get("title", ""),
                    "version": spec.get("info", {}).get("version", ""),
                    "apis": apis,
                    "total_apis": len(apis),
                },
                metadata={"source_type": source_type},
            )

        except Exception as e:
            logger.error(f"[SwaggerParseTool] 解析失败: {e}")
            return ToolResult(success=False, error=str(e))
