"""
AssetSearchService - 测试资产中心服务层 (资产搜索)

职责:
  1. 三源融合搜索编排 (MySQL + Milvus + Neo4j)
  2. 调用 AssetSearchRepository 做 MySQL 关键词搜索
  3. Phase 2: Milvus / Neo4j 为 stub (返回空), Phase 3 接入真实检索
  4. 融合得分计算 (0.5 * mysql + 0.3 * milvus + 0.2 * relation)
  5. 搜索结果格式化 (含命中原因, 供 Agent 使用)

不做:
  - HTTP 层逻辑
  - SQL 拼接
  - 向量嵌入生成 (由 AssetSearchAgent 在 Phase 3 调用 Embedding 服务)
  - Neo4j 图谱查询 (由 AssetSearchAgent 在 Phase 3 调用 graph_service)

依赖:
  - AssetSearchRepository
  - SessionLocal
"""
import logging
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.repositories.asset_repository import AssetRepository
from app.repositories.asset_search_repository import AssetSearchRepository
from app.schemas.asset_registry import (
    SearchRequest,
    SearchResponse,
    SearchHitItem,
    MatchReason,
)

logger = logging.getLogger(__name__)


# 融合权重 (与设计文档一致)
_FUSION_WEIGHTS = {"mysql": 0.5, "milvus": 0.3, "neo4j": 0.2}


