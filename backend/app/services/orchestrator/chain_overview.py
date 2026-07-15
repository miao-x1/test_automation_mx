"""
全链路总览脚本

展示所有业务流程经过的 Agent 链路：
  API → TaskOrchestrator → AgentRegistry.create() → Agent.method() → AgentExecutionMonitor

6 条流程，35 个 Agent，13 种 Action 映射。

运行方式：
  cd backend
  python -m app.services.orchestrator.chain_overview
"""
import asyncio
import json
import os
import sys
import time

# 确保路径
backend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, backend_dir)


# ==================== 流程定义（来自 task_flows.yaml） ====================

FLOWS = [
    {
        "flow_name": "image_test_flow",
        "description": "图片测试流程：截图分析 → 用例生成 → 脚本生成",
        "steps": [
            {"step": "analyze_image",       "agent": "element_agent",      "action": "analyze",   "input_from": None},
            {"step": "generate_cases",      "agent": "case_agent",          "action": "generate",  "input_from": "analyze_image"},
            {"step": "generate_script",     "agent": "script_generator",    "action": "generate",  "input_from": "generate_cases"},
        ],
    },
    {
        "flow_name": "requirement_test_flow",
        "description": "需求测试流程：需求解析 → 类型分类 → RAG检索 → 用例生成 → 用例审查 → 脚本生成",
        "steps": [
            {"step": "parse_requirement",   "agent": "requirement_agent",       "action": "parse",     "input_from": None},
            {"step": "classify_type",       "agent": "test_type_classifier",    "action": "classify",  "input_from": "parse_requirement"},
            {"step": "rag_retrieve",        "agent": "rag_agent",               "action": "retrieve",  "input_from": "parse_requirement"},
            {"step": "generate_cases",      "agent": "case_agent",              "action": "generate",  "input_from": "rag_retrieve"},
            {"step": "review_cases",        "agent": "review_agent",            "action": "review",    "input_from": "generate_cases"},
            {"step": "generate_script",     "agent": "script_generator",        "action": "generate",  "input_from": "review_cases"},
        ],
    },
    {
        "flow_name": "knowledge_ingest_flow",
        "description": "知识入库流程：文档解析 → 向量化 → 存储",
        "steps": [
            {"step": "parse_document",      "agent": "document_parser",     "action": "parse",    "input_from": None},
            {"step": "embed_elements",      "agent": "embedding_agent",      "action": "embed",    "input_from": "parse_document"},
            {"step": "store_knowledge",     "agent": "storage_agent",        "action": "store",    "input_from": "embed_elements"},
        ],
    },
    {
        "flow_name": "execution_flow",
        "description": "脚本执行流程：执行 → 反馈分析 → 知识更新",
        "steps": [
            {"step": "execute_script",      "agent": "execution_agent",          "action": "execute", "input_from": None},
            {"step": "analyze_feedback",    "agent": "feedback_agent",           "action": "analyze", "input_from": "execute_script"},
            {"step": "update_knowledge",    "agent": "knowledge_update_agent",   "action": "update",  "input_from": "analyze_feedback"},
        ],
    },
    {
        "flow_name": "graph_build_flow",
        "description": "图谱构建流程：关系推理 → 图谱构建",
        "steps": [
            {"step": "infer_relations",     "agent": "relation_agent",      "action": "infer",   "input_from": None},
            {"step": "build_graph",         "agent": "graph_agent",         "action": "build",   "input_from": "infer_relations"},
        ],
    },
    {
        "flow_name": "testcase_pipeline_flow",
        "description": "TestCase流水线：需求分析 → 测试点 → 用例生成 → 用例审查 → 知识同步",
        "steps": [
            {"step": "analyze_requirement", "agent": "requirement_analysis_agent", "action": "analyze",  "input_from": None},
            {"step": "analyze_test_points", "agent": "test_point_analysis_agent",   "action": "analyze",  "input_from": "analyze_requirement"},
            {"step": "generate_cases",      "agent": "testcase_generator_agent",   "action": "generate", "input_from": "analyze_test_points"},
            {"step": "review_cases",        "agent": "testcase_review_agent",       "action": "review",   "input_from": "generate_cases"},
            {"step": "sync_knowledge",      "agent": "knowledge_sync_agent",       "action": "sync",     "input_from": "review_cases"},
        ],
    },
]

# ==================== Action → Method 映射（来自 _dispatch_action） ====================

