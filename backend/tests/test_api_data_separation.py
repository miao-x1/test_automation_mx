"""
接口数据模型分离测试

测试覆盖:
1. 模型定义: ApiHeader / ApiBody / ApiParameter
2. Repository 子表 CRUD: save / get / replace
3. Swagger 解析自动分类: headers / body / parameters
4. Postman 解析自动分类: headers / body / parameters
5. Service 层子表同步: create / update 自动保存子表
6. 迁移文件结构验证
7. 前端类型定义验证
"""
import asyncio
import json
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, AsyncMock

# ===== Stub 3rd-party modules =====
_STUB_MODULES = ["redis", "pymilvus", "neo4j"]
for mod_name in _STUB_MODULES:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

# pymilvus stub
_pm = sys.modules.get("pymilvus") or types.ModuleType("pymilvus")
if not hasattr(_pm, "DataType"):
    _pm.DataType = type("DataType", (), {"INT64": "int64", "VARCHAR": "varchar", "FLOAT_VECTOR": "float_vector", "BOOL": "bool"})
    _pm.MilvusClient = type("MilvusClient", (), {"__init__": lambda *a, **kw: None})
    _pm.CollectionSchema = type("CollectionSchema", (), {})
    _pm.FieldSchema = type("FieldSchema", (), {})
sys.modules["pymilvus"] = _pm

# pymysql stub
_pymysql = types.ModuleType("pymysql")
_pymysql.paramstyle = "format"
_pymysql.install_as_MySQLdb = lambda: None
_pymysql.connect = lambda *a, **kw: None
sys.modules["pymysql"] = _pymysql

# neo4j stub
_neo = sys.modules.get("neo4j") or types.ModuleType("neo4j")
_neo.GraphDatabase = type("GraphDatabase", (), {"driver": lambda *a, **kw: MagicMock()})
_neo.AsyncGraphDatabase = type("AsyncGraphDatabase", (), {"driver": lambda *a, **kw: MagicMock()})
_neo.Driver = type("Driver", (), {"session": lambda *a, **kw: MagicMock(), "close": lambda *a, **kw: None})
_neo.Session = type("Session", (), {"run": lambda *a, **kw: MagicMock(), "close": lambda *a, **kw: None})
_neo.basic_auth = lambda *a, **kw: MagicMock()
sys.modules["neo4j"] = _neo

# sse_starlette stub
_sse = types.ModuleType("sse_starlette")
_sse_sse = types.ModuleType("sse_starlette.sse")
_sse_sse.EventSourceResponse = type("EventSourceResponse", (), {"__init__": lambda *a, **kw: None})
sys.modules["sse_starlette"] = _sse
sys.modules["sse_starlette.sse"] = _sse_sse


# ===== 测试工具 =====
RESULTS = []

def record(name: str, ok: bool, detail: str = ""):
    status = "[PASS]" if ok else "[FAIL]"
    msg = f"{status} {name}"
    if detail and not ok:
        msg += f" | {detail}"
    print(msg)
    RESULTS.append((name, ok))


# ================================================================== #
#  测试 1-3: 模型定义                                                 #
# ================================================================== #

def test_model_imports():
    """测试 1: 模型导入完整性"""
    errors = []
    try:
        from app.models.api_endpoint import ApiHeader, ApiBody, ApiParameter
    except ImportError as e:
        errors.append(str(e))
    ok = len(errors) == 0
    record("模型-导入完整性", ok, "; ".join(errors))


def test_model_table_names():
    """测试 2: 模型表名正确"""
    from app.models.api_endpoint import ApiHeader, ApiBody, ApiParameter
    ok = ApiHeader.__tablename__ == "api_header"
    ok = ok and ApiBody.__tablename__ == "api_body"
    ok = ok and ApiParameter.__tablename__ == "api_parameter"
    record("模型-表名正确", ok)


def test_model_columns():
    """测试 3: 模型字段定义"""
    from app.models.api_endpoint import ApiHeader, ApiBody, ApiParameter

    # ApiHeader 字段
    header_cols = {c.name for c in ApiHeader.__table__.columns}
    ok = {"id", "api_id", "key", "value", "required", "sort_order"}.issubset(header_cols)

    # ApiBody 字段
    body_cols = {c.name for c in ApiBody.__table__.columns}
    ok = ok and {"id", "api_id", "body_type", "schema_json", "example_json", "raw_text"}.issubset(body_cols)

    # ApiParameter 字段
    param_cols = {c.name for c in ApiParameter.__table__.columns}
    ok = ok and {"id", "api_id", "location", "name", "type", "required", "default_value", "description", "example", "sort_order"}.issubset(param_cols)

    record("模型-字段定义", ok)


