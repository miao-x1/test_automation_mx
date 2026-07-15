"""文档解析器基类"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from app.rag.models import LoadedDocument, DocumentType


class BaseDocumentLoader(ABC):
    """文档解析器基类"""
    
    def __init__(self):
        self.supported_types: List[DocumentType] = []
    
    @abstractmethod
    async def load(self, file_path: str, **kwargs) -> LoadedDocument:
        """解析文档"""
        pass
    
    @abstractmethod
    def can_handle(self, file_path: str, mime_type: str = "") -> bool:
        """判断是否能处理此文件"""
        pass
    
    def _detect_type(self, file_path: str) -> DocumentType:
        """根据文件扩展名推断类型"""
        ext = file_path.lower().split('.')[-1] if '.' in file_path else ''
        ext_map = {
            'pdf': DocumentType.PDF,
            'doc': DocumentType.WORD, 'docx': DocumentType.WORD,
            'xls': DocumentType.EXCEL, 'xlsx': DocumentType.EXCEL,
            'md': DocumentType.MARKDOWN, 'markdown': DocumentType.MARKDOWN,
            'json': DocumentType.SWAGGER,  # 可能是Swagger
            'txt': DocumentType.TEXT,
            'png': DocumentType.SCREENSHOT, 'jpg': DocumentType.SCREENSHOT,
            'jpeg': DocumentType.SCREENSHOT, 'webp': DocumentType.SCREENSHOT,
            'csv': DocumentType.EXCEL,
        }
        return ext_map.get(ext, DocumentType.UNKNOWN)
