"""多格式文档解析器"""
from app.rag.document_loader.base import BaseDocumentLoader
from app.rag.document_loader.pdf_loader import PDFLoader
from app.rag.document_loader.word_loader import WordLoader
from app.rag.document_loader.excel_loader import ExcelLoader
from app.rag.document_loader.markdown_loader import MarkdownLoader
from app.rag.document_loader.swagger_loader import SwaggerLoader
from app.rag.document_loader.postman_loader import PostmanLoader
from app.rag.document_loader.text_loader import TextLoader
from app.rag.document_loader.image_loader import ImageLoader
from app.rag.document_loader.loader_factory import (
    DocumentLoaderFactory,
    get_loader_factory,
)

__all__ = [
    "BaseDocumentLoader",
    "PDFLoader",
    "WordLoader",
    "ExcelLoader",
    "MarkdownLoader",
    "SwaggerLoader",
    "PostmanLoader",
    "TextLoader",
    "ImageLoader",
    "DocumentLoaderFactory",
    "get_loader_factory",
]
