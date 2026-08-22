"""
消息协议常量定义 - 接口自动化测试流程

流程: 接口解析 → 依赖分析 → 数据生成 → 测试用例 → 测试脚本 → 执行

每个阶段发布对应 topic,下游模块可订阅:

  endpoint.parsed     → 依赖分析订阅
  dependency.analyzed  → 数据生成订阅
  data.generated      → 用例生成订阅
  case.created        → 脚本生成订阅
  script.generated    → 执行订阅
  case.executed       → 报告生成订阅

事件 payload 结构:
  {
    "endpoint_id": int,
    "task_id": Optional[int],
    "source": str (发布者),
    "data": Dict (阶段产出),
    "status": "completed" | "failed"
  }
"""

# ============================================================
# 流程阶段 Topic
# ============================================================

# 1. 接口解析完成 (由 ApiEndpointService.create_endpoint / publish_endpoint 发布)
TOPIC_ENDPOINT_PARSED = "endpoint.parsed"

# 2. 依赖分析完成 (由 DependencyService 发布,目前为 stub)
TOPIC_DEPENDENCY_ANALYZED = "dependency.analyzed"

# 3. 数据生成完成 (由 ApiTestDataService.generate_for_case 发布)
TOPIC_DATA_GENERATED = "data.generated"

# 4. 用例创建完成 (由 case_controller.generate_cases_from_endpoint 发布)
TOPIC_CASE_CREATED = "case.created"

# 5. 脚本生成完成 (API 场景由 case_controller 间接完成,steps 字段即脚本)
TOPIC_SCRIPT_GENERATED = "script.generated"

# 6. 用例执行完成 (由 execution_controller 发布)
TOPIC_CASE_EXECUTED = "case.executed"


# ============================================================
# 标准 payload 字段
# ============================================================

FIELD_ENDPOINT_ID = "endpoint_id"
FIELD_TASK_ID = "task_id"
FIELD_SOURCE = "source"
FIELD_DATA = "data"
FIELD_STATUS = "status"
FIELD_CASE_ID = "case_id"
FIELD_DATA_TYPES = "data_types"
FIELD_TOTAL_COUNT = "total_count"


# ============================================================
# 数据生成阶段 payload schema
# ============================================================

DATA_GENERATED_PAYLOAD = {
    "endpoint_id": "int — 接口 ID",
    "data_types": "List[str] — 已生成类型 [normal, abnormal, boundary, dependent]",
    "total_count": "int — 总条数",
    "suggested_case_count": "int — 建议用例数",
}


# ============================================================
# 用例创建阶段 payload schema
# ============================================================

CASE_CREATED_PAYLOAD = {
    "case_id": "int — 新建用例 ID",
    "endpoint_id": "int — 关联接口 ID",
    "source": "str — 来源 (ai/manual)",
}


def build_data_generated_payload(
    endpoint_id: int,
    data_types: list,
    total_count: int,
    suggested_case_count: int,
) -> dict:
    """构造 data.generated 事件 payload"""
    return {
        FIELD_ENDPOINT_ID: endpoint_id,
        FIELD_DATA_TYPES: data_types,
        FIELD_TOTAL_COUNT: total_count,
        "suggested_case_count": suggested_case_count,
    }


def build_case_created_payload(case_id: int, endpoint_id: int, source: str = "ai") -> dict:
    """构造 case.created 事件 payload"""
    return {
        FIELD_CASE_ID: case_id,
        FIELD_ENDPOINT_ID: endpoint_id,
        FIELD_SOURCE: source,
    }