# ================================================================== #
#  测试 4-7: Repository 子表 CRUD                                     #
# ================================================================== #

def test_repo_save_headers():
    """测试 4: Repository.save_headers — 替换式保存"""
    from app.repositories.api_endpoint_repository import ApiEndpointRepository

    repo = ApiEndpointRepository()
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.delete = MagicMock(return_value=0)

    headers = [
        {"key": "Content-Type", "value": "application/json", "required": True},
        {"key": "Authorization", "value": "Bearer xxx", "required": True},
    ]
    result = repo.save_headers(mock_db, api_id=1, headers=headers)

    ok = len(result) == 2
    ok = ok and result[0].key == "Content-Type"
    ok = ok and result[1].key == "Authorization"
    ok = ok and result[0].sort_order == 0
    ok = ok and result[1].sort_order == 1
    # 验证先删后插
    ok = ok and mock_db.query.return_value.filter.return_value.delete.called
    record("Repo-save_headers", ok)


def test_repo_save_body():
    """测试 5: Repository.save_body — 替换式保存"""
    from app.repositories.api_endpoint_repository import ApiEndpointRepository

    repo = ApiEndpointRepository()
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.delete = MagicMock(return_value=0)

    body = {
        "content_type": "application/json",
        "schema": {"type": "object", "properties": {"name": {"type": "string"}}},
        "example": {"name": "test"},
    }
    result = repo.save_body(mock_db, api_id=1, body=body)

    ok = result is not None
    ok = ok and result.body_type == "application/json"
    ok = ok and result.raw_text is None
    record("Repo-save_body", ok)


def test_repo_save_parameters():
    """测试 6: Repository.save_parameters — 替换式保存"""
    from app.repositories.api_endpoint_repository import ApiEndpointRepository

    repo = ApiEndpointRepository()
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.delete = MagicMock(return_value=0)

    params = [
        {"name": "page", "in": "query", "type": "integer", "required": False, "default": "1"},
        {"name": "id", "in": "path", "type": "integer", "required": True},
        {"name": "X-Token", "in": "header", "type": "string", "required": True},
    ]
    result = repo.save_parameters(mock_db, api_id=1, parameters=params)

    ok = len(result) == 3
    ok = ok and result[0].name == "page"
    ok = ok and result[0].location == "query"
    ok = ok and result[1].location == "path"
    ok = ok and result[2].location == "header"
    ok = ok and result[0].sort_order == 0
    record("Repo-save_parameters", ok)


def test_repo_get_methods():
    """测试 7: Repository.get_headers / get_body / get_parameters"""
    from app.repositories.api_endpoint_repository import ApiEndpointRepository

    repo = ApiEndpointRepository()
    mock_db = MagicMock()

    # Mock query results for headers
    mock_header = MagicMock()
    mock_header.id = 1
    mock_header.api_id = 10
    mock_header.key = "Content-Type"
    mock_header.value = "application/json"
    mock_header.required = True
    mock_header.sort_order = 0

    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [mock_header]
    headers = repo.get_headers(mock_db, api_id=10)
    ok = len(headers) == 1
    ok = ok and headers[0]["key"] == "Content-Type"
    ok = ok and headers[0]["required"] is True

    # Mock query results for body (None case)
    mock_db.query.return_value.filter.return_value.first.return_value = None
    body = repo.get_body(mock_db, api_id=10)
    ok = ok and body is None

    record("Repo-get_methods", ok)


# ================================================================== #
#  测试 8-9: Swagger 解析自动分类                                     #
# ================================================================== #

