"""图片/截图加载器"""
import os
import logging
from app.rag.document_loader.base import BaseDocumentLoader
from app.rag.models import LoadedDocument, DocumentType

logger = logging.getLogger(__name__)

class ImageLoader(BaseDocumentLoader):
    def __init__(self):
        super().__init__()
        self.supported_types = [DocumentType.SCREENSHOT]
    
    def can_handle(self, file_path: str, mime_type: str = "") -> bool:
        ext = file_path.lower().split('.')[-1] if '.' in file_path else ''
        return ext in ('png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp') or 'image' in mime_type.lower()
    
    async def load(self, file_path: str, **kwargs) -> LoadedDocument:
        file_name = file_path.split('/')[-1].split('\\')[-1]
        file_size = os.path.getsize(file_path)
        # OCR 实际需要外部服务（PaddleOCR/Tesseract）
        # 这里只记录元数据，OCR 文本作为输入
        ocr_text = kwargs.get('ocr_text', '')
        return LoadedDocument(
            source_type=DocumentType.SCREENSHOT,
            file_path=file_path,
            file_name=file_name,
            file_size=file_size,
            content=ocr_text,
            metadata={
                "has_ocr_text": bool(ocr_text),
                "image_size": file_size,
                "needs_ocr": not bool(ocr_text),
            },
        )