ACTION_METHOD_MAP = {
    "analyze":   ["analyze", "execute", "process"],
    "generate":  ["generate", "generate_cases", "generate_script", "execute"],
    "review":    ["review", "execute"],
    "execute":   ["execute", "run", "run_script"],
    "retrieve":  ["retrieve", "search", "execute"],
    "parse":     ["parse", "execute", "process"],
    "embed":     ["embed", "embed_elements", "execute"],
    "store":     ["store", "save", "execute"],
    "classify":  ["classify", "classify_sync", "execute"],
    "infer":     ["infer", "find_related_pages", "execute"],
    "build":     ["build", "build_full_graph", "execute"],
    "update":    ["update", "execute"],
    "sync":      ["sync", "execute"],
}

# ==================== Agent 配置摘要（来自 agent_config.yaml） ====================

AGENT_CONFIG = {
    # 核心业务
    "requirement_agent":            {"class": "RequirementAgent",         "model": "qwen-plus",         "display": "需求解析Agent"},
    "case_agent":                   {"class": "CaseAgent",                "model": "deepseek-chat",     "display": "用例生成Agent"},
    "script_generator":             {"class": "ScriptGenerator",         "model": "qwen-coder-plus",   "display": "脚本生成Agent"},
    "execution_agent":              {"class": "ExecutionAgent",           "model": "qwen-plus",         "display": "脚本执行Agent"},
    "feedback_agent":               {"class": "FeedbackAgent",           "model": "claude-3-5-sonnet", "display": "反馈分析Agent"},
    "review_agent":                 {"class": "ReviewAgent",             "model": "claude-3-5-sonnet", "display": "用例审查Agent"},
    # RAG / 知识
    "rag_agent":                    {"class": "RAGAgent",                "model": None,                "display": "RAG检索Agent"},
    "embedding_agent":              {"class": "EmbeddingAgent",          "model": "text-embedding-v3", "display": "向量化Agent"},
    "knowledge_update_agent":       {"class": "KnowledgeUpdateAgent",    "model": None,                "display": "知识更新Agent"},
    # 图谱
    "graph_agent":                  {"class": "GraphAgent",              "model": None,                "display": "图谱推理Agent"},
    "relation_agent":               {"class": "RelationAgent",          "model": "qwen-plus",         "display": "页面关联Agent"},
    # 视觉
    "element_agent":                {"class": "ElementAgent",            "model": "qwen-vl-plus",      "display": "视觉元素识别Agent"},
    # 需求
    "test_type_classifier":         {"class": "TestTypeClassifierAgent",  "model": "qwen-plus",         "display": "测试类型分类Agent"},
    # 存储
    "storage_agent":               {"class": "StorageAgent",            "model": None,                "display": "存储Agent"},
    # TestCase 流水线
    "requirement_analysis_agent":   {"class": "RequirementAnalysisAgent", "model": "qwen-plus",        "display": "需求分析Agent"},
    "test_point_analysis_agent":    {"class": "TestPointAnalysisAgent",   "model": "qwen-plus",        "display": "测试点分析Agent"},
    "testcase_generator_agent":     {"class": "TestCaseGeneratorAgent",   "model": "qwen-plus",        "display": "用例生成Agent"},
    "testcase_review_agent":        {"class": "TestCaseReviewAgent",     "model": "qwen-plus",         "display": "用例审查Agent"},
    "knowledge_sync_agent":         {"class": "KnowledgeSyncAgent",      "model": None,                "display": "知识同步Agent"},
    # 文档
    "document_parser":              {"class": "DocumentParserAgent",     "model": "deepseek-chat",     "display": "文档解析Agent"},
}


# ==================== 打印函数 ====================

def print_separator(char="=", length=100):
    print(char * length)


def print_flow_chain(flow):
    """打印单条流程的完整链路"""
    print(f"\n  流程: {flow['flow_name']}")
    print(f"  描述: {flow['description']}")
    print(f"  步骤数: {len(flow['steps'])}")
    print()

    for i, step in enumerate(flow["steps"]):
        agent = step["agent"]
        action = step["action"]
        methods = ACTION_METHOD_MAP.get(action, [action])
        cfg = AGENT_CONFIG.get(agent, {})
        model = cfg.get("model", "?")
        display = cfg.get("display", agent)

        # 链路箭头
        arrow = "  ↓" if i < len(flow["steps"]) - 1 else ""

        print(f"  [{i}] {step['step']}")
        print(f"      Agent:     {agent} ({display})")
        print(f"      Class:     {cfg.get('class', '?')}")
        print(f"      Model:     {model or '无LLM'}")
        print(f"      Action:    {action}")
        print(f"      Methods:   {' → '.join(methods)}")
        if step.get("input_from"):
            print(f"      InputFrom: {step['input_from']} (上一步输出)")
        print(f"      Monitor:   record_start → record_success/record_failure")
        if arrow:
            print(f"  {arrow}")