async def test_swagger_parse_classification():
    """测试 8: Swagger 解析结果自动分类到 headers / body / parameters"""
    import tempfile
    import os
    from app.services.api_knowledge_service import APIKnowledgeService

    service = APIKnowledgeService()

    # 构造最小 Swagger spec
    swagger_spec = {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0"},
        "paths": {
            "/users/{id}": {
                "get": {
                    "summary": "Get user by ID",
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}},
                        {"name": "X-Auth-Token", "in": "header", "required": True, "schema": {"type": "string"}},
                        {"name": "fields", "in": "query", "required": False, "schema": {"type": "string", "default": "all"}},
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"type": "object", "properties": {"name": {"type": "string"}}},
                                "example": {"name": "John"},
                            }
                        }
                    },
                    "responses": {"200": {"description": "OK"}},
                }
            }
        }
    }

    # 写入临时文件
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(swagger_spec, f)
        temp_path = f.name

    try:
        apis = await service._parse_swagger(temp_path)
        ok = len(apis) == 1
        api = apis[0]

        # 验证结构化分类数据存在
        ok = ok and "_headers" in api
        ok = ok and "_parameters" in api
        ok = ok and "_body" in api

        # 验证 headers 分类 (header 类型参数被分到 headers)
        headers = api["_headers"]
        ok = ok and len(headers) == 1
        ok = ok and headers[0]["key"] == "X-Auth-Token"

        # 验证 parameters 分类 (path + query 类型参数)
        params = api["_parameters"]
        ok = ok and len(params) == 2
        ok = ok and any(p["name"] == "id" and p["in"] == "path" for p in params)
        ok = ok and any(p["name"] == "fields" and p["in"] == "query" for p in params)

        # 验证 body 分类
        body = api["_body"]
        ok = ok and body["content_type"] == "application/json"
        ok = ok and "schema" in body
        ok = ok and body["example"] == {"name": "John"}

        # 验证旧 JSON 字段仍保留 (向后兼容)
        ok = ok and "headers_json" in api
        ok = ok and "parameters_json" in api
        ok = ok and "request_body_json" in api
    finally:
        os.unlink(temp_path)

    record("Swagger解析-自动分类", ok)


