"""
ApiDataGeneratorAgent - 接口测试数据智能生成 Agent

职责:
  根据接口信息 + 参数 Schema + 依赖关系, 智能生成 4 类测试数据:
    1. normal    — 正常数据 (满足所有约束)
    2. abnormal  — 异常数据 (违反约束: 空/超长/类型错)
    3. boundary  — 边界数据 (min-1/min/max/max+1)
    4. dependent — 关联数据 (依赖其他接口返回值, 用 $REF 占位符)

生成策略 (四源融合):
  - Rule Engine:  基于 Schema 约束直接生成 (string/int/email/pattern/enum)
  - Faker:       语义化随机 (username/email/phone/uuid)
  - LLM:         复杂语义推理 (跨字段关联、业务约束)
  - Template:    模板复用 (查 api_test_data_template 表)
  - Runtime:     关联数据用 $REF.xxx 占位符, 运行时由脚本注入

决策树:
  Schema 完整? → 走规则
  字段名匹配语义? → 走 Faker
  跨字段关联? → 走 LLM
  有 active 模板? → 直接复用

通信方式:
  # 其他 Agent 调用
  response = await self.send_request(
      "api_data_generator_agent", "generate",
      {"endpoint_id": 1, "data_types": ["normal","abnormal","boundary"], "count": 3}
  )
  # response.data = {
  #   "normal":    [{"username":"test001",...}, ...],
  #   "abnormal":  [{"username":"",...}, ...],
  #   "boundary": [{"username":"a"*100,...}, ...],
  #   "dependent":[{"user_id":"$REF.get_user.response.id",...}]
  # }
"""
import json
import logging
import random
import re
import string
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from autogen_core import message_handler, MessageContext, default_subscription

from app.runtime.base_agent import BaseRoutedAgent, action_handler
from app.runtime.messages import AgentRequest, AgentResponse

logger = logging.getLogger(__name__)


# ============================================================
# Faker 可选依赖 (缺失时降级到规则引擎)
# ============================================================
try:
    from faker import Faker
    _FAKER = Faker(['zh_CN', 'en_US'])
    _FAKER_AVAILABLE = True
except ImportError:
    _FAKER = None
    _FAKER_AVAILABLE = False
    logger.warning("[ApiDataGeneratorAgent] faker 未安装, 降级到规则引擎")


# ============================================================
# 语义模式匹配表 (字段名 → Faker 方法)
# ============================================================
_SEMANTIC_PATTERNS = [
    # (正则模式, Faker 方法名, 说明)
    (r'^username$',         'user_name',         '用户名'),
    (r'^user_name$',        'user_name',         '用户名'),
    (r'^email$',             'email',             '邮箱'),
    (r'^mail$',               'email',             '邮箱'),
    (r'^phone$',              'phone_number',     '手机号'),
    (r'^mobile$',             'phone_number',     '手机号'),
    (r'^tel$',                'phone_number',     '电话'),
    (r'^password$',           'password',         '密码'),
    (r'^passwd$',             'password',         '密码'),
    (r'^pwd$',                'password',         '密码'),
    (r'^name$',               'name',              '姓名'),
    (r'^full_name$',          'name',              '全名'),
    (r'^first_name$',         'first_name',        '名'),
    (r'^last_name$',          'last_name',         '姓'),
    (r'^nickname$',           'user_name',         '昵称'),
    (r'^address$',            'address',           '地址'),
    (r'^city$',               'city',              '城市'),
    (r'^country$',            'country',          '国家'),
    (r'^company$',            'company',           '公司'),
    (r'^url$',                'uri',               'URL'),
    (r'^website$',            'uri',               '网站'),
    (r'^ip$',                 'ipv4',              'IP'),
    (r'^ipv4$',               'ipv4',              'IPv4'),
    (r'^ipv6$',               'ipv6',              'IPv6'),
    (r'^uuid$',               'uuid4',             'UUID'),
    (r'^guid$',               'uuid4',             'GUID'),
    (r'^token$',              'hexify',            'Token'),
    (r'^session_id$',         'uuid4',             '会话ID'),
    (r'^date$',               'date',              '日期'),
    (r'^time$',               'time',              '时间'),
    (r'^datetime$',          'date_time',         '日期时间'),
    (r'^timestamp$',          'unix_time',        '时间戳'),
    (r'^id_card$',            'ssn',               '身份证'),
    (r'^ssn$',                'ssn',               '社保号'),
    (r'^credit_card$',       'credit_card_number','信用卡'),
    (r'^card_number$',        'credit_card_number','卡号'),
    (r'^amount$',             'pydecimal',         '金额'),
    (r'^price$',              'pydecimal',         '价格'),
    (r'^title$',              'sentence',          '标题'),
    (r'^description$',        'paragraph',        '描述'),
    (r'^content$',           'paragraph',         '内容'),
    (r'^remark$',            'paragraph',         '备注'),
    (r'^comment$',           'paragraph',         '评论'),
    (r'^code$',              'bothify',           '编码'),
    (r'^captcha$',           'bothify',            '验证码'),
    (r'(?i).*id.*',          'uuid4',             'ID类字段'),
    (r'(?i).*time.*',        'date_time',         '时间类字段'),
    (r'(?i).*date.*',        'date',              '日期类字段'),
]

