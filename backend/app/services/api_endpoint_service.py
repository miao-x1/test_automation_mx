"""
ApiEndpointService - 接口管理服务层

职责:
  1. 业务逻辑编排(状态机、校验、版本管理)
  2. 事务边界管理(同事务内多步操作要么全成功要么全回滚)
  3. 委托 Repository 做 CRUD,Service 不直接写 SQL
  4. 数据转换:Model 实例 ↔ Schema/Dict(通过 repository.to_dict)

不做:
  - HTTP 层逻辑(由 router 负责)
  - SQL 拼接(由 repository 负责)

依赖:
  - ApiEndpointRepository(数据访问)
  - SessionLocal(事务管理)
"""
import logging
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.exceptions import (
    BusinessError,
    EndpointConflictError,
    EndpointNotFoundError,
    EndpointStateError,
    EndpointVersionNotFoundError,
    ValidationError,
)
from app.db.database import SessionLocal
from app.models.api_endpoint import (
    ApiEndpoint,
    ApiEndpointVersion,
    EndpointStatus,
    EndpointSource,
)
from app.repositories.api_endpoint_repository import ApiEndpointRepository
from app.schemas.api_endpoint import (
    EndpointCreate,
    EndpointUpdate,
    PublishRequest,
)

logger = logging.getLogger(__name__)


# ============================================================
# 状态机定义
# ============================================================

# 允许的状态流转(从 → 到)
_STATE_TRANSITIONS = {
    "draft":      {"active", "archived"},            # 草稿 → 发布/归档
    "active":     {"deprecated", "archived"},         # 已发布 → 废弃/归档
    "deprecated": {"active", "archived"},              # 已废弃 → 重新发布/归档
    "archived":   {"draft"},                           # 已归档 → 仅可恢复为草稿
}

# 允许的来源
_ALLOWED_SOURCES = {s.value for s in EndpointSource}


