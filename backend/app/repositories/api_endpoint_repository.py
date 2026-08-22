"""
ApiEndpointRepository - 接口管理数据访问层

职责:
  1. 封装 ApiEndpoint / ApiEndpointVersion 的 CRUD
  2. JSON 字段(headers/params/body/response/auth)的序列化
  3. 软删除过滤(is_deleted=False)
  4. 按 keyword/method/module/status/tags 过滤
  5. 分页查询

不做:
  - 业务校验(由 service 层负责)
  - 状态机流转(由 service 层负责)
  - 事务边界(由 service 层或 router 负责提交)
"""
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.models.api_endpoint import (
    ApiEndpoint,
    ApiEndpointVersion,
    ApiHeader,
    ApiBody,
    ApiParameter,
    EndpointStatus,
    EndpointSource,
)
from app.core.exceptions import (
    EndpointNotFoundError,
    EndpointConflictError,
    EndpointVersionNotFoundError,
)

logger = logging.getLogger(__name__)


def _dump_json(value: Any) -> Optional[str]:
    """Python 对象 → JSON 字符串(None 保持 None)"""
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as e:
        logger.warning(f"JSON 序列化失败: {e}")
        return None


def _load_json(value: Optional[str], default: Any = None) -> Any:
    """JSON 字符串 → Python 对象(None 返回 default)"""
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError) as e:
        logger.warning(f"JSON 反序列化失败: {e}, raw={value[:100]}")
        return default


