"""
接口测试 - 用例导入（Swagger/复制）

注意：AI生成已迁移到统一测试资产中心（/assets/v2/）。
本模块只保留 Swagger导入 和 用例复制。
AI导入端点保留兼容，内部重定向到 AssetService。
"""
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel as PydanticModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.response import Response
from app.models.api_case import ApiCase
from app.models.case_content import CaseContent
from app.core.auth import require_auth
from app.models.user import User

router = APIRouter()


# ========== Request Models ==========

class SwaggerImportRequest(PydanticModel):
    swagger_json: Optional[Dict[str, Any]] = None
    base_url: Optional[str] = None
    folder_id: Optional[int] = None


@router.post("/import/ai/{task_id}", summary="从AI生成结果导入（兼容，重定向到统一资产）")
async def import_from_ai(task_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    """
    [兼容] 从AI生成的CaseContent导入为ApiCase

    推荐使用：POST /assets/v2/migrate 迁移到统一资产体系
    """
    # 先尝试迁移到统一资产
    from app.services.assets.migration_service import MigrationService
    MigrationService.migrate_case_content()

    # 兼容旧逻辑
    ccs = db.query(CaseContent).filter(CaseContent.case_task_id == task_id, CaseContent.is_deleted == False).all()
    if not ccs:
        raise HTTPException(status_code=404, detail="未找到该任务下的AI生成用例")

    imported = []
    for cc in ccs:
        # 检查是否已导入（通过case_id去重）
        existing = db.query(ApiCase).filter(
            ApiCase.case_id == f"AI-{cc.id}",
            ApiCase.user_id == user.id,
            ApiCase.is_deleted == False,
        ).first()
        if existing:
            continue

        steps = json.loads(cc.steps) if cc.steps else []
        assertions = json.loads(cc.expected) if cc.expected else []
        if isinstance(assertions, dict):
            assertions = [assertions]

        # 将AI生成的步骤转换为ApiCase格式
        api_steps = []
        for step in steps:
            if isinstance(step, dict):
                api_steps.append(step)
            elif isinstance(step, str):
                api_steps.append({"action": "request", "description": step})

        api_assertions = []
        for assertion in assertions:
            if isinstance(assertion, dict):
                api_assertions.append(assertion)

        case = ApiCase(
            title=cc.title,
            case_id=f"AI-{cc.id}",
            description=cc.precondition,
            priority=cc.priority or "medium",
            status="draft",
            tags=cc.tags,
            precondition=cc.precondition,
            steps=json.dumps(api_steps, ensure_ascii=False),
            assertions=json.dumps(api_assertions, ensure_ascii=False) if api_assertions else None,
            extracts=None,
            user_id=user.id,
            created_by=user.id,
        )
        db.add(case)
        imported.append(case)

    if not imported:
        return Response(code=200, message="所有用例已导入过，无新增", data={"imported_count": 0})

    db.commit()
    for c in imported:
        db.refresh(c)

    return Response(code=200, message=f"成功导入 {len(imported)} 条用例", data={
        "imported_count": len(imported),
        "case_ids": [{"id": c.id, "title": c.title, "case_id": c.case_id} for c in imported],
    })


@router.post("/import/swagger", summary="Swagger/OpenAPI导入")
async def import_from_swagger(req: SwaggerImportRequest, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    """从Swagger/OpenAPI定义导入为ApiCase"""
    if not req.swagger_json:
        raise HTTPException(status_code=400, detail="请提供 swagger_json")

    swagger = req.swagger_json
    paths = swagger.get("paths", {})
    base_url = req.base_url or swagger.get("host", "http://localhost:8080")
    if not base_url.startswith("http"):
        base_url = f"http://{base_url}"
    # 处理 basePath
    base_path = swagger.get("basePath", "")
    if base_path and base_url.endswith(base_path):
        pass
    elif base_path:
        base_url = base_url.rstrip("/") + base_path

    imported = []
    for path, path_item in paths.items():
        for method, operation in path_item.items():
            if method.lower() not in ("get", "post", "put", "delete", "patch", "head", "options"):
                continue

            # 构建用例标题
            title = operation.get("summary") or operation.get("operationId") or f"{method.upper()} {path}"
            case_id_str = operation.get("operationId") or f"SW-{method.upper()}-{path.replace('/', '_').strip('_')}"

            # 构建步骤
            step = {
                "action": method.upper(),
                "url": path,
                "headers": {"Content-Type": "application/json"},
            }

            # 处理请求体
            request_body = operation.get("requestBody")
            if request_body:
                content = request_body.get("content", {})
                json_content = content.get("application/json", {})
                schema_ref = json_content.get("schema", {})
                if schema_ref:
                    step["body"] = _resolve_schema_example(swagger, schema_ref)

            # 处理参数
            parameters = operation.get("parameters", [])
            query_params = {}
            for param in parameters:
                if param.get("in") == "query":
                    query_params[param["name"]] = _get_param_example(param)
            if query_params:
                step["params"] = query_params

            # 构建断言 - 默认检查200响应
            assertions = []
            responses = operation.get("responses", {})
            if "200" in responses or "201" in responses:
                assertions.append({"type": "status", "expected": 200})
            elif responses:
                first_code = list(responses.keys())[0]
                try:
                    assertions.append({"type": "status", "expected": int(first_code)})
                except ValueError:
                    pass

            # 检查是否已导入
            existing = db.query(ApiCase).filter(
                ApiCase.case_id == case_id_str,
                ApiCase.user_id == user.id,
                ApiCase.is_deleted == False,
            ).first()
            if existing:
                continue

            case = ApiCase(
                title=title,
                case_id=case_id_str,
                description=operation.get("description"),
                folder_id=req.folder_id,
                priority="medium",
                status="draft",
                tags=json.dumps(["swagger-import"], ensure_ascii=False),
                steps=json.dumps([step], ensure_ascii=False),
                assertions=json.dumps(assertions, ensure_ascii=False) if assertions else None,
                extracts=None,
                env_override=json.dumps({"base_url": base_url}, ensure_ascii=False),
                user_id=user.id,
                created_by=user.id,
            )
            db.add(case)
            imported.append(case)

    if not imported:
        return Response(code=200, message="所有接口已导入过，无新增", data={"imported_count": 0})

    db.commit()
    for c in imported:
        db.refresh(c)

    return Response(code=200, message=f"成功导入 {len(imported)} 条用例", data={
        "imported_count": len(imported),
        "case_ids": [{"id": c.id, "title": c.title, "case_id": c.case_id} for c in imported],
    })


@router.post("/import/copy/{case_id}", summary="复制用例（导入方式）")
async def import_copy_case(case_id: int, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    """通过导入接口复制用例"""
    import copy

    case = db.query(ApiCase).filter(ApiCase.id == case_id, ApiCase.is_deleted == False).first()
    if not case:
        raise HTTPException(status_code=404, detail="用例不存在")

    steps_data = json.loads(case.steps) if case.steps else []
    assertions_data = json.loads(case.assertions) if case.assertions else []
    extracts_data = json.loads(case.extracts) if case.extracts else []
    env_override_data = json.loads(case.env_override) if case.env_override else None

    new_case = ApiCase(
        title=case.title + "（副本）",
        case_id=case.case_id,
        description=case.description,
        folder_id=case.folder_id,
        priority=case.priority,
        status="draft",
        tags=case.tags,
        precondition=case.precondition,
        steps=json.dumps(copy.deepcopy(steps_data), ensure_ascii=False),
        assertions=json.dumps(copy.deepcopy(assertions_data), ensure_ascii=False) if assertions_data else None,
        extracts=json.dumps(copy.deepcopy(extracts_data), ensure_ascii=False) if extracts_data else None,
        env_override=json.dumps(copy.deepcopy(env_override_data), ensure_ascii=False) if env_override_data else None,
        user_id=user.id,
        created_by=user.id,
    )
    db.add(new_case); db.commit(); db.refresh(new_case)

    return Response(code=200, message="复制成功", data={"id": new_case.id, "title": new_case.title, "status": new_case.status})


# ========== Helper ==========

def _resolve_schema_example(swagger: Dict, schema: Dict) -> Any:
    """尝试从schema中生成示例数据"""
    if "example" in schema:
        return schema["example"]
    if "$ref" in schema:
        ref_path = schema["$ref"]
        parts = ref_path.split("/")
        resolved = swagger
        for part in parts[1:]:  # skip #
            resolved = resolved.get(part, {})
        return _resolve_schema_example(swagger, resolved)
    schema_type = schema.get("type", "object")
    if schema_type == "object":
        props = schema.get("properties", {})
        return {k: _resolve_schema_example(swagger, v) for k, v in props.items()}
    if schema_type == "string":
        return schema.get("example", "string")
    if schema_type == "integer":
        return schema.get("example", 0)
    if schema_type == "number":
        return schema.get("example", 0.0)
    if schema_type == "boolean":
        return schema.get("example", True)
    if schema_type == "array":
        items = schema.get("items", {})
        return [_resolve_schema_example(swagger, items)]
    return None


def _get_param_example(param: Dict) -> Any:
    """从参数定义中获取示例值"""
    if "example" in param:
        return param["example"]
    schema = param.get("schema", {})
    if "example" in schema:
        return schema["example"]
    param_type = schema.get("type", param.get("type", "string"))
    if param_type == "string":
        return "string"
    if param_type == "integer":
        return 0
    if param_type == "number":
        return 0.0
    if param_type == "boolean":
        return True
    return "string"


# ========== 用例同步端点（兼容，重定向到统一资产） ==========

@router.post("/sync/to-api-test", summary="同步用例到接口测试（兼容，推荐使用 /assets/v2/publish）")
async def sync_to_api_test(
    source: str = Query("content", description="来源: content(单条) / task(批量)"),
    content_id: Optional[int] = Query(None, description="CaseContent ID（source=content时必填）"),
    task_id: Optional[int] = Query(None, description="CaseTask ID（source=task时必填）"),
    folder_id: Optional[int] = Query(None, description="目标目录ID"),
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """
    [兼容] 将test-case草稿同步到api-test发布层

    推荐使用：POST /assets/v2/publish 统一发布
    """
    from app.services.case.case_sync_service import CaseSyncService

    if source == "content":
        if not content_id:
            raise HTTPException(status_code=400, detail="source=content时content_id必填")
        result = CaseSyncService.sync_single(
            content_id=content_id,
            user_id=user.id,
            folder_id=folder_id,
        )
    elif source == "task":
        if not task_id:
            raise HTTPException(status_code=400, detail="source=task时task_id必填")
        result = CaseSyncService.sync_batch(
            task_id=task_id,
            user_id=user.id,
            folder_id=folder_id,
        )
    else:
        raise HTTPException(status_code=400, detail="source必须是content或task")

    if "error" in result:
        return Response(code=500, message=result["error"], data=result)
    return Response(code=200, message="同步成功", data=result)


@router.get("/sync/status", summary="查询同步状态")
async def get_sync_status(
    content_id: int = Query(..., description="CaseContent ID"),
    user: User = Depends(require_auth),
):
    """查询用例同步状态"""
    from app.services.case.case_sync_service import CaseSyncService
    result = CaseSyncService.get_sync_status(content_id)
    return Response(code=200, message="success", data=result)


@router.get("/sync/draft-count", summary="查询待同步用例数量")
async def get_draft_count(
    task_id: int = Query(..., description="CaseTask ID"),
    user: User = Depends(require_auth),
):
    """查询指定task下待同步的用例数量"""
    from app.services.case.case_sync_service import CaseSyncService
    count = CaseSyncService.get_draft_count(task_id)
    return Response(code=200, message="success", data={"task_id": task_id, "draft_count": count})
