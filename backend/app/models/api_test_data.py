"""
API 测试数据智能生成 — 数据库模型

新增 2 张表 (Phase 1):
  - api_test_data_template: 测试数据模板 (可复用, 关联到接口)
  - generated_api_data:      按模板生成的具体数据实例 (可追溯到模板)

设计原则:
  1. 继承 OwnedModel, 自动获得 id/created_at/updated_at/user_id/created_by
  2. 软删除 (is_deleted), 不物理删除
  3. 与 api_endpoint 软关联 (endpoint_id, 不加 FK 约束, 保持解耦)
  4. 模板 + 实例分离: 模板可复用, 实例可追溯
  5. data_type 枚举: normal / abnormal / boundary / dependent

与 ApiDataGeneratorAgent 的关系:
  - Agent 生成数据时, 优先查模板复用, 没有模板才从 Schema 推导
  - 每次生成的数据落 generated_api_data, 便于追溯和统计分析
"""
import enum
from sqlalchemy import (
    Column, String, Text, Integer, Boolean, Index,
    ForeignKey, Enum as SAEnum
)
from app.db.types import MEDIUMTEXT
from sqlalchemy.orm import relationship

from app.models.base import OwnedModel


# ============================================================
# 枚举定义
# ============================================================

class DataType(str, enum.Enum):
    """测试数据类型"""
    NORMAL = "normal"           # 正常数据: 满足所有约束的合法值
    ABNORMAL = "abnormal"       # 异常数据: 违反约束的非法值 (空/超长/类型错)
    BOUNDARY = "boundary"       # 边界数据: 边界值 (min-1/min/max/max+1)
    DEPENDENT = "dependent"     # 关联数据: 依赖其他接口返回的数据


class GenerationSource(str, enum.Enum):
    """数据生成来源"""
    RULE = "rule"               # 规则引擎: 基于 Schema 约束直接生成
    FAKER = "faker"             # Faker: 语义化随机 (email/username/phone)
    LLM = "llm"                 # LLM: 复杂语义推理 (跨字段关联)
    DB = "db"                   # DB: 从历史样本采样
    RUNTIME = "runtime"         # Runtime: 运行时从依赖接口取值
    TEMPLATE = "template"      # 模板复用


class TemplateStatus(str, enum.Enum):
    """模板状态"""
    DRAFT = "draft"             # 草稿
    ACTIVE = "active"           # 启用
    DEPRECATED = "deprecated"   # 废弃


# ============================================================
# api_test_data_template — 测试数据模板
# ============================================================

class ApiTestDataTemplate(OwnedModel):
    """API 测试数据模板

    一个模板对应一个接口的一类数据 (如: 注册接口的正常数据模板)。
    模板可被多次复用, 每次复用生成一条 generated_api_data 记录。

    使用场景:
      1. ApiDataGeneratorAgent 生成数据时, 优先按 endpoint_id + data_type 查模板
      2. 找到 active 模板 → 按模板规则生成
      3. 找不到 → 从 Schema 推导, 生成后回填为新模板 (下次可复用)
    """
    __tablename__ = "api_test_data_template"

    # ===== 关联 =====
    endpoint_id = Column(
        Integer, nullable=False, index=True,
        comment="关联 api_endpoint.id (软关联, 不加 FK)"
    )

    # ===== 基本信息 =====
    name = Column(
        String(200), nullable=False,
        comment="模板名称 (如: 注册接口-正常数据模板)"
    )
    description = Column(
        Text, nullable=True,
        comment="模板说明"
    )
    data_type = Column(
        SAEnum(DataType, length=20, native_enum=False),
        nullable=False, default=DataType.NORMAL,
        comment="数据类型: normal/abnormal/boundary/dependent"
    )

    # ===== 生成规则 (核心) =====
    # fields_schema: 接口参数的字段定义 JSON
    #   [{name, type, required, min_length, max_length, pattern, enum, format, description}]
    fields_schema = Column(
        MEDIUMTEXT, nullable=True,
        comment="字段定义 JSON (从接口 Schema 提取)"
    )
    # generation_rules: 每个字段的生成规则 JSON
    #   [{field, source, faker_method, rule_type, params, nullable_override}]
    generation_rules = Column(
        MEDIUMTEXT, nullable=True,
        comment="生成规则 JSON (source: rule/faker/llm/db/runtime)"
    )

    # ===== 关联接口 (dependent 类型用) =====
    # dependencies_json: 依赖的其他接口 JSON
    #   [{field, ref_endpoint_id, ref_path, extract_rule}]
    dependencies_json = Column(
        Text, nullable=True,
        comment="依赖接口 JSON (dependent 类型用)"
    )

    # ===== 状态 =====
    status = Column(
        SAEnum(TemplateStatus, length=20, native_enum=False),
        nullable=False, default=TemplateStatus.DRAFT,
        comment="模板状态"
    )

    # ===== 元数据 =====
    tags = Column(
        String(500), nullable=True,
        comment="标签 (逗号分隔)"
    )
    usage_count = Column(
        Integer, nullable=False, default=0,
        comment="被使用次数 (统计用)"
    )
    last_used_at = Column(
        String(30), nullable=True,
        comment="最后使用时间 (YYYY-MM-DD HH:MM:SS)"
    )
    is_deleted = Column(
        Boolean, nullable=False, default=False,
        comment="软删除标记"
    )

    # ===== 关系 (ORM 层, 非 DB FK) =====
    generated_data = relationship(
        "GeneratedApiData",
        back_populates="template",
        primaryjoin="ApiTestDataTemplate.id == GeneratedApiData.template_id",
        foreign_keys="GeneratedApiData.template_id",
        cascade="all, delete-orphan",
        passive_deletes=True
    )

    __table_args__ = (
        # 按接口 + 类型查模板 (Agent 首选查询)
        Index("idx_template_endpoint_type", "endpoint_id", "data_type", "status"),
        # 按状态查可用模板
        Index("idx_template_status", "status", "is_deleted"),
        # 按用户隔离
        Index("idx_template_user", "user_id", "is_deleted"),
        {"comment": "API 测试数据模板表"}
    )

    def __repr__(self):
        return f"<ApiTestDataTemplate(id={self.id}, endpoint_id={self.endpoint_id}, type={self.data_type})>"


