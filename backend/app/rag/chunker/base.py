"""分块器基类"""
import uuid
from abc import ABC, abstractmethod
from typing import List
from app.rag.models import Chunk, ChunkStrategy, LoadedDocument


class BaseChunker(ABC):
    """文档分块器基类"""
    
    def __init__(self, strategy: ChunkStrategy = ChunkStrategy.RECURSIVE):
        self.strategy = strategy
    
    @abstractmethod
    def chunk(self, document: LoadedDocument) -> List[Chunk]:
        """将文档分块"""
        pass
    
    def _create_chunk(self, text: str, source_id: str, index: int, 
                      start: int, end: int, chunk_type: str = "content",
                      metadata: dict = None) -> Chunk:
        """创建 Chunk 对象"""
        return Chunk(
            chunk_id=str(uuid.uuid4()),
            source_id=source_id,
            text=text,
            chunk_type=chunk_type,
            chunk_index=index,
            start_char=start,
            end_char=end,
            token_count=len(text) // 4,  # 粗略估算 token 数
            metadata=metadata or {},
        )
    
    def _estimate_tokens(self, text: str) -> int:
        """粗略估算 token 数（约4个字符=1 token，中文约2字符=1 token）"""
        chinese_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_count = len(text) - chinese_count
        return chinese_count // 2 + other_count // 4
