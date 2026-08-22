"""
AssetSearchRepository - 资产搜索数据访问层 (MySQL 部分)

职责:
  1. 基于 keyword 的 MySQL 全文匹配搜索 (name / asset_code / summary / tags)
  2. 计算 mysql_score (0-1, 基于命中字段权重)
  3. 多条件过滤 (asset_types / module / tags / status / quality)
  4. 三源融合辅助: 提供 merge_results 方法合并 MySQL + Milvus + Neo4j 得分
  5. 按 ref_type + ref_id 反查资产

不做:
  - Milvus 向量召回 (由 AssetSearchAgent 在 Phase 3 集成)
  - Neo4j 关系扩展 (由 AssetSearchAgent 在 Phase 3 集成)
  - 融合得分计算 (由 service / agent 层根据 0.5/0.3/0.2 权重计算)

MySQL 评分规则 (mysql_score):
  - name 命中:        1.0 (最高权重)
  - asset_code 命中:  0.9
  - summary 命中:     0.6
  - tags 命中:        0.5
  - description 命中: 0.3
  多字段命中取最大值; 完全匹配 > 前缀匹配 > 包含匹配。
"""
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.asset_registry import (
    AssetRegistry,
    AssetRegistryStatus,
    AssetRegistryType,
)

logger = logging.getLogger(__name__)


# 字段命中权重
FIELD_WEIGHTS = {
    "name": 1.0,
    "asset_code": 0.9,
    "summary": 0.6,
    "tags": 0.5,
    "description": 0.3,
}

# 完全匹配加成
EXACT_MATCH_BONUS = 0.1
# 前缀匹配加成
PREFIX_MATCH_BONUS = 0.05