# 异常数据规则库 (按字段类型)
_ABNORMAL_RULES = {
    'string': [
        ('empty',     ''),                              # 空字符串
        ('too_long',  'a' * 256),                       # 超长
        ('too_short', 'a'),                             # 过短
        ('null',      None),                             # null
        ('special',   '<script>alert(1)</script>'),      # 特殊字符 (XSS)
        ('sql',       "'; DROP TABLE users; --"),        # SQL 注入
        ('number',    12345),                            # 类型错误
    ],
    'integer': [
        ('empty',     None),
        ('zero',      0),
        ('negative',  -1),
        ('too_big',   99999999999),
        ('string',    'abc'),
    ],
    'number': [
        ('empty',     None),
        ('zero',      0),
        ('negative',  -1.5),
        ('too_big',   999999999.99),
        ('string',    'abc'),
    ],
    'boolean': [
        ('null',      None),
        ('string',    'true'),
        ('number',    1),
        ('empty',     ''),
    ],
    'email': [
        ('empty',     ''),
        ('no_at',     'testtest.com'),
        ('no_domain', 'test@'),
        ('no_user',   '@test.com'),
        ('null',      None),
    ],
    'phone': [
        ('empty',     ''),
        ('too_short', '123'),
        ('too_long',  '12345678901234567890'),
        ('letters',   'abcdefgh'),
        ('null',      None),
    ],
}

# 类型映射 (OpenAPI 类型 → Python 类型 + Faker 生成器)
_TYPE_MAP = {
    'string':  str,
    'integer': int,
    'number':  float,
    'boolean': bool,
    'array':   list,
    'object':  dict,
}


