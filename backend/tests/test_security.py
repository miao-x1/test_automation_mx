"""
企业级安全模块全链路测试

验证:
1. 数据模型(ApiKey/OperationLog/AuditEvent/MaskingRule CRUD + JSON解析)
2. 脱敏服务(内置策略/自动检测/字典脱敏/规则管理)
3. API Key服务(创建/验证/撤销/统计)
4. 审计服务(操作日志/审计事件/仪表盘/异常检测)
5. API路由完整性
6. 中间件注册验证

运行:
    cd backend
    python -m tests.test_security
"""
import json
import logging
import os
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

# 确保能 import app.*
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

# 测试用:强制使用 SQLite
os.environ.setdefault("USE_SQLITE", "True")
os.environ.setdefault("SQLITE_PATH", "data/test_security.db")

# stub out optional 3rd-party modules
_STUB_MODULES = ["redis"]
for mod_name in _STUB_MODULES:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

# neo4j stub
if "neo4j" not in sys.modules:
    _neo4j_stub = types.ModuleType("neo4j")
    _neo4j_stub.GraphDatabase = type("GraphDatabase", (), {
        "driver": staticmethod(lambda *a, **kw: None),
        "verify_connectivity": staticmethod(lambda *a, **kw: None),
    })
    _neo4j_stub.Driver = type("Driver", (), {})
    _neo4j_stub.Session = type("Session", (), {})
    _neo4j_stub.Graph = type("Graph", (), {})
    _neo4j_stub.Node = type("Node", (), {})
    _neo4j_stub.Relationship = type("Relationship", (), {})
    _neo4j_stub.Path = type("Path", (), {})
    _neo4j_stub.Transaction = type("Transaction", (), {})
    _neo4j_stub.Result = type("Result", (), {})
    _neo4j_stub.Record = type("Record", (), {})
    _neo4j_stub.exceptions = types.SimpleNamespace(
        ServiceUnavailable=Exception, AuthError=Exception, CypherError=Exception,
        ClientError=Exception, DatabaseError=Exception, TransientError=Exception,
    )
    sys.modules["neo4j"] = _neo4j_stub

# pymilvus stub
if "pymilvus" not in sys.modules:
    _pymilvus_stub = types.ModuleType("pymilvus")
    _pymilvus_stub.MilvusClient = type("MilvusClient", (), {
        "__init__": lambda self, *a, **kw: None,
        "create_collection": lambda self, *a, **kw: None,
        "drop_collection": lambda self, *a, **kw: None,
        "list_collections": lambda self, *a, **kw: [],
        "describe_collection": lambda self, *a, **kw: {},
        "insert": lambda self, *a, **kw: {"insert_count": 0},
        "search": lambda self, *a, **kw: [],
        "query": lambda self, *a, **kw: [],
        "delete": lambda self, *a, **kw: {"delete_count": 0},
        "upsert": lambda self, *a, **kw: {"upsert_count": 0},
        "close": lambda self, *a, **kw: None,
    })
    _pymilvus_stub.DataType = type("DataType", (), {
        "INT64": "INT64", "FLOAT_VECTOR": "FLOAT_VECTOR", "BOOL": "BOOL",
        "DOUBLE": "DOUBLE", "VARCHAR": "VARCHAR", "JSON": "JSON",
    })
    _pymilvus_stub.CollectionSchema = type("CollectionSchema", (), {"__init__": lambda self, *a, **kw: None})
    _pymilvus_stub.FieldSchema = type("FieldSchema", (), {"__init__": lambda self, *a, **kw: None})
    _pymilvus_stub.Collection = type("Collection", (), {
        "__init__": lambda self, *a, **kw: None,
        "create": lambda self, *a, **kw: None, "drop": lambda self, *a, **kw: None,
        "load": lambda self, *a, **kw: None, "release": lambda self, *a, **kw: None,
        "insert": lambda self, *a, **kw: None, "search": lambda self, *a, **kw: [],
        "query": lambda self, *a, **kw: [],
    })
    _pymilvus_stub.utility = types.SimpleNamespace(
        list_collections=lambda *a, **kw: [], has_collection=lambda *a, **kw: False,
        drop_collection=lambda *a, **kw: None, create_collection=lambda *a, **kw: None,
        get_connection=lambda *a, **kw: None, connect=lambda *a, **kw: None,
        disconnect=lambda *a, **kw: None,
    )
    _pymilvus_stub.exceptions = types.SimpleNamespace(MilvusException=Exception)
    _pymilvus_stub.list_collections = lambda *a, **kw: []
    sys.modules["pymilvus"] = _pymilvus_stub
    sys.modules["pymilvus.utility"] = _pymilvus_stub.utility
    sys.modules["pymilvus.exceptions"] = _pymilvus_stub.exceptions

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("test_security")

