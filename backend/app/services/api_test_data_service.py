"""
ApiTestDataService - 业务编排层

职责:
  1. 调用 ApiDataGeneratorAgent 生成数据
  2. 模板 CRUD 业务逻辑 (状态机、校验)
  3. 已生成数据查询
  4. 将 Agent 输出与用户输入组合成最终响应

不做:
  - HTTP 层逻辑 (由 router 负责)
  - SQL 拼接 (由 repository 负责)

调用关系:
  Router → Service → Repository
                  → Agent (ApiDataGeneratorAgent)
"""
import asyncio
import json
import logging
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.api_test_data import (
    ApiTestDataTemplate,
    GeneratedApiData,
    DataType,
    GenerationSource,
    TemplateStatus,
)
from app.repositories.api_test_data_repository import (
    ApiTestDataTemplateRepository,
    GeneratedDataRepository,
)
from app.core.exceptions import BusinessError, ValidationError

logger = logging.getLogger(__name__)


# ============================================================
# 异常定义
# ============================================================

class TemplateNotFoundError(BusinessError):
    def __init__(self, template_id: int):
        super().__init__(
            code="TEMPLATE_NOT_FOUND",
            message=f"模板不存在: id={template_id}",
            details={"template_id": template_id}
        )


class GeneratedDataNotFoundError(BusinessError):
    def __init__(self, data_id: int):
        super().__init__(
            code="GENERATED_DATA_NOT_FOUND",
            message=f"数据不存在: id={data_id}",
            details={"data_id": data_id}
        )


# ============================================================
# Service
# ============================================================

