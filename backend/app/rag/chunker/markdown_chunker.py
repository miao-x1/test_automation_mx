"""Markdown 标题分块器"""
import re
from typing import List
from app.rag.chunker.base import BaseChunker
from app.rag.models import Chunk, ChunkStrategy, LoadedDocument


class MarkdownChunker(BaseChunker):
    """按 Markdown 标题分块"""
    
    def __init__(self, max_chunk_size: int = 1500, min_chunk_size: int = 100):
        super().__init__(ChunkStrategy.MARKDOWN_HEADER)
        self.max_chunk_size = max_chunk_size
        self.min_chunk_size = min_chunk_size
    
    def chunk(self, document: LoadedDocument) -> List[Chunk]:
        text = document.content
        if not text:
            return []
        source_id = document.source_id or document.file_name
        # 如果文档已有 sections，直接使用
        if document.sections:
            chunks = []
            for section in document.sections:
                content = section.get("content", "").strip()
                if not content:
                    continue
                title = section.get("title", "")
                level = section.get("level", 0)
                # 如果内容太长，进一步分割
                if len(content) > self.max_chunk_size:
                    # 简单按段落分割
                    paragraphs = content.split("\n\n")
                    current = f"{'#' * level} {title}\n" if title else ""
                    for para in paragraphs:
                        if len(current) + len(para) <= self.max_chunk_size:
                            current += para + "\n\n"
                        else:
                            if len(current.strip()) >= self.min_chunk_size:
                                chunks.append(self._create_chunk(
                                    text=current.strip(),
                                    source_id=source_id,
                                    index=len(chunks),
                                    start=0, end=len(current),
                                    chunk_type="content",
                                    metadata={"title": title, "level": level, "strategy": "markdown_header"},
                                ))
                            current = f"{'#' * level} {title}\n{para}\n\n" if title else para + "\n\n"
                    if current.strip() and len(current.strip()) >= self.min_chunk_size:
                        chunks.append(self._create_chunk(
                            text=current.strip(),
                            source_id=source_id,
                            index=len(chunks),
                            start=0, end=len(current),
                            chunk_type="content",
                            metadata={"title": title, "level": level, "strategy": "markdown_header"},
                        ))
                else:
                    chunks.append(self._create_chunk(
                        text=content,
                        source_id=source_id,
                        index=len(chunks),
                        start=0, end=len(content),
                        chunk_type="content",
                        metadata={"title": title, "level": level, "strategy": "markdown_header"},
                    ))
            return chunks
        # 如果没有 sections，按标题正则分割
        return self._split_by_headers(text, source_id)
    
    def _split_by_headers(self, text: str, source_id: str) -> List[Chunk]:
        """按标题正则分割"""
        pattern = r'^(#{1,6})\s+(.+)'
        lines = text.split('\n')
        chunks = []
        current_header = ""
        current_level = 0
        current_content = ""
        for line in lines:
            match = re.match(pattern, line)
            if match:
                # 保存前一个块
                if current_content.strip() and len(current_content.strip()) >= self.min_chunk_size:
                    chunks.append(self._create_chunk(
                        text=current_content.strip(),
                        source_id=source_id,
                        index=len(chunks),
                        start=0, end=len(current_content),
                        chunk_type="content",
                        metadata={"title": current_header, "level": current_level, "strategy": "markdown_header"},
                    ))
                current_header = match.group(2)
                current_level = len(match.group(1))
                current_content = line + "\n"
            else:
                current_content += line + "\n"
        if current_content.strip() and len(current_content.strip()) >= self.min_chunk_size:
            chunks.append(self._create_chunk(
                text=current_content.strip(),
                source_id=source_id,
                index=len(chunks),
                start=0, end=len(current_content),
                chunk_type="content",
                metadata={"title": current_header, "level": current_level, "strategy": "markdown_header"},
            ))
        return chunks