results = []


def record(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    results.append({"name": name, "status": status, "detail": detail})
    logger.info(f"[{status}] {name}" + (f" - {detail}" if detail else ""))


# ============================================================
# 数据库准备
# ============================================================

def setup_database():
    from app.db.database import Base, sync_engine
    from app.models.security import ApiKey, OperationLog, AuditEvent, MaskingRule
    from app.models.user import User, Workspace

    # Monkey-patch MEDIUMTEXT → Text for SQLite compatibility
    from sqlalchemy.dialects.mysql import MEDIUMTEXT
    from sqlalchemy import Text
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, MEDIUMTEXT):
                col.type = Text()

    tables_to_create = [
        User.__table__,
        Workspace.__table__,
        ApiKey.__table__,
        OperationLog.__table__,
        AuditEvent.__table__,
        MaskingRule.__table__,
    ]
    Base.metadata.create_all(bind=sync_engine, tables=tables_to_create)
    logger.info("测试数据库表已创建")


def cleanup_database():
    from app.db.database import SessionLocal
    from app.models.security import ApiKey, OperationLog, AuditEvent, MaskingRule
    from app.models.user import User, Workspace

    db = SessionLocal()
    try:
        db.query(MaskingRule).delete()
        db.query(AuditEvent).delete()
        db.query(OperationLog).delete()
        db.query(ApiKey).delete()
        db.query(Workspace).delete()
        db.query(User).delete()
        db.commit()
        logger.info("测试数据已清理")
    finally:
        db.close()


def seed_user():
    from app.db.database import SessionLocal
    from app.models.user import User, Workspace

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == 1).first()
        if user is None:
            user = User(username="admin", email="admin@test.com",
                        hashed_password="hashed", role="admin")
            db.add(user)
            db.flush()

        ws = db.query(Workspace).filter(Workspace.user_id == user.id).first()
        if ws is None:
            ws = Workspace(user_id=user.id, name="测试空间")
            db.add(ws)
        db.commit()
    finally:
        db.close()


# ============================================================
# 脱敏函数测试
# ============================================================

def test_mask_phone():
    """测试 1: 手机号脱敏"""
    from app.services.masking_service import mask_phone
    ok = mask_phone("13812345678") == "138****5678"
    ok = ok and mask_phone("123") == "****"
    ok = ok and mask_phone("") == "****"
    record("脱敏-手机号", ok)


def test_mask_email():
    """测试 2: 邮箱脱敏"""
    from app.services.masking_service import mask_email
    ok = mask_email("test@example.com") == "t***@example.com"
    ok = ok and "*" in mask_email("a@b.com") and mask_email("a@b.com").endswith("@b.com")
    ok = ok and mask_email("invalid") == "****"
    record("脱敏-邮箱", ok)


def test_mask_id_card():
    """测试 3: 身份证脱敏"""
    from app.services.masking_service import mask_id_card
    result = mask_id_card("110101199001011234")
    ok = result.startswith("110") and result.endswith("1234")
    ok = ok and "*" in result
    record("脱敏-身份证", ok)


def test_mask_bank_card():
    """测试 4: 银行卡脱敏"""
    from app.services.masking_service import mask_bank_card
    result = mask_bank_card("6222021234567890123")
    ok = result.startswith("6222") and result.endswith("0123")
    ok = ok and "****" in result
    record("脱敏-银行卡", ok)


def test_mask_api_key():
    """测试 5: API密钥脱敏"""
    from app.services.masking_service import mask_api_key
    result = mask_api_key("sk-abc123def456ghi789")
    ok = result.startswith("sk-a") and result.endswith("i789")
    ok = ok and "***" in result
    record("脱敏-API密钥", ok)


def test_mask_password():
    """测试 6: 密码脱敏"""
    from app.services.masking_service import mask_password
    ok = mask_password("mysecret") == "********"
    ok = ok and mask_password("ab") == "**"
    ok = ok and mask_password("") == ""
    record("脱敏-密码", ok)


def test_mask_token():
    """测试 7: Token脱敏"""
    from app.services.masking_service import mask_token
    result = mask_token("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.123456")
    ok = result.startswith("***") and result.endswith("3456")
    record("脱敏-Token", ok)


def test_mask_custom():
    """测试 8: 自定义脱敏"""
    from app.services.masking_service import mask_custom
    result = mask_custom("abcdefghij", visible_chars=4)
    ok = result == "******ghij"
    result2 = mask_custom("abcdefghij", visible_chars=4, custom_mask="{start}***{end}")
    ok = ok and "abc" in result2 and "ghij" in result2
    record("脱敏-自定义", ok)


