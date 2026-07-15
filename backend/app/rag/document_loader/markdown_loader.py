"""Markdown 文档解析器"""
import re
import logging
from app.rag.document_loader.base import BaseDocumentLoader
from app.rag.models import LoadedDocument, DocumentType

logger = logging.getLogger(__name__)

class MarkdownLoader(BaseDocumentLoader):
    def __init__(self):
        super().__init__()
        self.supported_types = [DocumentType.MARKDOWN, DocumentType.TEXT]
    
    def can_handle(self, file_path: str, mime_type: str = "") -> bool:
        ext = file_path.lower().split('.')[-1]
        return ext in ('md', 'markdown', 'txt') or 'text' in mime_type.lower()
    
    async def load(self, file_path: str, **kwargs) -> LoadedDocument:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # 按标题分节
        sections = []
        current_section = {"title": "Root", "content": "", "level": 0}
        for line in content.split('\n'):
            header_match = re.match(r'^(#{1,6})\s+(.+)', line)
            if header_match:
                if current_section["content"].strip():
                    sections.append(current_section)
                current_section = {
                    "title": header_match.group(2),
                    "content": line + '\n',
                    "level": len(header_match.group(1)),
                }
            else:
                current_section["content"] += line + '\n'
        if current_section["content"].strip():
            sections.append(current_section)
        ext = file_path.lower().split('.')[-1]
        doc_type = DocumentType.MARKDOWN if ext in ('md', 'markdown') else DocumentType.TEXT
        return LoadedDocument(
            source_type=doc_type,
            file_path=file_path,
            file_name=file_path.split('/')[-1].split('\\')[-1],
            content=content,
            sections=sections,
            metadata={"section_count": len(sections)},
        )