def print_full_chain():
    """打印所有流程链路"""
    print_separator()
    print("全链路总览：API → TaskOrchestrator → Agent → Monitor")
    print_separator()
    print()
    print("调用架构:")
    print()
    print("  FastAPI API")
    print("    │")
    print("    ├─ POST /orchestrator/execute/{flow_name}     (SSE流式)")
    print("    ├─ POST /orchestrator/execute/{flow_name}/sync (同步)")
    print("    │")
    print("    ▼")
    print("  TaskOrchestrator.execute(flow_name, payload)")
    print("    │")
    print("    ├─ 1. 从 task_flows.yaml 加载流程定义")
    print("    ├─ 2. 创建 TaskState 记录 (DB持久化)")
    print("    ├─ 3. 逐步执行:")
    print("    │     │")
    print("    │     ├─ 3.1 构建步骤输入 (payload + input_from)")
    print("    │     │")
    print("    │     ├─ 3.2 _execute_agent(agent_name, action, input_data)")
    print("    │     │     │")
    print("    │     │     ├─ AgentExecutionMonitor.record_start()")
    print("    │     │     │     → 写入 AgentExecutionLog (status=running)")
    print("    │     │     │")
    print("    │     │     ├─ AgentRegistry.create(agent_name)")
    print("    │     │     │     → 从 agent_config.yaml 加载类配置")
    print("    │     │     │     → 实例化 Agent")
    print("    │     │     │")
    print("    │     │     ├─ _dispatch_action(agent, action)")
    print("    │     │     │     → action_map[action] → 尝试方法列表")
    print("    │     │     │     → agent.method(input_data)")
    print("    │     │     │")
    print("    │     │     ├─ AgentExecutionMonitor.record_success(output)")
    print("    │     │     │     → 更新 AgentExecutionLog (status=success)")
    print("    │     │     │")
    print("    │     │     └─ (异常) AgentExecutionMonitor.record_failure(error)")
    print("    │     │           → 更新 AgentExecutionLog (status=error)")
    print("    │     │")
    print("    │     ├─ 3.3 更新 TaskState (current_agent / step_index)")
    print("    │     │")
    print("    │     └─ 3.4 yield SSE 事件 (step_start / step_success / step_failed)")
    print("    │")
    print("    ├─ 4. 流程完成 → 更新 TaskState (status=success/failed)")
    print("    └─ 5. yield SSE 事件 (flow_success / flow_failed / done)")
    print()
    print("  监控查询:")
    print("    GET /orchestrator/timeline/{task_id}        → Dify风格时间线")
    print("    GET /orchestrator/timeline/{task_id}/failed  → 失败节点列表")
    print("    GET /orchestrator/node/{log_id}              → 单节点详情")
    print("    GET /orchestrator/stats                       → 执行统计")

    for flow in FLOWS:
        print_separator("-")
        print_flow_chain(flow)


def print_action_map():
    """打印 Action → Method 映射表"""
    print_separator()
    print("Action → Method 映射表（来自 _dispatch_action）")
    print_separator()
    print()
    print(f"  {'Action':<15} {'尝试方法（按顺序）':<60}")
    print(f"  {'─'*15} {'─'*60}")

    for action, methods in ACTION_METHOD_MAP.items():
        method_chain = " → ".join(methods)
        print(f"  {action:<15} {method_chain}")

    print()
    print("  规则: 按顺序尝试每个方法，第一个成功调用的返回结果。")
    print("  降级: 所有方法都失败时，返回输入数据。")


def print_agent_registry():
    """打印 Agent 注册表"""
    print_separator()
    print("Agent 注册表（来自 agent_config.yaml）")
    print_separator()
    print()
    print(f"  {'Agent Name':<35} {'Class':<30} {'Model':<25} {'Display Name'}")
    print(f"  {'─'*35} {'─'*30} {'─'*25} {'─'*25}")

    for name, cfg in AGENT_CONFIG.items():
        model = cfg.get("model") or "无LLM"
        print(f"  {name:<35} {cfg.get('class', '?'):<30} {model:<25} {cfg.get('display', '')}")

    print(f"\n  共 {len(AGENT_CONFIG)} 个 Agent（完整配置 35 个，此处展示链路涉及的）")


