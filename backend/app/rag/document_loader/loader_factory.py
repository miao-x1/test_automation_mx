"""文档加载器工厂 - 统一入口"""
import logging
from typing import List, Optional
from app.rag.document_loader.base import BaseDocumentLoader
from app.rag.document_loader.pdf_loader import PDFLoader
from app.rag.document_loader.word_loader import WordLoader
from app.rag.document_loader.excel_loader import ExcelLoader
from app.rag.document_loader.markdown_loader import MarkdownLoader
from app.rag.document_loader.swagger_loader import SwaggerLoader
from app.rag.document_loader.postman_loader import PostmanLoader
from app.rag.document_loader.text_loader import TextLoader
from app.rag.document_loader.image_loader import ImageLoader
from app.rag.models import LoadedDocument, DocumentType

logger = logging.getLogger(__name__)


class DocumentLoaderFactory:
    """文档加载器工厂"""
    
    def __init__(self):
        self._loaders: List[BaseDocumentLoader] = [
            PostmanLoader(),    # 先检查 Postman
            SwaggerLoader(),    # 再检查 Swagger
            PDFLoader(),
            WordLoader(),
            ExcelLoader(),
            MarkdownLoader(),
            ImageLoader(),
            TextLoader(),       # 兜底
        ]
    
    def register_loader(self, loader: BaseDocumentLoader, priority: int = -1):
        """注册自定义加载器"""
        if priority >= 0:
            self._loaders.insert(priority, loader)
        else:
            self._loaders.append(loader)
    
    async def load(self, file_path: str, mime_type: str = "", **kwargs) -> LoadedDocument:
        """自动选择加载器并解析文档"""
        # 找到合适的加载器
        for loader in self._loaders:
            if loader.can_handle(file_path, mime_type):
                logger.info(f"[LoaderFactory] Using {loader.__class__.__name__} for {file_path}")
                try:
                    doc = await loader.load(file_path, **kwargs)
                    if not doc.file_name:
                        doc.file_name = file_path.split('/')[-1].split('\\')[-1]
                    return doc
                except Exception as e:
                    logger.error(f"[LoaderFactory] {loader.__class__.__name__} failed: {e}")
                    continue
        # 兜底：当作纯文本处理
        logger.warning(f"[LoaderFactory] No loader found for {file_path}, using TextLoader")
        text_loader = TextLoader()
        return await text_loader.load(file_path, **kwargs)
    
    def get_supported_types(self) -> List[DocumentType]:
        """获取所有支持的文档类型"""
        types = set()
        for loader in self._loaders:
            types.update(loader.supported_types)
        return list(types)


# 单例
_loader_factory: Optional[DocumentLoaderFactory] = None

def get_loader_factory() -> DocumentLoaderFactory:
    global _loader_factory
    if _loader_factory is None:
        _loader_factory = DocumentLoaderFactory()
    return _loader_factory