@default_subscription
class ApiDataGeneratorAgent(BaseRoutedAgent):
    """接口测试数据智能生成 Agent

    继承 BaseRoutedAgent (继承 autogen_core.RoutedAgent)
    通过 AgentFactory 注册 (见 definitions.py)

    支持的 action:
      - generate:     批量生成数据 (4 类 × N 条)
      - generate_one: 生成单条数据
      - list:         查询已生成的数据
      - health:       健康检查
    """

    def __init__(self) -> None:
        super().__init__(
            description="接口测试数据智能生成 Agent — 支持 normal/abnormal/boundary/dependent 四类数据,融合 LLM+Faker+规则+模板",
            display_name="ApiDataGeneratorAgent",
            capabilities=["data_generation", "schema_analysis", "faker", "llm_reasoning"],
        )

    # ============================================================
    # 主入口 — generate action
    # ============================================================

    async def execute(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """GraphFlow 入口 — 默认走 generate"""
        action = payload.get("action", "generate")
        if action == "generate":
            return await self._do_generate(payload)
        elif action == "generate_one":
            return await self._do_generate_one(payload)
        elif action == "list":
            return await self._do_list(payload)
        elif action == "health":
            return await self._do_health()
        else:
            return {"status": "error", "message": f"Unknown action: {action}"}

    @action_handler("generate")
    async def handle_generate(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """批量生成测试数据"""
        return await self._do_generate(payload)

    @action_handler("generate_one")
    async def handle_generate_one(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """生成单条测试数据"""
        return await self._do_generate_one(payload)

    @action_handler("list")
    async def handle_list(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """查询已生成数据"""
        return await self._do_list(payload)

    @action_handler("health")
    async def handle_health(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """健康检查"""
        return await self._do_health()

    # ============================================================
    # 核心: _do_generate
    # ============================================================

    async def _do_generate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """批量生成测试数据

        参数:
          endpoint_id:    接口 ID (必填)
          data_types:     要生成的类型列表 ["normal","abnormal","boundary","dependent"]
          count:          每类生成条数 (默认 3)
          fields_schema:  字段定义 (可选, 缺失则从 DB 查)
          dependencies:    依赖关系 (可选, dependent 类型用)
          use_template:   是否优先使用模板 (默认 True)
          use_llm:        是否允许 LLM (默认 True, 失败降级到规则)
          user_id:        用户 ID (用于数据归属)

        返回:
          {
            "normal":    [ {...}, {...}, {...} ],
            "abnormal":  [ {...}, {...}, {...} ],
            "boundary":  [ {...}, {...}, {...} ],
            "dependent": [ {...} ],
            "metadata": { "elapsed_ms": ..., "sources": {...} }
          }
        """
        start = time.time()
        endpoint_id = payload.get("endpoint_id")
        if not endpoint_id:
            return {"status": "error", "message": "endpoint_id 必填"}

        data_types = payload.get("data_types", ["normal", "abnormal", "boundary"])
        count = int(payload.get("count", 3))
        user_id = payload.get("user_id")
        use_template = payload.get("use_template", True)
        use_llm = payload.get("use_llm", True)

        # 1. 获取字段 Schema (优先用传入的, 否则查 DB)
        fields_schema = payload.get("fields_schema")
        if not fields_schema:
            fields_schema = await self._load_schema_from_db(endpoint_id)
            if not fields_schema:
                return {
                    "status": "error",
                    "message": f"无法获取 endpoint_id={endpoint_id} 的字段 Schema"
                }

        # 2. 获取依赖关系 (用于 dependent 类型)
        dependencies = payload.get("dependencies", [])

        # 3. 生成每类数据
        result: Dict[str, List] = {}
        sources_used: Dict[str, int] = {}

        for dt in data_types:
            dt_key = dt if isinstance(dt, str) else dt.value
            dt_list = []
            n = 1 if dt_key == "dependent" else count  # dependent 生成 1 条占位符模板

            # 优先尝试模板复用
            if use_template:
                template_data = await self._try_template(endpoint_id, dt_key, n, user_id)
                if template_data:
                    dt_list.extend(template_data)
                    sources_used["template"] = sources_used.get("template", 0) + len(template_data)
                    # 模板已有, 不够的再用规则补
                    n = n - len(template_data)

            # 不足部分用策略生成
            for _ in range(max(0, n)):
                data, source = await self._generate_one_record(
                    dt_key, fields_schema, dependencies, use_llm
                )
                dt_list.append(data)
                sources_used[source] = sources_used.get(source, 0) + 1

            result[dt_key] = dt_list

        # 4. 持久化到 generated_api_data 表 (异步, 不阻塞返回)
        try:
            await self._persist_generated(
                endpoint_id=endpoint_id,
                result=result,
                sources_used=sources_used,
                user_id=user_id,
                elapsed_ms=int((time.time() - start) * 1000),
            )
        except Exception as e:
            logger.warning(f"[ApiDataGeneratorAgent] 持久化失败 (不阻塞): {e}")

        elapsed_ms = int((time.time() - start) * 1000)
        return {
            "status": "success",
            "endpoint_id": endpoint_id,
            "data": result,
            "metadata": {
                "elapsed_ms": elapsed_ms,
                "sources_used": sources_used,
                "fields_count": len(fields_schema) if isinstance(fields_schema, list) else 0,
                "faker_available": _FAKER_AVAILABLE,
            }
        }

    # ============================================================
    # 单条生成
    # ============================================================

    async def _do_generate_one(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """生成单条数据"""
        data_type = payload.get("data_type", "normal")
        fields_schema = payload.get("fields_schema", [])
        dependencies = payload.get("dependencies", [])
        use_llm = payload.get("use_llm", True)

        data, source = await self._generate_one_record(
            data_type, fields_schema, dependencies, use_llm
        )
        return {
            "status": "success",
            "data": data,
            "source": source,
        }

    # ============================================================
    # 核心生成逻辑 — 单条记录
    # ============================================================

    async def _generate_one_record(
        self,
        data_type: str,
        fields_schema: List[Dict],
        dependencies: List[Dict],
        use_llm: bool,
    ) -> tuple:
        """生成一条记录, 返回 (data_dict, source)

        策略决策树:
          dependent → 用 $REF 占位符
          normal    → 规则 → Faker → LLM
          abnormal  → 异常规则库
          boundary  → 边界值规则
        """
        if data_type == "dependent":
            return self._gen_dependent(fields_schema, dependencies), "rule"
        elif data_type == "abnormal":
            return self._gen_abnormal(fields_schema), "rule"
        elif data_type == "boundary":
            return self._gen_boundary(fields_schema), "rule"
        else:  # normal
            # 先尝试规则 + Faker
            data, source = self._gen_normal(fields_schema)
            # 若字段较多或 Faker 不可用且字段语义复杂, 可选 LLM 增强
            if use_llm and len(fields_schema) > 5 and source == "rule":
                # 5+ 字段且全走规则, 可用 LLM 增强 (此处简化: 仅当 Faker 不可用时调 LLM)
                if not _FAKER_AVAILABLE:
                    data, source = await self._gen_normal_llm(fields_schema), "llm"
            return data, source

    # ============================================================
    # 正常数据生成 — 规则 + Faker
    # ============================================================

    def _gen_normal(self, fields_schema: List[Dict]) -> tuple:
        """生成正常数据

        决策:
          1. 字段名匹配语义模式 → Faker
          2. 有 format/pattern 约束 → 规则
          3. 有 enum → 随机选一个
          4. 默认按 type 生成
        """
        data = {}
        used_faker = False

        for field in fields_schema:
            name = field.get('name', '')
            ftype = field.get('type', 'string')
            required = field.get('required', True)

            # 非必填, 30% 概率不生成
            if not required and random.random() < 0.3:
                data[name] = None
                continue

            # 1. enum 优先
            if field.get('enum'):
                data[name] = random.choice(field['enum'])
                continue

            # 2. 尝试 Faker (字段名语义匹配)
            if _FAKER_AVAILABLE:
                faker_value = self._try_faker(name, field)
                if faker_value is not None:
                    data[name] = faker_value
                    used_faker = True
                    continue

            # 3. 规则引擎 (基于 type + 约束)
            data[name] = self._gen_by_rule(field)

        return data, "faker" if used_faker else "rule"

    def _try_faker(self, field_name: str, field: Dict) -> Optional[Any]:
        """尝试用 Faker 生成值, 不匹配返回 None"""
        if not _FAKER_AVAILABLE:
            return None

        name_lower = field_name.lower()
        for pattern, method, _ in _SEMANTIC_PATTERNS:
            if re.match(pattern, name_lower):
                try:
                    method_fn = getattr(_FAKER, method, None)
                    if method_fn is None:
                        continue
                    value = method_fn()
                    # 长度约束
                    max_len = field.get('max_length') or field.get('maxLength')
                    if max_len and isinstance(value, str) and len(value) > max_len:
                        value = value[:max_len]
                    return value
                except Exception as e:
                    logger.debug(f"Faker {method} 失败: {e}")
                    return None
        return None

    def _gen_by_rule(self, field: Dict) -> Any:
        """规则引擎: 基于字段类型和约束生成"""
        ftype = field.get('type', 'string')
        min_val = field.get('minimum') or field.get('min')
        max_val = field.get('maximum') or field.get('max')
        min_len = field.get('min_length') or field.get('minLength', 1)
        max_len = field.get('max_length') or field.get('maxLength', 20)
        pattern = field.get('pattern')
        format_ = field.get('format')

        if ftype == 'string':
            # format 优先
            if format_ == 'email':
                return f"test_{random.randint(1000, 9999)}@test.com"
            if format_ == 'date':
                return datetime.now(timezone.utc).strftime('%Y-%m-%d')
            if format_ == 'date-time':
                return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            if format_ == 'uuid':
                return str(uuid.uuid4())
            if format_ == 'uri':
                return f"https://example.com/path/{random.randint(1, 1000)}"
            # pattern 简单处理: 生成匹配的字符串
            if pattern:
                return self._gen_by_pattern(pattern, min_len, max_len)
            # 默认随机字符串
            length = random.randint(max(min_len, 3), min(max_len, 20))
            return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

        elif ftype == 'integer':
            lo = int(min_val) if min_val is not None else 1
            hi = int(max_val) if max_val is not None else 1000
            return random.randint(lo, hi)

        elif ftype == 'number':
            lo = float(min_val) if min_val is not None else 0.1
            hi = float(max_val) if max_val is not None else 9999.99
            return round(random.uniform(lo, hi), 2)

        elif ftype == 'boolean':
            return random.choice([True, False])

        elif ftype == 'array':
            return []

        elif ftype == 'object':
            return {}

        return None

    def _gen_by_pattern(self, pattern: str, min_len: int, max_len: int) -> str:
        """简单 pattern 处理 (只处理常见 pattern)"""
        # ^[a-zA-Z0-9_]+$
        if re.match(r'\^\[a-zA-Z0-9', pattern):
            length = random.randint(max(min_len, 3), min(max_len, 12))
            return ''.join(random.choices(string.ascii_letters + string.digits, k=length))
        # ^[a-z]+$
        if re.match(r'\^\[a-z\]', pattern):
            length = random.randint(max(min_len, 3), min(max_len, 12))
            return ''.join(random.choices(string.ascii_lowercase, k=length))
        # 数字
        if re.match(r'\^\[0-9\]', pattern):
            length = random.randint(max(min_len, 4), min(max_len, 11))
            return ''.join(random.choices(string.digits, k=length))
        # 兜底
        return f"test_{random.randint(100, 999)}"

    # ============================================================
    # 异常数据生成
    # ============================================================

    def _gen_abnormal(self, fields_schema: List[Dict]) -> Dict:
        """生成异常数据: 对每个字段选一种异常规则"""
        data = {}
        for field in fields_schema:
            name = field.get('name', '')
            ftype = field.get('type', 'string')
            required = field.get('required', True)

            # 非必填字段跳过 (没有意义做异常)
            if not required:
                data[name] = None
                continue

            # 按字段类型选异常规则
            # email/phone 走特殊规则
            if name.lower() in ('email', 'mail'):
                rules = _ABNORMAL_RULES['email']
            elif name.lower() in ('phone', 'mobile', 'tel'):
                rules = _ABNORMAL_RULES['phone']
            else:
                rules = _ABNORMAL_RULES.get(ftype, _ABNORMAL_RULES['string'])

            # 随机选一条
            _, value = random.choice(rules)
            data[name] = value

        return data

    # ============================================================
    # 边界数据生成
    # ============================================================

    def _gen_boundary(self, fields_schema: List[Dict]) -> Dict:
        """生成边界数据: min-1, min, max, max+1"""
        data = {}
        for field in fields_schema:
            name = field.get('name', '')
            ftype = field.get('type', 'string')
            min_len = field.get('min_length') or field.get('minLength', 1)
            max_len = field.get('max_length') or field.get('maxLength', 100)
            min_val = field.get('minimum') or field.get('min')
            max_val = field.get('maximum') or field.get('max')

            if ftype == 'string':
                # 选 max+1 (超长) 或 min-1 (过短)
                choice = random.choice(['min', 'max', 'max_plus_1', 'min_minus_1'])
                if choice == 'min':
                    data[name] = 'a' * max(min_len, 1)
                elif choice == 'max':
                    data[name] = 'a' * min(max_len, 200)
                elif choice == 'max_plus_1':
                    data[name] = 'a' * min(max_len + 1, 300)
                else:  # min_minus_1
                    data[name] = '' if min_len <= 1 else 'a' * (min_len - 1)
            elif ftype == 'integer':
                lo = int(min_val) if min_val is not None else 1
                hi = int(max_val) if max_val is not None else 1000
                choice = random.choice(['min', 'max', 'min_minus_1', 'max_plus_1'])
                if choice == 'min':
                    data[name] = lo
                elif choice == 'max':
                    data[name] = hi
                elif choice == 'min_minus_1':
                    data[name] = lo - 1
                else:
                    data[name] = hi + 1
            elif ftype == 'number':
                lo = float(min_val) if min_val is not None else 0.1
                hi = float(max_val) if max_val is not None else 9999.99
                choice = random.choice(['min', 'max', 'min_minus_1', 'max_plus_1'])
                if choice == 'min':
                    data[name] = lo
                elif choice == 'max':
                    data[name] = hi
                elif choice == 'min_minus_1':
                    data[name] = round(lo - 1.0, 2)
                else:
                    data[name] = round(hi + 1.0, 2)
            else:
                data[name] = None

        return data

    # ============================================================
    # 关联数据生成 ($REF 占位符)
    # ============================================================

    def _gen_dependent(self, fields_schema: List[Dict], dependencies: List[Dict]) -> Dict:
        """生成关联数据

        对依赖字段, 用 $REF.<endpoint_name>.<path> 占位符
        对非依赖字段, 用正常数据
        """
        data = {}
        # 构建字段→依赖映射
        dep_map = {}
        for dep in dependencies:
            field_name = dep.get('field')
            if field_name:
                dep_map[field_name] = dep

        for field in fields_schema:
            name = field.get('name', '')
            if name in dep_map:
                dep = dep_map[name]
                # $REF.<ref_endpoint_path>.response.<ref_path>
                ref_path = dep.get('ref_endpoint_path', 'unknown')
                ref_field = dep.get('ref_path', 'id')
                data[name] = f"$REF.{ref_path}.response.{ref_field}"
            else:
                # 非依赖字段用正常值
                data[name] = self._gen_by_rule(field)

        return data

    # ============================================================
    # LLM 辅助生成 (复杂语义场景, 当前为降级用)
    # ============================================================

    async def _gen_normal_llm(self, fields_schema: List[Dict]) -> Dict:
        """LLM 生成正常数据 (当 Faker 不可用且字段语义复杂时)"""
        try:
            system_prompt = (
                "你是测试数据生成专家。根据字段定义生成一条合法的测试数据。"
                "输出严格的 JSON, 不要解释。"
            )
            fields_desc = json.dumps(fields_schema, ensure_ascii=False, indent=2)
            user_prompt = f"字段定义:\n{fields_desc}\n\n生成一条满足所有约束的 JSON 数据。"

            result = await self.call_llm_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.3,
            )
            if isinstance(result, dict) and 'error' not in result:
                return result
            # LLM 失败, 降级到纯规则
            logger.warning("[ApiDataGeneratorAgent] LLM 生成失败, 降级到规则")
            data, _ = self._gen_normal(fields_schema)
            return data
        except Exception as e:
            logger.warning(f"[ApiDataGeneratorAgent] LLM 异常: {e}, 降级到规则")
            data, _ = self._gen_normal(fields_schema)
            return data

    # ============================================================
    # 数据库相关 — 加载 Schema / 模板复用 / 持久化
    # ============================================================

    async def _load_schema_from_db(self, endpoint_id: int) -> List[Dict]:
        """从 api_endpoint 表加载字段 Schema"""
        try:
            from app.db.database import SessionLocal
            from app.models.api_endpoint import ApiEndpoint

            db = SessionLocal()
            try:
                ep = db.query(ApiEndpoint).filter(ApiEndpoint.id == endpoint_id).first()
                if not ep:
                    return []

                fields = []
                # 解析 params_json (Query/Path 参数)
                if ep.params_json:
                    params = json.loads(ep.params_json) if isinstance(ep.params_json, str) else ep.params_json
                    if isinstance(params, list):
                        for p in params:
                            fields.append({
                                'name': p.get('name', ''),
                                'type': p.get('type', 'string'),
                                'required': p.get('required', False),
                                'min_length': p.get('minLength') or p.get('min_length'),
                                'max_length': p.get('maxLength') or p.get('max_length'),
                                'pattern': p.get('pattern'),
                                'enum': p.get('enum'),
                                'format': p.get('format'),
                                'description': p.get('description', ''),
                            })
                # 解析 body_json (请求体字段)
                if ep.body_json:
                    body = json.loads(ep.body_json) if isinstance(ep.body_json, str) else ep.body_json
                    if isinstance(body, dict):
                        # body 是 Schema 格式
                        properties = body.get('properties', {})
                        required_fields = body.get('required', [])
                        for fname, fdef in properties.items():
                            fields.append({
                                'name': fname,
                                'type': fdef.get('type', 'string'),
                                'required': fname in required_fields,
                                'min_length': fdef.get('minLength') or fdef.get('min_length'),
                                'max_length': fdef.get('maxLength') or fdef.get('max_length'),
                                'pattern': fdef.get('pattern'),
                                'enum': fdef.get('enum'),
                                'format': fdef.get('format'),
                                'description': fdef.get('description', ''),
                            })
                return fields
            finally:
                db.close()
        except Exception as e:
            logger.error(f"[ApiDataGeneratorAgent] 加载 Schema 失败: {e}")
            return []

    async def _try_template(
        self, endpoint_id: int, data_type: str, count: int, user_id: Optional[int]
    ) -> List[Dict]:
        """尝试从模板复用数据"""
        try:
            from app.db.database import SessionLocal
            from app.models.api_test_data import (
                ApiTestDataTemplate, GeneratedApiData, TemplateStatus
            )

            db = SessionLocal()
            try:
                # 查 active 模板
                tmpl = db.query(ApiTestDataTemplate).filter(
                    ApiTestDataTemplate.endpoint_id == endpoint_id,
                    ApiTestDataTemplate.data_type == data_type,
                    ApiTestDataTemplate.status == TemplateStatus.ACTIVE,
                    ApiTestDataTemplate.is_deleted == False,
                ).first()

                if not tmpl:
                    return []

                # 取最近的 generated_api_data (基于该模板生成的)
                instances = db.query(GeneratedApiData).filter(
                    GeneratedApiData.template_id == tmpl.id,
                    GeneratedApiData.is_deleted == False,
                ).order_by(GeneratedApiData.created_at.desc()).limit(count).all()

                result = []
                for inst in instances:
                    if inst.generated_data:
                        data = json.loads(inst.generated_data) if isinstance(inst.generated_data, str) else inst.generated_data
                        result.append(data)

                # 更新模板使用计数
                if result:
                    tmpl.usage_count = (tmpl.usage_count or 0) + len(result)
                    tmpl.last_used_at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
                    db.commit()

                return result
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"[ApiDataGeneratorAgent] 模板复用失败: {e}")
            return []

    async def _persist_generated(
        self,
        endpoint_id: int,
        result: Dict[str, List],
        sources_used: Dict[str, int],
        user_id: Optional[int],
        elapsed_ms: int,
    ) -> None:
        """持久化生成结果到 generated_api_data"""
        from app.db.database import SessionLocal
        from app.models.api_test_data import GeneratedApiData, DataType, GenerationSource

        db = SessionLocal()
        try:
            for data_type, items in result.items():
                if not isinstance(items, list):
                    continue
                for item in items:
                    # 映射枚举
                    try:
                        dt_enum = DataType(data_type)
                    except ValueError:
                        dt_enum = DataType.NORMAL

                    # 主要来源
                    primary_source = GenerationSource.RULE
                    if sources_used.get("faker", 0) > 0:
                        primary_source = GenerationSource.FAKER
                    elif sources_used.get("llm", 0) > 0:
                        primary_source = GenerationSource.LLM
                    elif sources_used.get("template", 0) > 0:
                        primary_source = GenerationSource.TEMPLATE

                    record = GeneratedApiData(
                        endpoint_id=endpoint_id,
                        template_id=None,  # 未关联模板 (未来可扩展)
                        case_id=None,
                        data_type=dt_enum,
                        generated_data=json.dumps(item, ensure_ascii=False, default=str),
                        source=primary_source,
                        elapsed_ms=elapsed_ms,
                        is_valid=True,
                        user_id=user_id,
                        created_by=user_id,
                    )
                    db.add(record)
            db.commit()
            logger.info(f"[ApiDataGeneratorAgent] 持久化 {sum(len(v) for v in result.values() if isinstance(v, list))} 条数据")
        except Exception as e:
            db.rollback()
            raise e
        finally:
            db.close()

    # ============================================================
    # 辅助: list / health
    # ============================================================

    async def _do_list(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """查询已生成数据"""
        endpoint_id = payload.get("endpoint_id")
        data_type = payload.get("data_type")
        limit = int(payload.get("limit", 10))

        try:
            from app.db.database import SessionLocal
            from app.models.api_test_data import GeneratedApiData

            db = SessionLocal()
            try:
                q = db.query(GeneratedApiData).filter(GeneratedApiData.is_deleted == False)
                if endpoint_id:
                    q = q.filter(GeneratedApiData.endpoint_id == endpoint_id)
                if data_type:
                    try:
                        dt_enum = DataType(data_type)
                        q = q.filter(GeneratedApiData.data_type == dt_enum)
                    except ValueError:
                        pass
                items = q.order_by(GeneratedApiData.created_at.desc()).limit(limit).all()

                return {
                    "status": "success",
                    "total": len(items),
                    "items": [
                        {
                            "id": it.id,
                            "endpoint_id": it.endpoint_id,
                            "data_type": it.data_type.value if it.data_type else None,
                            "source": it.source.value if it.source else None,
                            "generated_data": json.loads(it.generated_data) if isinstance(it.generated_data, str) else it.generated_data,
                            "elapsed_ms": it.elapsed_ms,
                            "created_at": str(it.created_at) if it.created_at else None,
                        }
                        for it in items
                    ]
                }
            finally:
                db.close()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def _do_health(self) -> Dict[str, Any]:
        """健康检查"""
        return {
            "status": "healthy",
            "agent": "ApiDataGeneratorAgent",
            "faker_available": _FAKER_AVAILABLE,
            "llm_available": True,  # 由 call_llm 内部判断
            "supported_types": ["normal", "abnormal", "boundary", "dependent"],
            "supported_sources": ["rule", "faker", "llm", "template", "runtime"],
        }