def test_mask_value_dispatch():
    """测试 9: mask_value 分发"""
    from app.services.masking_service import mask_value, MaskType
    ok = mask_value("13812345678", MaskType.PHONE.value) == "138****5678"
    ok = ok and mask_value("test@example.com", MaskType.EMAIL.value) == "t***@example.com"
    ok = ok and mask_value("secret123", MaskType.PASSWORD.value) == "********"
    ok = ok and mask_value(None, MaskType.PHONE.value) is None
    record("脱敏-mask_value分发", ok)


def test_auto_detect():
    """测试 10: 自动类型检测"""
    from app.services.masking_service import auto_detect_mask_type, MaskType
    ok = auto_detect_mask_type("13812345678") == MaskType.PHONE.value
    ok = ok and auto_detect_mask_type("test@example.com") == MaskType.EMAIL.value
    ok = ok and auto_detect_mask_type("110101199001011234") == MaskType.ID_CARD.value
    ok = ok and auto_detect_mask_type("6222021234567890123") == MaskType.BANK_CARD.value
    ok = ok and auto_detect_mask_type("random text") is None
    record("脱敏-自动类型检测", ok)


def test_is_sensitive_field():
    """测试 11: 敏感字段检测"""
    from app.services.masking_service import is_sensitive_field
    ok = is_sensitive_field("password") is True
    ok = ok and is_sensitive_field("api_key") is True
    ok = ok and is_sensitive_field("token") is True
    ok = ok and is_sensitive_field("secret") is True
    ok = ok and is_sensitive_field("user_password") is True
    ok = ok and is_sensitive_field("my_api_key") is True
    ok = ok and is_sensitive_field("name") is False
    ok = ok and is_sensitive_field("email") is False
    ok = ok and is_sensitive_field("") is False
    record("脱敏-敏感字段检测", ok)


def test_get_default_mask_type():
    """测试 12: 默认脱敏类型"""
    from app.services.masking_service import get_default_mask_type, MaskType
    ok = get_default_mask_type("password") == MaskType.PASSWORD.value
    ok = ok and get_default_mask_type("api_key") == MaskType.API_KEY.value
    ok = ok and get_default_mask_type("token") == MaskType.TOKEN.value
    ok = ok and get_default_mask_type("email") == MaskType.EMAIL.value
    ok = ok and get_default_mask_type("phone") == MaskType.PHONE.value
    ok = ok and get_default_mask_type("unknown_field") == MaskType.CUSTOM.value
    record("脱敏-默认类型推断", ok)


# ============================================================
# 脱敏服务测试
# ============================================================

def test_masking_service_dict():
    """测试 13: 字典级脱敏"""
    from app.services.masking_service import get_masking_service, reset_masking_service
    reset_masking_service()
    svc = get_masking_service()

    data = {
        "username": "admin",
        "password": "mysecret",
        "api_key": "sk-abc123def456",
        "token": "eyJhbGciOiJIUzI1NiJ9.abc123",
        "email": "admin@test.com",
        "phone": "13812345678",
        "description": "正常字段",
    }
    masked = svc.mask_dict(data, rules=[])

    ok = masked["username"] == "admin"
    ok = ok and masked["password"] == "********"
    ok = ok and "***" in masked["api_key"]
    ok = ok and "***" in masked["token"]
    ok = ok and masked["email"] == "a***@test.com"
    ok = ok and masked["phone"] == "138****5678"
    ok = ok and masked["description"] == "正常字段"

    record("脱敏服务-字典级脱敏", ok)


def test_masking_service_json_string():
    """测试 14: JSON字符串脱敏"""
    from app.services.masking_service import get_masking_service, reset_masking_service
    reset_masking_service()
    svc = get_masking_service()

    json_str = json.dumps({
        "password": "secret123",
        "username": "admin",
    })
    masked_str = svc.mask_json_string(json_str, rules=[])
    masked = json.loads(masked_str)

    ok = masked["password"] == "********"
    ok = ok and masked["username"] == "admin"

    # 无效JSON
    ok = ok and svc.mask_json_string("not json") == "not json"

    record("脱敏服务-JSON字符串脱敏", ok)


def test_masking_service_rules_crud():
    """测试 15: 脱敏规则 CRUD"""
    from app.services.masking_service import get_masking_service, reset_masking_service
    reset_masking_service()
    svc = get_masking_service()

    # 创建规则
    rule = svc.create_rule({
        "name": "测试密码规则",
        "field_name": "test_password",
        "mask_type": "password",
    })
    ok = rule.get("id") is not None
    ok = ok and rule["field_name"] == "test_password"

    # 查询
    rules = svc.list_rules()
    ok = ok and rules["total"] >= 1

    # 更新
    updated = svc.update_rule(rule["id"], {"description": "更新描述"})
    ok = ok and updated["description"] == "更新描述"

    # 验证规则生效(使用8+字符的密码,mask_password返回min(len,8)个星号)
    masked = svc.mask_dict({"test_password": "secret123"}, rules=[updated])
    ok = ok and masked["test_password"] == "********"

    # 删除(无论前面断言结果如何,都执行删除以保持测试隔离)
    svc.delete_rule(rule["id"])
    record("脱敏服务-规则CRUD", ok)


