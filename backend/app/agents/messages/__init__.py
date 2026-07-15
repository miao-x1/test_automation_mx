"""
业务流消息类型定义

所有消息均为 Pydantic BaseModel，完全可序列化，支持分布式部署。

业务流：
    RequirementMessage → RequirementAgent → PageMessage
    PageMessage       → ImageAgent       → CaseMessage
    CaseMessage        → CaseAgent        → ReviewMessage
    ReviewMessage      → ReviewAgent      → ScriptMessage
    ScriptMessage      → ScriptAgent      → ExportMessage
    ExportMessage      → ExportAgent      → 结果保存

每条消息携带：
- task_id:      全局任务 ID（贯穿整个流程）
- session_key:  会话标识（多用户隔离）
- user_id:      用户 ID
- step:         当前步骤名
- timestamp:    时间戳
- data:         业务数据（Dict，可序列化）
"""
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
import time
import uuid


def _gen_id() -> str:
    return str(uuid.uuid4())


# ================================================================ #
#  基类                                                               #
# ================================================================ #

class FlowMessage(BaseModel):
    """所有业务流消息的基类"""
    task_id: str = Field(default_factory=_gen_id)
    session_key: str = "default"
    user_id: Optional[int] = None
    step: str = ""
    timestamp: float = Field(default_factory=time.time)

    def to_db_dict(self) -> Dict[str, Any]:
        """转换为数据库存储格式"""
        return {
            "task_id": self.task_id,
            "session_key": self.session_key,
            "step": self.step,
            "input_json": self.model_dump_json(),
        }


# ================================================================ #
#  Step 1: 需求消息                                                   #
# ================================================================ #

class RequirementMessage(FlowMessage):
    """
    需求消息 - 流程入口

    由 FastAPI 发送给 RequirementAgent。
    """
    step: str = "requirement"
    requirement: str = ""                         # 用户原始需求文本
    input_mode: str = "text"                     # 输入方式: text / image / document / url
    image_paths: List[str] = Field(default_factory=list)   # 图片路径列表
    document_paths: List[str] = Field(default_factory=list) # 文档路径列表
    urls: List[str] = Field(default_factory=list)          # URL 列表
    context: Dict[str, Any] = Field(default_factory=dict)  # 附加上下文


class RequirementItem(BaseModel):
    """需求项 - 需求拆分后的单个测试点

    每一个 RequirementItem 会单独查询 RAG 获取相关上下文。
    """
    item_id: str = Field(default_factory=_gen_id)
    text: str = ""                               # 需求点文本
    category: str = ""                           # 分类: functional/boundary/error/security/performance
    priority: str = "medium"                     # 优先级: high/medium/low
    rag_context: str = ""                        # RAG 查询返回的上下文（单独查询）
    rag_results: List[Dict[str, Any]] = Field(default_factory=list)  # RAG 检索结果
    tags: List[str] = Field(default_factory=list)  # 自动提取的标签


# ================================================================ #
#  Step 2: 页面消息                                                   #
# ================================================================ #

class PageMessage(FlowMessage):
    """
    页面消息 - RequirementAgent → ImageAgent

    携带解析后的需求信息和目标页面。
    """
    step: str = "page"
    intent: str = ""                             # 测试意图
    test_steps: List[str] = Field(default_factory=list)    # 测试步骤
    target_urls: List[str] = Field(default_factory=list)   # 目标页面 URL
    page_descriptions: Dict[str, str] = Field(default_factory=dict)  # 页面描述
    test_scope: str = ""                         # 测试范围
    requirement_items: List[RequirementItem] = Field(default_factory=list)  # 需求项（带RAG上下文）


# ================================================================ #
#  Step 3: 用例消息                                                   #
# ================================================================ #

