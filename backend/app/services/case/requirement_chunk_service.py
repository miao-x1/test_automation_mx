"""
RequirementChunkService - 大需求文档分块处理

核心流程：
  上传需求 → 切分为chunks → 滚动摘要 → 合并输出

滚动摘要策略：
  chunk1~6 → summary_1
  summary_1 + chunk7~12 → summary_2
  ...直到结束

配置：
  chunk_size: 4000字符
  summary_window: 6块
  overlap: 300字符

禁止：
  一次发送全文给模型
"""
import json
from typing import Any, Dict, List, Optional
from app.core.config import settings
from app.core.logger import log
from app.db.database import SessionLocal
from app.models.requirement_chunk import RequirementChunk


# 分块配置
CHUNK_SIZE = 4000      # 每块最大字符数
SUMMARY_WINDOW = 6     # 每次摘要处理的块数
OVERLAP = 300          # 块间重叠字符数


class RequirementChunkService:
    """大需求文档分块处理服务"""

    @staticmethod
    def split_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = OVERLAP) -> List[str]:
        """
        将长文本切分为多个chunk

        策略：
        1. 先按段落切分
        2. 合并小段落直到达到chunk_size
        3. 块间保留overlap字符重叠

        Args:
            text: 原始文本
            chunk_size: 每块最大字符数
            overlap: 块间重叠字符数

        Returns:
            分块列表
        """
        if not text:
            return []

        if len(text) <= chunk_size:
            return [text]

        chunks = []
        # 按段落切分
        paragraphs = text.split("\n\n")
        current_chunk = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(current_chunk) + len(para) + 2 <= chunk_size:
                current_chunk += ("\n\n" if current_chunk else "") + para
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                # 处理超长段落
                if len(para) > chunk_size:
                    sub_chunks = RequirementChunkService._split_long_paragraph(para, chunk_size, overlap)
                    chunks.extend(sub_chunks[:-1])
                    current_chunk = sub_chunks[-1] if sub_chunks else ""
                else:
                    current_chunk = para

        if current_chunk:
            chunks.append(current_chunk)

        log.info(f"RequirementChunkService | 分块完成 | total_chars={len(text)}, chunks={len(chunks)}")
        return chunks

    @staticmethod
    def _split_long_paragraph(para: str, chunk_size: int, overlap: int) -> List[str]:
        """切分超长段落（按句子+重叠）"""
        import re
        # 中英文句子分割
        sentences = re.split(r'(?<=[。！？；\n])|(?<=[.!?:;]\s)', para)
        sentences = [s for s in sentences if s.strip()]

        chunks = []
        current = ""

        for sent in sentences:
            if len(current) + len(sent) <= chunk_size:
                current += sent
            else:
                if current:
                    chunks.append(current)
                # 保留overlap
                current = current[-overlap:] + sent if overlap and current else sent

        if current:
            chunks.append(current)

        return chunks

    @staticmethod
    def save_chunks(db, session_id: int, chunks: List[str]) -> List[int]:
        """保存分块到数据库"""
        chunk_ids = []
        for i, content in enumerate(chunks):
            chunk = RequirementChunk(
                session_id=session_id,
                chunk_index=i,
                content=content,
                char_count=len(content),
                is_processed=False,
            )
            db.add(chunk)
            db.flush()
            chunk_ids.append(chunk.id)
        db.commit()
        return chunk_ids

    @staticmethod
    def rolling_summarize(
        session_id: int,
        chunk_size: int = CHUNK_SIZE,
        summary_window: int = SUMMARY_WINDOW,
    ) -> str:
        """
        滚动摘要：逐窗口处理chunks，每次将前序摘要+当前窗口一起发给LLM

        chunk1~6 → summary_1
        summary_1 + chunk7~12 → summary_2
        ...

        Returns:
            最终合并摘要
        """
        db = SessionLocal()
        try:
            chunks = db.query(RequirementChunk).filter(
                RequirementChunk.session_id == session_id,
            ).order_by(RequirementChunk.chunk_index).all()

            if not chunks:
                return ""

            # 如果总块数 ≤ summary_window，直接一次性摘要
            if len(chunks) <= summary_window:
                combined = "\n\n".join(c.content for c in chunks)
                summary = RequirementChunkService._llm_summarize(combined)
                # 更新所有chunk为已处理
                for c in chunks:
                    c.is_processed = True
                    c.summary = summary
                db.commit()
                return summary

            # 滚动摘要
            prev_summary = ""
            for window_start in range(0, len(chunks), summary_window):
                window = chunks[window_start:window_start + summary_window]
                window_text = "\n\n".join(c.content for c in window)

                if prev_summary:
                    prompt_text = f"之前的摘要：\n{prev_summary}\n\n新增内容：\n{window_text}"
                else:
                    prompt_text = window_text

                prev_summary = RequirementChunkService._llm_summarize(prompt_text)

                # 更新chunk状态
                for c in window:
                    c.is_processed = True
                    c.summary = prev_summary
                db.commit()

                log.info(f"RequirementChunkService | 滚动摘要 | window={window_start}-{window_start + len(window) - 1}")

            return prev_summary

        finally:
            db.close()

    @staticmethod
    def _llm_summarize(text: str) -> str:
        """调用LLM生成摘要"""
        import httpx

        # 截断过长文本
        if len(text) > 12000:
            text = text[:12000] + "...(截断)"

        api_key = settings.QWEN_API_KEY
        if not api_key:
            # 无API Key时返回截断原文
            return text[:2000] + "..." if len(text) > 2000 else text

        url = settings.QWEN_API_URL
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": settings.QWEN_MODEL.replace("-vl-plus", "-plus").replace("-vl-max", "-max"),
            "messages": [
                {
                    "role": "system",
                    "content": "你是需求分析专家。请将以下需求内容压缩为简洁的结构化摘要，保留：1)核心功能点 2)关键业务规则 3)重要约束条件 4)涉及的数据实体和API。摘要不超过800字。"
                },
                {
                    "role": "user",
                    "content": f"请摘要以下需求：\n\n{text}"
                },
            ],
            "temperature": 0.2,
        }

        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=60)
            result = response.json()
            if "choices" in result:
                return result["choices"][0]["message"]["content"]
            return text[:2000]
        except Exception as e:
            log.warning(f"RequirementChunkService | LLM摘要失败: {e}")
            return text[:2000]

    @staticmethod
    def get_chunks_status(session_id: int) -> Dict[str, Any]:
        """获取分块处理状态"""
        db = SessionLocal()
        try:
            chunks = db.query(RequirementChunk).filter(
                RequirementChunk.session_id == session_id,
            ).all()

            total = len(chunks)
            processed = sum(1 for c in chunks if c.is_processed)

            return {
                "total": total,
                "processed": processed,
                "progress": int(processed / total * 100) if total > 0 else 100,
                "chunks": [
                    {
                        "chunk_index": c.chunk_index,
                        "char_count": c.char_count,
                        "is_processed": c.is_processed,
                        "has_summary": bool(c.summary),
                    }
                    for c in chunks
                ],
            }
        finally:
            db.close()
