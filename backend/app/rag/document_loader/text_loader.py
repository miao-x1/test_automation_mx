"""纯文本和URL加载器"""
import logging
import httpx
from app.rag.document_loader.base import BaseDocumentLoader
from app.rag.models import LoadedDocument, DocumentType

logger = logging.getLogger(__name__)

class TextLoader(BaseDocumentLoader):
    def __init__(self):
        super().__init__()
        self.supported_types = [DocumentType.TEXT, DocumentType.DB_SCHEMA, DocumentType.OCR_TEXT, DocumentType.REQUIREMENT, DocumentType.DESIGN]
    
    def can_handle(self, file_path: str, mime_type: str = "") -> bool:
        ext = file_path.lower().split('.')[-1] if '.' in file_path else ''
        return ext in ('txt', 'sql', 'text') or file_path.startswith('http')
    
    async def load(self, file_path: str, **kwargs) -> LoadedDocument:
        source_type = kwargs.get('source_type', DocumentType.TEXT)
        if file_path.startswith('http'):
            # 从 URL 加载
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(file_path)
                resp.raise_for_status()
                content = resp.text
            file_name = file_path.split('/')[-1] or "url_content"
        else:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            file_name = file_path.split('/')[-1].split('\\')[-1]
        return LoadedDocument(
            source_type=source_type,
            file_path=file_path,
            file_name=file_name,
            content=content,
            metadata={"char_count": len(content)},
        )
