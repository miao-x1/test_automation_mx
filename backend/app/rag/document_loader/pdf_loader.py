"""PDF 文档解析器"""
import logging
from typing import List
import pdfplumber
from app.rag.document_loader.base import BaseDocumentLoader
from app.rag.models import LoadedDocument, DocumentType

logger = logging.getLogger(__name__)

class PDFLoader(BaseDocumentLoader):
    def __init__(self):
        super().__init__()
        self.supported_types = [DocumentType.PDF]
    
    def can_handle(self, file_path: str, mime_type: str = "") -> bool:
        return file_path.lower().endswith('.pdf') or 'pdf' in mime_type.lower()
    
    async def load(self, file_path: str, **kwargs) -> LoadedDocument:
        content_parts = []
        tables = []
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                if text:
                    content_parts.append(f"## Page {i+1}\n{text}")
                # 提取表格
                for table in page.extract_tables():
                    if table:
                        tables.append({"page": i+1, "data": table})
        content = "\n\n".join(content_parts)
        return LoadedDocument(
            source_type=DocumentType.PDF,
            file_path=file_path,
            file_name=file_path.split('/')[-1].split('\\')[-1],
            content=content,
            tables=tables,
            metadata={"page_count": len(pdf.pages) if 'pdf' in locals() else 0},
        )
