"""Postman Collection 解析器"""
import json
import logging
from app.rag.document_loader.base import BaseDocumentLoader
from app.rag.models import LoadedDocument, DocumentType

logger = logging.getLogger(__name__)

class PostmanLoader(BaseDocumentLoader):
    def __init__(self):
        super().__init__()
        self.supported_types = [DocumentType.POSTMAN, DocumentType.API_DOC]
    
    def can_handle(self, file_path: str, mime_type: str = "") -> bool:
        return file_path.lower().endswith('.postman_collection.json') or 'postman' in file_path.lower()
    
    async def load(self, file_path: str, **kwargs) -> LoadedDocument:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        content_parts = []
        sections = []
        def process_item(item, parent_name=""):
            name = item.get('name', '')
            full_name = f"{parent_name} > {name}" if parent_name else name
            request = item.get('request', {})
            if request:
                method = request.get('method', 'GET')
                url = request.get('url', {})
                if isinstance(url, dict):
                    url_str = '/'.join(url.get('path', []))
                else:
                    url_str = str(url)
                description = request.get('description', '')
                headers = request.get('header', [])
                body = request.get('body', {})
                section_content = f"## {method} {url_str}\n"
                section_content += f"名称: {full_name}\n"
                if description:
                    section_content += f"描述: {description}\n"
                if headers:
                    section_content += "Headers:\n"
                    for h in headers:
                        section_content += f"  - {h.get('key', '')}: {h.get('value', '')}\n"
                if body and body.get('raw'):
                    section_content += f"Body: {body['raw'][:500]}\n"
                content_parts.append(section_content)
                sections.append({"title": f"{method} {url_str}", "content": section_content, "level": 2})
            # 递归处理子项
            for child in item.get('item', []):
                process_item(child, full_name)
        for item in data.get('item', []):
            process_item(item)
        return LoadedDocument(
            source_type=DocumentType.POSTMAN,
            file_path=file_path,
            file_name=file_path.split('/')[-1].split('\\')[-1],
            content="\n\n".join(content_parts),
            sections=sections,
            metadata={"collection_name": data.get('info', {}).get('name', ''), "request_count": len(sections)},
        )