class CaseMessage(FlowMessage):
    """
    用例消息 - ImageAgent → CaseAgent

    携带页面元素信息。
    """
    step: str = "case"
    page_elements: Dict[str, List[Dict]] = Field(default_factory=dict)  # 页面 → 元素列表
    element_locators: Dict[str, Dict] = Field(default_factory=dict)      # 元素定位器
    requirement_summary: str = ""               # 需求摘要
    intent: str = ""                             # 测试意图
    rag_context: str = ""                        # RAG 全局上下文（所有需求项合并）
    requirement_items: List[RequirementItem] = Field(default_factory=list)  # 需求项（每个带独立RAG上下文）


# ================================================================ #
#  Step 4: 审查消息                                                   #
# ================================================================ #

class ReviewMessage(FlowMessage):
    """
    审查消息 - CaseAgent → ReviewAgent

    携带生成的测试用例。
    """
    step: str = "review"
    cases: List[Dict[str, Any]] = Field(default_factory=list)  # 测试用例列表
    case_count: int = 0                          # 用例数量
    coverage_notes: str = ""                     # 覆盖说明


# ================================================================ #
#  Step 5: 脚本消息                                                   #
# ================================================================ #

class ScriptMessage(FlowMessage):
    """
    脚本消息 - ReviewAgent → ScriptAgent

    携带审查通过的用例和元素信息。
    """
    step: str = "script"
    approved_cases: List[Dict[str, Any]] = Field(default_factory=list)  # 审查通过的用例
    rejected_cases: List[Dict[str, Any]] = Field(default_factory=list)  # 被拒绝的用例
    review_notes: str = ""                       # 审查备注
    page_elements: Dict[str, List[Dict]] = Field(default_factory=dict)  # 页面元素


# ================================================================ #
#  Step 6: 导出消息                                                   #
# ================================================================ #

class ExportMessage(FlowMessage):
    """
    导出消息 - ScriptAgent → ExportAgent

    携带生成的脚本。
    """
    step: str = "export"
    scripts: List[Dict[str, Any]] = Field(default_factory=list)  # 脚本列表
    script_language: str = "python"             # 脚本语言
    framework: str = "playwright"               # 测试框架
    total_scripts: int = 0                       # 脚本总数


# ================================================================ #
#  导出                                                               #
# ================================================================ #

# ================================================================ #
#  存储消息                                                           #
# ================================================================ #

class StorageMessage(FlowMessage):
    """存储消息 - Agent → StorageAgent

    所有需要持久化数据的 Agent 统一发送此消息给 StorageAgent。
    禁止 Agent 直接调用 Service 写数据库。

    操作类型：
      - mysql_save:     保存到 MySQL（指定表名和数据）
      - mysql_query:    查询 MySQL
      - mysql_delete:   删除 MySQL 记录
      - vector_insert:  插入 Milvus 向量
      - vector_search:  搜索 Milvus 向量
      - vector_delete:  删除 Milvus 向量
      - graph_create:   创建 Neo4j 节点
      - graph_link:     创建 Neo4j 关系
      - graph_query:    查询 Neo4j 图谱
      - graph_delete:   删除 Neo4j 节点
    """
    step: str = "storage"
    storage_type: str = "mysql"                # mysql / vector / graph
    operation: str = "save"                    # save / query / delete / insert / search / create / link
    table: str = ""                            # MySQL 表名
    entity_type: str = ""                      # 向量集合类型 / 图谱节点标签
    data: Dict[str, Any] = Field(default_factory=dict)       # 写入数据
    filters: Dict[str, Any] = Field(default_factory=dict)    # 查询/删除条件
    options: Dict[str, Any] = Field(default_factory=dict)    # 额外选项


# ================================================================ #
#  OCR 消息                                                          #
# ================================================================ #

class OCRMessage(FlowMessage):
    """OCR 消息 - Agent → OCAgent / PageKnowledgeAgent

    用于触发 OCR 识别和页面元素提取。
    """
    step: str = "ocr"
    image_path: str = ""                      # 图片路径
    image_base64: str = ""                    # 图片 Base64（二选一）
    ocr_type: str = "page"                    # page / element / document
    extract_elements: bool = True             # 是否提取页面元素
    target_url: str = ""                      # 关联页面 URL