class AssetSearchService:
    """测试资产中心 — 资产搜索服务"""

    def __init__(self):
        self._search_repo = AssetSearchRepository()
        self._asset_repo = AssetRepository()

    # ------------------------------------------------------------------
    # 会话管理
    # ------------------------------------------------------------------

    @contextmanager
    def _session(self) -> Iterator[Session]:
        db = SessionLocal()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ------------------------------------------------------------------
    # 搜索入口
    # ------------------------------------------------------------------

    def search(
        self,
        payload: SearchRequest,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """三源融合搜索

        步骤:
          1. MySQL 关键词搜索 (同步, 必执行)
          2. Milvus 向量召回 (Phase 2 stub, Phase 3 接入)
          3. Neo4j 关系扩展 (Phase 2 stub, Phase 3 接入)
          4. 三源结果合并 + 融合得分计算
          5. 按 final_score 降序返回

        Returns:
            搜索响应 dict (与 SearchResponse schema 对应)
        """
        start_ts = time.time()
        sources_used: List[str] = ["mysql"]

        with self._session() as db:
            # 1. MySQL 搜索
            mysql_results = self._search_repo.search_mysql(
                db,
                query=payload.query,
                asset_types=payload.asset_types,
                module=payload.module,
                tags=payload.tags,
                include_inactive=payload.include_inactive,
                user_id=user_id,
                limit=payload.limit,
            )
            logger.info(
                f"[AssetSearchSvc] MySQL 搜索完成: {len(mysql_results)} 条命中"
            )

            # 2. Milvus 向量召回 (Phase 2 stub)
            vector_results: List[Dict[str, Any]] = []
            if payload.use_vector:
                vector_results = self._search_milvus(
                    db,
                    query=payload.query,
                    asset_types=payload.asset_types,
                    limit=payload.limit,
                    user_id=user_id,
                )
                if vector_results:
                    sources_used.append("milvus")
                logger.info(
                    f"[AssetSearchSvc] Milvus 向量召回: {len(vector_results)} 条 "
                    f"(Phase 2 stub)"
                )

            # 3. Neo4j 关系扩展 (Phase 2 stub)
            relation_results: List[Dict[str, Any]] = []
            if payload.use_relation and mysql_results:
                # 基于 MySQL 结果, 扩展相关资产
                asset_ids = [
                    r["asset"].id for r in mysql_results if hasattr(r.get("asset"), "id")
                ]
                relation_results = self._search_neo4j(
                    db,
                    seed_asset_ids=asset_ids,
                    limit=payload.limit,
                    user_id=user_id,
                )
                if relation_results:
                    sources_used.append("neo4j")
                logger.info(
                    f"[AssetSearchSvc] Neo4j 关系扩展: {len(relation_results)} 条 "
                    f"(Phase 2 stub)"
                )

            # 4. 三源融合
            merged = self._search_repo.merge_results(
                mysql_results,
                vector_results=vector_results,
                relation_results=relation_results,
                weights=_FUSION_WEIGHTS,
            )

            # 5. 截断到 limit
            merged = merged[:payload.limit]

            # 6. 格式化响应
            hits = [self._format_hit(item) for item in merged]
            elapsed_ms = int((time.time() - start_ts) * 1000)

            return {
                "query": payload.query,
                "total": len(hits),
                "hits": hits,
                "elapsed_ms": elapsed_ms,
                "sources_used": sources_used,
            }

    # ------------------------------------------------------------------
    # Milvus 向量召回 (Phase 2 stub)
    # ------------------------------------------------------------------

    def _search_milvus(
        self,
        db: Session,
        *,
        query: str,
        asset_types: Optional[List[str]] = None,
        limit: int = 10,
        user_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Milvus 向量召回 (Phase 2 stub)

        Phase 2: 返回空列表
        Phase 3: 调用 Embedding 服务生成 query 向量, 再查 Milvus
        """
        # Phase 2: 不实现
        return []

    # ------------------------------------------------------------------
    # Neo4j 关系扩展 (Phase 2 stub)
    # ------------------------------------------------------------------

    def _search_neo4j(
        self,
        db: Session,
        *,
        seed_asset_ids: List[int],
        limit: int = 10,
        user_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Neo4j 关系扩展 (Phase 2 stub)

        Phase 2: 返回空列表
        Phase 3: 调用 graph_service 查询相关资产
        """
        # Phase 2: 不实现
        return []

    # ------------------------------------------------------------------
    # 格式化
    # ------------------------------------------------------------------

    def _format_hit(self, merged_item: Dict[str, Any]) -> Dict[str, Any]:
        """将融合后的搜索结果项格式化为响应 dict

        merged_item 结构:
          {
            "asset_id": int,
            "asset": <AssetRegistry>,
            "mysql_score": float,
            "vector_score": Optional[float],
            "relation_score": Optional[float],
            "final_score": float,
            "match_reasons": [...]
          }
        """
        asset = merged_item.get("asset")
        if asset is None:
            # 仅含 asset_id 的情况 (向量/关系命中但无 MySQL 命中)
            # 需要补充查询 — 此处简化, 跳过
            return {
                "asset_id": merged_item.get("asset_id", 0),
                "asset_code": "",
                "name": "",
                "asset_type": "",
                "status": "",
                "module": None,
                "summary": None,
                "tags": [],
                "quality_score": 0.0,
                "reuse_count": 0,
                "mysql_score": merged_item.get("mysql_score", 0.0),
                "vector_score": merged_item.get("vector_score"),
                "relation_score": merged_item.get("relation_score"),
                "final_score": merged_item.get("final_score", 0.0),
                "match_reasons": merged_item.get("match_reasons", []),
            }

        # 使用 AssetRepository.to_list_item 保持字段一致
        asset_dict = self._asset_repo.to_list_item(asset)
        return {
            **asset_dict,
            "mysql_score": merged_item.get("mysql_score", 0.0),
            "vector_score": merged_item.get("vector_score"),
            "relation_score": merged_item.get("relation_score"),
            "final_score": merged_item.get("final_score", 0.0),
            "match_reasons": merged_item.get("match_reasons", []),
        }

    # ------------------------------------------------------------------
    # 反查 (供 Agent 使用)
    # ------------------------------------------------------------------

    def find_by_ref(
        self,
        ref_type: str,
        ref_id: int,
        *,
        user_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """按 ref_type + ref_id 反查资产 (精确匹配)

        用于 Agent 根据既有业务对象 ID 查找对应的资产索引
        """
        with self._session() as db:
            asset = self._search_repo.find_by_ref(
                db, ref_type, ref_id, user_id=user_id
            )
            if asset is None:
                return None
            return self._asset_repo.to_dict(asset)

    def find_by_codes(
        self,
        asset_codes: List[str],
        *,
        user_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """按 asset_code 列表批量查询"""
        with self._session() as db:
            assets = self._search_repo.find_by_codes(
                db, asset_codes, user_id=user_id
            )
            return [self._asset_repo.to_dict(a) for a in assets]
