"""
页面关联 API

提供：
- GET  /api/page-relation/task/{task_id}  — 获取任务的页面关联
- POST /api/page-relation/discover         — 自动发现关联页面
- POST /api/page-relation/                 — 手动创建关联
- PUT  /api/page-relation/{id}/sort        — 更新排序
- DELETE /api/page-relation/{id}           — 删除关联
- POST /api/page-relation/build-flow       — 构建完整流程
- GET  /api/page-relation/history          — 获取历史页面流程
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.models.user import User
from app.models.page_relation import PageRelation
from app.api.auth import require_auth
from app.core.logger import log
from app.runtime.agent_factory import AgentFactory

router = APIRouter(tags=["页面关联"])


class CreateRelationRequest(BaseModel):
    task_id: int
    source_page: str
    source_page_title: Optional[str] = None
    target_page: str
    target_page_title: Optional[str] = None
    relation_type: str = "navigation"
    confidence: float = 0.5
    trigger: Optional[str] = None
    trigger_locator: Optional[str] = None
    sort_order: int = 0


class DiscoverRequest(BaseModel):
    requirement: str
    keywords: Optional[list[str]] = None
    steps: Optional[list[str]] = None
    target_url: Optional[str] = ""


class BuildFlowRequest(BaseModel):
    requirement: str
    task_id: Optional[int] = None
    target_url: Optional[str] = ""


class SortRequest(BaseModel):
    sort_orders: list[dict]  # [{"id": 1, "sort_order": 0}, ...]


class Response(BaseModel):
    code: int = 200
    message: str = "success"
    data: Optional[dict | list] = None


@router.get("/task/{task_id}", summary="获取任务的页面关联")
async def get_task_relations(
    task_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    relations = db.query(PageRelation).filter(
        PageRelation.task_id == task_id
    ).order_by(PageRelation.sort_order).all()

    return Response(data=[r.to_dict() for r in relations])


@router.post("/discover", summary="自动发现关联页面")
async def discover_pages(
    req: DiscoverRequest,
    user: User = Depends(require_auth),
):
    """自动发现需求涉及的页面和关联关系"""
    agent = AgentFactory.create("relation_agent")
    result = agent.find_related_pages(
        requirement=req.requirement,
        keywords=req.keywords or [],
        steps=req.steps or [],
        target_url=req.target_url or "",
    )

    # 排序
    result["pages"] = agent.rank_pages(result["pages"], req.requirement)

    return Response(data=result)


@router.post("/", summary="手动创建页面关联")
async def create_relation(
    req: CreateRelationRequest,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    relation = PageRelation(
        task_id=req.task_id,
        source_page=req.source_page,
        source_page_title=req.source_page_title,
        target_page=req.target_page,
        target_page_title=req.target_page_title,
        relation_type=req.relation_type,
        confidence=req.confidence,
        trigger=req.trigger,
        trigger_locator=req.trigger_locator,
        sort_order=req.sort_order,
    )
    db.add(relation)
    db.commit()
    db.refresh(relation)
    return Response(data=relation.to_dict())


@router.put("/{relation_id}/sort", summary="更新排序")
async def update_sort(
    relation_id: int,
    sort_order: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    relation = db.query(PageRelation).filter(PageRelation.id == relation_id).first()
    if not relation:
        raise HTTPException(status_code=404, detail="关联不存在")
    relation.sort_order = sort_order
    db.commit()
    return Response(message="排序更新成功")


@router.delete("/{relation_id}", summary="删除页面关联")
async def delete_relation(
    relation_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    relation = db.query(PageRelation).filter(PageRelation.id == relation_id).first()
    if not relation:
        raise HTTPException(status_code=404, detail="关联不存在")
    db.delete(relation)
    db.commit()
    return Response(message="删除成功")


@router.post("/build-flow", summary="构建完整页面流程")
async def build_flow(
    req: BuildFlowRequest,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """
    构建完整的页面测试流程

    整合：页面关联 + RAG元素 + Graph推理 → 完整page_flow
    """
    agent = AgentFactory.create("relation_agent")

    # 1. 发现关联页面
    discover_result = agent.find_related_pages(
        requirement=req.requirement,
        target_url=req.target_url or "",
    )

    pages = discover_result["pages"]
    relations = discover_result["relations"]

    # 2. 如果有task_id，加载已保存的关联
    if req.task_id:
        saved_relations = db.query(PageRelation).filter(
            PageRelation.task_id == req.task_id
        ).order_by(PageRelation.sort_order).all()

        for sr in saved_relations:
            # 补充已保存的关联到发现结果
            relations.append({
                "source": sr.source_page,
                "source_title": sr.source_page_title,
                "target": sr.target_page,
                "target_title": sr.target_page_title,
                "type": sr.relation_type,
                "confidence": sr.confidence,
                "trigger": sr.trigger,
                "trigger_locator": sr.trigger_locator,
            })

    # 3. 构建流程
    flow = agent.build_flow(
        requirement=req.requirement,
        pages=pages,
        relations=relations,
        target_url=req.target_url or "",
    )

    # 4. 如果有task_id，保存关联关系到数据库
    if req.task_id and relations:
        # 先清除旧关联
        db.query(PageRelation).filter(PageRelation.task_id == req.task_id).delete()
        agent.save_relations(db, req.task_id, relations)

    return Response(data=flow)


@router.get("/history", summary="获取历史页面流程")
async def get_history_flows(
    limit: int = 10,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """获取用户的历史页面流程（用于"历史流程"选择）"""
    from app.models.task import Task
    from sqlalchemy import func

    # 查询有关联关系的任务
    tasks_with_relations = (
        db.query(Task.id, Task.task_name, Task.created_at)
        .join(PageRelation, PageRelation.task_id == Task.id)
        .filter(Task.user_id == user.id)
        .group_by(Task.id)
        .order_by(Task.created_at.desc())
        .limit(limit)
        .all()
    )

    result = []
    for task_id, task_name, created_at in tasks_with_relations:
        relations = db.query(PageRelation).filter(
            PageRelation.task_id == task_id
        ).order_by(PageRelation.sort_order).all()

        page_names = []
        for r in relations:
            if r.source_page_title and r.source_page_title not in page_names:
                page_names.append(r.source_page_title)
            if r.target_page_title and r.target_page_title not in page_names:
                page_names.append(r.target_page_title)

        result.append({
            "task_id": task_id,
            "task_name": task_name,
            "page_count": len(page_names),
            "page_names": page_names,
            "created_at": str(created_at) if created_at else "",
        })

    return Response(data=result)