# ================================================================ #
#  执行消息                                                          #
# ================================================================ #

class ExecutionMessage(FlowMessage):
    """执行消息 - ScriptAgent → ExecutionAgent

    触发脚本执行。
    """
    step: str = "execution"
    script_path: str = ""                     # 脚本文件路径
    script_content: str = ""                  # 脚本内容（二选一）
    script_language: str = "python"           # 脚本语言
    framework: str = "playwright"             # 测试框架
    env: str = "dev"                           # 执行环境
    browser: str = "chromium"                  # 浏览器类型
    headless: bool = True                      # 是否无头模式
    timeout: int = 300                         # 超时时间（秒）


# ================================================================ #
#  报告消息                                                          #
# ================================================================ #

class ReportMessage(FlowMessage):
    """报告消息 - ExecutionAgent → ReportAgent

    携带执行结果，生成测试报告。
    """
    step: str = "report"
    execution_id: str = ""                    # 执行 ID
    total: int = 0                            # 总用例数
    passed: int = 0                           # 通过数
    failed: int = 0                           # 失败数
    skipped: int = 0                          # 跳过数
    duration: float = 0.0                     # 执行耗时
    results: List[Dict[str, Any]] = Field(default_factory=list)  # 详细结果
    screenshots: List[str] = Field(default_factory=list)          # 截图路径列表
    logs: str = ""                            # 执行日志


# ================================================================ #
#  日志消息                                                          #
# ================================================================ #

class LogMessage(FlowMessage):
    """日志消息 - Agent → CollectorAgent → AgentLog 表

    统一日志记录，替代 print() 和 logger.info()。
    所有 Agent 日志统一通过消息驱动写入数据库。
    """
    step: str = "log"
    log_level: str = "info"                   # debug / info / warning / error / critical
    agent_name: str = ""                      # Agent 名称
    message: str = ""                         # 日志内容
    module: str = ""                          # 模块名
    extra: Dict[str, Any] = Field(default_factory=dict)  # 额外字段


# ================================================================ #
#  脑图消息                                                          #
# ================================================================ #

class MindMapMessage(FlowMessage):
    """脑图消息 - CaseAgent → ExportAgent / Frontend

    测试用例思维导图数据。
    """
    step: str = "mindmap"
    root: str = ""                            # 根节点文本
    nodes: List[Dict[str, Any]] = Field(default_factory=list)  # 节点列表
    edges: List[Dict[str, Any]] = Field(default_factory=list)  # 边列表
    format: str = "json"                      # json / markdown / freemind


# ================================================================ #
#  需求上下文消息（InputRouterAgent → TestCaseGeneratorAgent）          #
# ================================================================ #

class RequirementContextMessage(FlowMessage):
    """
    需求上下文消息 - InputRouterAgent → TestCaseGeneratorAgent

    携带统一的 RequirementContext，包含：
    - pages: 页面信息列表
    - elements: UI元素列表
    - business_flow: 业务流程列表
    - test_points: 测试点列表
    - constraints: 约束条件列表

    由 InputRouterAgent 路由多种输入类型后合并生成。
    """
    step: str = "requirement_context"
    source_types: List[str] = Field(default_factory=list)       # ["text","pdf","image","swagger","schema","video"]
    context: Dict[str, Any] = Field(default_factory=dict)       # RequirementContext.to_dict()


# ================================================================ #
#  导出                                                               #
# ================================================================ #

ALL_FLOW_MESSAGES = [
    RequirementMessage,
    RequirementItem,
    PageMessage,
    CaseMessage,
    ReviewMessage,
    ScriptMessage,
    ExportMessage,
    StorageMessage,
    OCRMessage,
    ExecutionMessage,
    ReportMessage,
    LogMessage,
    MindMapMessage,
    RequirementContextMessage,
]
