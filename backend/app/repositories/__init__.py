"""
Repository 模块 - 数据访问层

本目录是 API 接口管理模块引入的"数据访问层"抽象。
既有代码沿用 services 直接访问 DB 的模式,本目录作为新模块的独立架构,
不影响既有代码,后续模块可按需沿用此模式。

设计原则:
  1. Repository 只做 CRUD,不含业务逻辑
  2. 输入输出均为 SQLAlchemy 模型实例(不返回 schema)
  3. JSON 字段的序列化/反序列化由 repository 内部处理
  4. 软删除统一过滤(is_deleted=False)
"""
from app.repositories.api_endpoint_repository import ApiEndpointRepository

__all__ = ["ApiEndpointRepository"]
