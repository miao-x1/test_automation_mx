"""递归分块器 - 按分隔符递归分割"""
import re
from typing import List
from app.rag.chunker.base import BaseChunker
from app.rag.models import Chunk, ChunkStrategy, LoadedDocument


class RecursiveChunker(BaseChunker):
    """递归分块器，支持多级分隔符"""
    
    SEPARATORS = [
        "\n## ", "\n### ", "\n#### ",   # Markdown 标题
        "\n\n",                            # 段落
        "\n",                              # 行
        "。", ".", "！", "！", "？", "?",  # 句子结束
        "；", ";", "，", ",",              # 子句
        " ",                               # 空格
        "",                                # 字符
    ]
    
    def __init__(self, chunk_size: int = 1000, overlap: int = 100, min_chunk_size: int = 100):
        super().__init__(ChunkStrategy.RECURSIVE)
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.min_chunk_size = min_chunk_size
    
    def chunk(self, document: LoadedDocument) -> List[Chunk]:
        text = document.content
        if not text:
            return []
        source_id = document.source_id or document.file_name
        # 递归分割
        splits = self._split_text(text, self.SEPARATORS)
        # 合并小的分块
        merged = self._merge_splits(splits, self.chunk_size, self.overlap)
        # 创建 Chunk 对象
        chunks = []
        current_pos = 0
        for i, chunk_text in enumerate(merged):
            if len(chunk_text.strip()) < self.min_chunk_size and i < len(merged) - 1:
                continue
            # 找到在原文中的位置
            start = text.find(chunk_text, current_pos)
            if start == -1:
                start = current_pos
            end = start + len(chunk_text)
            current_pos = end - self.overlap if self.overlap > 0 else end
            chunks.append(self._create_chunk(
                text=chunk_text,
                source_id=source_id,
                index=len(chunks),
                start=start,
                end=end,
                chunk_type="content",
                metadata={"strategy": "recursive", "chunk_size": len(chunk_text)},
            ))
        return chunks
    
    def _split_text(self, text: str, separators: List[str]) -> List[str]:
        """递归分割文本"""
        if len(text) <= self.chunk_size:
            return [text] if text.strip() else []
        if not separators:
            return [text] if text.strip() else []
        sep = separators[0]
        if sep == "":
            # 按字符分割
            return [text[i:i+self.chunk_size] for i in range(0, len(text), self.chunk_size)]
        # 按分隔符分割
        parts = text.split(sep)
        parts = [p + sep for p in parts[:-1]] + [parts[-1]]  # 保留分隔符
        # 递归处理每个部分
        result = []
        for part in parts:
            if len(part) > self.chunk_size:
                result.extend(self._split_text(part, separators[1:]))
            elif part.strip():
                result.append(part)
        return result
    
    def _merge_splits(self, splits: List[str], max_size: int, overlap: int) -> List[str]:
        """合并小的分块"""
        if not splits:
            return []
        merged = []
        current = ""
        for split in splits:
            if len(current) + len(split) <= max_size:
                current += split
            else:
                if current.strip():
                    merged.append(current)
                # 保留重叠部分
                if overlap > 0 and len(current) > overlap:
                    current = current[-overlap:] + split
                else:
                    current = split
        if current.strip():
            merged.append(current)
        return merged
