"""
测试用例生成 API

提供3个端点：
- POST /api/v1/testcase/generate: 开始测试用例生成
- GET /api/v1/testcase/{task_id}: 查询生成结果
- GET /api/v1/testcase/mindmap/{task_id}: 获取思维导图数据

流程：
    用户输入需求 → TaskOrchestrator编排 → 4个Agent执行 → 结果存数据库 → 返回
"""
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.runtime import get_task_runtime
from app.db.database import SessionLocal

logger = logging.getLogger(__name__)
router = APIRouter()


# ================================================================== #
#  请求/响应模型                                                       #
# ================================================================== #

class GenerateRequest(BaseModel):
    """测试用例生成请求"""
    requirement: str = Field(..., description="需求文本")
    task_id: str = Field(default="", description="任务ID（可选，不传则自动生成）")
    source_type: str = Field(default="text", description="需求来源: text/image/pdf/word/api_doc/db_schema")
    document_context: str = Field(default="", description="文档解析结果（可选）")
    image_description: str = Field(default="", description="图片描述信息（可选）")
    workflow_name: str = Field(default="testcase_generation", description="工作流名称")


class GenerateResponse(BaseModel):
    """测试用例生成响应"""
    session_id: str
    task_id: str
    status: str
    workflow: str
    requirement_id: int = Field(default=0, description="创建的需求记录ID")
    total_points: int = Field(default=0, description="测试点数")
    total_cases: int = Field(default=0, description="用例数")
    avg_score: float = Field(default=0.0, description="平均审核分")
    duration: float = Field(default=0.0, description="总耗时（秒）")
    error: str = Field(default="", description="错误信息")


class TestCaseStep(BaseModel):
    """测试步骤"""
    step_no: int = 0
    action: str = ""
    description: str = ""
    target: str = ""
    value: str = ""
    expected: str = ""


class TestCaseItem(BaseModel):
    """测试用例项"""
    id: int = 0
    point_id: int = 0
    case_name: str = ""
    precondition: str = ""
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    expected_result: str = ""
    priority: str = "P1"
    type: str = "functional"
    status: str = "draft"
    review_score: float = 0.0
    review_result: str = ""
    review_suggestions: List[str] = Field(default_factory=list)


class TestCaseResult(BaseModel):
    """测试用例查询结果"""
    requirement: Optional[Dict[str, Any]] = None
    test_points: List[Dict[str, Any]] = Field(default_factory=list)
    test_cases: List[TestCaseItem] = Field(default_factory=list)
    total: int = 0


class MindMapNode(BaseModel):
    """思维导图节点"""
    name: str
    children: List["MindMapNode"] = Field(default_factory=list)


# ================================================================== #
#  API 端点                                                           #
# ================================================================== #

