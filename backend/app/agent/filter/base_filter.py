"""
BaseFilter — Agent 数据过滤基类

设计原则:
    1. 输入: Agent 完整输出 (dict)
    2. 输出: 下游 Agent 需要的数据 (dict)
    3. 支持白名单 (keep_fields) 和黑名单 (drop_fields) 双模式
    4. 支持深度字段过滤 (如 "scripts[].script_content" 删除列表项内字段)
    5. 记录过滤效果 (原始大小 / 过滤后大小 / 压缩比)

使用方式:
    class MyFilter(BaseFilter):
        keep_fields = {"method", "url", "headers"}
        drop_fields = {"raw_text", "debug_info"}

    filter = MyFilter()
    result = filter.apply(agent_output)
    # result.data — 过滤后数据
    # result.metrics — 过滤效果统计
"""
import copy
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class FilterMetrics:
    """过滤效果统计"""
    filter_name: str = ""
    original_size_bytes: int = 0
    filtered_size_bytes: int = 0
    original_field_count: int = 0
    filtered_field_count: int = 0
    dropped_fields: List[str] = field(default_factory=list)
    dropped_deep_fields: List[str] = field(default_factory=list)
    duration_ms: float = 0.0

    @property
    def reduction_ratio(self) -> float:
        """压缩比 (0-1, 越大表示过滤掉越多)"""
        if self.original_size_bytes == 0:
            return 0.0
        return round(1.0 - self.filtered_size_bytes / self.original_size_bytes, 4)

    @property
    def saved_bytes(self) -> int:
        return self.original_size_bytes - self.filtered_size_bytes

    def to_dict(self) -> Dict[str, Any]:
        return {
            "filter_name": self.filter_name,
            "original_size_bytes": self.original_size_bytes,
            "filtered_size_bytes": self.filtered_size_bytes,
            "original_field_count": self.original_field_count,
            "filtered_field_count": self.filtered_field_count,
            "dropped_fields": self.dropped_fields,
            "dropped_deep_fields": self.dropped_deep_fields,
            "reduction_ratio": self.reduction_ratio,
            "saved_bytes": self.saved_bytes,
            "duration_ms": self.duration_ms,
        }


@dataclass
class FilterResult:
    """过滤结果"""
    data: Dict[str, Any] = field(default_factory=dict)
    metrics: FilterMetrics = field(default_factory=FilterMetrics)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "data": self.data,
            "metrics": self.metrics.to_dict(),
        }