def test_masking_service_init_defaults():
    """测试 16: 初始化默认规则"""
    from app.services.masking_service import get_masking_service, reset_masking_service
    reset_masking_service()
    svc = get_masking_service()

    # 清理已有规则(防止前序测试残留导致init返回0)
    from app.db.database import SessionLocal
    from app.models.security import MaskingRule
    db = SessionLocal()
    try:
        db.query(MaskingRule).delete()
        db.commit()
    finally:
        db.close()
    svc.reload_rules()

    count = svc.init_default_rules()
    ok = count > 0

    # 再次调用应返回0(已存在)
    count2 = svc.init_default_rules()
    ok = ok and count2 == 0

    # 验证默认规则生效(使用8+字符密码,确保返回8个星号)
    masked = svc.mask_dict({"password": "secret123", "api_key": "sk-123"}, rules=None)
    ok = ok and masked["password"] == "********"
    ok = ok and "***" in masked["api_key"]

    # 清理
    rules = svc.list_rules()
    for r in rules["items"]:
        svc.delete_rule(r["id"], hard=True)

    record("脱敏服务-初始化默认规则", ok, f"创建{count}条")


# ============================================================
# API Key 服务测试
# ============================================================

def test_apikey_create():
    """测试 17: 创建API Key"""
    from app.services.api_key_service import get_api_key_service, reset_api_key_service
    reset_api_key_service()
    svc = get_api_key_service()

    result = svc.create_key(
        name="测试Key",
        description="用于测试",
        scopes=["read", "write"],
        user_id=1,
    )

    ok = result.get("id") is not None
    ok = ok and result.get("plaintext_key", "").startswith("sk_")
    ok = ok and result.get("key_prefix", "").startswith("sk_")
    ok = ok and result.get("key_hash") is None  # to_dict 默认不含 hash
    ok = ok and "warning" in result
    ok = ok and result["scopes"] == ["read", "write"]

    record("API Key-创建", ok, f"prefix={result.get('key_prefix')}")
    return result.get("plaintext_key"), result.get("id")


def test_apikey_validate():
    """测试 18: 验证API Key"""
    from app.services.api_key_service import get_api_key_service, reset_api_key_service
    reset_api_key_service()
    svc = get_api_key_service()

    # 先创建
    created = svc.create_key(name="验证测试", scopes=["read"], user_id=1)
    plaintext = created["plaintext_key"]

    # 验证有效Key
    validated = svc.validate_key(plaintext)
    ok = validated is not None
    ok = ok and validated["name"] == "验证测试"
    ok = ok and validated["scopes"] == ["read"]

    # 验证无效Key
    ok = ok and svc.validate_key("invalid_key") is None
    ok = ok and svc.validate_key("") is None
    ok = ok and svc.validate_key(None) is None

    record("API Key-验证", ok)


def test_apikey_hash():
    """测试 19: API Key 哈希"""
    from app.models.security import ApiKey

    plaintext, prefix, hash_val = ApiKey.generate_key()

    ok = plaintext.startswith("sk_")
    ok = ok and len(plaintext) > 30
    ok = ok and prefix == plaintext[:12]
    ok = ok and len(hash_val) == 64  # SHA-256 hex
    ok = ok and ApiKey.hash_key(plaintext) == hash_val
    ok = ok and ApiKey.hash_key("different") != hash_val

    record("API Key-哈希生成", ok)


def test_apikey_revoke():
    """测试 20: 撤销API Key"""
    from app.services.api_key_service import get_api_key_service, reset_api_key_service
    reset_api_key_service()
    svc = get_api_key_service()

    created = svc.create_key(name="撤销测试", user_id=1)
    plaintext = created["plaintext_key"]
    key_id = created["id"]

    # 撤销前可验证
    ok = svc.validate_key(plaintext) is not None

    # 撤销
    revoked = svc.revoke_key(key_id, user_id=1)
    ok = ok and revoked["is_active"] is False

    # 撤销后不可验证
    ok = ok and svc.validate_key(plaintext) is None

    record("API Key-撤销", ok)


