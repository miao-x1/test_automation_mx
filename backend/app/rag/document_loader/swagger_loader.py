"""Swagger/OpenAPI 文档解析器"""
import json
import logging
import yaml
from app.rag.document_loader.base import BaseDocumentLoader
from app.rag.models import LoadedDocument, DocumentType

logger = logging.getLogger(__name__)

class SwaggerLoader(BaseDocumentLoader):
    def __init__(self):
        super().__init__()
        self.supported_types = [DocumentType.SWAGGER, DocumentType.API_DOC]
    
    def can_handle(self, file_path: str, mime_type: str = "") -> bool:
        ext = file_path.lower().split('.')[-1]
        return ext in ('json', 'yaml', 'yml')
    
    async def load(self, file_path: str, **kwargs) -> LoadedDocument:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # 解析 JSON 或 YAML
        try:
            spec = json.loads(content)
        except json.JSONDecodeError:
            try:
                spec = yaml.safe_load(content)
            except Exception:
                spec = {}
        # 判断是否是 Swagger/OpenAPI
        if 'swagger' not in spec and 'openapi' not in spec:
            # 不是 Swagger，当作普通文本
            return LoadedDocument(
                source_type=DocumentType.JSON if file_path.endswith('.json') else DocumentType.TEXT,
                file_path=file_path,
                file_name=file_path.split('/')[-1].split('\\')[-1],
                content=content,
                metadata={"is_swagger": False},
            )
        # 提取 API 端点
        content_parts = []
        sections = []
        paths = spec.get('paths', {})
        info = spec.get('info', {})
        title = info.get('title', 'Unknown API')
        version = info.get('version', '')
        content_parts.append(f"# {title} (v{version})")
        for path, methods in paths.items():
            for method, details in methods.items():
                if method.upper() not in ('GET', 'POST', 'PUT', 'DELETE', 'PATCH'):
                    continue
                summary = details.get('summary', '')
                description = details.get('description', '')
                parameters = details.get('parameters', [])
                responses = details.get('responses', {})
                section_content = f"## {method.upper()} {path}\n"
                if summary:
                    section_content += f"摘要: {summary}\n"
                if description:
                    section_content += f"描述: {description}\n"
                if parameters:
                    section_content += "参数:\n"
                    for param in parameters:
                        section_content += f"  - {param.get('name', '')} ({param.get('in', '')}, {'必填' if param.get('required') else '可选'}): {param.get('description', '')}\n"
                if responses:
                    section_content += "响应:\n"
                    for code, resp in responses.items():
                        section_content += f"  - {code}: {resp.get('description', '')}\n"
                content_parts.append(section_content)
                sections.append({
                    "title": f"{method.upper()} {path}",
                    "content": section_content,
                    "level": 2,
                })
        return LoadedDocument(
            source_type=DocumentType.SWAGGER,
            file_path=file_path,
            file_name=file_path.split('/')[-1].split('\\')[-1],
            content="\n\n".join(content_parts),
            sections=sections,
            metadata={
                "is_swagger": True,
                "api_count": len(paths),
                "title": title,
                "version": version,
            },
        )