def _measure_size(data: Any) -> int:
    """测量数据序列化后的字节大小"""
    try:
        return len(json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"))
    except (TypeError, ValueError):
        return len(str(data).encode("utf-8"))


def _count_fields(data: Dict[str, Any]) -> int:
    """递归统计字段数量"""
    count = 0
    for key, value in data.items():
        count += 1
        if isinstance(value, dict):
            count += _count_fields(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    count += _count_fields(item)
    return count


def _deep_drop(data: Any, field_path: str) -> bool:
    """深度删除字段

    路径格式:
        "scripts[].script_content" — 删除列表中每项的 script_content
        "metadata.apis"            — 删除嵌套字典的 apis
        "cases[].steps[].description" — 删除嵌套列表中的字段
    """
    parts = field_path.split(".")
    return _deep_drop_recursive(data, parts)


def _deep_drop_recursive(data: Any, parts: List[str]) -> bool:
    if not parts:
        return False

    part = parts[0]
    rest = parts[1:]

    if part.endswith("[]"):
        # 列表处理
        key = part[:-2]
        if isinstance(data, dict) and key in data and isinstance(data[key], list):
            if not rest:
                del data[key]
                return True
            for item in data[key]:
                if isinstance(item, dict):
                    _deep_drop_recursive(item, rest)
            return True
    elif isinstance(data, dict):
        if not rest:
            if part in data:
                del data[part]
                return True
            return False
        if part in data:
            return _deep_drop_recursive(data[part], rest)

    return False


class BaseFilter(ABC):
    """Agent 数据过滤基类

    子类通过设置以下类属性定义过滤规则:
        keep_fields:    白名单 — 只保留这些顶层字段 (优先于 drop_fields)
        drop_fields:    黑名单 — 删除这些顶层字段
        deep_drop_fields: 深度删除 — 删除嵌套字段 (如 "scripts[].script_content")
        truncate_fields: 截断 — 对大文本字段截断到指定长度

    若 keep_fields 非空, 则使用白名单模式 (只保留 keep_fields 中的字段)。
    否则使用黑名单模式 (删除 drop_fields 中的字段)。
    """

    # 过滤器名称
    name: str = "BaseFilter"

    # 白名单: 只保留这些顶层字段 (设置后 drop_fields 被忽略)
    keep_fields: Set[str] = set()

    # 黑名单: 删除这些顶层字段 (keep_fields 为空时生效)
    drop_fields: Set[str] = set()

    # 深度删除: 删除嵌套字段 (格式: "list_key[].field" 或 "dict.key")
    deep_drop_fields: Set[str] = set()

    # 截断: {field_name: max_length} — 对大文本字段截断
    truncate_fields: Dict[str, int] = {}

    # 描述
    description: str = ""

    def apply(self, data: Dict[str, Any]) -> FilterResult:
        """执行过滤

        Args:
            data: Agent 完整输出
        Returns:
            FilterResult: 过滤后数据 + 效果统计
        """
        start_time = time.time()
        metrics = FilterMetrics(filter_name=self.name)

        # 测量原始数据
        metrics.original_size_bytes = _measure_size(data)
        metrics.original_field_count = _count_fields(data) if isinstance(data, dict) else 0

        # 深拷贝 (不修改原始数据)
        filtered = copy.deepcopy(data) if isinstance(data, dict) else {}

        if not isinstance(filtered, dict):
            filtered = {"data": filtered}

        # 执行子类自定义预处理
        filtered = self.pre_process(filtered)

        dropped: List[str] = []

        if self.keep_fields:
            # 白名单模式: 只保留 keep_fields 中的字段
            all_keys = set(filtered.keys())
            to_drop = all_keys - self.keep_fields
            for key in to_drop:
                dropped.append(key)
                filtered.pop(key, None)
        else:
            # 黑名单模式: 删除 drop_fields
            for key in self.drop_fields:
                if key in filtered:
                    dropped.append(key)
                    filtered.pop(key, None)

        # 深度删除嵌套字段
        dropped_deep: List[str] = []
        for path in self.deep_drop_fields:
            if _deep_drop(filtered, path):
                dropped_deep.append(path)

        # 截断大文本字段
        for field_name, max_len in self.truncate_fields.items():
            if field_name in filtered and isinstance(filtered[field_name], str):
                if len(filtered[field_name]) > max_len:
                    filtered[field_name] = (
                        filtered[field_name][:max_len] + "...[truncated]"
                    )
                    dropped_deep.append(f"{field_name}(truncated to {max_len})")

        # 执行子类自定义后处理
        filtered = self.post_process(filtered)

        # 测量过滤后数据
        metrics.filtered_size_bytes = _measure_size(filtered)
        metrics.filtered_field_count = _count_fields(filtered)
        metrics.dropped_fields = dropped
        metrics.dropped_deep_fields = dropped_deep
        metrics.duration_ms = round((time.time() - start_time) * 1000, 2)

        logger.info(
            f"[Filter:{self.name}] "
            f"{metrics.original_size_bytes}B → {metrics.filtered_size_bytes}B "
            f"(减少 {metrics.reduction_ratio*100:.1f}%, "
            f"删除 {len(dropped)} 顶层字段 + {len(dropped_deep)} 深度字段)"
        )

        return FilterResult(data=filtered, metrics=metrics)

    def pre_process(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """预处理 — 子类可重写"""
        return data

    def post_process(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """后处理 — 子类可重写"""
        return data

    def apply_to_workflow(self, state_data: Dict[str, Any]) -> Dict[str, Any]:
        """便捷方法: 过滤并只返回数据 (不含 metrics)

        适用于 FilterNode 的 filter_func 调用。
        """
        result = self.apply(state_data)
        # 将 metrics 存入 metadata 供后续查询
        result.data.setdefault("_filter_metrics", result.metrics.to_dict())
        return result.data
