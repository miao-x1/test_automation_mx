"""固定大小分块器"""
from typing import List
from app.rag.chunker.base import BaseChunker
from app.rag.models import Chunk, ChunkStrategy, LoadedDocument


class FixedSizeChunker(BaseChunker):
    """按固定字符数分块，带重叠"""
    
    def __init__(self, chunk_size: int = 500, overlap: int = 50):
        super().__init__(ChunkStrategy.FIXED_SIZE)
        self.chunk_size = chunk_size
        self.overlap = overlap
    
    def chunk(self, document: LoadedDocument) -> List[Chunk]:
        text = document.content
        if not text:
            return []
        source_id = document.source_id or document.file_name
        chunks = []
        index = 0
        start = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            chunk_text = text[start:end]
            if chunk_text.strip():
                chunks.append(self._create_chunk(
                    text=chunk_text,
                    source_id=source_id,
                    index=index,
                    start=start,
                    end=end,
                    chunk_type="content",
                    metadata={"strategy": "fixed_size", "chunk_size": self.chunk_size, "overlap": self.overlap},
                ))
                index += 1
            start = end - self.overlap if end - self.overlap > start else end
        return chunks
