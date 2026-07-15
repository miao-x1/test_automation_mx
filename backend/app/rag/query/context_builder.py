"""
上下文构建器

将检索结果拼接为 LLM 上下文文本，并提供 token 估算与截断能力。

输出格式：

    [来源: {source_name} | 类型: {source_type}]
    {text}
    ---
    [来源: ... | 类型: ...]
    {text}
    ---

默认最大 4000 tokens，超出时从尾部按块截断，保证不破坏单块完整性。
"""
import logging
import re
from typing import List

from app.rag.models import RetrievalResult

logger = logging.getLogger(__name__)

# 中日韩统一表意文字范围
_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
# 英文 / 数字 / 下划线 连续串
_WORD_PATTERN = re.compile(r"[A-Za-z0-9_]+")


class ContextBuilder:
    """上下文构建器"""

    DEFAULT_MAX_TOKENS = 4000

    def __init__(self, max_tokens: int = DEFAULT_MAX_TOKENS):
        self.max_tokens = max_tokens

    # ------------------------------------------------------------------
    # 上下文拼接
    # ------------------------------------------------------------------
    def build_context(self, results: List[RetrievalResult]) -> str:
        """将检索结果拼接为 LLM 上下文文本

        Args:
            results: 检索结果列表（建议已按相关性排序）

        Returns:
            拼接后的上下文文本（已按 max_tokens 截断）
        """
        if not results:
            return ""

        blocks: List[str] = []
        for r in results:
            text = (r.text or "").strip()
            if not text:
                continue
            blocks.append(self._format_block(r, text))

        if not blocks:
            return ""

        context = "\n---\n".join(blocks)
        # 按 token 限制截断
        context = self.truncate_context(context, self.max_tokens)
        return context

    def _format_block(self, r: RetrievalResult, text: str) -> str:
        """格式化单个结果块"""
        source_name = r.source_name or r.source_id or "未知"
        source_type = r.source_type or r.chunk_type or "未知"
        header = f"[来源: {source_name} | 类型: {source_type}]"
        return f"{header}\n{text}"

    # ------------------------------------------------------------------
    # Token 估算
    # ------------------------------------------------------------------
    def estimate_tokens(self, text: str) -> int:
        """估算文本的 token 数

        启发式估算：
          - 中日韩字符：约 1 token / 字
          - 英文 / 数字单词：约 1.3 token / 词
          - 其他字符（标点、空白）：约 4 字符 / token
        """
        if not text:
            return 0

        cjk_count = len(_CJK_PATTERN.findall(text))
        words = _WORD_PATTERN.findall(text)
        word_count = len(words)
        # 非中文、非英文单词的字符数
        non_cjk_chars = len(text) - cjk_count
        # 去掉已被 word_pattern 计数的英文单词字符长度
        word_chars = sum(len(w) for w in words)
        other_chars = max(non_cjk_chars - word_chars, 0)

        tokens = int(cjk_count + word_count * 1.3 + other_chars / 4.0)
        return max(tokens, 1)

    # ------------------------------------------------------------------
    # 截断
    # ------------------------------------------------------------------
    def truncate_context(self, context: str, max_tokens: int) -> str:
        """如果超过 token 限制，按块截断（不破坏单块完整性）

        策略：
          1. 先尝试整体截断到字符级（保留前 N 个字符）
          2. 若已按 ``---`` 分块，则从尾部丢弃完整块直到低于限制
        """
        if not context or max_tokens <= 0:
            return context

        if self.estimate_tokens(context) <= max_tokens:
            return context

        # 按 --- 分块
        parts = context.split("\n---\n")
        kept: List[str] = []
        current_tokens = 0
        for part in parts:
            part_tokens = self.estimate_tokens(part)
            if current_tokens + part_tokens > max_tokens:
                # 剩余配额无法容纳完整块，尝试字符级截断该块
                remaining = max_tokens - current_tokens
                if remaining > 50:
                    # 按 token 反推字符上限（粗略）
                    char_limit = self._token_to_char_limit(part, remaining)
                    if char_limit > 0:
                        kept.append(part[:char_limit].rstrip())
                break
            kept.append(part)
            current_tokens += part_tokens

        truncated = "\n---\n".join(kept)
        if not truncated:
            # 极端情况：单块即超限，字符级截断
            char_limit = self._token_to_char_limit(context, max_tokens)
            truncated = context[:char_limit].rstrip()

        logger.info(
            f"[ContextBuilder] 上下文已截断: 原始约 {self.estimate_tokens(context)} tokens, "
            f"截断后约 {self.estimate_tokens(truncated)} tokens (max={max_tokens})"
        )
        return truncated

    def _token_to_char_limit(self, text: str, max_tokens: int) -> int:
        """根据 token 上限反推字符截断位置（粗略）"""
        if max_tokens <= 0:
            return 0
        # 估算平均 2.5 字符 / token
        return int(max_tokens * 2.5)
