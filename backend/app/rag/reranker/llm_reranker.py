"""
LLM 重排序器

使用大语言模型对检索结果进行相关性评分（0-10），结合关键词重合度评分，
输出更精准的排序。当 LLM API 不可用时，自动降级为关键词重排序。

两种评分策略：
1. 关键词重合度评分（始终计算，作为基线与降级方案）
2. LLM 评分（可选，当 API 可用时启用）

最终分数 = 关键词归一化分数 * 关键词权重 + LLM 归一化分数 * LLM 权重
（LLM 不可用时仅使用关键词分数）
"""
import asyncio
import json
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

from app.core.llm import call_llm
from app.rag.models import RetrievalResult
from app.rag.reranker.base import BaseReranker
from app.rag.reranker.keyword_reranker import KeywordReranker

logger = logging.getLogger(__name__)

# 分数融合权重（LLM 可用时）
_LLM_WEIGHT = 0.7
_KEYWORD_WEIGHT = 0.3

# 单次送入 LLM 的最大候选数量（控制 token 消耗）
_MAX_LLM_CANDIDATES = 20
# 单个 chunk 截断长度
_CHUNK_TEXT_LIMIT = 500


class LLMReranker(BaseReranker):
    """LLM 重排序器（自动降级到关键词）"""

    def __init__(self):
        self._keyword_reranker = KeywordReranker()
        # LLM 配置缓存
        self._llm_config: Optional[Dict] = None
        self._llm_config_inited = False

    # ------------------------------------------------------------------
    # LLM 配置检测（惰性）
    # ------------------------------------------------------------------
    def _get_llm_config(self) -> Optional[Dict]:
        """检测可用的 LLM 配置（dashscope / deepseek）

        优先级：
          1. dashscope (DASHSCOPE_API_KEY / QWEN_API_KEY)
          2. deepseek (DEEPSEEK_API_KEY)

        返回 None 表示无可用 LLM。
        """
        if self._llm_config_inited:
            return self._llm_config
        self._llm_config_inited = True

        try:
            from app.core.config import settings  # noqa: F401
        except Exception:
            settings = None  # type: ignore

        # dashscope
        dashscope_key = os.getenv("DASHSCOPE_API_KEY", "")
        if not dashscope_key and settings is not None:
            dashscope_key = getattr(settings, "QWEN_API_KEY", "") or ""
        if dashscope_key:
            self._llm_config = {
                "provider": "dashscope",
                "api_key": dashscope_key,
                "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                "model": os.getenv("LLM_MODEL", "qwen-plus"),
            }
            logger.debug("[LLMReranker] 使用 dashscope 进行 LLM 评分")
            return self._llm_config

        # deepseek
        deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
        if not deepseek_key and settings is not None:
            deepseek_key = getattr(settings, "DEEPSEEK_API_KEY", "") or ""
        if deepseek_key:
            self._llm_config = {
                "provider": "deepseek",
                "api_key": deepseek_key,
                "url": "https://api.deepseek.com/v1/chat/completions",
                "model": os.getenv("LLM_MODEL", "deepseek-chat"),
            }
            logger.debug("[LLMReranker] 使用 deepseek 进行 LLM 评分")
            return self._llm_config

        logger.info("[LLMReranker] 无可用 LLM API，将降级为关键词重排序")
        self._llm_config = None
        return self._llm_config

    # ------------------------------------------------------------------
    # 重排序主流程
    # ------------------------------------------------------------------
    async def rerank(
        self,
        query: str,
        results: List[RetrievalResult],
        top_k: int = 5,
    ) -> List[RetrievalResult]:
        """对检索结果进行 LLM + 关键词重排序"""
        if not results:
            return []

        # 1. 始终先做关键词重排序（作为基线 / 降级方案 / 融合分量）
        #    取全部候选参与关键词打分，便于后续融合
        keyword_ranked = await self._keyword_reranker.rerank(
            query, results, top_k=len(results)
        )

        # 2. 尝试 LLM 评分
        llm_scores = await self._llm_score(query, keyword_ranked)

        if llm_scores is None:
            # 降级：直接使用关键词结果，截断到 top_k
            reranked = keyword_ranked[:top_k]
            for idx, r in enumerate(reranked):
                r.rank = idx + 1
            logger.info(
                f"[LLMReranker] 降级关键词重排序完成: 输入 {len(results)} 条, "
                f"返回 {len(reranked)} 条"
            )
            return reranked

        # 3. 融合分数：keyword（已归一化于自身）+ llm（0-10 -> 0-1）
        kw_scores = [r.score for r in keyword_ranked]
        kw_max = max(kw_scores) if kw_scores else 1.0
        if kw_max <= 0:
            kw_max = 1.0

        scored: List[Tuple[float, RetrievalResult]] = []
        for r in keyword_ranked:
            kw_norm = r.score / kw_max  # 关键词分数归一化到 0-1
            llm_norm = llm_scores.get(r.chunk_id, 0.0) / 10.0  # LLM 0-10 -> 0-1
            final = _KEYWORD_WEIGHT * kw_norm + _LLM_WEIGHT * llm_norm
            scored.append((final, r))

        scored.sort(key=lambda x: x[0], reverse=True)

        reranked: List[RetrievalResult] = []
        for idx, (sc, r) in enumerate(scored[:top_k]):
            r.score = float(sc)
            r.rank = idx + 1
            reranked.append(r)

        logger.info(
            f"[LLMReranker] LLM+关键词重排序完成: 输入 {len(results)} 条, "
            f"返回 {len(reranked)} 条"
        )
        return reranked

    # ------------------------------------------------------------------
    # LLM 评分
    # ------------------------------------------------------------------
    async def _llm_score(
        self,
        query: str,
        results: List[RetrievalResult],
    ) -> Optional[Dict[str, float]]:
        """让 LLM 对每个结果打分（0-10）

        Returns:
            {chunk_id: score} 字典；LLM 不可用或失败时返回 None
        """
        config = self._get_llm_config()
        if config is None:
            return None
        if not query or not query.strip():
            return None

        # 限制候选数量，控制 token 消耗
        candidates = results[:_MAX_LLM_CANDIDATES]
        if not candidates:
            return None

        # 构建 prompt
        chunks_text = self._build_candidates_text(candidates)
        system_prompt = (
            "你是一个专业的信息检索相关性评估专家。"
            "你需要根据用户查询，对每个候选文档片段的相关性进行打分。"
            "分数范围 0-10，10 表示完全相关，0 表示完全无关。"
            "请严格按照指定格式输出，不要输出多余内容。"
        )
        user_prompt = (
            f"用户查询：{query}\n\n"
            f"候选文档片段：\n{chunks_text}\n\n"
            "请为每个文档片段打分（0-10 的整数或一位小数），"
            '输出格式为 JSON 对象，键为文档编号(数字)，值为分数。'
            '示例：{"1": 8.5, "2": 3.0, "3": 9.0}'
        )

        try:
            content = await self._call_llm(config, system_prompt, user_prompt)
            return self._parse_scores(content, candidates)
        except Exception as e:
            logger.warning(f"[LLMReranker] LLM 评分失败，降级到关键词: {e}")
            return None

    def _build_candidates_text(self, candidates: List[RetrievalResult]) -> str:
        """构建候选文档文本（带编号）"""
        lines = []
        for i, r in enumerate(candidates, start=1):
            text = (r.text or "").strip()[:_CHUNK_TEXT_LIMIT]
            lines.append(f"[{i}] {text}")
        return "\n".join(lines)

    async def _call_llm(
        self, config: Dict, system_prompt: str, user_prompt: str
    ) -> str:
        """调用 LLM（OpenAI 兼容接口）

        通过统一工具 app.core.llm.call_llm 同步调用，
        使用 asyncio.to_thread 避免阻塞事件循环。
        """
        model = config.get("model") if isinstance(config, dict) else None
        return await asyncio.to_thread(
            call_llm,
            system_prompt,
            user_prompt,
            temperature=0.0,
            max_tokens=1024,
            model=model,
        )

    def _parse_scores(
        self,
        content: str,
        candidates: List[RetrievalResult],
    ) -> Optional[Dict[str, float]]:
        """解析 LLM 输出的分数

        支持 JSON 对象 {"1": 8.5, ...} 与简单列表格式。
        """
        if not content:
            return None

        scores: Dict[str, float] = {}

        # 1. 尝试直接解析 JSON
        try:
            # 提取第一个 JSON 对象（避免被前后说明文字包裹）
            match = re.search(r"\{[^{}]*\}", content, re.DOTALL)
            if match:
                obj = json.loads(match.group(0))
                for k, v in obj.items():
                    try:
                        idx = int(k)
                        score = float(v)
                        if 1 <= idx <= len(candidates):
                            chunk_id = candidates[idx - 1].chunk_id
                            if chunk_id:
                                scores[chunk_id] = max(0.0, min(10.0, score))
                    except (ValueError, TypeError):
                        continue
        except (json.JSONDecodeError, AttributeError):
            pass

        # 2. 退化：按行解析 "编号: 分数" 形式
        if not scores:
            for line in content.splitlines():
                m = re.match(r"\s*(\d+)\s*[:：]\s*([0-9]+(?:\.[0-9]+)?)\s*", line)
                if m:
                    idx = int(m.group(1))
                    score = float(m.group(2))
                    if 1 <= idx <= len(candidates):
                        chunk_id = candidates[idx - 1].chunk_id
                        if chunk_id:
                            scores[chunk_id] = max(0.0, min(10.0, score))

        if not scores:
            logger.debug(f"[LLMReranker] 无法解析 LLM 评分输出: {content[:200]}")
            return None
        return scores