def test_apikey_list_stats():
    """测试 21: API Key 列表和统计"""
    from app.services.api_key_service import get_api_key_service, reset_api_key_service
    reset_api_key_service()
    svc = get_api_key_service()

    # 创建多个Key
    svc.create_key(name="Key1", user_id=1)
    svc.create_key(name="Key2", user_id=1)
    svc.create_key(name="Key3", user_id=1, scopes=["read"])

    # 列表
    result = svc.list_keys(user_id=1)
    ok = result["total"] >= 3

    # 统计
    stats = svc.get_stats(user_id=1)
    ok = ok and stats["total"] >= 3
    ok = ok and stats["active"] >= 3

    record("API Key-列表和统计", ok, f"total={stats['total']}")


def test_apikey_expiry():
    """测试 22: API Key 过期"""
    from app.services.api_key_service import get_api_key_service, reset_api_key_service
    from datetime import datetime, timedelta
    reset_api_key_service()
    svc = get_api_key_service()

    # 创建已过期的Key
    created = svc.create_key(
        name="过期测试",
        expires_at=datetime.now() - timedelta(hours=1),
        user_id=1,
    )
    plaintext = created["plaintext_key"]

    # 验证过期Key无效
    validated = svc.validate_key(plaintext)
    ok = validated is None

    record("API Key-过期检查", ok)


def test_apikey_usage_tracking():
    """测试 23: API Key 使用统计"""
    from app.services.api_key_service import get_api_key_service, reset_api_key_service
    reset_api_key_service()
    svc = get_api_key_service()

    created = svc.create_key(name="使用统计", user_id=1)
    key_id = created["id"]

    # 记录使用
    svc.record_usage(key_id, ip_address="192.168.1.1")
    svc.record_usage(key_id, ip_address="192.168.1.2")

    # 查询
    key_info = svc.get_key(key_id, user_id=1)
    ok = key_info["usage_count"] >= 2
    ok = ok and key_info["last_used_ip"] == "192.168.1.2"

    record("API Key-使用统计", ok)


def test_apikey_delete():
    """测试 24: 删除API Key"""
    from app.services.api_key_service import get_api_key_service, reset_api_key_service
    reset_api_key_service()
    svc = get_api_key_service()

    created = svc.create_key(name="删除测试", user_id=1)
    key_id = created["id"]

    # 软删除
    ok = svc.delete_key(key_id, user_id=1)
    ok = ok and svc.get_key(key_id, user_id=1) is None

    record("API Key-删除", ok)


# ============================================================
# 审计服务测试
# ============================================================

def test_audit_log_operation():
    """测试 25: 记录操作日志"""
    from app.services.audit_service import get_audit_service, reset_audit_service
    reset_audit_service()
    svc = get_audit_service()

    svc.log_operation(
        user_id=1,
        username="admin",
        action="create",
        method="POST",
        path="/api/test",
        resource_type="test",
        resource_id=1,
        ip_address="192.168.1.1",
        request_body=json.dumps({"password": "secret123", "name": "test"}),
        response_status=200,
        duration=0.5,
    )

    logs = svc.list_operation_logs(username="admin")
    ok = logs["total"] >= 1
    ok = ok and logs["items"][0]["action"] == "create"
    ok = ok and logs["items"][0]["path"] == "/api/test"

    # 验证请求体已脱敏
    req_body = logs["items"][0].get("request_body")
    if isinstance(req_body, dict):
        ok = ok and req_body.get("password") == "********"
        ok = ok and req_body.get("name") == "test"

    record("审计-操作日志记录", ok)


def test_audit_log_event():
    """测试 26: 记录审计事件"""
    from app.services.audit_service import get_audit_service, reset_audit_service
    reset_audit_service()
    svc = get_audit_service()

    event = svc.log_event(
        event_type="permission_change",
        severity="warning",
        user_id=1,
        username="admin",
        action="用户角色变更",
        target_type="user",
        target_id="2",
        details={"old_role": "user", "new_role": "admin", "token": "secret_token"},
        ip_address="192.168.1.1",
    )

    ok = event.get("id") is not None
    ok = ok and event["event_type"] == "permission_change"
    ok = ok and event["severity"] == "warning"

    # 验证 details 已脱敏
    details = event.get("details")
    if isinstance(details, dict):
        ok = ok and details.get("old_role") == "user"
        ok = ok and details.get("new_role") == "admin"
        ok = ok and "token" in details
        ok = ok and details["token"] != "secret_token"  # 已脱敏

    record("审计-事件记录+脱敏", ok)