def print_api_endpoints():
    """打印所有 API 端点"""
    print_separator()
    print("API 端点清单")
    print_separator()
    print()
    print("  任务编排:")
    print("    GET  /orchestrator/flows                    列出所有流程")
    print("    GET  /orchestrator/flows/{flow_name}        获取流程详情")
    print("    POST /orchestrator/execute/{flow_name}      执行流程（SSE流式）")
    print("    POST /orchestrator/execute/{flow_name}/sync 执行流程（同步）")
    print("    GET  /orchestrator/task/{task_id}           查询任务状态")
    print("    POST /orchestrator/reload                   重新加载流程定义")
    print()
    print("  执行监控:")
    print("    GET  /orchestrator/timeline/{task_id}       获取执行时间线（Dify风格）")
    print("    GET  /orchestrator/timeline/{task_id}/failed 获取失败节点列表")
    print("    GET  /orchestrator/node/{log_id}            获取单节点详情")
    print("    GET  /orchestrator/stats                    获取执行统计")
    print()
    print("  会话管理:")
    print("    POST /session/v2/create                      创建会话")
    print("    GET  /session/v2/list                       会话列表")
    print("    GET  /session/v2/{id}                       会话详情")
    print("    GET  /session/v2/{id}/detail                 会话完整详情（企业级）")
    print("    GET  /session/v2/{id}/restore                恢复会话")
    print("    GET  /session/v2/{id}/messages               Agent消息记录")
    print("    GET  /session/v2/{id}/execution-logs         执行日志")
    print("    GET  /session/v2/{id}/task-states            TaskState记录")
    print("    GET  /session/v2/{id}/results               生成结果")
    print("    POST /session/v2/{id}/run                   执行GraphFlow")
    print("    POST /session/v2/{id}/artifacts             添加制品")
    print("    GET  /session/v2/{id}/artifacts              获取制品列表")
    print("    POST /session/v2/{id}/upload                上传文件")


def print_data_flow():
    """打印数据流转"""
    print_separator()
    print("数据流转图（以 requirement_test_flow 为例）")
    print_separator()
    print()
    print("  用户输入: {\"requirement\": \"测试登录功能\"}")
    print("    │")
    print("    ▼")
    print("  [Step 0] parse_requirement")
    print("    Agent: requirement_agent.parse({\"requirement\": \"测试登录功能\"})")
    print("    Output: {\"parsed\": {\"intent\": \"login\", \"target_url\": \"/login\", \"steps\": [...]}}")
    print("    │")
    print("    ▼ input_from=parse_requirement")
    print("  [Step 1] classify_type")
    print("    Agent: test_type_classifier.classify({\"parsed\": {...}})")
    print("    Output: {\"test_type\": \"WEB\", \"confidence\": 0.95}")
    print("    │")
    print("    ▼ input_from=parse_requirement")
    print("  [Step 2] rag_retrieve")
    print("    Agent: rag_agent.retrieve({\"parsed\": {...}})")
    print("    Output: {\"contexts\": [{\"element\": \"btn_login\", \"similarity\": 0.92}]}")
    print("    │")
    print("    ▼ input_from=rag_retrieve")
    print("  [Step 3] generate_cases")
    print("    Agent: case_agent.generate({\"contexts\": [...], \"parsed\": {...}})")
    print("    Output: {\"cases\": [{\"id\": 1, \"title\": \"登录成功\", \"steps\": [...]}]}")
    print("    │")
    print("    ▼ input_from=generate_cases")
    print("  [Step 4] review_cases")
    print("    Agent: review_agent.review({\"cases\": [...]})")
    print("    Output: {\"approved\": true, \"issues\": [], \"score\": 85}")
    print("    │")
    print("    ▼ input_from=review_cases")
    print("  [Step 5] generate_script")
    print("    Agent: script_generator.generate({\"approved\": true, \"cases\": [...]})")
    print("    Output: {\"script\": \"def test_login(): ...\", \"language\": \"python\"}")
    print("    │")
    print("    ▼")
    print("  最终结果: {\"parse_requirement\": {...}, \"classify_type\": {...}, ...}")


# ==================== 活跃链路模拟（实际写入DB） ====================

