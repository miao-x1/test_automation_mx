"""
PageRelation - 页面关联模型

记录页面之间的关联关系，用于构建多页面测试流程。

关系类型：
- navigation: 页面跳转（点击链接/按钮跳转到另一页面）
- form_submit: 表单提交（提交后跳转）
- redirect: 重定向
- flow: 业务流程（同一业务流中的先后页面）
- dependency: 依赖关系（页面B依赖页面A的数据/状态）
"""
from sqlalchemy import Column, Integer, String, Float, Text, ForeignKey, Index
from app.models.base import BaseModel


class PageRelation(BaseModel):
    """页面关联关系"""
    __tablename__ = "page_relation"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")

    # 关联的任务
    task_id = Column(
        Integer,
        ForeignKey("task.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联任务ID"
    )

    # 源页面
    source_page = Column(
        String(500),
        nullable=False,
        comment="源页面标识（URL或页面名称）"
    )

    source_page_title = Column(
        String(200),
        nullable=True,
        comment="源页面标题"
    )

    # 目标页面
    target_page = Column(
        String(500),
        nullable=False,
        comment="目标页面标识（URL或页面名称）"
    )

    target_page_title = Column(
        String(200),
        nullable=True,
        comment="目标页面标题"
    )

    # 关系类型
    relation_type = Column(
        String(50),
        nullable=False,
        default="navigation",
        comment="关系类型: navigation/form_submit/redirect/flow/dependency"
    )

    # 置信度
    confidence = Column(
        Float,
        nullable=False,
        default=0.5,
        comment="关联置信度 0-1"
    )

    # 触发条件（什么操作导致从source到target）
    trigger = Column(
        String(500),
        nullable=True,
        comment="触发条件（如：点击登录按钮）"
    )

    trigger_locator = Column(
        String(500),
        nullable=True,
        comment="触发元素的定位器"
    )

    # 排序（同一任务内的页面顺序）
    sort_order = Column(
        Integer,
        nullable=False,
        default=0,
        comment="排序序号（同一任务内）"
    )

    # 额外元数据
    metadata_json = Column(
        Text,
        nullable=True,
        comment="额外元数据(JSON)"
    )

    # 索引
    __table_args__ = (
        Index('idx_page_relation_task', 'task_id'),
        Index('idx_page_relation_source', 'source_page'),
        Index('idx_page_relation_target', 'target_page'),
    )

    def to_dict(self):
        """转换为字典"""
        import json
        result = {}
        for column in self.__table__.columns:
            val = getattr(self, column.name)
            if column.name == 'metadata_json' and val:
                try:
                    val = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass
            result[column.name] = val
        return result