def test_audit_list_events():
    """测试 27: 审计事件列表"""
    from app.services.audit_service import get_audit_service, reset_audit_service
    reset_audit_service()
    svc = get_audit_service()

    # 创建多个事件
    svc.log_event(event_type="login_event", severity="info", action="用户登录",
                  username="admin", user_id=1)
    svc.log_event(event_type="security_alert", severity="critical", action="异常登录",
                  username="hacker", user_id=2)
    svc.log_event(event_type="api_key_operation", severity="warning", action="Key撤销",
                  username="admin", user_id=1)

    # 按类型筛选
    login_events = svc.list_audit_events(event_type="login_event")
    ok = login_events["total"] >= 1

    # 按严重级别筛选
    critical_events = svc.list_audit_events(severity="critical")
    ok = ok and critical_events["total"] >= 1
    ok = ok and critical_events["items"][0]["action"] == "异常登录"

    # 全部
    all_events = svc.list_audit_events()
    ok = ok and all_events["total"] >= 3

    record("审计-事件列表筛选", ok, f"total={all_events['total']}")


def test_audit_dashboard():
    """测试 28: 安全仪表盘"""
    from app.services.audit_service import get_audit_service, reset_audit_service
    reset_audit_service()
    svc = get_audit_service()

    # 创建测试数据
    for i in range(5):
        svc.log_operation(
            user_id=1, username="admin",
            action="create", method="POST", path=f"/api/test/{i}",
            ip_address="192.168.1.1",
            response_status=200, duration=0.1,
        )
    for i in range(3):
        svc.log_operation(
            user_id=1, username="admin",
            action="delete", method="DELETE", path=f"/api/test/{i}",
            ip_address="192.168.1.1",
            response_status=500, duration=0.2,
            error_message="Internal error",
        )
    svc.log_event(event_type="security_alert", severity="critical",
                  action="异常", username="admin", user_id=1)

    dashboard = svc.get_dashboard(hours=24)

    ok = "operation_logs" in dashboard
    ok = ok and dashboard["operation_logs"]["total"] >= 8
    ok = ok and "by_action" in dashboard["operation_logs"]
    ok = ok and "by_status" in dashboard["operation_logs"]
    ok = ok and dashboard["operation_logs"]["error_rate"] > 0
    ok = ok and "audit_events" in dashboard
    ok = ok and dashboard["audit_events"]["total"] >= 1
    ok = ok and dashboard["audit_events"]["by_severity"]["critical"] >= 1
    ok = ok and "alerts" in dashboard

    record("审计-安全仪表盘", ok, f"logs={dashboard['operation_logs']['total']}")


def test_audit_stats():
    """测试 29: 安全统计"""
    from app.services.audit_service import get_audit_service, reset_audit_service
    reset_audit_service()
    svc = get_audit_service()

    svc.log_operation(
        user_id=1, username="admin",
        action="create", method="POST", path="/api/test",
        ip_address="192.168.1.1",
    )
    svc.log_event(event_type="security_alert", severity="critical",
                  action="测试告警", user_id=1)

    stats = svc.get_stats(hours=24)

    ok = stats["operation_logs_total"] >= 1
    ok = ok and stats["audit_events_total"] >= 1
    ok = ok and stats["critical_events"] >= 1
    ok = ok and stats["unique_users"] >= 1
    ok = ok and stats["unique_ips"] >= 1

    record("审计-安全统计", ok)


def test_audit_anomaly_detection():
    """测试 30: 安全异常检测"""
    from app.services.audit_service import get_audit_service, reset_audit_service
    reset_audit_service()
    svc = get_audit_service()

    # 模拟高频访问
    for i in range(55):
        svc.log_operation(
            user_id=1, username="admin",
            action="read", method="GET", path=f"/api/data/{i}",
            ip_address="10.0.0.1",
            response_status=200,
        )

    # 模拟大量失败
    for i in range(15):
        svc.log_operation(
            user_id=1, username="admin",
            action="read", method="GET", path=f"/api/fail/{i}",
            ip_address="10.0.0.2",
            response_status=500,
            error_message="Error",
        )

    # 模拟敏感操作
    svc.log_operation(
        user_id=1, username="admin",
        action="delete", method="DELETE", path="/api/critical/1",
        ip_address="10.0.0.3",
        response_status=200,
    )

    anomalies = svc.detect_security_anomalies(hours=1)

    ok = len(anomalies) >= 1
    # 应检测到高频IP
    has_high_freq = any(a["type"] == "high_frequency_ip" for a in anomalies)
    ok = ok and has_high_freq
    # 应检测到高失败率
    has_failures = any(a["type"] == "high_failure_rate" for a in anomalies)
    ok = ok and has_failures
    # 应检测到敏感操作
    has_sensitive = any(a["type"] == "sensitive_operation" for a in anomalies)
    ok = ok and has_sensitive

    record("审计-异常检测", ok, f"发现{len(anomalies)}个异常")


# ============================================================
# 模型测试
# ============================================================

