"""
MindMapAgent - 思维导图生成Agent

职责：根据测试用例生成思维导图数据结构

输出格式（兼容多种前端渲染库）：
{
    "name": "根节点",
    "children": [
        {
            "name": "功能测试",
            "children": [
                {"name": "用例1", "priority": "high"},
                {"name": "用例2", "priority": "medium"}
            ]
        }
    ]
}
"""
import json
from typing import Any, Dict, List
from app.core.logger import log
from app.agent.core.base import BaseAgent


class MindMapAgent(BaseAgent):
    """思维导图生成Agent"""

    agent_name = "mindmap"

    def __init__(self):
        super().__init__()
        self.model = None

    def execute(self, **kwargs) -> Any:
        """统一执行入口"""
        return self.generate(**kwargs)

    def generate(
        self,
        title: str = "测试用例",
        cases: List[Dict[str, Any]] = None,
        group_by: str = "case_type",  # case_type / priority / tags
    ) -> Dict[str, Any]:
        """
        生成思维导图数据

        Args:
            title: 根节点标题
            cases: 用例列表
            group_by: 分组维度 (case_type/priority/tags)

        Returns:
            思维导图数据结构
        """
        if not cases:
            cases = []

        log.info(f"MindMapAgent | 生成思维导图 | cases={len(cases)}, group_by={group_by}")

        if group_by == "case_type":
            data = self._group_by_type(title, cases)
        elif group_by == "priority":
            data = self._group_by_priority(title, cases)
        elif group_by == "tags":
            data = self._group_by_tags(title, cases)
        else:
            data = self._group_by_type(title, cases)

        self.emit("generated", {"group_by": group_by, "case_count": len(cases)})
        return data

    def _group_by_type(self, title: str, cases: List[Dict]) -> Dict:
        """按用例类型分组"""
        type_labels = {
            "functional": "功能测试",
            "error": "异常测试",
            "boundary": "边界测试",
        }
        groups = {}
        for c in cases:
            ct = c.get("case_type", "functional")
            if ct not in groups:
                groups[ct] = []
            groups[ct].append({
                "name": c.get("title", "未命名"),
                "priority": c.get("priority", "medium"),
            })

        children = []
        for ct, items in groups.items():
            children.append({
                "name": type_labels.get(ct, ct),
                "children": items,
            })

        return {"name": title, "children": children}

    def _group_by_priority(self, title: str, cases: List[Dict]) -> Dict:
        """按优先级分组"""
        priority_labels = {"high": "高优先级", "medium": "中优先级", "low": "低优先级"}
        groups = {}
        for c in cases:
            p = c.get("priority", "medium")
            if p not in groups:
                groups[p] = []
            groups[p].append({
                "name": c.get("title", "未命名"),
                "case_type": c.get("case_type", "functional"),
            })

        children = []
        for p in ("high", "medium", "low"):
            if p in groups:
                children.append({
                    "name": priority_labels.get(p, p),
                    "children": groups[p],
                })

        return {"name": title, "children": children}

    def _group_by_tags(self, title: str, cases: List[Dict]) -> Dict:
        """按标签分组"""
        groups = {}
        for c in cases:
            tags_str = c.get("tags", "")
            tag_list = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else ["未标记"]
            for tag in tag_list:
                if tag not in groups:
                    groups[tag] = []
                groups[tag].append({
                    "name": c.get("title", "未命名"),
                    "priority": c.get("priority", "medium"),
                })

        children = [{"name": tag, "children": items} for tag, items in groups.items()]
        return {"name": title, "children": children}