@router.post("/testcase/generate", response_model=GenerateResponse)
async def generate_test_cases(request: GenerateRequest):
    """
    开始测试用例生成

    流程：
        1. 通过TaskOrchestrator执行testcase_generation工作流
        2. 工作流包含4个Agent：需求解析→测试点分析→用例生成→用例审核
        3. 结果自动保存到数据库
    """
    # 构建需求输入
    requirement_text = request.requirement
    if request.document_context:
        requirement_text += f"\n\n[文档信息]\n{request.document_context}"
    if request.image_description:
        requirement_text += f"\n\n[截图描述]\n{request.image_description}"

    try:
        # 执行工作流
        task_runtime = get_task_runtime()
        result = await task_runtime.execute_pipeline(
            steps=[
                {"agent_type": "requirement_analysis_agent", "action": "execute",
                 "payload": {"requirement": requirement_text}, "output_key": "requirement_analysis"},
                {"agent_type": "test_point_analysis_agent", "action": "execute",
                 "input_keys": ["requirement_analysis"], "output_key": "test_points"},
                {"agent_type": "testcase_generator_agent", "action": "execute",
                 "input_keys": ["requirement_analysis", "test_points"], "output_key": "test_cases"},
                {"agent_type": "testcase_review_agent", "action": "execute",
                 "input_keys": ["test_cases"], "output_key": "reviews"},
            ],
            user_id=0,
            session_id=str(request.task_id) if request.task_id else "",
        )

        if result.get("status") == "failed":
            return GenerateResponse(
                session_id=result.get("session_id", ""),
                task_id=request.task_id or "",
                status="failed",
                workflow=request.workflow_name,
                error=result.get("error", "未知错误"),
            )

        # 保存结果到数据库
        requirement_id = await _save_results(
            task_id=request.task_id or "",
            session_id=result.get("session_id", ""),
            requirement_text=request.requirement,
            source_type=request.source_type,
            workflow_result=result,
        )

        # 统计
        context = result.get("context", {})
        test_points_data = context.get("test_points", {}).get("test_points", [])
        test_cases_data = context.get("test_cases", {}).get("test_cases", [])
        reviews_data = context.get("reviews", {})
        avg_score = reviews_data.get("avg_score", 0.0) if isinstance(reviews_data, dict) else 0.0

        return GenerateResponse(
            session_id=result.get("session_id", ""),
            task_id=request.task_id or "",
            status="completed",
            workflow=request.workflow_name,
            requirement_id=requirement_id,
            total_points=len(test_points_data),
            total_cases=len(test_cases_data),
            avg_score=avg_score,
            duration=result.get("duration", 0.0),
        )

    except Exception as e:
        logger.error(f"[TestCaseAPI] 生成失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"生成失败: {e}")


@router.get("/testcase/{task_id}", response_model=TestCaseResult)
async def get_test_cases(task_id: str):
    """
    查询测试用例生成结果

    返回：需求信息 + 测试点列表 + 测试用例列表（含审核结果）
    """
    db = SessionLocal()
    try:
        from app.models.test_requirement import TestRequirement
        from app.models.test_case_point import TestCasePoint
        from app.models.test_case import TestCase
        from app.models.test_case_review import TestCaseReview

        # 查询需求
        requirement = db.query(TestRequirement).filter(
            TestRequirement.task_id == task_id
        ).first()

        if not requirement:
            raise HTTPException(status_code=404, detail=f"未找到task_id={task_id}的记录")

        # 查询测试点
        points = db.query(TestCasePoint).filter(
            TestCasePoint.requirement_id == requirement.id,
            TestCasePoint.is_deleted == False,
        ).all()

        # 查询用例
        point_ids = [p.id for p in points]
        cases = db.query(TestCase).filter(
            TestCase.point_id.in_(point_ids),
            TestCase.is_deleted == False,
        ).all() if point_ids else []

        # 查询审核结果
        case_ids = [c.id for c in cases]
        reviews = db.query(TestCaseReview).filter(
            TestCaseReview.case_id.in_(case_ids),
        ).all() if case_ids else []

        # 构建审核映射
        review_map = {r.case_id: r for r in reviews}

        # 构建响应
        test_case_items = []
        for case in cases:
            review = review_map.get(case.id)
            steps = []
            if case.steps:
                try:
                    steps = json.loads(case.steps) if isinstance(case.steps, str) else case.steps
                except json.JSONDecodeError:
                    steps = []

            test_case_items.append(TestCaseItem(
                id=case.id,
                point_id=case.point_id,
                case_name=case.case_name,
                precondition=case.precondition or "",
                steps=steps if isinstance(steps, list) else [],
                expected_result=case.expected_result or "",
                priority=case.priority,
                type=case.type,
                status=case.status,
                review_score=review.score if review else 0.0,
                review_result=review.review_result if review else "",
                review_suggestions=json.loads(review.suggestion) if review and review.suggestion else [],
            ))

        # 解析需求信息
        req_data = {
            "id": requirement.id,
            "task_id": requirement.task_id,
            "content": requirement.content,
            "source_type": requirement.source_type,
            "status": requirement.status,
            "parsed_result": json.loads(requirement.parsed_result) if requirement.parsed_result else None,
        }

        # 测试点列表
        point_list = []
        for p in points:
            point_list.append({
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "priority": p.priority,
                "type": p.type,
                "scenario": p.scenario,
                "case_count": p.case_count,
            })

        return TestCaseResult(
            requirement=req_data,
            test_points=point_list,
            test_cases=test_case_items,
            total=len(test_case_items),
        )

    finally:
        db.close()


@router.get("/testcase/mindmap/{task_id}")
async def get_mindmap(task_id: str):
    """
    获取思维导图数据

    返回JSON树形结构，可用于前端React Flow或AntV G6渲染。
    """
    db = SessionLocal()
    try:
        from app.models.mind_map import MindMap
        from app.models.test_requirement import TestRequirement
        from app.models.test_case_point import TestCasePoint
        from app.models.test_case import TestCase

        # 查询已有思维导图
        mindmap = db.query(MindMap).filter(
            MindMap.task_id == task_id
        ).order_by(MindMap.version.desc()).first()

        if mindmap and mindmap.content:
            return {
                "task_id": task_id,
                "mindmap": json.loads(mindmap.content),
                "format": mindmap.format,
                "version": mindmap.version,
            }

        # 未找到，从数据库生成
        requirement = db.query(TestRequirement).filter(
            TestRequirement.task_id == task_id
        ).first()

        if not requirement:
            raise HTTPException(status_code=404, detail=f"未找到task_id={task_id}的记录")

        points = db.query(TestCasePoint).filter(
            TestCasePoint.requirement_id == requirement.id,
            TestCasePoint.is_deleted == False,
        ).all()

        point_ids = [p.id for p in points]
        cases = db.query(TestCase).filter(
            TestCase.point_id.in_(point_ids),
            TestCase.is_deleted == False,
        ).all() if point_ids else []

        # 解析需求信息获取业务模块
        business_module = "测试系统"
        if requirement.parsed_result:
            try:
                parsed = json.loads(requirement.parsed_result)
                business_module = parsed.get("business_module", business_module)
            except json.JSONDecodeError:
                pass

        # 生成思维导图树
        mindmap_data = _build_mindmap(
            business_module=business_module,
            test_points=points,
            test_cases=cases,
        )

        # 保存到数据库
        new_mindmap = MindMap(
            task_id=task_id,
            content=json.dumps(mindmap_data, ensure_ascii=False),
            format="json",
            version=1,
        )
        db.add(new_mindmap)
        db.commit()

        return {
            "task_id": task_id,
            "mindmap": mindmap_data,
            "format": "json",
            "version": 1,
        }

    finally:
        db.close()


# ================================================================== #
#  PUT / DELETE 端点（阶段四新增）                                       #
# ================================================================== #

class UpdateTestCaseRequest(BaseModel):
    """更新测试用例请求"""
    case_name: str = Field(default="", description="用例名称")
    precondition: str = Field(default="", description="前置条件")
    steps: List[Dict[str, Any]] = Field(default_factory=list, description="测试步骤")
    expected_result: str = Field(default="", description="预期结果")
    priority: str = Field(default="P1", description="优先级")
    type: str = Field(default="functional", description="用例类型")
    status: str = Field(default="draft", description="用例状态")


@router.put("/test-case/{case_id}")
async def update_test_case(case_id: int, request: UpdateTestCaseRequest):
    """
    修改测试用例

    支持人工修改AI生成的测试用例，包括：
    - 用例名称、前置条件、步骤、预期结果
    - 优先级、类型、状态
    - 自动递增版本号
    """
    db = SessionLocal()
    try:
        from app.models.test_case import TestCase

        case = db.query(TestCase).filter(
            TestCase.id == case_id,
            TestCase.is_deleted == False,
        ).first()

        if not case:
            raise HTTPException(status_code=404, detail=f"未找到用例 id={case_id}")

        # 更新字段
        if request.case_name:
            case.case_name = request.case_name
        if request.precondition is not None:
            case.precondition = request.precondition
        if request.steps:
            case.steps = json.dumps(request.steps, ensure_ascii=False)
        if request.expected_result is not None:
            case.expected_result = request.expected_result
        if request.priority:
            case.priority = request.priority
        if request.type:
            case.type = request.type
        if request.status:
            case.status = request.status

        # 版本递增
        case.version += 1

        db.commit()
        db.refresh(case)

        return {
            "status": "success",
            "case_id": case.id,
            "version": case.version,
            "message": f"用例已更新，当前版本: {case.version}",
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"[TestCaseAPI] 更新用例失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新失败: {e}")
    finally:
        db.close()


@router.delete("/test-case/{case_id}")
async def delete_test_case(case_id: int):
    """
    删除测试用例（软删除）

    将is_deleted设为True，不实际删除数据。
    同时删除关联的审核记录。
    """
    db = SessionLocal()
    try:
        from app.models.test_case import TestCase
        from app.models.test_case_review import TestCaseReview

        case = db.query(TestCase).filter(
            TestCase.id == case_id,
            TestCase.is_deleted == False,
        ).first()

        if not case:
            raise HTTPException(status_code=404, detail=f"未找到用例 id={case_id}")

        # 软删除用例
        case.is_deleted = True

        # 删除关联审核记录
        reviews = db.query(TestCaseReview).filter(
            TestCaseReview.case_id == case_id
        ).all()
        for review in reviews:
            db.delete(review)

        db.commit()

        return {
            "status": "success",
            "case_id": case_id,
            "message": "用例已删除",
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"[TestCaseAPI] 删除用例失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除失败: {e}")
    finally:
        db.close()


@router.post("/test-case/regenerate/{task_id}")
async def regenerate_test_cases(task_id: str):
    """
    重新生成测试用例

    根据已有的task_id重新执行测试用例生成流程。
    会清除旧用例并重新生成。
    """
    db = SessionLocal()
    try:
        from app.models.test_requirement import TestRequirement
        from app.models.test_case import TestCase
        from app.models.test_case_point import TestCasePoint

        # 查询原始需求
        requirement = db.query(TestRequirement).filter(
            TestRequirement.task_id == task_id
        ).first()

        if not requirement:
            raise HTTPException(status_code=404, detail=f"未找到task_id={task_id}的需求记录")

        # 软删除旧用例和测试点
        old_points = db.query(TestCasePoint).filter(
            TestCasePoint.requirement_id == requirement.id,
            TestCasePoint.is_deleted == False,
        ).all()

        for point in old_points:
            point.is_deleted = True
            old_cases = db.query(TestCase).filter(
                TestCase.point_id == point.id,
                TestCase.is_deleted == False,
            ).all()
            for case in old_cases:
                case.is_deleted = True

        db.commit()

        # 重新执行工作流
        task_runtime = get_task_runtime()
        result = await task_runtime.execute_pipeline(
            steps=[
                {"agent_type": "requirement_analysis_agent", "action": "execute",
                 "payload": {"requirement": requirement.content}, "output_key": "requirement_analysis"},
                {"agent_type": "test_point_analysis_agent", "action": "execute",
                 "input_keys": ["requirement_analysis"], "output_key": "test_points"},
                {"agent_type": "testcase_generator_agent", "action": "execute",
                 "input_keys": ["requirement_analysis", "test_points"], "output_key": "test_cases"},
                {"agent_type": "testcase_review_agent", "action": "execute",
                 "input_keys": ["test_cases"], "output_key": "reviews"},
            ],
            user_id=0,
            session_id=str(task_id) if task_id else "",
        )

        return {
            "status": "success" if result.get("status") != "failed" else "failed",
            "task_id": task_id,
            "message": "重新生成完成" if result.get("status") != "failed" else f"重新生成失败: {result.get('error', '')}",
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"[TestCaseAPI] 重新生成失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重新生成失败: {e}")
    finally:
        db.close()


@router.get("/test-case/{task_id}/messages")
async def get_agent_messages(task_id: str):
    """
    获取Agent执行消息日志

    返回该任务所有Agent的消息通信记录，用于前端展示执行过程。
    """
    db = SessionLocal()
    try:
        from app.models.agent_message import AgentMessage

        messages = db.query(AgentMessage).filter(
            AgentMessage.task_id == task_id
        ).order_by(AgentMessage.created_at.asc()).all()

        return {
            "task_id": task_id,
            "messages": [
                {
                    "id": m.id,
                    "message_type": m.message_type,
                    "sender": m.sender,
                    "receiver": m.receiver,
                    "action": m.action,
                    "content": json.loads(m.content) if m.content else None,
                    "result": json.loads(m.result) if m.result else None,
                    "status": m.status,
                    "error": m.error,
                    "duration": m.duration,
                    "step": m.step,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in messages
            ],
            "total": len(messages),
        }

    finally:
        db.close()

async def _save_results(
    task_id: str,
    session_id: str,
    requirement_text: str,
    source_type: str,
    workflow_result: Dict[str, Any],
) -> int:
    """保存工作流结果到数据库

    Returns:
        requirement_id: 创建的需求记录ID
    """
    db = SessionLocal()
    try:
        from app.models.test_requirement import TestRequirement
        from app.models.test_case_point import TestCasePoint
        from app.models.test_case import TestCase
        from app.models.test_case_review import TestCaseReview
        from app.models.mind_map import MindMap

        context = workflow_result.get("context", {})

        # 1. 保存需求
        req_analysis = context.get("requirement_analysis", {})
        parsed_result = json.dumps(req_analysis, ensure_ascii=False) if req_analysis else None

        requirement = TestRequirement(
            task_id=task_id,
            content=requirement_text,
            source_type=source_type,
            parsed_result=parsed_result,
            status="completed",
        )
        db.add(requirement)
        db.flush()  # 获取ID

        # 2. 保存测试点
        test_points_data = context.get("test_points", {}).get("test_points", [])
        point_ids = []
        for tp in test_points_data:
            point = TestCasePoint(
                requirement_id=requirement.id,
                name=tp.get("name", ""),
                description=tp.get("description", ""),
                priority=tp.get("priority", "P1"),
                type=tp.get("type", "functional"),
                scenario=tp.get("scenario", ""),
                expected_behavior=tp.get("expected_behavior", ""),
            )
            db.add(point)
            db.flush()
            point_ids.append((point.id, tp))

        # 3. 保存测试用例
        test_cases_data = context.get("test_cases", {}).get("test_cases", [])
        case_ids = []
        for case_data in test_cases_data:
            # 找到对应的测试点
            point_id = None
            for pid, tp in point_ids:
                if tp.get("name", "") == case_data.get("case_name", "").split("-")[0].strip():
                    point_id = pid
                    break
            if point_id is None and point_ids:
                point_id = point_ids[0][0]

            case = TestCase(
                task_id=task_id,
                point_id=point_id or 0,
                case_name=case_data.get("case_name", ""),
                precondition=case_data.get("precondition", ""),
                steps=json.dumps(case_data.get("steps", []), ensure_ascii=False),
                expected_result=case_data.get("expected_result", ""),
                priority=case_data.get("priority", "P1"),
                type=case_data.get("type", "functional"),
                status="draft",
                rag_references=json.dumps(case_data.get("rag_references", []), ensure_ascii=False) if case_data.get("rag_references") else None,
            )
            db.add(case)
            db.flush()
            case_ids.append((case.id, case_data))

        # 4. 保存审核结果
        reviews_data = context.get("reviews", {})
        if isinstance(reviews_data, dict) and "reviews" in reviews_data:
            reviews_list = reviews_data["reviews"]
            for review_data in reviews_list:
                # 找到对应的用例
                case_id = None
                for cid, cd in case_ids:
                    if cd.get("case_name", "") == review_data.get("case_name", ""):
                        case_id = cid
                        break
                if case_id is None and case_ids:
                    case_id = case_ids[0][0]

                review = TestCaseReview(
                    case_id=case_id or 0,
                    score=review_data.get("score", 0),
                    review_result=review_data.get("review_result", "need_revision"),
                    suggestion=json.dumps(review_data.get("suggestions", []), ensure_ascii=False),
                    issues=json.dumps(review_data.get("issues", []), ensure_ascii=False),
                )
                db.add(review)

        # 5. 生成并保存思维导图
        business_module = req_analysis.get("business_module", "测试系统") if req_analysis else "测试系统"
        points_for_mm = db.query(TestCasePoint).filter(
            TestCasePoint.requirement_id == requirement.id
        ).all()
        cases_for_mm = db.query(TestCase).filter(
            TestCase.point_id.in_([p.id for p in points_for_mm])
        ).all() if points_for_mm else []

        mindmap_data = _build_mindmap(
            business_module=business_module,
            test_points=points_for_mm,
            test_cases=cases_for_mm,
        )

        mindmap = MindMap(
            task_id=task_id,
            content=json.dumps(mindmap_data, ensure_ascii=False),
            format="json",
            version=1,
        )
        db.add(mindmap)

        db.commit()
        logger.info(
            f"[TestCaseAPI] 结果已保存 | requirement_id={requirement.id} | "
            f"points={len(test_points_data)} | cases={len(test_cases_data)}"
        )
        return requirement.id

    except Exception as e:
        db.rollback()
        logger.error(f"[TestCaseAPI] 保存结果失败: {e}", exc_info=True)
        return 0
    finally:
        db.close()


def _build_mindmap(
    business_module: str,
    test_points: List[Any],
    test_cases: List[Any],
) -> Dict[str, Any]:
    """
    构建思维导图树形结构

    结构：
        业务模块
          ├── 测试类型1（功能测试）
          │   ├── 测试点1
          │   │   ├── 用例1
          │   │   └── 用例2
          │   └── 测试点2
          ├── 测试类型2（异常测试）
          │   └── 测试点3
          └── ...
    """
    # 按测试类型分组测试点
    type_groups: Dict[str, List[Any]] = {}
    for point in test_points:
        ptype = getattr(point, "type", "functional") or "functional"
        if ptype not in type_groups:
            type_groups[ptype] = []
        type_groups[ptype].append(point)

    type_names = {
        "functional": "功能测试",
        "error": "异常测试",
        "boundary": "边界测试",
        "permission": "权限测试",
        "data_validation": "数据校验",
    }

    type_children = []
    for ptype, points in type_groups.items():
        # 构建测试点的子节点
        point_children = []
        for point in points:
            # 找到该测试点下的用例
            point_cases = [c for c in test_cases if getattr(c, "point_id", None) == getattr(point, "id", None)]
            case_children = []
            for case in point_cases:
                case_children.append({
                    "name": getattr(case, "case_name", ""),
                    "children": [],
                    "priority": getattr(case, "priority", ""),
                    "status": getattr(case, "status", ""),
                })

            point_children.append({
                "name": getattr(point, "name", ""),
                "children": case_children,
                "priority": getattr(point, "priority", ""),
            })

        type_children.append({
            "name": type_names.get(ptype, ptype),
            "children": point_children,
        })

    return {
        "name": business_module,
        "children": type_children,
    }