class ApiTestDataService:
    """接口测试数据服务"""

    def __init__(self):
        self._template_repo = ApiTestDataTemplateRepository()
        self._data_repo = GeneratedDataRepository()

    @contextmanager
    def _session(self) -> Iterator[Session]:
        """事务会话上下文"""
        db = SessionLocal()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ============================================================
    # 数据生成 (核心)
    # ============================================================

    async def generate_data(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """调用 ApiDataGeneratorAgent 生成数据"""
        # 1. 懒加载 Agent (避免循环导入)
        from app.agents.flows.api_data_generator_agent import ApiDataGeneratorAgent

        # 2. 创建 Agent 实例 (生产环境应由 AgentFactory 管理)
        agent = ApiDataGeneratorAgent()

        # 3. 调用 Agent 生成
        try:
            result = await agent.execute(payload, ctx=None)
            logger.info(
                f"[ApiTestDataSvc] 生成数据成功: endpoint_id={payload.get('endpoint_id')}, "
                f"types={payload.get('data_types')}, elapsed_ms={result.get('metadata', {}).get('elapsed_ms')}"
            )
            return result
        except Exception as e:
            logger.error(f"[ApiTestDataSvc] 生成数据失败: {e}")
            return {
                "status": "error",
                "message": str(e),
            }

    # ============================================================
    # 健康检查
    # ============================================================

    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        from app.agents.flows.api_data_generator_agent import ApiDataGeneratorAgent
        agent = ApiDataGeneratorAgent()
        return await agent._do_health()

    # ============================================================
    # 模板管理
    # ============================================================

    def create_template(self, payload: Dict[str, Any], *, user_id: Optional[int] = None) -> Dict[str, Any]:
        """创建模板"""
        # 校验 data_type
        data_type = payload.get("data_type", "normal")
        try:
            DataType(data_type)
        except ValueError:
            raise ValidationError(
                f"非法数据类型: {data_type}",
                details={"allowed": [e.value for e in DataType]}
            )

        with self._session() as db:
            tmpl = self._template_repo.create(
                db,
                endpoint_id=payload["endpoint_id"],
                name=payload["name"],
                description=payload.get("description"),
                data_type=DataType(data_type),
                fields_schema=payload.get("fields_schema"),
                generation_rules=payload.get("generation_rules"),
                dependencies_json=payload.get("dependencies_json"),
                tags=payload.get("tags"),
                status=TemplateStatus.DRAFT,
                user_id=user_id,
                created_by=user_id,
            )
            result = self._template_repo.to_dict(tmpl)
            logger.info(f"[ApiTestDataSvc] 创建模板: id={tmpl.id} name={tmpl.name}")
            return result

    def get_template(self, template_id: int) -> Dict[str, Any]:
        """查模板详情"""
        with self._session() as db:
            tmpl = self._template_repo.get_by_id(db, template_id)
            if not tmpl:
                raise TemplateNotFoundError(template_id)
            return self._template_repo.to_dict(tmpl)

    def list_templates(
        self,
        *,
        endpoint_id: Optional[int] = None,
        data_type: Optional[str] = None,
        status: Optional[str] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """分页查询模板"""
        with self._session() as db:
            items, total = self._template_repo.list(
                db,
                endpoint_id=endpoint_id,
                data_type=data_type,
                status=status,
                keyword=keyword,
                page=page,
                page_size=page_size,
            )
            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "items": [self._template_repo.to_dict(t) for t in items],
            }

    def update_template(self, template_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        """更新模板"""
        with self._session() as db:
            tmpl = self._template_repo.get_by_id(db, template_id)
            if not tmpl:
                raise TemplateNotFoundError(template_id)

            # 状态流转校验
            if "status" in payload and payload["status"]:
                new_status = payload["status"]
                try:
                    TemplateStatus(new_status)
                except ValueError:
                    raise ValidationError(
                        f"非法状态: {new_status}",
                        details={"allowed": [e.value for e in TemplateStatus]}
                    )

            # 过滤空值
            update_data = {k: v for k, v in payload.items() if v is not None}
            self._template_repo.update(db, tmpl, **update_data)
            result = self._template_repo.to_dict(tmpl)
            logger.info(f"[ApiTestDataSvc] 更新模板: id={template_id}")
            return result

    def delete_template(self, template_id: int) -> Dict[str, Any]:
        """软删除模板"""
        with self._session() as db:
            tmpl = self._template_repo.get_by_id(db, template_id)
            if not tmpl:
                raise TemplateNotFoundError(template_id)
            self._template_repo.soft_delete(db, tmpl)
            logger.info(f"[ApiTestDataSvc] 软删除模板: id={template_id}")
            return {"id": template_id, "is_deleted": True}

    # ============================================================
    # 已生成数据查询
    # ============================================================

    def list_generated_data(
        self,
        *,
        endpoint_id: Optional[int] = None,
        data_type: Optional[str] = None,
        case_id: Optional[int] = None,
        template_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """分页查询已生成数据"""
        with self._session() as db:
            items, total = self._data_repo.list(
                db,
                endpoint_id=endpoint_id,
                data_type=data_type,
                case_id=case_id,
                template_id=template_id,
                page=page,
                page_size=page_size,
            )
            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "items": [self._data_repo.to_dict(it) for it in items],
            }

    def get_generated_data(self, data_id: int) -> Dict[str, Any]:
        """查单条生成数据"""
        with self._session() as db:
            record = self._data_repo.get_by_id(db, data_id)
            if not record:
                raise GeneratedDataNotFoundError(data_id)
            return self._data_repo.to_dict(record)

    def delete_generated_data(self, data_id: int) -> Dict[str, Any]:
        """软删除生成数据"""
        with self._session() as db:
            record = self._data_repo.get_by_id(db, data_id)
            if not record:
                raise GeneratedDataNotFoundError(data_id)
            self._data_repo.soft_delete(db, record)
            return {"id": data_id, "is_deleted": True}

    # ============================================================
    # 流程接入: 数据 → 用例 (替代用户声称的 ApiCaseAgent 接入点)
    # ============================================================

    async def generate_for_case(
        self,
        endpoint_id: int,
        *,
        count: int = 3,
        use_llm: bool = True,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """生成数据并构造可执行的 ApiCase 结构

        流程: 接口解析(已存在) → 依赖分析(本服务内置) → 数据生成 → 测试用例建议

        返回:
          {
            "endpoint": {...},
            "generated_data": {"normal": [...], "abnormal": [...], ...},
            "suggested_cases": [
              {
                "title": "正常场景-用户登录",
                "data_type": "normal",
                "method": "POST",
                "url": "/api/login",
                "steps": [{action, url, headers, body, timeout}],
                "assertions": [{type, path, expected}],
                "extracts": [...],
                "variables": {},
              },
              ...
            ]
          }
        """
        import json as _json
        from app.models.api_endpoint import ApiEndpoint

        # 1. 加载接口定义
        with self._session() as db:
            endpoint = db.query(ApiEndpoint).filter(
                ApiEndpoint.id == endpoint_id,
                ApiEndpoint.is_deleted == False,
            ).first()
            if not endpoint:
                raise BusinessError(
                    code="ENDPOINT_NOT_FOUND",
                    message=f"接口不存在: id={endpoint_id}",
                    details={"endpoint_id": endpoint_id}
                )
            endpoint_dict = {
                "id": endpoint.id,
                "name": endpoint.name,
                "method": endpoint.method,
                "path": endpoint.path,
                "headers": _json.loads(endpoint.headers_json) if endpoint.headers_json else [],
                "params": _json.loads(endpoint.params_json) if endpoint.params_json else [],
                "body": _json.loads(endpoint.body_json) if endpoint.body_json else {},
                "response": _json.loads(endpoint.response_json) if endpoint.response_json else {},
                "auth_type": endpoint.auth_type,
            }

        # 2. 构造 fields_schema (从 params + body 合并)
        fields_schema = self._build_fields_schema_from_endpoint(endpoint_dict)

        # 3. 调用 Agent 生成 4 类数据
        agent_payload = {
            "action": "generate",
            "endpoint_id": endpoint_id,
            "data_types": ["normal", "abnormal", "boundary", "dependent"],
            "count": count,
            "fields_schema": fields_schema,
            "dependencies": [],  # 由依赖分析模块填充,此处留空
            "use_template": True,
            "use_llm": use_llm,
            "user_id": user_id,
        }
        gen_result = await self.generate_data(agent_payload)
        generated_data = gen_result.get("data", {})

        # 4. 将生成数据格式化为 ApiCase 建议结构
        suggested_cases = self._build_suggested_cases(endpoint_dict, generated_data)

        # 5. 发布数据生成事件 (消息协议)
        try:
            from app.agent.core.message_bus import MessageBus
            bus = MessageBus()
            bus.publish(
                topic="data.generated",
                source="api_test_data_service",
                data={
                    "endpoint_id": endpoint_id,
                    "data_types": list(generated_data.keys()),
                    "total_count": sum(len(v) for v in generated_data.values()),
                    "suggested_case_count": len(suggested_cases),
                },
                task_id=None,
                status="completed",
            )
            logger.info(f"[ApiTestDataSvc] 发布 data.generated 事件: endpoint={endpoint_id}")
        except Exception as e:
            logger.debug(f"[ApiTestDataSvc] 发布事件失败(忽略): {e}")

        logger.info(
            f"[ApiTestDataSvc] generate_for_case 完成: endpoint={endpoint_id}, "
            f"data_types={list(generated_data.keys())}, suggested_cases={len(suggested_cases)}"
        )

        return {
            "endpoint": endpoint_dict,
            "generated_data": generated_data,
            "suggested_cases": suggested_cases,
            "metadata": gen_result.get("metadata", {}),
        }

    def _build_fields_schema_from_endpoint(self, endpoint: Dict[str, Any]) -> List[Dict[str, Any]]:
        """从接口定义构造 fields_schema

        合并 params (Query/Path) 与 body 字段
        """
        fields: List[Dict[str, Any]] = []

        # params 字段
        for p in endpoint.get("params", []) or []:
            if not isinstance(p, dict):
                continue
            fields.append({
                "name": p.get("name", ""),
                "type": p.get("type", "string"),
                "required": p.get("required", False),
                "in": p.get("in", "query"),
                "description": p.get("description", ""),
                "default": p.get("default"),
                "min": p.get("min"),
                "max": p.get("max"),
            })

        # body 字段
        body = endpoint.get("body") or {}
        if isinstance(body, dict):
            body_fields = body.get("fields") if isinstance(body.get("fields"), list) else None
            if body_fields is None and isinstance(body.get("properties"), dict):
                # OpenAPI Schema 格式
                body_fields = [
                    {"name": k, **v}
                    for k, v in body["properties"].items()
                ]
            for f in body_fields or []:
                if not isinstance(f, dict):
                    continue
                fields.append({
                    "name": f.get("name", ""),
                    "type": f.get("type", "string"),
                    "required": f.get("required", False),
                    "in": "body",
                    "description": f.get("description", ""),
                    "default": f.get("default"),
                    "min": f.get("min"),
                    "max": f.get("max"),
                    "format": f.get("format"),
                })

        return fields

    def _build_suggested_cases(
        self,
        endpoint: Dict[str, Any],
        generated_data: Dict[str, List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        """将生成数据格式化为 ApiCase 建议结构

        每条数据 → 1 个建议用例
        """
        import json as _json

        method = endpoint.get("method", "POST")
        path = endpoint.get("path", "/")
        headers = endpoint.get("headers") or []

        # 默认断言: HTTP 200 + 业务码 0
        default_assertions = [
            {"type": "status_equals", "path": "status_code", "expected": 200},
        ]
        if endpoint.get("response"):
            default_assertions.append(
                {"type": "json_path_equals", "path": "code", "expected": 0}
            )

        cases = []
        type_label = {
            "normal": "正常场景",
            "abnormal": "异常场景",
            "boundary": "边界场景",
            "dependent": "关联场景",
        }

        for data_type, records in generated_data.items():
            for idx, rec in enumerate(records):
                if not isinstance(rec, dict):
                    continue
                # 区分 query / body 字段
                query_data = {}
                body_data = {}
                fields_meta = rec.get("_fields_meta", [])
                if not fields_meta:
                    # 缺省全部塞 body
                    body_data = {k: v for k, v in rec.items() if not k.startswith("_")}
                else:
                    for fm in fields_meta:
                        name = fm.get("name")
                        loc = fm.get("in", "body")
                        if name and name in rec:
                            if loc == "query":
                                query_data[name] = rec[name]
                            else:
                                body_data[name] = rec[name]

                # 构造 URL (带 query string)
                url = path
                if query_data:
                    qs = "&".join(f"{k}={v}" for k, v in query_data.items())
                    url = f"{path}?{qs}"

                steps = [{
                    "action": method,
                    "url": url,
                    "headers": headers,
                    "body": body_data,
                    "timeout": 5000,
                }]

                # 异常场景: 期望 4xx/5xx
                assertions = list(default_assertions)
                if data_type == "abnormal":
                    assertions = [
                        {"type": "status_in", "path": "status_code", "expected": [400, 401, 403, 422, 500]},
                    ]

                case = {
                    "title": f"{type_label.get(data_type, data_type)}-{endpoint.get('name', '')}-{idx+1}",
                    "data_type": data_type,
                    "method": method,
                    "url": url,
                    "steps": steps,
                    "assertions": assertions,
                    "extracts": [],
                    "variables": {},
                    "source_data": rec.get("_source", "rule"),
                    "elapsed_ms": rec.get("_elapsed_ms", 0),
                }
                cases.append(case)

        return cases