async def simulate_flow_with_monitor():
    """模拟一条完整流程，实际写入 AgentExecutionLog，生成时间线"""
    from app.db.database import Base, SessionLocal, sync_engine
    from app.models.agent_execution_log import AgentExecutionLog
    from app.services.monitor import get_execution_monitor

    # 确保表存在
    Base.metadata.create_all(bind=sync_engine, tables=[AgentExecutionLog.__table__])

    monitor = get_execution_monitor()
    task_id = f"demo_{int(time.time())}"
    session_id = "demo_session"
    flow_name = "requirement_test_flow"

    print_separator()
    print(f"活跃链路模拟: {flow_name}")
    print(f"  task_id: {task_id}")
    print_separator()

    # 模拟 6 个步骤
    steps = [
        ("parse_requirement",  "requirement_agent",       "parse",     {"requirement": "测试登录功能"}, {"intent": "login", "url": "/login"}),
        ("classify_type",     "test_type_classifier",    "classify",  {"req": "login"}, {"type": "WEB", "confidence": 0.95}),
        ("rag_retrieve",      "rag_agent",               "retrieve",  {"query": "login"}, {"docs": [{"elem": "btn_login"}]}),
        ("generate_cases",    "case_agent",              "generate",  {"elements": []}, {"cases": [{"id": 1, "title": "登录成功"}]}),
        ("review_cases",      "review_agent",            "review",    {"cases": []}, {"approved": True, "score": 85}),
        ("generate_script",   "script_generator",        "generate",  {"cases": [{"id": 1}]}, {"script": "def test_login(): pass"}),
    ]

    log_ids = []
    for step_name, agent_name, action, input_data, output in steps:
        print(f"\n  [{step_name}]")
        print(f"    → AgentRegistry.create('{agent_name}')")
        print(f"    → monitor.record_start(agent='{agent_name}', step='{step_name}')")

        lid = monitor.record_start(
            agent_name=agent_name,
            step=step_name,
            input_data=input_data,
            task_id=task_id,
            session_id=session_id,
            flow_name=flow_name,
        )
        log_ids.append(lid)

        time.sleep(0.02)

        # 模拟 agent.method(input_data) 调用
        methods = ACTION_METHOD_MAP.get(action, [action])
        print(f"    → agent.{' → '.join(methods)}(input_data)")

        # 第 4 步模拟失败
        if step_name == "review_cases":
            print(f"    ✗ monitor.record_failure(error='审查超时')")
            monitor.record_failure(log_id=lid, error="LLM 调用超时", duration_ms=50.0)
        else:
            print(f"    ✓ monitor.record_success(output={list(output.keys())})")
            monitor.record_success(log_id=lid, output=output, duration_ms=20.0)

    # 查询时间线
    print(f"\n{'─'*60}")
    print(f"时间线查询: GET /orchestrator/timeline/{task_id}")
    print(f"{'─'*60}")

    timeline = monitor.get_timeline(task_id)
    print(f"\n  task_id:         {timeline['task_id']}")
    print(f"  total_steps:     {timeline['total_steps']}")
    print(f"  success_count:   {timeline['success_count']}")
    print(f"  failed_count:     {timeline['failed_count']}")
    print(f"  total_duration:  {timeline['total_duration_ms']}ms")
    print()

    for item in timeline["timeline"]:
        status_icon = "✓" if item["status"] == "success" else "✗" if item["status"] == "error" else "○"
        print(f"  [{item['step_index']}] {status_icon} {item['step_name']:<25} | {item['agent_name']:<30} | {item['status']:<8} | {item['duration_ms']}ms")
        if item["error"]:
            print(f"       ERROR: {item['error']}")

    # 查询失败节点
    print(f"\n{'─'*60}")
    print(f"失败节点查询: GET /orchestrator/timeline/{task_id}/failed")
    print(f"{'─'*60}")

    failed = monitor.get_failed_nodes(task_id)
    print(f"\n  失败节点数: {len(failed)}")
    for f in failed:
        print(f"  ✗ {f['step_name']:<25} | {f['agent_name']:<30} | error={f['error']}")

    # 统计
    print(f"\n{'─'*60}")
    print(f"执行统计: GET /orchestrator/stats?task_id={task_id}")
    print(f"{'─'*60}")

    stats = monitor.get_stats(task_id=task_id)
    print(f"\n  total:          {stats['total']}")
    print(f"  success:        {stats['success']}")
    print(f"  failed:         {stats['failed']}")
    print(f"  running:        {stats['running']}")
    print(f"  success_rate:   {stats['success_rate']}%")
    print(f"  total_duration: {stats['total_duration_s']}s")

    # 清理
    db = SessionLocal()
    try:
        db.query(AgentExecutionLog).filter(AgentExecutionLog.task_id == task_id).delete()
        db.commit()
    finally:
        db.close()

    print(f"\n  [完成] 模拟数据已清理")


# ==================== 主入口 ====================

if __name__ == "__main__":
    # 打印静态链路
    print_full_chain()
    print_action_map()
    print_agent_registry()
    print_api_endpoints()
    print_data_flow()

    # 运行活跃链路模拟
    asyncio.run(simulate_flow_with_monitor())

    print_separator()
    print("全链路总览完成")
    print_separator()
