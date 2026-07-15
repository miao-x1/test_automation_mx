"""
思维导图模型

存储测试用例的思维导图数据，用于前端可视化展示。

关系：
  TestRequirement (1) → (1) MindMap

注意：此表与已有的 case_mindmap 表不同：
- case_mindmap: 关联 case_task_id（旧架构）
- mind_map: 关联 task_id（新架构，测试用例生成流程）
"""
from sqlalchemy import Column, String, Text, Integer, Index
from app.models.base import BaseModel


class MindMap(BaseModel):
    """思维导图

    存储测试用例的树形结构数据，用于前端思维导图展示。

    字段说明：
    - task_id: 关联的AgentRuntime任务ID
    - content: 思维导图数据（JSON树形结构）
    - format: 数据格式（json/markdown）
    - version: 版本号
    """
    __tablename__ = "mind_map"

    # 关联信息
    task_id = Column(
        String(64), nullable=False, index=True,
        comment="关联的AgentRuntime任务ID"
    )

    # 内容
    content = Column(
        Text, nullable=True,
        comment="思维导图数据(JSON树形结构)"
    )
    format = Column(
        String(20), nullable=False, default="json",
        comment="数据格式: json/markdown"
    )

    # 版本
    version = Column(
        Integer, nullable=False, default=1,
        comment="版本号"
    )


# 索引
Index("idx_mm_task", MindMap.task_id)