def test_model_apikey():
    """测试 31: ApiKey 模型"""
    from app.db.database import SessionLocal
    from app.models.security import ApiKey

    db = SessionLocal()
    try:
        plaintext, prefix, hash_val = ApiKey.generate_key()
        key = ApiKey(
            name="模型测试",
            key_prefix=prefix,
            key_hash=hash_val,
            scopes=json.dumps(["read"]),
            is_active=True,
            is_deleted=False,
            usage_count=0,
            user_id=1, created_by=1,
        )
        db.add(key)
        db.commit()
        db.refresh(key)

        ok = key.id is not None
        ok = ok and key.key_hash == hash_val
        ok = ok and key.is_active is True

        d = key.to_dict()
        ok = ok and d["key_prefix"] == prefix
        ok = ok and d["scopes"] == ["read"]
        ok = ok and "key_hash" not in d  # 默认不含hash
        ok = ok and d["is_expired"] is False

        # include_hash=True
        d2 = key.to_dict(include_hash=True)
        ok = ok and "key_hash" in d2

        record("模型-ApiKey", ok)
    finally:
        db.close()


def test_model_operation_log():
    """测试 32: OperationLog 模型"""
    from app.db.database import SessionLocal
    from app.models.security import OperationLog

    db = SessionLocal()
    try:
        log = OperationLog(
            user_id=1, created_by=1, username="admin",
            action="create", method="POST", path="/api/test",
            resource_type="test", resource_id=1,
            ip_address="192.168.1.1",
            request_body='{"password": "******"}',
            response_status=200, duration=0.5,
        )
        db.add(log)
        db.commit()
        db.refresh(log)

        ok = log.id is not None
        ok = ok and log.action == "create"
        ok = ok and log.method == "POST"

        d = log.to_dict()
        ok = ok and d["action"] == "create"
        ok = ok and d["response_status"] == 200

        record("模型-OperationLog", ok)
    finally:
        db.close()


def test_model_audit_event():
    """测试 33: AuditEvent 模型"""
    from app.db.database import SessionLocal
    from app.models.security import AuditEvent

    db = SessionLocal()
    try:
        event = AuditEvent(
            event_type="permission_change",
            severity="warning",
            user_id=1, created_by=1, username="admin",
            action="角色变更",
            target_type="user", target_id="2",
            details=json.dumps({"old": "user", "new": "admin"}),
            ip_address="192.168.1.1",
        )
        db.add(event)
        db.commit()
        db.refresh(event)

        ok = event.id is not None
        ok = ok and event.event_type == "permission_change"
        ok = ok and event.severity == "warning"

        d = event.to_dict()
        ok = ok and d["details"]["old"] == "user"
        ok = ok and d["details"]["new"] == "admin"

        record("模型-AuditEvent", ok)
    finally:
        db.close()


def test_model_masking_rule():
    """测试 34: MaskingRule 模型"""
    from app.db.database import SessionLocal
    from app.models.security import MaskingRule

    db = SessionLocal()
    try:
        rule = MaskingRule(
            name="测试规则",
            field_name="password",
            mask_type="password",
            visible_chars=4,
            is_active=True,
            is_deleted=False,
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)

        ok = rule.id is not None
        ok = ok and rule.mask_type == "password"

        d = rule.to_dict()
        ok = ok and d["field_name"] == "password"
        ok = ok and d["visible_chars"] == 4

        record("模型-MaskingRule", ok)
    finally:
        db.close()


# ============================================================
# API 路由测试
# ============================================================

def test_api_routes():
    """测试 35: API路由完整性"""
    from app.api.security import router

    route_set = set()
    for r in router.routes:
        for method in r.methods:
            route_set.add((r.path, method))

    expected = [
        ("/api-keys", "POST"),
        ("/api-keys/list", "GET"),
        ("/api-keys/stats", "GET"),
        ("/api-keys/{key_id}", "GET"),
        ("/api-keys/{key_id}", "PUT"),
        ("/api-keys/{key_id}", "DELETE"),
        ("/api-keys/{key_id}/revoke", "POST"),
        ("/api-keys/cleanup-expired", "POST"),
        ("/masking/rules", "POST"),
        ("/masking/rules/list", "GET"),
        ("/masking/rules/{rule_id}", "GET"),
        ("/masking/rules/{rule_id}", "PUT"),
        ("/masking/rules/{rule_id}", "DELETE"),
        ("/masking/init-defaults", "POST"),
        ("/masking/test", "POST"),
        ("/audit/logs/list", "GET"),
        ("/audit/logs/{log_id}", "GET"),
        ("/audit/events/list", "GET"),
        ("/audit/events/{event_id}", "GET"),
        ("/dashboard", "GET"),
        ("/stats", "GET"),
        ("/anomalies", "GET"),
    ]

    ok = True
    for path, method in expected:
        if (path, method) not in route_set:
            ok = False
            break

    record("API-路由完整性", ok, f"found={len(route_set)} combos")


