"""
关键词重排序器

基于 BM25 风格的关键词匹配评分，纯本地计算，不依赖外部 API。

评分维度：
1. 关键词重合度（BM25）：query 中的关键词在 chunk 中的词频与稀有度
2. 位置权重：关键词出现在文本前部（首段 / 标题）得分更高
3. chunk_type 权重：标题 > 接口 > 实体 > 表格 > 代码 > 正文

中文分词优先使用 jieba；若不可用则退化为「英文按单词 + 中文按单字」规则。
"""
import logging
import math
import re
from collections import Counter
from typing import Dict, List, Set

from app.rag.models import RetrievalResult
from app.rag.reranker.base import BaseReranker

logger = logging.getLogger(__name__)

# chunk_type 权重：结构化信息通常更具信息量
CHUNK_TYPE_WEIGHTS: Dict[str, float] = {
    "title": 1.5,
    "api": 1.3,
    "entity": 1.2,
    "table": 1.2,
    "code": 1.1,
    "content": 1.0,
}

# 通用停用词
_STOPWORDS: Set[str] = {
    # 中文
    "的", "了", "和", "是", "在", "我", "有", "也", "就", "都", "与", "及",
    "或", "为", "以", "对", "可", "能", "这", "那", "一", "个", "中", "上",
    "下", "不", "无", "并", "等", "被", "把", "让", "给", "向", "从", "到",
    # 英文
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "and", "or", "not", "in", "on", "at", "to", "of", "for", "with",
    "from", "by", "as", "this", "that", "it", "if", "then", "but",
}

# 是否已尝试导入 jieba
_jieba_checked = False
_jieba_available = False


def _check_jieba() -> bool:
    """检测 jieba 是否可用（仅检测一次）"""
    global _jieba_checked, _jieba_available
    if not _jieba_checked:
        _jieba_checked = True
        try:
            import jieba  # noqa: F401

            _jieba_available = True
            logger.debug("[KeywordReranker] jieba 可用，使用 jieba 分词")
        except ImportError:
            _jieba_available = False
            logger.debug("[KeywordReranker] jieba 不可用，使用规则分词")
    return _jieba_available


def tokenize(text: str) -> List[str]:
    """中文分词

    优先使用 jieba；否则退化为：
      - 英文 / 数字 / 下划线 按单词（小写化）
      - 中文按单字

    过滤停用词与空白。
    """
    if not text:
        return []

    if _check_jieba():
        try:
            import jieba

            tokens = [
                t.strip().lower()
                for t in jieba.lcut(text)
                if t.strip() and t.strip().lower() not in _STOPWORDS
            ]
            return tokens
        except Exception as e:
            logger.debug(f"[KeywordReranker] jieba 分词异常，降级规则分词: {e}")

    # 规则分词
    tokens: List[str] = []
    # 英文 / 数字 / 下划线 连续串
    for m in re.findall(r"[A-Za-z0-9_]+", text):
        word = m.lower()
        if word not in _STOPWORDS:
            tokens.append(word)
    # 中文字符按单字
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            if ch not in _STOPWORDS:
                tokens.append(ch)
    return tokens


class KeywordReranker(BaseReranker):
    """基于 BM25 关键词匹配的重排序器"""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        # BM25 参数
        self.k1 = k1
        self.b = b

    async def rerank(
        self,
        query: str,
        results: List[RetrievalResult],
        top_k: int = 5,
    ) -> List[RetrievalResult]:
        """对检索结果进行 BM25 关键词重排序"""
        if not results:
            return []

        if not query or not query.strip():
            # 无查询文本，保持原序，仅截断到 top_k 并设置 rank
            ranked = list(results[:top_k])
            for idx, r in enumerate(ranked):
                r.rank = idx + 1
            return ranked

        query_tokens = tokenize(query)
        if not query_tokens:
            ranked = list(results[:top_k])
            for idx, r in enumerate(ranked):
                r.rank = idx + 1
            return ranked

        query_set: Set[str] = set(query_tokens)

        # 预处理文档 token
        docs_tokens: List[List[str]] = [tokenize(r.text) for r in results]
        n_docs = len(docs_tokens)
        avgdl = sum(len(t) for t in docs_tokens) / max(n_docs, 1)

        # 词频统计（用于 IDF）
        df: Dict[str, int] = {}
        for tokens in docs_tokens:
            for term in set(tokens):
                df[term] = df.get(term, 0) + 1

        scored: List[tuple] = []
        for i, r in enumerate(results):
            doc_tokens = docs_tokens[i]
            bm25 = self._bm25_score(doc_tokens, query_set, df, n_docs, avgdl)
            type_weight = CHUNK_TYPE_WEIGHTS.get(r.chunk_type, 1.0)
            position_weight = self._position_weight(r.text, query_set)
            final_score = max(bm25, 0.0) * type_weight * position_weight
            scored.append((final_score, r))

        # 按分数降序
        scored.sort(key=lambda x: x[0], reverse=True)

        # 截断并更新 score / rank
        reranked: List[RetrievalResult] = []
        for idx, (sc, r) in enumerate(scored[:top_k]):
            r.score = float(sc)
            r.rank = idx + 1
            reranked.append(r)

        logger.info(
            f"[KeywordReranker] 重排序完成: 输入 {len(results)} 条, "
            f"返回 {len(reranked)} 条 (top_k={top_k})"
        )
        return reranked

    # ------------------------------------------------------------------
    # 评分细节
    # ------------------------------------------------------------------
    def _bm25_score(
        self,
        doc_tokens: List[str],
        query_set: Set[str],
        df: Dict[str, int],
        n_docs: int,
        avgdl: float,
    ) -> float:
        """计算单篇文档的 BM25 分数"""
        if not doc_tokens:
            return 0.0

        tf = Counter(doc_tokens)
        dl = len(doc_tokens)
        avgdl = avgdl if avgdl > 0 else 1.0

        score = 0.0
        for term in query_set:
            f = tf.get(term, 0)
            if f == 0:
                continue
            n_q = df.get(term, 0)
            # IDF（BM25+ 变体，保证非负）
            idf = math.log(1 + (n_docs - n_q + 0.5) / (n_q + 0.5))
            denom = f + self.k1 * (1 - self.b + self.b * dl / avgdl)
            score += idf * (f * (self.k1 + 1)) / denom
        return score

    def _position_weight(self, text: str, query_set: Set[str]) -> float:
        """位置权重

        关键词出现在文本越靠前的位置，权重越高：
          - 前 10% 出现: 1.3
          - 前 30% 出现: 1.15
          - 其他: 1.0
        """
        if not text or not query_set:
            return 1.0
        total = len(text)
        if total == 0:
            return 1.0

        earliest = total  # 最早出现位置
        for term in query_set:
            pos = text.lower().find(term.lower()) if not _is_cjk(term) else text.find(term)
            if pos >= 0 and pos < earliest:
                earliest = pos

        if earliest == total:
            return 1.0
        ratio = earliest / total
        if ratio <= 0.1:
            return 1.3
        if ratio <= 0.3:
            return 1.15
        return 1.0


def _is_cjk(term: str) -> bool:
    """判断 token 是否为中文（单字）"""
    return len(term) == 1 and "\u4e00" <= term <= "\u9fff"
