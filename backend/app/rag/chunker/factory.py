"""分块器工厂"""
from typing import Optional
from app.rag.chunker.base import BaseChunker
from app.rag.chunker.fixed_size_chunker import FixedSizeChunker
from app.rag.chunker.recursive_chunker import RecursiveChunker
from app.rag.chunker.markdown_chunker import MarkdownChunker
from app.rag.models import ChunkStrategy, LoadedDocument, DocumentType


class ChunkerFactory:
    """分块器工厂"""
    
    def __init__(self):
        self._chunkers = {
            ChunkStrategy.FIXED_SIZE: FixedSizeChunker(),
            ChunkStrategy.RECURSIVE: RecursiveChunker(),
            ChunkStrategy.MARKDOWN_HEADER: MarkdownChunker(),
        }
        self._default_strategy = ChunkStrategy.RECURSIVE
    
    def get_chunker(self, strategy: ChunkStrategy = None) -> BaseChunker:
        """获取分块器"""
        if strategy and strategy in self._chunkers:
            return self._chunkers[strategy]
        return self._chunkers[self._default_strategy]
    
    def chunk_document(self, document: LoadedDocument, strategy: ChunkStrategy = None) -> list:
        """自动选择分块器并分块"""
        if strategy is None:
            # 自动选择策略
            if document.source_type in (DocumentType.MARKDOWN, DocumentType.TEXT):
                strategy = ChunkStrategy.MARKDOWN_HEADER
            elif document.source_type in (DocumentType.SWAGGER, DocumentType.POSTMAN, DocumentType.API_DOC):
                strategy = ChunkStrategy.MARKDOWN_HEADER  # 这些文档有分节
            else:
                strategy = ChunkStrategy.RECURSIVE
        chunker = self.get_chunker(strategy)
        return chunker.chunk(document)
    
    def register_chunker(self, strategy: ChunkStrategy, chunker: BaseChunker):
        """注册自定义分块器"""
        self._chunkers[strategy] = chunker


_chunker_factory: Optional[ChunkerFactory] = None

def get_chunker_factory() -> ChunkerFactory:
    global _chunker_factory
    if _chunker_factory is None:
        _chunker_factory = ChunkerFactory()
    return _chunker_factory