def test_api_registration():
    """测试 36: API路由注册验证"""
    from app.api.security import router as security_router

    ok = security_router is not None
    ok = ok and len(security_router.routes) >= 20

    record("API-路由注册验证", ok, f"routes={len(security_router.routes)}")


def test_middleware_import():
    """测试 37: 中间件可导入"""
    from app.core.operation_log_middleware import OperationLogMiddleware

    ok = OperationLogMiddleware is not None
    ok = ok and hasattr(OperationLogMiddleware, "dispatch")

    record("中间件-可导入", ok)


def test_middleware_infer_action():
    """测试 38: 中间件动作推断"""
    from app.core.operation_log_middleware import OperationLogMiddleware

    infer = OperationLogMiddleware._infer_action

    ok = infer("GET", "/api/test") == "read"
    ok = ok and infer("POST", "/api/auth/login") == "login"
    ok = ok and infer("POST", "/api/auth/logout") == "logout"
    ok = ok and infer("POST", "/api/tasks") == "create"
    ok = ok and infer("PUT", "/api/tasks/1") == "update"
    ok = ok and infer("DELETE", "/api/tasks/1") == "delete"
    ok = ok and infer("POST", "/api/execution/run") == "execute"

    record("中间件-动作推断", ok)


def test_middleware_infer_resource():
    """测试 39: 中间件资源推断"""
    from app.core.operation_log_middleware import OperationLogMiddleware

    infer = OperationLogMiddleware._infer_resource

    rtype, rid = infer("/api/tasks/123")
    ok = rtype == "tasks" and rid == 123

    rtype, rid = infer("/api/security/api-keys/456")
    ok = ok and rtype == "security" and rid is None  # /security/api-keys 不是数字

    rtype, rid = infer("/docs")
    ok = ok and rtype is None

    record("中间件-资源推断", ok)


def test_model_registration():
    """测试 40: 模型注册验证"""
    from app.models import (
        ApiKey, OperationLog, AuditEvent, MaskingRule,
        AuditEventType, AuditSeverity, MaskType,
    )

    ok = ApiKey is not None
    ok = ok and OperationLog is not None
    ok = ok and AuditEvent is not None
    ok = ok and MaskingRule is not None
    ok = ok and AuditEventType.PERMISSION_CHANGE.value == "permission_change"
    ok = ok and AuditSeverity.CRITICAL.value == "critical"
    ok = ok and MaskType.PHONE.value == "phone"

    record("模型-注册验证", ok)


# ============================================================
# 主函数
# ============================================================

def main():
    logger.info("=" * 60)
    logger.info("企业级安全模块全链路测试")
    logger.info("=" * 60)

    setup_database()
    cleanup_database()
    seed_user()

    tests = [
        # 脱敏函数
        test_mask_phone,
        test_mask_email,
        test_mask_id_card,
        test_mask_bank_card,
        test_mask_api_key,
        test_mask_password,
        test_mask_token,
        test_mask_custom,
        test_mask_value_dispatch,
        test_auto_detect,
        test_is_sensitive_field,
        test_get_default_mask_type,
        # 脱敏服务
        test_masking_service_dict,
        test_masking_service_json_string,
        test_masking_service_rules_crud,
        test_masking_service_init_defaults,
        # API Key
        test_apikey_create,
        test_apikey_validate,
        test_apikey_hash,
        test_apikey_revoke,
        test_apikey_list_stats,
        test_apikey_expiry,
        test_apikey_usage_tracking,
        test_apikey_delete,
        # 审计
        test_audit_log_operation,
        test_audit_log_event,
        test_audit_list_events,
        test_audit_dashboard,
        test_audit_stats,
        test_audit_anomaly_detection,
        # 模型
        test_model_apikey,
        test_model_operation_log,
        test_model_audit_event,
        test_model_masking_rule,
        # API
        test_api_routes,
        test_api_registration,
        # 中间件
        test_middleware_import,
        test_middleware_infer_action,
        test_middleware_infer_resource,
        # 注册
        test_model_registration,
    ]

    for test_func in tests:
        try:
            test_func()
        except Exception as e:
            record(test_func.__name__, False, f"异常: {e}")
            logger.error(f"测试异常: {test_func.__name__}", exc_info=True)

    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    total = len(results)

    logger.info("=" * 60)
    logger.info(f"测试结果: {passed}/{total} 通过, {failed} 失败")
    logger.info("=" * 60)

    if failed > 0:
        logger.info("失败测试:")
        for r in results:
            if r["status"] == "FAIL":
                logger.info(f"  - {r['name']}: {r['detail']}")

    cleanup_database()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