class ApiEndpointService:
    """接口管理服务

    使用方式:
        service = ApiEndpointService()
        result = service.create_endpoint(endpoint_create, user_id=1)
    """

    def __init__(self):
        self._repo = ApiEndpointRepository()

    # ------------------------------------------------------------------
    # 会话管理
    # ------------------------------------------------------------------

    @contextmanager
    def _session(self) -> Iterator[Session]:
        """事务会话上下文管理器

        正常退出 → commit
        异常退出 → rollback + 抛出原异常
        """
        db = SessionLocal()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ------------------------------------------------------------------
    # 创建接口
    # ------------------------------------------------------------------

    def create_endpoint(
        self,
        payload: EndpointCreate,
        *,
        user_id: Optional[int] = None,
        created_by: Optional[int] = None,
    ) -> Dict[str, Any]:
        """创建接口

        业务校验:
          1. source 必须在允许集合内
          2. status 只能是 draft(首次创建)
          3. method+path 不重复(由 repository 检查)

        Returns:
            接口详情 dict
        """
        if payload.source not in _ALLOWED_SOURCES:
            raise ValidationError(
                f"非法来源: {payload.source}",
                details={"allowed": list(_ALLOWED_SOURCES)},
            )

        # 首次创建只允许 draft
        create_status = "draft"
        if payload.status and payload.status != "draft":
            logger.warning(
                f"[ApiEndpointSvc] 创建时强制 draft,传入 status={payload.status} 被忽略"
            )

        with self._session() as db:
            try:
                endpoint = self._repo.create(
                    db,
                    name=payload.name,
                    method=payload.method,
                    path=payload.path,
                    summary=payload.summary,
                    description=payload.description,
                    tags=payload.tags,
                    module=payload.module,
                    status=create_status,
                    source=payload.source,
                    headers=[h.model_dump() for h in payload.headers] if payload.headers else None,
                    params=[p.model_dump() for p in payload.params] if payload.params else None,
                    body=payload.body.model_dump() if payload.body else None,
                    response=payload.response.model_dump() if payload.response else None,
                    auth=payload.auth.model_dump() if payload.auth else None,
                    user_id=user_id,
                    created_by=created_by,
                )
            except EndpointConflictError as e:
                # 把 repository 的冲突错误透传
                raise e

            result = self._repo.to_dict(endpoint)
            logger.info(
                f"[ApiEndpointSvc] 创建接口成功 id={endpoint.id} {endpoint.method} {endpoint.path}"
            )

            # 自动分类保存到子表 (api_header / api_body / api_parameter)
            self._save_subtables(
                db, endpoint.id,
                headers=[h.model_dump() for h in payload.headers] if payload.headers else None,
                params=[p.model_dump() for p in payload.params] if payload.params else None,
                body=payload.body.model_dump() if payload.body else None,
            )
            # 更新返回结果含子表数据
            result = self._repo.to_dict_with_subtables(db, endpoint)

            # 触发资产索引 Hook (失败不影响主流程)
            try:
                from app.services.asset_index_hook import register_from_api_endpoint
                register_from_api_endpoint(result, user_id=user_id)
            except Exception as hook_err:
                logger.warning(
                    f"[ApiEndpointSvc] 资产索引 Hook 异常 (已忽略): {hook_err}"
                )

            return result

    # ------------------------------------------------------------------
    # 查询接口详情
    # ------------------------------------------------------------------

    def get_endpoint(
        self,
        endpoint_id: int,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """按 ID 获取接口详情 (含子表数据)"""
        with self._session() as db:
            endpoint = self._repo.get_by_id(db, endpoint_id, user_id=user_id)
            return self._repo.to_dict_with_subtables(db, endpoint)

    # ------------------------------------------------------------------
    # 查询接口列表(分页)
    # ------------------------------------------------------------------

    def list_endpoints(
        self,
        *,
        user_id: Optional[int] = None,
        keyword: Optional[str] = None,
        method: Optional[str] = None,
        module: Optional[str] = None,
        status: Optional[str] = None,
        tags: Optional[List[str]] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """分页查询接口列表"""
        with self._session() as db:
            items, total = self._repo.list(
                db,
                user_id=user_id,
                keyword=keyword,
                method=method,
                module=module,
                status=status,
                tags=tags,
                page=page,
                page_size=page_size,
            )
            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "items": [self._repo.to_list_item(ep) for ep in items],
            }

    # ------------------------------------------------------------------
    # 更新接口
    # ------------------------------------------------------------------

    def update_endpoint(
        self,
        endpoint_id: int,
        payload: EndpointUpdate,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """更新接口

        业务校验:
          1. 接口存在(由 repository 检查)
          2. 如果改 method/path,需检查不重复
          3. status 流转必须合法(若提供)
        """
        # 收集非空字段
        update_data = payload.model_dump(exclude_unset=True, exclude_none=True)

        with self._session() as db:
            endpoint = self._repo.get_by_id(db, endpoint_id, user_id=user_id)

            # 状态流转校验
            if "status" in update_data and update_data["status"]:
                new_status = update_data["status"]
                if not self._can_transition(endpoint.status, new_status):
                    raise EndpointStateError(
                        f"状态流转非法: {endpoint.status} → {new_status}",
                        endpoint_id=endpoint.id,
                        current_status=endpoint.status,
                        expected_status=new_status,
                    )

            # method/path 改变时检查重复
            new_method = update_data.get("method", endpoint.method)
            new_path = update_data.get("path", endpoint.path)
            if new_method != endpoint.method or new_path != endpoint.path:
                from sqlalchemy import and_
                from app.models.api_endpoint import ApiEndpoint as _AE
                existing = (
                    db.query(_AE)
                    .filter(
                        _AE.user_id == user_id,
                        _AE.method == new_method,
                        _AE.path == new_path,
                        _AE.is_deleted == False,
                        _AE.id != endpoint.id,
                    )
                    .first()
                )
                if existing:
                    raise EndpointConflictError(
                        f"接口已存在: {new_method} {new_path}",
                        endpoint_id=existing.id,
                    )

            # schema 对象 → dict(供 repository 处理)
            repo_kwargs: Dict[str, Any] = {}
            for key, value in update_data.items():
                if key == "headers" and value:
                    repo_kwargs[key] = [h.model_dump() if hasattr(h, "model_dump") else h for h in value]
                elif key == "params" and value:
                    repo_kwargs[key] = [p.model_dump() if hasattr(p, "model_dump") else p for p in value]
                elif key == "body" and value:
                    repo_kwargs[key] = value.model_dump() if hasattr(value, "model_dump") else value
                elif key == "response" and value:
                    repo_kwargs[key] = value.model_dump() if hasattr(value, "model_dump") else value
                elif key == "auth" and value:
                    repo_kwargs[key] = value.model_dump() if hasattr(value, "model_dump") else value
                else:
                    repo_kwargs[key] = value

            self._repo.update(db, endpoint, **repo_kwargs)

            # 同步更新子表 (如果请求中包含 headers/params/body)
            if "headers" in repo_kwargs:
                self._save_subtables(db, endpoint.id, headers=repo_kwargs["headers"])
            if "params" in repo_kwargs:
                self._save_subtables(db, endpoint.id, params=repo_kwargs["params"])
            if "body" in repo_kwargs:
                self._save_subtables(db, endpoint.id, body=repo_kwargs["body"])

            result = self._repo.to_dict_with_subtables(db, endpoint)
            logger.info(f"[ApiEndpointSvc] 更新接口成功 id={endpoint.id}")
            return result

    # ------------------------------------------------------------------
    # 删除接口(软删除)
    # ------------------------------------------------------------------

    def delete_endpoint(
        self,
        endpoint_id: int,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """软删除接口"""
        with self._session() as db:
            endpoint = self._repo.get_by_id(db, endpoint_id, user_id=user_id)
            self._repo.soft_delete(db, endpoint)
            logger.info(f"[ApiEndpointSvc] 软删除接口 id={endpoint.id}")
            return {"id": endpoint.id, "is_deleted": True}

    # ------------------------------------------------------------------
    # 发布接口(生成版本快照)
    # ------------------------------------------------------------------

    def publish_endpoint(
        self,
        endpoint_id: int,
        payload: PublishRequest,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """发布接口:生成版本快照 + 状态置为 active

        状态约束:
          - draft → active 允许
          - active → active 允许(重新发布,生成新版本)
          - deprecated → active 允许(恢复发布)
          - archived → 不允许(必须先恢复为 draft)
        """
        with self._session() as db:
            endpoint = self._repo.get_by_id(db, endpoint_id, user_id=user_id)

            if endpoint.status == "archived":
                raise EndpointStateError(
                    "已归档的接口不能直接发布,请先恢复为草稿",
                    endpoint_id=endpoint.id,
                    current_status=endpoint.status,
                    expected_status="active",
                )

            version = self._repo.create_version(
                db,
                endpoint,
                change_log=payload.change_log,
                user_id=user_id,
                created_by=user_id,
            )
            result = self._repo.to_dict(endpoint)
            result["current_version"] = self._repo.version_to_dict(version)
            logger.info(
                f"[ApiEndpointSvc] 发布接口成功 id={endpoint.id} v{version.version}"
            )

            # 触发资产发布 Hook (失败不影响主流程)
            try:
                from app.services.asset_index_hook import publish_from_api_endpoint
                publish_from_api_endpoint(
                    endpoint_id,
                    change_log=payload.change_log,
                    user_id=user_id,
                )
            except Exception as hook_err:
                logger.warning(
                    f"[ApiEndpointSvc] 资产发布 Hook 异常 (已忽略): {hook_err}"
                )

            return result

    # ------------------------------------------------------------------
    # 状态流转(显式)
    # ------------------------------------------------------------------

    def change_status(
        self,
        endpoint_id: int,
        new_status: str,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """显式状态流转(不生成版本)

        用于 deprecated/archived 等不涉及内容变更的状态切换
        """
        if new_status not in {"draft", "active", "deprecated", "archived"}:
            raise ValidationError(
                f"非法状态: {new_status}",
                details={"allowed": ["draft", "active", "deprecated", "archived"]},
            )

        with self._session() as db:
            endpoint = self._repo.get_by_id(db, endpoint_id, user_id=user_id)
            if endpoint.status == new_status:
                return self._repo.to_dict(endpoint)

            if not self._can_transition(endpoint.status, new_status):
                raise EndpointStateError(
                    f"状态流转非法: {endpoint.status} → {new_status}",
                    endpoint_id=endpoint.id,
                    current_status=endpoint.status,
                    expected_status=new_status,
                )

            self._repo.update(db, endpoint, status=new_status)
            logger.info(
                f"[ApiEndpointSvc] 状态流转 id={endpoint.id} {endpoint.status} → {new_status}"
            )
            return self._repo.to_dict(endpoint)

    # ------------------------------------------------------------------
    # 版本管理
    # ------------------------------------------------------------------

    def list_versions(
        self,
        endpoint_id: int,
        *,
        user_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """列出接口的所有版本"""
        with self._session() as db:
            versions = self._repo.list_versions(db, endpoint_id, user_id=user_id)
            return [self._repo.version_to_dict(v) for v in versions]

    def get_version(
        self,
        endpoint_id: int,
        version: int,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """获取指定版本详情(含快照)"""
        with self._session() as db:
            v = self._repo.get_version(db, endpoint_id, version, user_id=user_id)
            return self._repo.version_to_dict(v, include_snapshot=True)

    def rollback_to_version(
        self,
        endpoint_id: int,
        version: int,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """回滚到指定版本"""
        with self._session() as db:
            endpoint = self._repo.get_by_id(db, endpoint_id, user_id=user_id)

            # 状态约束:archived 不允许回滚
            if endpoint.status == "archived":
                raise EndpointStateError(
                    "已归档的接口不能回滚,请先恢复为草稿",
                    endpoint_id=endpoint.id,
                    current_status=endpoint.status,
                )

            endpoint = self._repo.rollback_to_version(
                db, endpoint, version, user_id=user_id
            )
            result = self._repo.to_dict(endpoint)
            logger.info(
                f"[ApiEndpointSvc] 回滚成功 id={endpoint.id} 至 v{version},新版本 v{endpoint.version}"
            )
            return result

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def get_stats(
        self,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """接口统计"""
        with self._session() as db:
            return self._repo.stats(db, user_id=user_id)

    # ------------------------------------------------------------------
    # 批量导入
    # ------------------------------------------------------------------

    def batch_import(
        self,
        endpoints: List[EndpointCreate],
        *,
        source: str = "import",
        user_id: Optional[int] = None,
        created_by: Optional[int] = None,
    ) -> Dict[str, Any]:
        """批量导入接口

        Returns:
            { total, imported, skipped, failed, errors, imported_ids }
        """
        total = len(endpoints)
        imported = 0
        skipped = 0
        failed = 0
        errors: List[str] = []
        imported_ids: List[int] = []

        with self._session() as db:
            for idx, ep_data in enumerate(endpoints):
                try:
                    # 强制 source 为批量导入指定值
                    ep_dict = ep_data.model_dump()
                    ep_dict["source"] = source
                    ep_create = EndpointCreate(**ep_dict)

                    endpoint = self._repo.create(
                        db,
                        name=ep_create.name,
                        method=ep_create.method,
                        path=ep_create.path,
                        summary=ep_create.summary,
                        description=ep_create.description,
                        tags=ep_create.tags,
                        module=ep_create.module,
                        status="draft",
                        source=ep_create.source,
                        headers=[h.model_dump() for h in ep_create.headers] if ep_create.headers else None,
                        params=[p.model_dump() for p in ep_create.params] if ep_create.params else None,
                        body=ep_create.body.model_dump() if ep_create.body else None,
                        response=ep_create.response.model_dump() if ep_create.response else None,
                        auth=ep_create.auth.model_dump() if ep_create.auth else None,
                        user_id=user_id,
                        created_by=created_by,
                    )
                    # 自动分类保存到子表
                    self._save_subtables(
                        db, endpoint.id,
                        headers=[h.model_dump() for h in ep_create.headers] if ep_create.headers else None,
                        params=[p.model_dump() for p in ep_create.params] if ep_create.params else None,
                        body=ep_create.body.model_dump() if ep_create.body else None,
                    )
                    imported += 1
                    imported_ids.append(endpoint.id)
                except EndpointConflictError:
                    skipped += 1
                    logger.debug(
                        f"[ApiEndpointSvc] 批量导入跳过(重复): #{idx} {ep_data.method} {ep_data.path}"
                    )
                except Exception as e:
                    failed += 1
                    err_msg = f"#{idx} {ep_data.method if hasattr(ep_data, 'method') else '?'} {getattr(ep_data, 'path', '?')}: {str(e)}"
                    errors.append(err_msg)
                    logger.warning(f"[ApiEndpointSvc] 批量导入失败: {err_msg}")

        logger.info(
            f"[ApiEndpointSvc] 批量导入完成 total={total} imported={imported} skipped={skipped} failed={failed}"
        )
        return {
            "total": total,
            "imported": imported,
            "skipped": skipped,
            "failed": failed,
            "errors": errors,
            "imported_ids": imported_ids,
        }

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _can_transition(from_status: str, to_status: str) -> bool:
        """检查状态流转是否合法"""
        if from_status == to_status:
            return True
        allowed = _STATE_TRANSITIONS.get(from_status, set())
        return to_status in allowed

    # ------------------------------------------------------------------
    # 子表辅助方法
    # ------------------------------------------------------------------

    def _save_subtables(
        self,
        db: Session,
        api_id: int,
        *,
        headers: Optional[List[Dict[str, Any]]] = None,
        params: Optional[List[Dict[str, Any]]] = None,
        body: Optional[Dict[str, Any]] = None,
    ) -> None:
        """将 headers/body/params 分类保存到子表

        在创建/更新接口时自动调用。传入 None 的部分不修改。
        """
        if headers is not None:
            self._repo.save_headers(db, api_id, headers)
        if params is not None:
            self._repo.save_parameters(db, api_id, params)
        if body is not None:
            self._repo.save_body(db, api_id, body)
