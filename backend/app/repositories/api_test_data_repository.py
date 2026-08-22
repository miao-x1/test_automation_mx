"""
ApiTestDataRepository - 数据访问层

职责:
  1. 封装 api_test_data_template / generated_api_data 的 CRUD
  2. JSON 字段序列化 (fields_schema / generation_rules / generated_data)
  3. 软删除过滤 (is_deleted=False)
  4. 按 endpoint_id / data_type / status 过滤
  5. 分页查询

不做:
  - 业务校验 (由 service 负责)
  - 调用 Agent (由 service 负责)
"""
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.models.api_test_data import (
    ApiTestDataTemplate,
    GeneratedApiData,
    DataType,
    GenerationSource,
    TemplateStatus,
)

logger = logging.getLogger(__name__)


def _dump_json(value: Any) -> Optional[str]:
    """Python 对象 → JSON 字符串"""
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as e:
        logger.warning(f"JSON 序列化失败: {e}")
        return None


def _load_json(value: Optional[str], default: Any = None) -> Any:
    """JSON 字符串 → Python 对象"""
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError) as e:
        logger.warning(f"JSON 反序列化失败: {e}")
        return default


# ============================================================
# 模板 Repository
# ============================================================

class ApiTestDataTemplateRepository:
    """测试数据模板数据访问层"""

    def create(self, db: Session, **kwargs) -> ApiTestDataTemplate:
        """创建模板"""
        # 序列化 JSON 字段
        if "fields_schema" in kwargs and kwargs["fields_schema"] is not None:
            kwargs["fields_schema"] = _dump_json(kwargs["fields_schema"])
        if "generation_rules" in kwargs and kwargs["generation_rules"] is not None:
            kwargs["generation_rules"] = _dump_json(kwargs["generation_rules"])
        if "dependencies_json" in kwargs and kwargs["dependencies_json"] is not None:
            kwargs["dependencies_json"] = _dump_json(kwargs["dependencies_json"])

        tmpl = ApiTestDataTemplate(**kwargs)
        db.add(tmpl)
        db.flush()
        db.refresh(tmpl)
        return tmpl

    def get_by_id(self, db: Session, tmpl_id: int) -> ApiTestDataTemplate:
        """按 ID 查询 (含软删除过滤)"""
        return db.query(ApiTestDataTemplate).filter(
            ApiTestDataTemplate.id == tmpl_id,
            ApiTestDataTemplate.is_deleted == False,
        ).first()

    def list(
        self,
        db: Session,
        *,
        endpoint_id: Optional[int] = None,
        data_type: Optional[str] = None,
        status: Optional[str] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[ApiTestDataTemplate], int]:
        """分页查询模板"""
        q = db.query(ApiTestDataTemplate).filter(
            ApiTestDataTemplate.is_deleted == False
        )

        if endpoint_id:
            q = q.filter(ApiTestDataTemplate.endpoint_id == endpoint_id)
        if data_type:
            try:
                dt = DataType(data_type)
                q = q.filter(ApiTestDataTemplate.data_type == dt)
            except ValueError:
                pass
        if status:
            try:
                st = TemplateStatus(status)
                q = q.filter(ApiTestDataTemplate.status == st)
            except ValueError:
                pass
        if keyword:
            q = q.filter(
                or_(
                    ApiTestDataTemplate.name.like(f"%{keyword}%"),
                    ApiTestDataTemplate.description.like(f"%{keyword}%"),
                )
            )

        total = q.count()
        items = q.order_by(ApiTestDataTemplate.created_at.desc()) \
                 .offset((page - 1) * page_size) \
                 .limit(page_size) \
                 .all()
        return items, total

    def update(self, db: Session, tmpl: ApiTestDataTemplate, **kwargs) -> ApiTestDataTemplate:
        """更新模板"""
        for key, value in kwargs.items():
            if value is None:
                continue
            if key in ("fields_schema", "generation_rules", "dependencies_json"):
                value = _dump_json(value)
            setattr(tmpl, key, value)
        db.flush()
        db.refresh(tmpl)
        return tmpl

    def soft_delete(self, db: Session, tmpl: ApiTestDataTemplate) -> None:
        """软删除"""
        tmpl.is_deleted = True
        db.flush()

    def to_dict(self, tmpl: ApiTestDataTemplate) -> Dict[str, Any]:
        """转换为 dict (用于响应)"""
        return {
            "id": tmpl.id,
            "endpoint_id": tmpl.endpoint_id,
            "name": tmpl.name,
            "description": tmpl.description,
            "data_type": tmpl.data_type.value if tmpl.data_type else None,
            "fields_schema": _load_json(tmpl.fields_schema),
            "generation_rules": _load_json(tmpl.generation_rules),
            "dependencies_json": _load_json(tmpl.dependencies_json),
            "status": tmpl.status.value if tmpl.status else None,
            "tags": tmpl.tags,
            "usage_count": tmpl.usage_count,
            "last_used_at": tmpl.last_used_at,
            "created_at": str(tmpl.created_at) if tmpl.created_at else None,
            "updated_at": str(tmpl.updated_at) if tmpl.updated_at else None,
        }