class ApiEndpointRepository:
    """接口管理 Repository

    所有方法接收一个 Session 参数,由调用方负责事务生命周期。
    """

    # ------------------------------------------------------------------
    # 创建
    # ------------------------------------------------------------------

    def create(
        self,
        db: Session,
        *,
        name: str,
        method: str,
        path: str,
        summary: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        module: Optional[str] = None,
        status: str = "draft",
        source: str = "manual",
        headers: Optional[List[Dict]] = None,
        params: Optional[List[Dict]] = None,
        body: Optional[Dict] = None,
        response: Optional[Dict] = None,
        auth: Optional[Dict] = None,
        user_id: Optional[int] = None,
        created_by: Optional[int] = None,
    ) -> ApiEndpoint:
        """创建接口

        重复检测:同 user_id + method + path 视为重复(抛 EndpointConflictError)
        """
        existing = db.query(ApiEndpoint).filter(
            ApiEndpoint.user_id == user_id,
            ApiEndpoint.method == method,
            ApiEndpoint.path == path,
            ApiEndpoint.is_deleted == False,
        ).first()
        if existing:
            raise EndpointConflictError(
                f"接口已存在: {method} {path}",
                endpoint_id=existing.id,
            )

        tags_str = ",".join(tags) if tags else None
        endpoint = ApiEndpoint(
            name=name,
            method=method,
            path=path,
            summary=summary,
            description=description,
            tags=tags_str,
            module=module,
            status=status,
            source=source,
            headers_json=_dump_json(headers),
            params_json=_dump_json(params),
            body_json=_dump_json(body),
            response_json=_dump_json(response),
            auth_type=(auth or {}).get("type", "none") if auth else "none",
            auth_details_json=_dump_json((auth or {}).get("details")) if auth else None,
            version=1,
            is_deleted=False,
            user_id=user_id,
            created_by=created_by,
        )
        db.add(endpoint)
        db.flush()  # 取 id,但不 commit
        logger.info(f"[ApiEndpointRepo] 创建接口 id={endpoint.id} {method} {path}")
        return endpoint

    # ------------------------------------------------------------------
    # 查询(单个)
    # ------------------------------------------------------------------

    def get_by_id(
        self,
        db: Session,
        endpoint_id: int,
        *,
        user_id: Optional[int] = None,
        include_deleted: bool = False,
    ) -> ApiEndpoint:
        """按 ID 查询接口,不存在或软删除则抛 NotFoundError"""
        q = db.query(ApiEndpoint).filter(ApiEndpoint.id == endpoint_id)
        if user_id is not None:
            q = q.filter(ApiEndpoint.user_id == user_id)
        if not include_deleted:
            q = q.filter(ApiEndpoint.is_deleted == False)
        endpoint = q.first()
        if not endpoint:
            raise EndpointNotFoundError(
                f"接口不存在或已删除: id={endpoint_id}",
                endpoint_id=endpoint_id,
            )
        return endpoint

    # ------------------------------------------------------------------
    # 查询(列表分页)
    # ------------------------------------------------------------------

    def list(
        self,
        db: Session,
        *,
        user_id: Optional[int] = None,
        keyword: Optional[str] = None,
        method: Optional[str] = None,
        module: Optional[str] = None,
        status: Optional[str] = None,
        tags: Optional[List[str]] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[ApiEndpoint], int]:
        """分页查询接口列表

        返回 (items, total)
        """
        q = db.query(ApiEndpoint).filter(ApiEndpoint.is_deleted == False)

        if user_id is not None:
            q = q.filter(ApiEndpoint.user_id == user_id)
        if keyword:
            kw = f"%{keyword}%"
            q = q.filter(or_(
                ApiEndpoint.name.ilike(kw),
                ApiEndpoint.path.ilike(kw),
                ApiEndpoint.summary.ilike(kw),
            ))
        if method:
            q = q.filter(ApiEndpoint.method == method.upper())
        if module:
            q = q.filter(ApiEndpoint.module == module)
        if status:
            q = q.filter(ApiEndpoint.status == status)
        if tags:
            # tags 是逗号分隔字符串,任一匹配即返回
            tag_conds = [ApiEndpoint.tags.like(f"%{t}%") for t in tags]
            q = q.filter(or_(*tag_conds))

        total = q.count()
        items = (
            q.order_by(ApiEndpoint.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    # ------------------------------------------------------------------
    # 更新
    # ------------------------------------------------------------------

    def update(
        self,
        db: Session,
        endpoint: ApiEndpoint,
        **fields,
    ) -> ApiEndpoint:
        """部分更新接口

        支持的字段:
          name, method, path, summary, description, tags(list), module,
          status, headers(list), params(list), body(dict), response(dict), auth(dict)
        """
        list_to_str = lambda v: ",".join(v) if v else None

        field_map = {
            "name": ("name", lambda v: v),
            "method": ("method", lambda v: v.upper() if v else v),
            "path": ("path", lambda v: v),
            "summary": ("summary", lambda v: v),
            "description": ("description", lambda v: v),
            "module": ("module", lambda v: v),
            "status": ("status", lambda v: v),
        }
        json_field_map = {
            "tags": ("tags", list_to_str),  # tags 是 list → CSV
            "headers": ("headers_json", _dump_json),
            "params": ("params_json", _dump_json),
            "body": ("body_json", _dump_json),
            "response": ("response_json", _dump_json),
        }

        for key, value in fields.items():
            if value is None:
                continue
            if key in field_map:
                col, conv = field_map[key]
                setattr(endpoint, col, conv(value))
            elif key in json_field_map:
                col, conv = json_field_map[key]
                setattr(endpoint, col, conv(value))
            elif key == "auth":
                setattr(endpoint, "auth_type", (value or {}).get("type", "none"))
                setattr(endpoint, "auth_details_json", _dump_json((value or {}).get("details")))
            else:
                logger.debug(f"[ApiEndpointRepo] 跳过未识别字段: {key}")

        db.flush()
        logger.info(f"[ApiEndpointRepo] 更新接口 id={endpoint.id}")
        return endpoint

    # ------------------------------------------------------------------
    # 软删除
    # ------------------------------------------------------------------

    def soft_delete(self, db: Session, endpoint: ApiEndpoint) -> ApiEndpoint:
        """软删除(标记 is_deleted=True)"""
        endpoint.is_deleted = True
        db.flush()
        logger.info(f"[ApiEndpointRepo] 软删除接口 id={endpoint.id}")
        return endpoint

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def stats(
        self,
        db: Session,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """按状态/方法/模块统计接口数"""
        q = db.query(ApiEndpoint).filter(ApiEndpoint.is_deleted == False)
        if user_id is not None:
            q = q.filter(ApiEndpoint.user_id == user_id)

        total = q.count()

        by_status: Dict[str, int] = {}
        by_method: Dict[str, int] = {}
        by_module: Dict[str, int] = {}

        for ep in q.with_entities(ApiEndpoint.status, ApiEndpoint.method, ApiEndpoint.module):
            s, m, mod = ep
            by_status[s] = by_status.get(s, 0) + 1
            by_method[m] = by_method.get(m, 0) + 1
            if mod:
                by_module[mod] = by_module.get(mod, 0) + 1

        return {
            "total": total,
            "by_status": by_status,
            "by_method": by_method,
            "by_module": by_module,
        }

    # ------------------------------------------------------------------
    # 版本管理
    # ------------------------------------------------------------------

    def create_version(
        self,
        db: Session,
        endpoint: ApiEndpoint,
        change_log: str = "",
        user_id: Optional[int] = None,
        created_by: Optional[int] = None,
    ) -> ApiEndpointVersion:
        """为接口创建版本快照

        步骤:
          1. 取当前接口完整快照
          2. version = endpoint.version + 1
          3. 把旧版本的 is_current 置为 False
          4. 插入新版本,is_current=True
          5. endpoint.version = new_version
          6. endpoint.status = active
        """
        snapshot = self._snapshot(endpoint)
        new_version_no = endpoint.version + 1

        # 旧版本 is_current = False
        db.query(ApiEndpointVersion).filter(
            ApiEndpointVersion.endpoint_id == endpoint.id,
            ApiEndpointVersion.is_current == True,
        ).update({ApiEndpointVersion.is_current: False}, synchronize_session=False)

        version = ApiEndpointVersion(
            endpoint_id=endpoint.id,
            version=new_version_no,
            snapshot_json=_dump_json(snapshot),
            change_log=change_log,
            is_current=True,
            user_id=user_id,
            created_by=created_by,
        )
        db.add(version)

        endpoint.version = new_version_no
        endpoint.status = EndpointStatus.ACTIVE.value
        db.flush()

        logger.info(f"[ApiEndpointRepo] 创建版本 ep={endpoint.id} v{new_version_no}")
        return version

    def list_versions(
        self,
        db: Session,
        endpoint_id: int,
        *,
        user_id: Optional[int] = None,
    ) -> List[ApiEndpointVersion]:
        """列出接口的所有版本(按版本号倒序)"""
        self.get_by_id(db, endpoint_id, user_id=user_id)  # 校验存在
        q = db.query(ApiEndpointVersion).filter(
            ApiEndpointVersion.endpoint_id == endpoint_id,
        )
        if user_id is not None:
            q = q.filter(ApiEndpointVersion.user_id == user_id)
        return q.order_by(ApiEndpointVersion.version.desc()).all()

    def get_version(
        self,
        db: Session,
        endpoint_id: int,
        version: int,
        *,
        user_id: Optional[int] = None,
    ) -> ApiEndpointVersion:
        """获取指定版本"""
        self.get_by_id(db, endpoint_id, user_id=user_id)
        q = db.query(ApiEndpointVersion).filter(
            ApiEndpointVersion.endpoint_id == endpoint_id,
            ApiEndpointVersion.version == version,
        )
        if user_id is not None:
            q = q.filter(ApiEndpointVersion.user_id == user_id)
        v = q.first()
        if not v:
            raise EndpointVersionNotFoundError(
                f"版本不存在: ep={endpoint_id} v{version}",
                endpoint_id=endpoint_id,
                version=version,
            )
        return v

    def rollback_to_version(
        self,
        db: Session,
        endpoint: ApiEndpoint,
        version: int,
        user_id: Optional[int] = None,
    ) -> ApiEndpoint:
        """回滚到指定版本

        步骤:
          1. 取目标版本快照
          2. 把快照字段写回 endpoint
          3. endpoint.version 设为目标版本号(后续发布时再 +1)
          4. 创建新版本记录(标记为"回滚自 vX")
        """
        target = self.get_version(db, endpoint.id, version, user_id=user_id)
        snapshot = _load_json(target.snapshot_json, default={})

        # 回写字段
        endpoint.name = snapshot.get("name", endpoint.name)
        endpoint.method = snapshot.get("method", endpoint.method)
        endpoint.path = snapshot.get("path", endpoint.path)
        endpoint.summary = snapshot.get("summary")
        endpoint.description = snapshot.get("description")
        endpoint.tags = snapshot.get("tags")
        endpoint.module = snapshot.get("module")
        endpoint.headers_json = _dump_json(snapshot.get("headers"))
        endpoint.params_json = _dump_json(snapshot.get("params"))
        endpoint.body_json = _dump_json(snapshot.get("body"))
        endpoint.response_json = _dump_json(snapshot.get("response"))
        endpoint.auth_type = (snapshot.get("auth") or {}).get("type", "none")
        endpoint.auth_details_json = _dump_json((snapshot.get("auth") or {}).get("details"))

        # 新建回滚版本记录
        rollback_version = ApiEndpointVersion(
            endpoint_id=endpoint.id,
            version=endpoint.version + 1,
            snapshot_json=_dump_json(self._snapshot(endpoint)),
            change_log=f"回滚自 v{version}",
            is_current=True,
            user_id=user_id,
            created_by=user_id,
        )
        # 旧 is_current 置 False
        db.query(ApiEndpointVersion).filter(
            ApiEndpointVersion.endpoint_id == endpoint.id,
            ApiEndpointVersion.is_current == True,
        ).update({ApiEndpointVersion.is_current: False}, synchronize_session=False)
        db.add(rollback_version)

        endpoint.version = endpoint.version + 1
        db.flush()

        logger.info(f"[ApiEndpointRepo] 回滚 ep={endpoint.id} 至 v{version}, 新版本 v{endpoint.version}")
        return endpoint

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _snapshot(self, endpoint: ApiEndpoint) -> Dict[str, Any]:
        """生成接口完整快照(dict)"""
        return {
            "name": endpoint.name,
            "method": endpoint.method,
            "path": endpoint.path,
            "summary": endpoint.summary,
            "description": endpoint.description,
            "tags": endpoint.tags,
            "module": endpoint.module,
            "status": endpoint.status,
            "source": endpoint.source,
            "headers": _load_json(endpoint.headers_json, default=[]),
            "params": _load_json(endpoint.params_json, default=[]),
            "body": _load_json(endpoint.body_json),
            "response": _load_json(endpoint.response_json),
            "auth": {
                "type": endpoint.auth_type,
                "details": _load_json(endpoint.auth_details_json),
            },
            "version": endpoint.version,
        }

    def to_dict(self, endpoint: ApiEndpoint) -> Dict[str, Any]:
        """模型实例 → 响应 dict(JSON 字段已反序列化)"""
        tags_list = []
        if endpoint.tags:
            tags_list = [t.strip() for t in endpoint.tags.split(",") if t.strip()]
        return {
            "id": endpoint.id,
            "name": endpoint.name,
            "method": endpoint.method,
            "path": endpoint.path,
            "summary": endpoint.summary,
            "description": endpoint.description,
            "tags": tags_list,
            "module": endpoint.module,
            "status": endpoint.status,
            "source": endpoint.source,
            "headers": _load_json(endpoint.headers_json, default=[]),
            "params": _load_json(endpoint.params_json, default=[]),
            "body": _load_json(endpoint.body_json),
            "response": _load_json(endpoint.response_json),
            "auth": {
                "type": endpoint.auth_type,
                "details": _load_json(endpoint.auth_details_json),
            },
            "version": endpoint.version,
            "user_id": endpoint.user_id,
            "created_by": endpoint.created_by,
            "created_at": endpoint.created_at,
            "updated_at": endpoint.updated_at,
        }

    def to_list_item(self, endpoint: ApiEndpoint) -> Dict[str, Any]:
        """模型实例 → 列表项 dict(精简)"""
        tags_list = []
        if endpoint.tags:
            tags_list = [t.strip() for t in endpoint.tags.split(",") if t.strip()]
        return {
            "id": endpoint.id,
            "name": endpoint.name,
            "method": endpoint.method,
            "path": endpoint.path,
            "summary": endpoint.summary,
            "module": endpoint.module,
            "status": endpoint.status,
            "source": endpoint.source,
            "version": endpoint.version,
            "tags": tags_list,
            "created_at": endpoint.created_at,
            "updated_at": endpoint.updated_at,
        }

    def version_to_dict(self, v: ApiEndpointVersion, include_snapshot: bool = False) -> Dict[str, Any]:
        """版本模型 → dict"""
        d = {
            "id": v.id,
            "endpoint_id": v.endpoint_id,
            "version": v.version,
            "change_log": v.change_log,
            "is_current": v.is_current,
            "created_by": v.created_by,
            "created_at": v.created_at,
        }
        if include_snapshot:
            d["snapshot"] = _load_json(v.snapshot_json, default={})
        return d

    # ------------------------------------------------------------------
    # 子表 CRUD (api_header / api_body / api_parameter)
    # ------------------------------------------------------------------

    def save_headers(
        self,
        db: Session,
        api_id: int,
        headers: List[Dict[str, Any]],
    ) -> List[ApiHeader]:
        """替换接口的所有请求头 (先删后插)"""
        db.query(ApiHeader).filter(ApiHeader.api_id == api_id).delete()
        result = []
        for i, h in enumerate(headers):
            header = ApiHeader(
                api_id=api_id,
                key=h.get("key", ""),
                value=h.get("value", ""),
                required=h.get("required", True),
                sort_order=i,
            )
            db.add(header)
            result.append(header)
        db.flush()
        logger.info(f"[ApiEndpointRepo] 保存 {len(result)} 个请求头 ep={api_id}")
        return result

    def save_body(
        self,
        db: Session,
        api_id: int,
        body: Dict[str, Any],
    ) -> Optional[ApiBody]:
        """替换接口的请求体 (先删后插, 最多一行)"""
        db.query(ApiBody).filter(ApiBody.api_id == api_id).delete()
        if not body:
            db.flush()
            return None
        body_obj = ApiBody(
            api_id=api_id,
            body_type=body.get("content_type") or body.get("body_type") or "application/json",
            schema_json=_dump_json(body.get("schema") or body.get("schema_json")),
            example_json=_dump_json(body.get("example") or body.get("example_json")),
            raw_text=body.get("raw") or body.get("raw_text"),
        )
        db.add(body_obj)
        db.flush()
        logger.info(f"[ApiEndpointRepo] 保存请求体 ep={api_id} type={body_obj.body_type}")
        return body_obj

    def save_parameters(
        self,
        db: Session,
        api_id: int,
        parameters: List[Dict[str, Any]],
    ) -> List[ApiParameter]:
        """替换接口的所有参数 (先删后插)"""
        db.query(ApiParameter).filter(ApiParameter.api_id == api_id).delete()
        result = []
        for i, p in enumerate(parameters):
            param = ApiParameter(
                api_id=api_id,
                location=p.get("in") or p.get("location") or "query",
                name=p.get("name", ""),
                type=p.get("type", "string"),
                required=p.get("required", False),
                default_value=str(p.get("default") or p.get("default_value") or ""),
                description=p.get("description", ""),
                example=str(p.get("example") or ""),
                sort_order=i,
            )
            db.add(param)
            result.append(param)
        db.flush()
        logger.info(f"[ApiEndpointRepo] 保存 {len(result)} 个参数 ep={api_id}")
        return result

    def get_headers(self, db: Session, api_id: int) -> List[Dict[str, Any]]:
        """查询接口的所有请求头"""
        rows = db.query(ApiHeader).filter(
            ApiHeader.api_id == api_id,
        ).order_by(ApiHeader.sort_order).all()
        return [
            {
                "id": r.id,
                "api_id": r.api_id,
                "key": r.key,
                "value": r.value,
                "required": r.required,
                "sort_order": r.sort_order,
            }
            for r in rows
        ]

    def get_body(self, db: Session, api_id: int) -> Optional[Dict[str, Any]]:
        """查询接口的请求体"""
        row = db.query(ApiBody).filter(ApiBody.api_id == api_id).first()
        if not row:
            return None
        return {
            "id": row.id,
            "api_id": row.api_id,
            "body_type": row.body_type,
            "schema_json": _load_json(row.schema_json),
            "example_json": _load_json(row.example_json),
            "raw_text": row.raw_text,
        }

    def get_parameters(self, db: Session, api_id: int) -> List[Dict[str, Any]]:
        """查询接口的所有参数"""
        rows = db.query(ApiParameter).filter(
            ApiParameter.api_id == api_id,
        ).order_by(ApiParameter.sort_order).all()
        return [
            {
                "id": r.id,
                "api_id": r.api_id,
                "location": r.location,
                "name": r.name,
                "type": r.type,
                "required": r.required,
                "default_value": r.default_value,
                "description": r.description,
                "example": r.example,
                "sort_order": r.sort_order,
            }
            for r in rows
        ]

    def to_dict_with_subtables(
        self,
        db: Session,
        endpoint: ApiEndpoint,
    ) -> Dict[str, Any]:
        """模型实例 → 响应 dict (含子表数据)

        优先返回子表数据 (api_headers / api_body / api_parameters),
        同时保留旧 JSON 字段 (headers / params / body) 做向后兼容。
        """
        base = self.to_dict(endpoint)
        base["api_headers"] = self.get_headers(db, endpoint.id)
        base["api_body"] = self.get_body(db, endpoint.id)
        base["api_parameters"] = self.get_parameters(db, endpoint.id)
        return base