class AssetSearchRepository:
    """资产搜索 Repository (MySQL 部分)"""

    def search_mysql(
        self,
        db: Session,
        *,
        query: str,
        asset_types: Optional[List[str]] = None,
        module: Optional[str] = None,
        tags: Optional[List[str]] = None,
        include_inactive: bool = False,
        min_quality: Optional[float] = None,
        user_id: Optional[int] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """MySQL 关键词搜索

        返回结构:
          [
            {
              "asset": <AssetRegistry>,
              "mysql_score": float,    # 0-1
              "match_reasons": [
                {"source": "mysql", "field": "name", "score": 1.0, "detail": "..."},
                ...
              ]
            },
            ...
          ]
        """
        if not query or not query.strip():
            return []

        kw = f"%{query.strip()}%"
        q = db.query(AssetRegistry).filter(
            AssetRegistry.is_deleted == False  # noqa: E712
        )

        # 用户隔离
        if user_id is not None:
            q = q.filter(AssetRegistry.user_id == user_id)

        # 状态过滤
        if not include_inactive:
            q = q.filter(AssetRegistry.status == AssetRegistryStatus.ACTIVE)
        else:
            q = q.filter(AssetRegistry.status.in_([
                AssetRegistryStatus.DRAFT,
                AssetRegistryStatus.ACTIVE,
                AssetRegistryStatus.DEPRECATED,
            ]))

        # 类型过滤
        if asset_types:
            q = q.filter(AssetRegistry.asset_type.in_(asset_types))

        # 模块过滤
        if module:
            q = q.filter(AssetRegistry.module == module)

        # 标签过滤 (AND, 必须包含所有指定标签)
        if tags:
            for t in tags:
                q = q.filter(AssetRegistry.tags.like(f"%{t}%"))

        # 最低质量评分
        if min_quality is not None:
            q = q.filter(AssetRegistry.quality_score >= min_quality)

        # 关键词匹配 (任一字段命中即返回)
        q = q.filter(or_(
            AssetRegistry.name.ilike(kw),
            AssetRegistry.asset_code.ilike(kw),
            AssetRegistry.summary.ilike(kw),
            AssetRegistry.tags.ilike(kw),
            AssetRegistry.description.ilike(kw),
        ))

        # 取 limit * 3 条 (因为需要评分后再排序截断)
        # 给后续向量/关系融合留余量
        candidates = q.order_by(
            AssetRegistry.quality_score.desc(),
            AssetRegistry.reuse_count.desc(),
        ).limit(limit * 3).all()

        # 计算每条记录的 mysql_score 与命中原因
        results: List[Dict[str, Any]] = []
        query_lower = query.strip().lower()
        for asset in candidates:
            score, reasons = self._compute_mysql_score(asset, query_lower)
            results.append({
                "asset": asset,
                "mysql_score": score,
                "match_reasons": reasons,
            })

        # 按 mysql_score 降序, 取前 limit 条
        results.sort(key=lambda x: x["mysql_score"], reverse=True)
        return results[:limit]

    # ------------------------------------------------------------------
    # 评分计算
    # ------------------------------------------------------------------

    def _compute_mysql_score(
        self,
        asset: AssetRegistry,
        query_lower: str,
    ) -> Tuple[float, List[Dict[str, Any]]]:
        """计算单条资产的 MySQL 匹配得分与命中原因

        规则:
          1. 检查每个字段是否命中 (完全匹配 / 前缀匹配 / 包含匹配)
          2. 取所有命中字段的最大权重作为基础分
          3. 加上匹配模式加成 (完全匹配 +0.1, 前缀匹配 +0.05)
          4. 最终 mysql_score 截断到 [0, 1]
        """
        reasons: List[Dict[str, Any]] = []
        max_score = 0.0

        # 检查各字段
        fields = {
            "name": (asset.name or "").lower(),
            "asset_code": (asset.asset_code or "").lower(),
            "summary": (asset.summary or "").lower(),
            "tags": (asset.tags or "").lower(),
            "description": (asset.description or "").lower(),
        }

        for field_name, value in fields.items():
            if not value:
                continue
            weight = FIELD_WEIGHTS.get(field_name, 0.1)
            hit, mode, detail = self._match_field(value, query_lower)
            if not hit:
                continue

            # 计算该字段得分
            field_score = weight
            if mode == "exact":
                field_score += EXACT_MATCH_BONUS
            elif mode == "prefix":
                field_score += PREFIX_MATCH_BONUS

            if field_score > max_score:
                max_score = field_score

            reasons.append({
                "source": "mysql",
                "field": field_name,
                "score": min(field_score, 1.0),
                "detail": detail,
            })

        # 截断到 [0, 1]
        final_score = min(max_score, 1.0)
        return final_score, reasons

    def _match_field(
        self,
        value: str,
        query: str,
    ) -> Tuple[bool, str, str]:
        """匹配字段值

        返回 (hit, mode, detail):
          - mode: "exact" / "prefix" / "contains"
          - detail: 命中详情 (用于可解释性)
        """
        if not value or not query:
            return False, "", ""

        # 完全匹配
        if value == query:
            return True, "exact", f"完全匹配: '{query}'"

        # 前缀匹配
        if value.startswith(query):
            return True, "prefix", f"前缀匹配: '{value[:len(query) + 10]}'"

        # 包含匹配
        if query in value:
            # 取命中位置前后 20 字符作为详情
            idx = value.find(query)
            start = max(0, idx - 10)
            end = min(len(value), idx + len(query) + 10)
            snippet = value[start:end]
            return True, "contains", f"包含匹配: '...{snippet}...'"

        return False, "", ""

    # ------------------------------------------------------------------
    # 反查
    # ------------------------------------------------------------------

    def find_by_ref(
        self,
        db: Session,
        ref_type: str,
        ref_id: int,
        *,
        user_id: Optional[int] = None,
    ) -> Optional[AssetRegistry]:
        """按 ref_type + ref_id 反查资产 (精确匹配)"""
        q = db.query(AssetRegistry).filter(
            AssetRegistry.ref_type == ref_type,
            AssetRegistry.ref_id == ref_id,
            AssetRegistry.is_deleted == False,  # noqa: E712
        )
        if user_id is not None:
            q = q.filter(AssetRegistry.user_id == user_id)
        return q.first()

    def find_by_codes(
        self,
        db: Session,
        asset_codes: List[str],
        *,
        user_id: Optional[int] = None,
    ) -> List[AssetRegistry]:
        """按 asset_code 列表批量查询"""
        if not asset_codes:
            return []
        q = db.query(AssetRegistry).filter(
            AssetRegistry.asset_code.in_(asset_codes),
            AssetRegistry.is_deleted == False,  # noqa: E712
        )
        if user_id is not None:
            q = q.filter(AssetRegistry.user_id == user_id)
        return q.all()

    # ------------------------------------------------------------------
    # 三源融合辅助
    # ------------------------------------------------------------------

    @staticmethod
    def merge_results(
        mysql_results: List[Dict[str, Any]],
        vector_results: Optional[List[Dict[str, Any]]] = None,
        relation_results: Optional[List[Dict[str, Any]]] = None,
        *,
        weights: Optional[Dict[str, float]] = None,
    ) -> List[Dict[str, Any]]:
        """合并三源搜索结果, 计算 final_score

        每个结果项格式:
          {
            "asset_id": int,
            "mysql_score": float,        # 0-1, 缺失为 0
            "vector_score": Optional[float],  # 0-1, 缺失为 None
            "relation_score": Optional[float],  # 0-1, 缺失为 None
            "match_reasons": [...],
            ...其他字段
          }

        weights 默认:
          mysql=0.5, milvus=0.3, neo4j=0.2

        返回按 final_score 降序排列的合并结果。
        """
        if weights is None:
            weights = {"mysql": 0.5, "milvus": 0.3, "neo4j": 0.2}

        # 以 asset_id 为键合并
        merged: Dict[int, Dict[str, Any]] = {}

        # MySQL 结果
        for item in mysql_results:
            asset = item.get("asset")
            asset_id = asset.id if hasattr(asset, "id") else item.get("asset_id")
            if asset_id is None:
                continue
            merged[asset_id] = {
                "asset_id": asset_id,
                "asset": asset,
                "mysql_score": item.get("mysql_score", 0.0),
                "vector_score": None,
                "relation_score": None,
                "match_reasons": item.get("match_reasons", []),
            }

        # Milvus 结果 (Phase 3 由 AssetSearchAgent 提供)
        if vector_results:
            for item in vector_results:
                asset_id = item.get("asset_id")
                if asset_id is None:
                    continue
                if asset_id not in merged:
                    merged[asset_id] = {
                        "asset_id": asset_id,
                        "asset": item.get("asset"),
                        "mysql_score": 0.0,
                        "vector_score": None,
                        "relation_score": None,
                        "match_reasons": [],
                    }
                merged[asset_id]["vector_score"] = item.get("vector_score", 0.0)
                merged[asset_id]["match_reasons"].extend(
                    item.get("match_reasons", [])
                )

        # Neo4j 结果 (Phase 3 由 AssetSearchAgent 提供)
        if relation_results:
            for item in relation_results:
                asset_id = item.get("asset_id")
                if asset_id is None:
                    continue
                if asset_id not in merged:
                    merged[asset_id] = {
                        "asset_id": asset_id,
                        "asset": item.get("asset"),
                        "mysql_score": 0.0,
                        "vector_score": None,
                        "relation_score": None,
                        "match_reasons": [],
                    }
                merged[asset_id]["relation_score"] = item.get("relation_score", 0.0)
                merged[asset_id]["match_reasons"].extend(
                    item.get("match_reasons", [])
                )

        # 计算 final_score
        for asset_id, item in merged.items():
            mysql_s = item.get("mysql_score", 0.0) or 0.0
            vector_s = item.get("vector_score")
            relation_s = item.get("relation_score")

            # 缺失源不参与计算 (权重归一化)
            used_weights = {}
            used_scores = {}
            used_weights["mysql"] = weights["mysql"]
            used_scores["mysql"] = mysql_s
            total_w = weights["mysql"]

            if vector_s is not None:
                used_weights["milvus"] = weights["milvus"]
                used_scores["milvus"] = vector_s
                total_w += weights["milvus"]

            if relation_s is not None:
                used_weights["neo4j"] = weights["neo4j"]
                used_scores["neo4j"] = relation_s
                total_w += weights["neo4j"]

            if total_w > 0:
                final_score = sum(
                    used_scores[k] * used_weights[k] for k in used_scores
                ) / total_w
            else:
                final_score = 0.0

            item["final_score"] = min(final_score, 1.0)

        # 按 final_score 降序
        result_list = list(merged.values())
        result_list.sort(key=lambda x: x.get("final_score", 0.0), reverse=True)
        return result_list