# ============================================================
# 已生成数据 Repository
# ============================================================

class GeneratedDataRepository:
    """已生成数据访问层"""

    def create(self, db: Session, **kwargs) -> GeneratedApiData:
        """创建一条生成数据"""
        if "generated_data" in kwargs and not isinstance(kwargs["generated_data"], str):
            kwargs["generated_data"] = _dump_json(kwargs["generated_data"])
        if "fields_meta" in kwargs and kwargs["fields_meta"] is not None:
            kwargs["fields_meta"] = _dump_json(kwargs["fields_meta"])

        record = GeneratedApiData(**kwargs)
        db.add(record)
        db.flush()
        db.refresh(record)
        return record

    def get_by_id(self, db: Session, data_id: int) -> GeneratedApiData:
        """按 ID 查询"""
        return db.query(GeneratedApiData).filter(
            GeneratedApiData.id == data_id,
            GeneratedApiData.is_deleted == False,
        ).first()

    def list(
        self,
        db: Session,
        *,
        endpoint_id: Optional[int] = None,
        data_type: Optional[str] = None,
        case_id: Optional[int] = None,
        template_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[GeneratedApiData], int]:
        """分页查询已生成数据"""
        q = db.query(GeneratedApiData).filter(GeneratedApiData.is_deleted == False)

        if endpoint_id:
            q = q.filter(GeneratedApiData.endpoint_id == endpoint_id)
        if data_type:
            try:
                dt = DataType(data_type)
                q = q.filter(GeneratedApiData.data_type == dt)
            except ValueError:
                pass
        if case_id:
            q = q.filter(GeneratedApiData.case_id == case_id)
        if template_id:
            q = q.filter(GeneratedApiData.template_id == template_id)

        total = q.count()
        items = q.order_by(GeneratedApiData.created_at.desc()) \
                 .offset((page - 1) * page_size) \
                 .limit(page_size) \
                 .all()
        return items, total

    def to_dict(self, record: GeneratedApiData) -> Dict[str, Any]:
        """转换为 dict"""
        return {
            "id": record.id,
            "endpoint_id": record.endpoint_id,
            "template_id": record.template_id,
            "case_id": record.case_id,
            "data_type": record.data_type.value if record.data_type else None,
            "generated_data": _load_json(record.generated_data),
            "source": record.source.value if record.source else None,
            "elapsed_ms": record.elapsed_ms,
            "is_valid": record.is_valid,
            "validation_errors": record.validation_errors,
            "created_at": str(record.created_at) if record.created_at else None,
        }

    def soft_delete(self, db: Session, record: GeneratedApiData) -> None:
        """软删除"""
        record.is_deleted = True
        db.flush()