# ============================================================
# generated_api_data — 生成的测试数据实例
# ============================================================

class GeneratedApiData(OwnedModel):
    """生成的 API 测试数据实例

    每次调用 ApiDataGeneratorAgent 生成数据, 都落一条实例记录。
    与 api_test_data_template 是 N:1 关系 (一个模板可生成多个实例)。

    使用场景:
      1. 数据可追溯: 哪个接口、哪次生成、用了什么规则
      2. 统计分析: 接口数据生成成功率、各类型分布
      3. 历史回放: 复现某次测试的具体数据
    """
    __tablename__ = "generated_api_data"

    # ===== 关联 =====
    endpoint_id = Column(
        Integer, nullable=False, index=True,
        comment="关联 api_endpoint.id (软关联)"
    )
    template_id = Column(
        Integer, nullable=True, index=True,
        comment="关联 api_test_data_template.id (无模板则空)"
    )
    case_id = Column(
        Integer, nullable=True, index=True,
        comment="关联 api_case.id (若被用例引用)"
    )

    # ===== 数据内容 =====
    data_type = Column(
        SAEnum(DataType, length=20, native_enum=False),
        nullable=False, default=DataType.NORMAL,
        comment="数据类型"
    )
    # generated_data: 生成的具体数据 JSON
    #   normal:   {"username":"test001","password":"123456","email":"test@test.com"}
    #   abnormal: {"username":"","password":"123"}
    #   boundary: {"username":"a"*100}
    #   dependent: {"user_id":"$REF.get_user.response.id"}
    generated_data = Column(
        MEDIUMTEXT, nullable=False,
        comment="生成的数据 JSON"
    )

    # ===== 生成元信息 =====
    source = Column(
        SAEnum(GenerationSource, length=20, native_enum=False),
        nullable=False, default=GenerationSource.RULE,
        comment="生成来源: rule/faker/llm/db/runtime/template"
    )
    # fields_meta: 每个字段的生成详情 JSON
    #   [{field, source, value, faker_method, llm_reason}]
    fields_meta = Column(
        Text, nullable=True,
        comment="字段生成详情 JSON (用于可解释性)"
    )
    elapsed_ms = Column(
        Integer, nullable=False, default=0,
        comment="生成耗时 (毫秒)"
    )

    # ===== 校验结果 =====
    is_valid = Column(
        Boolean, nullable=False, default=True,
        comment="数据是否通过校验 (符合 Schema)"
    )
    validation_errors = Column(
        Text, nullable=True,
        comment="校验错误信息 (若 is_valid=False)"
    )

    # ===== 软删除 =====
    is_deleted = Column(
        Boolean, nullable=False, default=False,
        comment="软删除标记"
    )

    # ===== 关系 =====
    template = relationship(
        "ApiTestDataTemplate",
        back_populates="generated_data",
        primaryjoin="GeneratedApiData.template_id == ApiTestDataTemplate.id",
        foreign_keys="GeneratedApiData.template_id",
        lazy="select"
    )

    __table_args__ = (
        # 按接口 + 类型查数据 (统计/列表)
        Index("idx_data_endpoint_type", "endpoint_id", "data_type", "is_deleted"),
        # 按用例查数据 (执行时回放)
        Index("idx_data_case", "case_id", "is_deleted"),
        # 按模板查数据 (模板使用统计)
        Index("idx_data_template", "template_id", "is_deleted"),
        # 按用户隔离
        Index("idx_data_user", "user_id", "is_deleted"),
        # 按时间排序 (历史)
        Index("idx_data_created", "created_at"),
        {"comment": "生成的 API 测试数据实例表"}
    )

    def __repr__(self):
        return (
            f"<GeneratedApiData(id={self.id}, endpoint_id={self.endpoint_id}, "
            f"type={self.data_type}, source={self.source})>"
        )