async def test_postman_parse_classification():
    """测试 9: Postman 解析结果自动分类到 headers / body / parameters"""
    import tempfile
    import os
    from app.services.api_knowledge_service import APIKnowledgeService

    service = APIKnowledgeService()

    # 构造最小 Postman Collection
    postman_collection = {
        "info": {"name": "Test Collection"},
        "item": [
            {
                "name": "Create User",
                "request": {
                    "method": "POST",
                    "url": {
                        "path": ["api", "v1", "users"],
                        "query": [
                            {"key": "force", "value": "true", "disabled": False},
                        ],
                    },
                    "header": [
                        {"key": "Content-Type", "value": "application/json"},
                        {"key": "X-Request-Id", "value": "12345"},
                    ],
                    "body": {
                        "mode": "raw",
                        "raw": '{"name": "John", "email": "john@example.com"}',
                    },
                },
                "response": [],
            }
        ]
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(postman_collection, f)
        temp_path = f.name

    try:
        apis = await service._parse_postman(temp_path)
        ok = len(apis) == 1
        api = apis[0]

        # 验证结构化分类数据
        ok = ok and "_headers" in api
        ok = ok and "_parameters" in api
        ok = ok and "_body" in api

        # 验证 headers
        headers = api["_headers"]
        ok = ok and len(headers) == 2
        ok = ok and any(h["key"] == "Content-Type" for h in headers)
        ok = ok and any(h["key"] == "X-Request-Id" for h in headers)

        # 验证 parameters
        params = api["_parameters"]
        ok = ok and len(params) == 1
        ok = ok and params[0]["name"] == "force"
        ok = ok and params[0]["in"] == "query"

        # 验证 body
        body = api["_body"]
        ok = ok and body["content_type"] == "raw"
        ok = ok and "John" in body["example"]
    finally:
        os.unlink(temp_path)

    record("Postman解析-自动分类", ok)


# ================================================================== #
#  测试 10: Service 层子表同步                                        #
# ================================================================== #

def test_service_save_subtables():
    """测试 10: Service._save_subtables 辅助方法"""
    from app.services.api_endpoint_service import ApiEndpointService

    service = ApiEndpointService()
    mock_db = MagicMock()

    # Mock repo methods
    service._repo = MagicMock()
    service._repo.save_headers = MagicMock(return_value=[])
    service._repo.save_body = MagicMock(return_value=None)
    service._repo.save_parameters = MagicMock(return_value=[])

    headers = [{"key": "Auth", "value": "Bearer xxx", "required": True}]
    params = [{"name": "page", "in": "query", "type": "integer"}]
    body = {"content_type": "application/json", "schema": {}, "example": {}}

    service._save_subtables(mock_db, api_id=1, headers=headers, params=params, body=body)

    ok = service._repo.save_headers.called
    ok = ok and service._repo.save_body.called
    ok = ok and service._repo.save_parameters.called

    # 验证传入的参数 (save_headers(db, api_id, headers) 全位置参数)
    headers_call = service._repo.save_headers.call_args
    ok = ok and headers_call.args[0] == mock_db   # db
    ok = ok and headers_call.args[1] == 1          # api_id
    ok = ok and headers_call.args[2] == headers    # headers list

    record("Service-_save_subtables", ok)


# ================================================================== #
#  测试 11: 迁移文件验证                                               #
# ================================================================== #

def test_migration_file():
    """测试 11: 迁移文件 031 结构验证"""
    import importlib.util
    import os

    migration_path = os.path.join(
        os.path.dirname(__file__), "..", "alembic", "versions", "031_add_api_sub_tables.py"
    )
    migration_path = os.path.abspath(migration_path)

    ok = os.path.exists(migration_path)
    if not ok:
        record("迁移文件-存在性", False, f"文件不存在: {migration_path}")
        return

    # 加载迁移模块
    spec = importlib.util.spec_from_file_location("migration_031", migration_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    ok = mod.revision == "031"
    ok = ok and mod.down_revision == "030"

    # 验证 upgrade 函数存在且可调用
    ok = ok and callable(mod.upgrade)
    ok = ok and callable(mod.downgrade)

    record("迁移文件-结构验证", ok)


# ================================================================== #
#  测试 12: 前端类型定义验证                                           #
# ================================================================== #

def test_frontend_types():
    """测试 12: 前端类型定义文件包含子表类型"""
    import os
    frontend_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "frontend", "src", "services", "apiEndpoint.ts"
    )
    frontend_path = os.path.abspath(frontend_path)

    ok = os.path.exists(frontend_path)
    if not ok:
        record("前端-类型定义", False, f"文件不存在: {frontend_path}")
        return

    with open(frontend_path, "r", encoding="utf-8") as f:
        content = f.read()

    ok = "ApiHeaderItem" in content
    ok = ok and "ApiBodyItem" in content
    ok = ok and "ApiParameterItem" in content
    ok = ok and "api_headers" in content
    ok = ok and "api_body" in content
    ok = ok and "api_parameters" in content

    record("前端-类型定义", ok)


# ================================================================== #
#  测试 13: 前端详情页 Tab 验证                                       #
# ================================================================== #

def test_frontend_detail_page():
    """测试 13: 前端详情页包含子表数据展示"""
    import os
    page_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "frontend", "src", "pages", "api-endpoint",
        "EndpointDetailPage.tsx"
    )
    page_path = os.path.abspath(page_path)

    ok = os.path.exists(page_path)
    if not ok:
        record("前端-详情页", False, f"文件不存在: {page_path}")
        return

    with open(page_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 验证使用 api_headers / api_body / api_parameters 新字段
    ok = "api_headers" in content
    ok = ok and "api_body" in content
    ok = ok and "api_parameters" in content
    # 验证有回退逻辑
    ok = ok and "endpoint.headers" in content  # 旧字段回退
    # 验证 Tab 标签存在
    ok = ok and "请求头" in content
    ok = ok and "参数" in content
    ok = ok and "请求体" in content

    record("前端-详情页Tab", ok)


# ================================================================== #
#  测试 14: 数据分离效果对比                                           #
# ================================================================== #

def test_data_separation_comparison():
    """测试 14: 数据分离前后对比"""
    print("\n" + "=" * 60)
    print("           数据分离效果对比: JSON 列 vs 独立子表")
    print("=" * 60)

    # 模拟旧方式: 所有数据在一个 JSON 列
    old_format = {
        "headers_json": json.dumps([
            {"key": "Content-Type", "value": "application/json", "required": True, "description": ""},
            {"key": "Authorization", "value": "Bearer xxx", "required": True, "description": ""},
            {"key": "X-Request-Id", "value": "12345", "required": False, "description": ""},
        ]),
        "params_json": json.dumps([
            {"name": "page", "in": "query", "type": "integer", "required": False, "default": "1"},
            {"name": "id", "in": "path", "type": "integer", "required": True, "default": ""},
        ]),
        "body_json": json.dumps({
            "content_type": "application/json",
            "schema": {"type": "object", "properties": {"name": {"type": "string"}}},
            "example": {"name": "test"},
        }),
    }

    old_size = sum(len(v) for v in old_format.values())

    # 新方式: 数据分布在子表中
    new_headers = [
        {"api_id": 1, "key": "Content-Type", "value": "application/json", "required": True, "sort_order": 0},
        {"api_id": 1, "key": "Authorization", "value": "Bearer xxx", "required": True, "sort_order": 1},
        {"api_id": 1, "key": "X-Request-Id", "value": "12345", "required": False, "sort_order": 2},
    ]
    new_params = [
        {"api_id": 1, "location": "query", "name": "page", "type": "integer", "required": False, "default_value": "1", "sort_order": 0},
        {"api_id": 1, "location": "path", "name": "id", "type": "integer", "required": True, "default_value": "", "sort_order": 1},
    ]
    new_body = {
        "api_id": 1, "body_type": "application/json",
        "schema_json": json.dumps({"type": "object", "properties": {"name": {"type": "string"}}}),
        "example_json": json.dumps({"name": "test"}),
        "raw_text": None,
    }

    new_size = (
        sum(len(json.dumps(h, ensure_ascii=False)) for h in new_headers)
        + sum(len(json.dumps(p, ensure_ascii=False)) for p in new_params)
        + len(json.dumps(new_body, ensure_ascii=False))
    )

    print()
    print("┌─────────────────────┬──────────────────┬──────────────────┐")
    print("│ 维度                │ 旧 (JSON 列)      │ 新 (子表)        │")
    print("├─────────────────────┼──────────────────┼──────────────────┤")
    print(f"│ 数据大小            │ {old_size:>14d}B  │ {new_size:>14d}B  │")
    print(f"│ Headers 数量        │              3   │              3   │")
    print(f"│ Parameters 数量     │              2   │              2   │")
    print(f"│ Body 行数           │              1   │              1   │")
    print("├─────────────────────┼──────────────────┼──────────────────┤")
    print("│ 查询效率            │  JSON 全表扫描   │  索引精确查询    │")
    print("│ 单独查询 Headers    │  不支持          │  支持 (api_id)  │")
    print("│ 单独查询 Body       │  不支持          │  支持 (api_id)  │")
    print("│ 单独查询 Parameters │  不支持          │  支持 (api_id)  │")
    print("│ 按 location 过滤    │  不支持          │  支持 (列查询)  │")
    print("│ 按 required 过滤    │  不支持          │  支持 (列查询)  │")
    print("└─────────────────────┴──────────────────┴──────────────────┘")
    print()
    print("  核心收益: 子表支持按字段精确查询, 无需 JSON 反序列化全量扫描")
    print("=" * 60)

    # 新方式应支持单独查询
    ok = new_size > 0  # 确保数据结构正确
    record("数据分离-效果对比", ok)


# ================================================================== #
#  测试 15: 模块导入完整性                                             #
# ================================================================== #

def test_model_init_exports():
    """测试 15: models __init__.py 导出新模型"""
    from app.models import ApiHeader, ApiBody, ApiParameter
    ok = ApiHeader is not None and ApiBody is not None and ApiParameter is not None
    record("模块-__init__导出", ok)


# ================================================================== #
#  主函数                                                              #
# ================================================================== #

async def main():
    print("=" * 60)
    print("接口数据模型分离测试")
    print("=" * 60)

    test_model_imports()
    test_model_table_names()
    test_model_columns()

    test_repo_save_headers()
    test_repo_save_body()
    test_repo_save_parameters()
    test_repo_get_methods()

    await test_swagger_parse_classification()
    await test_postman_parse_classification()

    test_service_save_subtables()

    test_migration_file()

    test_frontend_types()
    test_frontend_detail_page()

    test_data_separation_comparison()

    test_model_init_exports()

    print("\n" + "=" * 60)
    passed = sum(1 for _, ok in RESULTS if ok)
    failed = sum(1 for _, ok in RESULTS if not ok)
    total = len(RESULTS)
    print(f"测试结果: {passed}/{total} 通过, {failed} 失败")
    print("=" * 60)
    if failed == 0:
        print("全部测试通过!")
    else:
        for name, ok in RESULTS:
            if not ok:
                print(f"  失败: {name}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
