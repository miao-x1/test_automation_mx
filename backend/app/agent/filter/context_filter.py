"""
上下文数据过滤器

过滤跨 Agent 传递的上下文数据:

    ContextPayloadFilter — 过滤传递给 Agent 的完整上下文 payload
    GraphStateFilter     — 过滤 WorkflowState.intermediate 中间结果

过滤策略:
    1. 保留当前 Agent 实际需要的 input_keys
    2. 删除中间结果中的大文本和历史日志
    3. 限制传递的上下文深度和大小
"""
import logging
from typing import Any, Dict, List, Set

from app.agent.filter.base_filter import BaseFilter, FilterResult, _measure_size

logger = logging.getLogger(__name__)


class ContextPayloadFilter(BaseFilter):
    """上下文 Payload 过滤器 — 过滤传递给 Agent 的上下文

    场景: 当 WorkflowState.build_payload() 收集了所有中间结果后,
    数据可能非常大。此过滤器根据当前 Agent 的 input_keys 裁剪 payload。

    使用方式:
        filter = ContextPayloadFilter(input_keys={"steps", "elements"})
        filtered = filter.apply(payload)
    """

    name = "ContextPayloadFilter"
    description = "按 Agent input_keys 裁剪上下文 payload"

    def __init__(self, input_keys: Set[str] = None, max_payload_size: int = 50000):
        """
        Args:
            input_keys: 当前 Agent 需要的输入键
            max_payload_size: payload 最大字节数 (超过则触发深度裁剪)
        """
        self._input_keys = input_keys or set()
        self._max_payload_size = max_payload_size
        # 始终保留的字段
        self.keep_fields = {"requirement", "task_id", "action"} | self._input_keys

    def apply(self, data: Dict[str, Any]) -> FilterResult:
        """按 input_keys 裁剪 payload"""
        result = super().apply(data)

        # 如果仍然超过大小限制, 执行深度裁剪
        if result.metrics.filtered_size_bytes > self._max_payload_size:
            result.data = self._deep_truncate(result.data)
            result.metrics.filtered_size_bytes = _measure_size(result.data)

        return result

    def _deep_truncate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """深度裁剪 — 截断列表和长文本"""
        for key, value in list(data.items()):
            if isinstance(value, list) and len(value) > 20:
                # 列表截断到前 20 项
                data[key] = value[:20]
                logger.debug(f"[ContextPayloadFilter] 截断列表 {key}: {len(value)} → 20")
            elif isinstance(value, str) and len(value) > 2000:
                # 长文本截断
                data[key] = value[:2000] + "...[auto-truncated]"
                logger.debug(f"[ContextPayloadFilter] 截断文本 {key}: {len(value)} → 2000")
            elif isinstance(value, dict):
                data[key] = self._deep_truncate(value)

        return data


class GraphStateFilter(BaseFilter):
    """GraphState 中间结果过滤器 — 清理 WorkflowState.intermediate

    场景: 工作流执行多个节点后, intermediate 中积累了大量中间结果。
    此过滤器清理已完成节点中不再需要的大文本数据。

    使用方式:
        filter = GraphStateFilter(completed_nodes=["requirement", "rag"])
        filter.cleanup_intermediate(state.intermediate)
    """

    name = "GraphStateFilter"
    description = "清理 WorkflowState 中间结果中的大文本"

    # 已知的大文本字段 (可配置)
    LARGE_TEXT_FIELDS = {
        "raw_requirement",
        "script_content",
        "business_flow",
        "coverage_notes",
    }

    def __init__(self, preserve_nodes: Set[str] = None):
        """
        Args:
            preserve_nodes: 保留不清理的节点名 (如当前正在执行的节点)
        """
        self._preserve_nodes = preserve_nodes or set()

    def cleanup_intermediate(self, intermediate: Dict[str, Dict]) -> Dict[str, Dict]:
        """清理中间结果中的大文本字段

        Args:
            intermediate: WorkflowState.intermediate
        Returns:
            清理后的 intermediate
        """
        original_size = _measure_size(intermediate)
        cleaned = 0

        for node_name, node_output in intermediate.items():
            if node_name in self._preserve_nodes:
                continue

            if not isinstance(node_output, dict):
                continue

            for field in self.LARGE_TEXT_FIELDS:
                if field in node_output:
                    size = _measure_size(node_output[field])
                    node_output[field] = f"[cleaned: {size}B]"
                    cleaned += 1

        cleaned_size = _measure_size(intermediate)
        logger.info(
            f"[GraphStateFilter] 中间结果清理: "
            f"{original_size}B → {cleaned_size}B "
            f"(清理 {cleaned} 个大文本字段, "
            f"减少 {round(1 - cleaned_size / max(original_size, 1), 4) * 100:.1f}%)"
        )

        return intermediate
