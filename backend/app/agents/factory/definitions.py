"""
全部 Agent 规格定义

迁移所有现有 Agent 到 AgentFactory 管理。
每个 Agent 配置独立的模型、Prompt、工具、能力标签。

模型分配策略：
- Qwen (qwen-plus):        需求解析、用例生成、RAG检索、图谱推理
- Qwen-VL (qwen-vl-max):   元素分析、图片解析、页面抓取（视觉任务）
- QwenCoder (qwen-coder):   脚本生成、脚本验证、跨页面脚本生成（代码任务）
- DeepSeek (deepseek-chat): 用例生成(V2)、类型分类、文档解析（推理任务）
- Claude (claude-3.5):       用例审查、反馈分析（质量评估任务）
- Mock:                      测试用

新增 Agent 只需在此列表添加一条 AgentSpec，无需修改 Factory。
"""
from typing import List

from app.agents.factory.config import AgentSpec, ModelConfig


# ================================================================== #
#  全部 Agent 规格定义                                                  #
#  新增 Agent 在此列表添加一条记录即可                                   #
# ================================================================== #

DEFAULT_AGENT_SPECS: List[AgentSpec] = [

    # ================================================================ #
    #  核心业务 Agent                                                     #
    # ================================================================ #

    AgentSpec(
        name="requirement_agent",
        display_name="需求解析Agent",
        description="解析自然语言需求，提取意图、步骤、测试范围",
        agent_type="llm",
        module_path="app.agent.requirement.requirement_agent",
        class_name="RequirementAgent",
        model=ModelConfig(provider="dashscope", model_name="qwen-plus", temperature=0.3),
        system_prompt=(
            "你是一个需求分析专家。请仔细分析用户提供的测试需求，"
            "提取测试意图、测试步骤、涉及的页面和元素。"
            "输出 JSON 格式的分析结果。"
        ),
        tools=["http_fetch", "text_extract"],
        capabilities=["requirement_parse"],
        enabled=True,
    ),

    AgentSpec(
        name="element_agent",
        display_name="元素分析Agent",
        description="使用视觉模型分析页面截图，提取UI元素和定位器",
        agent_type="llm",
        module_path="app.agent.vision.element_agent",
        class_name="ElementAgent",
        model=ModelConfig(provider="dashscope", model_name="qwen-vl-max", temperature=0.5),
        system_prompt=(
            "你是一个UI元素分析专家。请分析提供的页面截图，"
            "识别所有可交互的UI元素（按钮、输入框、链接、下拉框等），"
            "并给出每个元素的定位策略。"
        ),
        tools=["image_load", "base64_encode"],
        capabilities=["vision"],
        enabled=True,
    ),

    AgentSpec(
        name="script_generation_agent",
        display_name="脚本生成Agent",
        description="根据测试用例和元素信息生成Playwright自动化脚本（含4级降级链）",
        agent_type="llm",
        module_path="app.agent.script.script_generation_agent",
        class_name="ScriptGenerationAgent",
        model=ModelConfig(provider="dashscope", model_name="qwen-coder-plus", temperature=0.2, max_tokens=8192),
        system_prompt=(
            "你是一个自动化测试脚本专家。请根据测试用例和页面元素信息，"
            "生成高质量的Playwright Python测试脚本。"
            "脚本应包含：页面对象、定位器、断言、截图、异常处理。"
        ),
        tools=["strategy_selector", "prompt_builder", "retry_injector"],
        capabilities=["script_generate"],
        enabled=True,
    ),

    AgentSpec(
        name="execution_agent",
        display_name="脚本执行Agent",
        description="执行Playwright脚本，收集执行结果和日志",
        agent_type="tool",
        module_path="app.agent.execution.execution_agent",
        class_name="ExecutionAgent",
        model=ModelConfig(provider="dashscope", model_name="qwen-plus", temperature=0.3),
        system_prompt="你是脚本执行和失败分析专家。分析执行日志，定位失败原因。",
        tools=["subprocess_runner", "log_parser", "screenshot_capture"],
        capabilities=["script_execute"],
        enabled=True,
    ),

    AgentSpec(
        name="case_agent",
        display_name="用例生成Agent",
        description="根据需求生成结构化测试用例",
        agent_type="llm",
        module_path="app.agent.case.case_agent",
        class_name="CaseAgent",
        model=ModelConfig(provider="deepseek", model_name="deepseek-chat", temperature=0.4),
        system_prompt=(
            "你是一个测试用例设计专家。请根据需求分析结果，"
            "设计覆盖正常流程、异常流程、边界条件的测试用例。"
            "输出 JSON 格式，包含用例标题、步骤、预期结果。"
        ),
        tools=["rag_retrieve", "graph_infer"],
        capabilities=["case_generate"],
        enabled=True,
    ),

    AgentSpec(
        name="rag_agent",
        display_name="RAG检索Agent",
        description="从向量数据库检索相关的历史元素、用例、脚本",
        agent_type="tool",
        module_path="app.agent.rag.rag_agent",
        class_name="RAGAgent",
        model=ModelConfig(provider="dashscope", model_name="text-embedding-v3", temperature=0.0),
        system_prompt="你是RAG检索专家。根据查询从向量数据库中检索最相关的历史数据。",
        tools=["milvus_client", "embedding"],
        capabilities=["rag_retrieve"],
        enabled=True,
    ),

    AgentSpec(
        name="graph_agent",
        display_name="图谱推理Agent",
        description="从Neo4j图谱中推理页面关系和业务流程",
        agent_type="tool",
        module_path="app.agent.graph.graph_agent",
        class_name="GraphAgent",
        model=None,
        system_prompt="",
        tools=["neo4j_client"],
        capabilities=["graph_infer"],
        enabled=True,
    ),

    AgentSpec(
        name="page_crawler",
        display_name="页面抓取Agent",
        description="使用Playwright抓取页面DOM，提取UI元素",
        agent_type="tool",
        module_path="app.agent.vision.page_crawler_agent",
        class_name="PageCrawlerAgent",
        model=None,
        system_prompt="",
        tools=["playwright_browser", "dom_extractor"],
        capabilities=["crawl"],
        enabled=True,
    ),

    AgentSpec(
        name="knowledge_update",
        display_name="知识更新Agent",
        description="执行后将结果更新到Milvus和Neo4j知识库",
        agent_type="tool",
        module_path="app.agent.requirement.knowledge_update_agent",
        class_name="KnowledgeUpdateAgent",
        model=None,
        system_prompt="",
        tools=["milvus_client", "neo4j_client", "embedding"],
        capabilities=["knowledge_update"],
        enabled=True,
    ),

    AgentSpec(
        name="storage_agent",
        display_name="存储Agent",
        description="脚本入库 + Milvus向量化 + Neo4j知识更新",
        agent_type="tool",
        module_path="app.agent.storage.storage_agent",
        class_name="StorageAgent",
        model=None,
        system_prompt="",
        tools=["milvus_client", "neo4j_client", "embedding", "mysql_client"],
        capabilities=["knowledge_update", "storage"],
        enabled=True,
    ),

    AgentSpec(
        name="feedback_agent",
        display_name="反馈Agent",
        description="收集用户对执行结果的反馈，用于改进脚本质量",
        agent_type="llm",
        module_path="app.agent.feedback.feedback_agent",
        class_name="FeedbackAgent",
        model=ModelConfig(provider="anthropic", model_name="claude-3-5-sonnet-20241022", temperature=0.5),
        system_prompt=(
            "你是一个质量评估专家。请分析用户反馈和执行结果，"
            "给出改进建议和脚本质量评分。"
        ),
        tools=[],
        capabilities=["feedback"],
        enabled=True,
    ),

    # ================================================================ #
    #  辅助 Agent                                                         #
    # ================================================================ #

    AgentSpec(
        name="embedding_agent",
        display_name="向量嵌入Agent",
        description="将文本转为向量嵌入，用于RAG检索",
        agent_type="tool",
        module_path="app.agent.rag.embedding_agent",
        class_name="EmbeddingAgent",
        model=ModelConfig(provider="dashscope", model_name="text-embedding-v3", temperature=0.0),
        system_prompt="",
        tools=["dashscope_embedding"],
        capabilities=["embedding"],
        enabled=True,
    ),

    AgentSpec(
        name="retrieval_agent",
        display_name="检索Agent",
        description="从Milvus向量数据库检索相似内容",
        agent_type="tool",
        module_path="app.agent.rag.retrieval_agent",
        class_name="RetrievalAgent",
        model=None,
        system_prompt="",
        tools=["milvus_client"],
        capabilities=["retrieval"],
        enabled=True,
    ),

    AgentSpec(
        name="script_reuse_agent",
        display_name="脚本复用Agent",
        description="检索历史脚本，判断是否可复用",
        agent_type="llm",
        module_path="app.agent.script.script_reuse_agent",
        class_name="ScriptReuseAgent",
        model=ModelConfig(provider="dashscope", model_name="qwen-plus", temperature=0.2),
        system_prompt="你是脚本复用分析专家。判断是否有历史脚本可以直接复用。",
        tools=["milvus_client"],
        capabilities=["script_reuse"],
        enabled=True,
    ),

    AgentSpec(
        name="relation_agent",
        display_name="关系分析Agent",
        description="分析页面间的关系（导航、数据流转）",
        agent_type="llm",
        module_path="app.agent.graph.relation_agent",
        class_name="RelationAgent",
        model=ModelConfig(provider="dashscope", model_name="qwen-plus", temperature=0.3),
        system_prompt="你是页面关系分析专家。分析页面间的导航路径和数据流转关系。",
        tools=["neo4j_client"],
        capabilities=["relation"],
        enabled=True,
    ),

    AgentSpec(
        name="flow_parser",
        display_name="流程解析Agent",
        description="解析业务流程，提取页面跳转路径",
        agent_type="llm",
        module_path="app.agent.requirement.flow_parser",
        class_name="FlowParser",
        model=ModelConfig(provider="dashscope", model_name="qwen-plus", temperature=0.3),
        system_prompt="你是业务流程分析专家。从需求中提取页面跳转路径和业务流程。",
        tools=[],
        capabilities=["flow_parse"],
        enabled=True,
    ),

    AgentSpec(
        name="flow_script_generator",
        display_name="跨页面脚本生成Agent",
        description="生成跨页面业务流程的Playwright脚本",
        agent_type="llm",
        module_path="app.agent.requirement.flow_script_generator",
        class_name="FlowScriptGenerator",
        model=ModelConfig(provider="dashscope", model_name="qwen-coder-plus", temperature=0.2, max_tokens=8192),
        system_prompt=(
            "你是跨页面自动化测试脚本专家。"
            "生成包含页面导航、数据传递、变量管理的Playwright脚本。"
        ),
        tools=["page_state_manager", "variable_context"],
        capabilities=["flow_script"],
        enabled=True,
    ),

    AgentSpec(
        name="strategy_agent",
        display_name="策略选择Agent",
        description="根据任务类型选择最佳脚本生成策略",
        agent_type="llm",
        module_path="app.agent.script.strategy_agent",
        class_name="StrategyAgent",
        model=ModelConfig(provider="deepseek", model_name="deepseek-chat", temperature=0.2),
        system_prompt="你是测试策略专家。根据任务特征选择最佳脚本生成策略。",
        tools=[],
        capabilities=["strategy"],
        enabled=True,
    ),

    AgentSpec(
        name="type_classifier",
        display_name="类型分类Agent",
        description="对测试任务进行类型分类",
        agent_type="llm",
        module_path="app.agent.requirement.type_classifier",
        class_name="TypeClassifier",
        model=ModelConfig(provider="deepseek", model_name="deepseek-chat", temperature=0.1),
        system_prompt="你是测试分类专家。对测试任务进行类型分类（UI/API/集成/性能）。",
        tools=[],
        capabilities=["classify"],
        enabled=True,
    ),

    AgentSpec(
        name="test_type_classifier",
        display_name="测试类型智能识别Agent",
        description="分析需求文本/图片/Swagger/数据库结构/页面信息，自动判断测试类型、平台、框架",
        agent_type="llm",
        module_path="app.agent.requirement.test_type_classifier_agent",
        class_name="TestTypeClassifierAgent",
        model=ModelConfig(provider="dashscope", model_name="qwen-plus", temperature=0.1),
        system_prompt=(
            "你是测试架构师。分析用户需求，判断最适合的自动化测试类型（WEB/API/ANDROID/PERFORMANCE），"
            "并映射对应的平台（browser/mobile/server）和框架（playwright/appium/pytest/jmeter）。"
        ),
        tools=["text_extract"],
        capabilities=["type_classify"],
        enabled=True,
    ),

    # === 需求输入路由 + 解析Agent ===
    AgentSpec(
        name="input_router_agent",
        display_name="需求输入路由Agent",
        description="根据输入类型(文本/图片/PDF/Word/视频/Swagger/Schema)路由到对应解析Agent，合并结果为RequirementContext",
        agent_type="router",
        module_path="app.agent.requirement.input_router_agent",
        class_name="InputRouterAgent",
        model=ModelConfig(provider="dashscope", model_name="qwen-plus", temperature=0.3),
        system_prompt="你是需求输入路由器。根据输入类型选择合适的解析Agent，合并所有解析结果为统一的RequirementContext。",
        tools=["text_extract"],
        capabilities=["input_route", "requirement_parse"],
        enabled=True,
    ),
    AgentSpec(
        name="pdf_parser_agent",
        display_name="PDF文档解析Agent",
        description="使用pdfplumber提取PDF文本和表格，LLM分析提取测试要点",
        agent_type="llm",
        module_path="app.agent.requirement.parsers.pdf_parser_agent",
        class_name="PDFParserAgent",
        model=ModelConfig(provider="dashscope", model_name="qwen-plus", temperature=0.3),
        system_prompt="你是PDF文档分析专家。从PDF中提取页面、元素、业务流程、测试点和约束条件。",
        tools=["text_extract"],
        capabilities=["pdf_parse", "requirement_parse"],
        enabled=True,
    ),
    AgentSpec(
        name="image_analyzer_agent",
        display_name="图片分析Agent",
        description="使用视觉模型分析UI截图，识别页面元素和交互流程",
        agent_type="llm",
        module_path="app.agent.requirement.parsers.image_analyzer_agent",
        class_name="ImageAnalyzerAgent",
        model=ModelConfig(provider="dashscope", model_name="qwen-vl-max", temperature=0.3),
        system_prompt="你是UI截图分析专家。识别页面类型、UI元素、交互动作，提取测试要点。",
        tools=["text_extract", "vision"],
        capabilities=["image_parse", "requirement_parse"],
        enabled=True,
    ),
    AgentSpec(
        name="video_analyzer_agent",
        display_name="视频分析Agent",
        description="提取视频关键帧，使用视觉模型分析操作流程",
        agent_type="llm",
        module_path="app.agent.requirement.parsers.video_analyzer_agent",
        class_name="VideoAnalyzerAgent",
        model=ModelConfig(provider="dashscope", model_name="qwen-vl-max", temperature=0.3),
        system_prompt="你是视频操作分析专家。从视频中提取关键帧，分析用户操作流程和测试要点。",
        tools=["text_extract", "vision"],
        capabilities=["video_parse", "requirement_parse"],
        enabled=True,
    ),
    AgentSpec(
        name="swagger_parser_agent",
        display_name="Swagger解析Agent",
        description="解析Swagger/OpenAPI文档，提取API端点、参数、响应结构",
        agent_type="llm",
        module_path="app.agent.requirement.parsers.swagger_parser_agent",
        class_name="SwaggerParserAgent",
        model=ModelConfig(provider="dashscope", model_name="qwen-plus", temperature=0.3),
        system_prompt="你是API文档分析专家。从Swagger/OpenAPI中提取接口信息，生成接口测试要点。",
        tools=["text_extract"],
        capabilities=["swagger_parse", "requirement_parse"],
        enabled=True,
    ),
    AgentSpec(
        name="database_schema_agent",
        display_name="数据库Schema解析Agent",
        description="解析SQL DDL，提取表结构、字段、主外键关系",
        agent_type="llm",
        module_path="app.agent.requirement.parsers.database_schema_agent",
        class_name="DatabaseSchemaAgent",
        model=ModelConfig(provider="dashscope", model_name="qwen-plus", temperature=0.3),
        system_prompt="你是数据库分析专家。从DDL中提取表结构、字段类型、约束关系，生成数据相关测试要点。",
        tools=["text_extract"],
        capabilities=["schema_parse", "requirement_parse"],
        enabled=True,
    ),

    AgentSpec(
        name="script_parser",
        display_name="脚本解析Agent",
        description="解析已有脚本，提取结构信息",
        agent_type="tool",
        module_path="app.agent.script.script_parser",
        class_name="ScriptParser",
        model=None,
        system_prompt="",
        tools=["ast_parser"],
        capabilities=["script_parse"],
        enabled=True,
    ),

    AgentSpec(
        name="script_validator",
        display_name="脚本验证Agent",
        description="验证生成脚本的语法和逻辑正确性",
        agent_type="llm",
        module_path="app.agent.script.script_validator",
        class_name="ScriptValidator",
        model=ModelConfig(provider="dashscope", model_name="qwen-coder-plus", temperature=0.1),
        system_prompt="你是代码审查专家。验证Playwright脚本的语法和逻辑正确性。",
        tools=["ast_parser", "lint"],
        capabilities=["script_validate"],
        enabled=True,
    ),

    AgentSpec(
        name="script_executor",
        display_name="脚本执行器Agent",
        description="直接执行脚本并返回结果",
        agent_type="tool",
        module_path="app.agent.script.script_executor",
        class_name="ScriptExecutor",
        model=None,
        system_prompt="",
        tools=["subprocess_runner"],
        capabilities=["script_execute"],
        enabled=True,
    ),

    AgentSpec(
        name="element_merge_agent",
        display_name="元素合并Agent",
        description="合并多来源的元素信息",
        agent_type="tool",
        module_path="app.agent.vision.element_merge_agent",
        class_name="ElementMergeAgent",
        model=None,
        system_prompt="",
        tools=[],
        capabilities=["merge"],
        enabled=True,
    ),

    AgentSpec(
        name="fusion_agent",
        display_name="融合Agent",
        description="融合多源数据",
        agent_type="tool",
        module_path="app.agent.requirement.fusion_agent",
        class_name="FusionAgent",
        model=None,
        system_prompt="",
        tools=[],
        capabilities=["fusion"],
        enabled=True,
    ),

    AgentSpec(
        name="scheduler_agent",
        display_name="定时调度Agent",
        description="管理定时执行任务",
        agent_type="tool",
        module_path="app.agent.scheduling.scheduler_agent",
        class_name="SchedulerAgent",
        model=None,
        system_prompt="",
        tools=["apscheduler"],
        capabilities=["schedule"],
        enabled=True,
    ),

    AgentSpec(
        name="task_executor",
        display_name="任务执行器Agent",
        description="执行调度任务",
        agent_type="tool",
        module_path="app.agent.scheduling.task_executor",
        class_name="TaskExecutor",
        model=None,
        system_prompt="",
        tools=["subprocess_runner"],
        capabilities=["execute"],
        enabled=True,
    ),

    AgentSpec(
        name="playwright_agent",
        display_name="Playwright Agent",
        description="Playwright浏览器操作Agent",
        agent_type="tool",
        module_path="app.agent.vision.playwright_agent",
        class_name="PlaywrightAgent",
        model=None,
        system_prompt="",
        tools=["playwright_browser"],
        capabilities=["playwright"],
        enabled=True,
    ),

    # ================================================================ #
    #  Case 子模块 Agent                                                  #
    # ================================================================ #

    AgentSpec(
        name="document_parser",
        display_name="文档解析Agent",
        description="解析PDF/Word/Excel/TXT/Markdown文档",
        agent_type="llm",
        module_path="app.agent.case.document_parser",
        class_name="DocumentParserAgent",
        model=ModelConfig(provider="deepseek", model_name="deepseek-chat", temperature=0.2),
        system_prompt="你是文档解析专家。从文档中提取测试相关信息。",
        tools=["pdf_reader", "docx_reader", "xlsx_reader"],
        capabilities=["document_parse"],
        enabled=True,
    ),

    AgentSpec(
        name="case_review",
        display_name="用例审查Agent",
        description="审查用例的完整性和可执行性",
        agent_type="llm",
        module_path="app.agent.case.review_agent",
        class_name="ReviewAgent",
        model=ModelConfig(provider="anthropic", model_name="claude-3-5-sonnet-20241022", temperature=0.3),
        system_prompt=(
            "你是测试用例审查专家。检查用例的完整性、可执行性、"
            "边界覆盖、异常覆盖。给出改进建议。"
        ),
        tools=[],
        capabilities=["review"],
        enabled=True,
    ),

    AgentSpec(
        name="mindmap_agent",
        display_name="脑图Agent",
        description="生成测试用例脑图",
        agent_type="llm",
        module_path="app.agent.case.mindmap_agent",
        class_name="MindMapAgent",
        model=ModelConfig(provider="dashscope", model_name="qwen-plus", temperature=0.5),
        system_prompt="你是脑图生成专家。将测试用例组织为脑图结构。",
        tools=[],
        capabilities=["mindmap"],
        enabled=True,
    ),

    AgentSpec(
        name="case_retriever",
        display_name="Case检索Agent",
        description="从向量数据库检索历史用例",
        agent_type="tool",
        module_path="app.agent.case.retriever_agent",
        class_name="RetrieverAgent",
        model=None,
        system_prompt="",
        tools=["milvus_client", "embedding"],
        capabilities=["retrieval"],
        enabled=True,
    ),

    # ================================================================ #
    #  Flow Agent（消息驱动业务流）                                        #
    #  继承 BaseRoutedAgent，使用 @message_handler 处理消息               #
    #  通过 publish_message() 发布下一步消息                              #
    # ================================================================ #

    AgentSpec(
        name="flow_requirement_agent",
        display_name="需求解析Agent(Flow)",
        description="接收RequirementMessage，解析需求，发布PageMessage",
        agent_type="llm",
        module_path="app.agents.flows.requirement_agent",
        class_name="RequirementAgent",
        model=ModelConfig(provider="dashscope", model_name="qwen-plus", temperature=0.3),
        system_prompt="你是需求分析专家。解析需求并提取测试意图、步骤、目标URL。",
        tools=[],
        capabilities=["requirement_parse", "flow"],
        enabled=True,
    ),

    AgentSpec(
        name="flow_image_agent",
        display_name="页面元素Agent(Flow)",
        description="接收PageMessage，分析页面元素，发布CaseMessage",
        agent_type="llm",
        module_path="app.agents.flows.image_agent",
        class_name="ImageAgent",
        model=ModelConfig(provider="dashscope", model_name="qwen-vl-max", temperature=0.5),
        system_prompt="你是页面元素分析专家。从页面URL提取UI元素和定位器。",
        tools=["image_load", "base64_encode"],
        capabilities=["vision", "flow"],
        enabled=True,
    ),

    AgentSpec(
        name="flow_case_agent",
        display_name="用例生成Agent(Flow)",
        description="接收CaseMessage，生成测试用例，发布ReviewMessage",
        agent_type="llm",
        module_path="app.agents.flows.case_agent",
        class_name="CaseAgent",
        model=ModelConfig(provider="deepseek", model_name="deepseek-chat", temperature=0.4),
        system_prompt="你是测试用例设计专家。根据页面元素生成结构化测试用例。",
        tools=[],
        capabilities=["case_generate", "flow"],
        enabled=True,
    ),

    AgentSpec(
        name="flow_review_agent",
        display_name="用例审查Agent(Flow)",
        description="接收ReviewMessage，审查用例，发布ScriptMessage",
        agent_type="llm",
        module_path="app.agents.flows.review_agent",
        class_name="ReviewAgent",
        model=ModelConfig(provider="anthropic", model_name="claude-3-5-sonnet-20241022", temperature=0.3),
        system_prompt="你是测试用例审查专家。检查用例完整性、可执行性，给出批准/拒绝。",
        tools=[],
        capabilities=["review", "flow"],
        enabled=True,
    ),

    AgentSpec(
        name="flow_script_agent",
        display_name="脚本生成Agent(Flow)",
        description="接收ScriptMessage，生成Playwright脚本，发布ExportMessage",
        agent_type="llm",
        module_path="app.agents.flows.script_agent",
        class_name="ScriptAgent",
        model=ModelConfig(provider="dashscope", model_name="qwen-coder-plus", temperature=0.2, max_tokens=8192),
        system_prompt="你是自动化脚本生成专家。根据审查通过的用例生成Playwright Python脚本。",
        tools=[],
        capabilities=["script_generate", "flow"],
        enabled=True,
    ),

    AgentSpec(
        name="flow_export_agent",
        display_name="结果导出Agent(Flow)",
        description="接收ExportMessage，保存最终结果，投递ResultMessage给CollectorAgent",
        agent_type="tool",
        module_path="app.agents.flows.export_agent",
        class_name="ExportAgent",
        model=None,
        system_prompt="",
        tools=["database"],
        capabilities=["export", "flow"],
        enabled=True,
    ),

    # ================================================================ #
    #  RAG 查询 Agent                                                     #
    #  所有 Agent 获取上下文的统一入口                                      #
    #  禁止其他 Agent 直接查数据库，统一调用 RAGQueryAgent                   #
    # ================================================================ #

    AgentSpec(
        name="rag_query_agent",
        display_name="RAG上下文查询Agent",
        description="统一上下文查询入口：关键词检索→向量检索→图谱扩展→重排序→返回TopK",
        agent_type="tool",
        module_path="app.agents.flows.rag_query_agent",
        class_name="RAGQueryAgent",
        model=None,
        system_prompt="",
        tools=["milvus_client", "neo4j_client", "embedding", "mysql_client"],
        capabilities=["rag_query", "context_retrieve"],
        enabled=True,
    ),

    # ================================================================ #
    #  测试资产中心 Agents                                                 #
    #  1. AssetSearchAgent       - 三源融合搜索已有资产                    #
    #  2. AssetReuseAgent        - LLM 判断资产可复用性                   #
    #  3. AssetOptimizationAgent - LLM 生成优化测试方案                   #
    #                                                                  #
    #  链式编排: Search → Reuse → Optimization                         #
    #  禁止 Agent 直接操作数据库, 统一通过 AssetSearchService          #
    # ================================================================ #

    AgentSpec(
        name="asset_search_agent",
        display_name="测试资产搜索Agent",
        description="三源融合搜索: MySQL关键词 + Milvus向量 + Neo4j关系, 返回TopK资产",
        agent_type="tool",
        module_path="app.agents.flows.asset_search_agent",
        class_name="AssetSearchAgent",
        model=None,
        system_prompt="",
        tools=["mysql_client", "milvus_client", "neo4j_client"],
        capabilities=["asset_search", "asset_retrieve"],
        enabled=True,
    ),

    AgentSpec(
        name="asset_reuse_agent",
        display_name="资产复用判断Agent",
        description="基于搜索结果用LLM评估资产复用性, 计算reuse_score, 输出复用决策",
        agent_type="llm",
        module_path="app.agents.flows.asset_reuse_agent",
        class_name="AssetReuseAgent",
        model=ModelConfig(
            provider="dashscope",
            model_name="qwen-plus",
            temperature=0.3,
            max_tokens=2048,
        ),
        system_prompt="",
        tools=[],
        capabilities=["asset_reuse", "asset_evaluate"],
        enabled=True,
    ),

    AgentSpec(
        name="asset_optimization_agent",
        display_name="资产优化Agent",
        description="基于复用决策用LLM生成优化测试方案: 复用清单+补充清单+执行顺序",
        agent_type="llm",
        module_path="app.agents.flows.asset_optimization_agent",
        class_name="AssetOptimizationAgent",
        model=ModelConfig(
            provider="dashscope",
            model_name="qwen-plus",
            temperature=0.4,
            max_tokens=4096,
        ),
        system_prompt="",
        tools=[],
        capabilities=["asset_optimization", "plan_generation"],
        enabled=True,
    ),

    # ================================================================ #
    #  PageKnowledgeAgent                                                 #
    #  页面知识Agent：截图→OCR→元素→关系→三库存储                      #
    #  CaseAgent 可直接查询「登录页面」返回所有元素，不需要再次OCR       #
    # ================================================================ #

    AgentSpec(
        name="page_knowledge_agent",
        display_name="页面知识Agent",
        description="截图→OCR→页面描述→元素→关系→MySQL+Milvus+Neo4j，支持按名称查询元素",
        agent_type="tool",
        module_path="app.agents.flows.page_knowledge_agent",
        class_name="PageKnowledgeAgent",
        model=None,
        system_prompt="",
        tools=["milvus_client", "neo4j_client", "embedding", "mysql_client"],
        capabilities=["page_ocr", "page_analysis", "page_query"],
        enabled=True,
    ),

    # ================================================================ #
    #  APIKnowledgeAgent                                                 #
    #  接口知识Agent：解析Swagger/Postman/JMeter/JSON→结构化→三库存储  #
    #  建立接口依赖关系，API Agent 可查询相关接口                       #
    # ================================================================ #

    AgentSpec(
        name="api_knowledge_agent",
        display_name="接口知识Agent",
        description="解析Swagger/OpenAPI/Postman/JMeter/JSON→接口→参数→Header→Body→Response→三库存储+依赖关系",
        agent_type="tool",
        module_path="app.agents.flows.api_knowledge_agent",
        class_name="APIKnowledgeAgent",
        model=None,
        system_prompt="",
        tools=["milvus_client", "neo4j_client", "embedding", "mysql_client"],
        capabilities=["api_parse", "api_query", "dependency_analysis"],
        enabled=True,
    ),

    # ================================================================ #
    #  Storage Agents - 数据库 Agent 化                                   #
    #  禁止 Service 直接写数据库，统一通过消息驱动                         #
    # ================================================================ #

    AgentSpec(
        name="mysql_storage_agent",
        display_name="MySQL存储Agent",
        description="统一处理MySQL写入/查询/删除/更新，禁止Service直接操作数据库",
        agent_type="tool",
        module_path="app.agents.flows.mysql_storage_agent",
        class_name="MysqlStorageAgent",
        model=None,
        system_prompt="",
        tools=["mysql_client"],
        capabilities=["mysql_save", "mysql_query", "mysql_delete", "mysql_update"],
        enabled=True,
    ),

    AgentSpec(
        name="vector_storage_agent",
        display_name="向量存储Agent",
        description="统一处理Milvus向量插入/搜索/删除，Milvus不可用时优雅降级",
        agent_type="tool",
        module_path="app.agents.flows.vector_storage_agent",
        class_name="VectorStorageAgent",
        model=None,
        system_prompt="",
        tools=["milvus_client", "embedding"],
        capabilities=["vector_insert", "vector_search", "vector_delete"],
        enabled=True,
    ),

    AgentSpec(
        name="graph_storage_agent",
        display_name="图谱存储Agent",
        description="统一处理Neo4j节点/关系/查询/删除/追溯，Neo4j不可用时优雅降级",
        agent_type="tool",
        module_path="app.agents.flows.graph_storage_agent",
        class_name="GraphStorageAgent",
        model=None,
        system_prompt="",
        tools=["neo4j_client"],
        capabilities=["graph_create", "graph_link", "graph_query", "graph_delete", "graph_trace"],
        enabled=True,
    ),

    # ================================================================ #
    #  完整工作流 Agent                                                    #
    #  补全 Requirement→PageSearch→RAG→Element→Case→Review→Script        #
    #  →Storage→Execution→Report→Defect→Export                          #
    # ================================================================ #

    AgentSpec(
        name="execution_flow_agent",
        display_name="脚本执行Agent(Flow)",
        description="消息驱动脚本执行Agent，使用PlaywrightTool执行测试脚本并收集结果",
        agent_type="tool",
        module_path="app.agents.flows.execution_flow_agent",
        class_name="ExecutionFlowAgent",
        model=None,
        system_prompt="",
        tools=["playwright"],
        capabilities=["script_execute", "playwright"],
        enabled=True,
    ),

    AgentSpec(
        name="report_agent",
        display_name="测试报告Agent",
        description="汇总执行结果，生成HTML/JSON测试报告并保存，发送StorageMessage",
        agent_type="tool",
        module_path="app.agents.flows.report_agent",
        class_name="ReportAgent",
        model=None,
        system_prompt="",
        tools=["db_save"],
        capabilities=["report_generate", "report_export"],
        enabled=True,
    ),

    AgentSpec(
        name="defect_agent",
        display_name="缺陷管理Agent",
        description="分析失败用例，提取缺陷信息（错误类型/堆栈/截图）并保存",
        agent_type="tool",
        module_path="app.agents.flows.defect_agent",
        class_name="DefectAgent",
        model=None,
        system_prompt="",
        tools=["db_save"],
        capabilities=["defect_analysis", "defect_create", "defect_export"],
        enabled=True,
    ),

    AgentSpec(
        name="quality_analysis_agent",
        display_name="质量分析Agent",
        description="基于LLM分析测试资产/执行记录/缺陷数据, 生成覆盖/风险/重复/缺陷趋势四维度质量报告",
        agent_type="llm",
        module_path="app.agents.flows.quality_analysis_agent",
        class_name="QualityAnalysisAgent",
        model=ModelConfig(
            provider="dashscope",
            model_name="qwen-plus",
            temperature=0.3,
            max_tokens=2048,
        ),
        system_prompt="",
        tools=[],
        capabilities=["quality_analysis", "coverage_analysis", "risk_analysis",
                      "duplication_analysis", "defect_trend_analysis"],
        enabled=True,
    ),

    AgentSpec(
        name="feedback_learning_agent",
        display_name="反馈学习Agent",
        description="收集成功/失败/人工修改案例, 通过LLM分析生成RAG/Prompt/策略优化建议",
        agent_type="llm",
        module_path="app.agents.flows.feedback_learning_agent",
        class_name="FeedbackLearningAgent",
        model=ModelConfig(
            provider="dashscope",
            model_name="qwen-plus",
            temperature=0.3,
            max_tokens=2048,
        ),
        system_prompt="",
        tools=[],
        capabilities=["feedback_learning", "case_collection",
                      "rag_optimization", "prompt_optimization", "strategy_optimization"],
        enabled=True,
    ),

    # ================================================================ #
    #  Testcase Agents - 测试用例生成流程                                #
    # ================================================================ #

    AgentSpec(
        name="requirement_analysis_agent",
        display_name="需求解析Agent(V2)",
        description="解析测试需求，提取测试场景和条件",
        agent_type="llm",
        module_path="app.agent.testcase.requirement_analysis_agent",
        class_name="RequirementAnalysisAgent",
        model=ModelConfig(provider="dashscope", model_name="qwen-plus", temperature=0.3),
        system_prompt="你是测试需求分析专家。解析需求文档，提取测试场景、前置条件、测试数据。",
        tools=[],
        capabilities=["requirement_parse"],
        enabled=True,
    ),

    AgentSpec(
        name="test_point_analysis_agent",
        display_name="测试点分析Agent",
        description="分析需求，生成测试点",
        agent_type="llm",
        module_path="app.agent.testcase.test_point_analysis_agent",
        class_name="TestPointAnalysisAgent",
        model=ModelConfig(provider="dashscope", model_name="qwen-plus", temperature=0.4),
        system_prompt="你是测试点分析专家。根据需求分析结果，生成覆盖全面的测试点。",
        tools=[],
        capabilities=["case_generate"],
        enabled=True,
    ),

    AgentSpec(
        name="testcase_generator_agent",
        display_name="用例生成Agent(V3)",
        description="根据测试点生成结构化测试用例",
        agent_type="llm",
        module_path="app.agent.testcase.testcase_generator_agent",
        class_name="TestCaseGeneratorAgent",
        model=ModelConfig(provider="dashscope", model_name="qwen-plus", temperature=0.5),
        system_prompt="你是测试用例设计专家。根据测试点和RAG上下文，生成结构化的测试用例。",
        tools=["rag_retrieve"],
        capabilities=["case_generate", "rag_retrieve"],
        enabled=True,
    ),

    AgentSpec(
        name="testcase_review_agent",
        display_name="用例审核Agent(V2)",
        description="审核生成的测试用例，确保质量和覆盖率",
        agent_type="llm",
        module_path="app.agent.testcase.testcase_review_agent",
        class_name="TestCaseReviewAgent",
        model=ModelConfig(provider="dashscope", model_name="qwen-plus", temperature=0.2),
        system_prompt="你是测试用例审查专家。检查用例的完整性、正确性、可执行性和覆盖率。",
        tools=[],
        capabilities=["feedback"],
        enabled=True,
    ),

    AgentSpec(
        name="knowledge_sync_agent",
        display_name="数据同步Agent",
        description="将生成的测试用例同步到知识库",
        agent_type="tool",
        module_path="app.agent.testcase.knowledge_sync_agent",
        class_name="KnowledgeSyncAgent",
        model=None,
        system_prompt="",
        tools=["database"],
        capabilities=["knowledge_update"],
        enabled=True,
    ),

    # ================================================================ #
    #  接口自动化测试数据生成 Agent                                       #
    #  ApiDataGeneratorAgent - 四源融合 (LLM+Faker+规则+模板)           #
    #  支持 normal/abnormal/boundary/dependent 四类数据                  #
    # ================================================================ #

    AgentSpec(
        name="api_data_generator_agent",
        display_name="接口测试数据生成Agent",
        description="根据接口Schema+依赖关系智能生成4类测试数据(正常/异常/边界/关联),融合LLM+Faker+规则+模板",
        agent_type="llm",
        module_path="app.agents.flows.api_data_generator_agent",
        class_name="ApiDataGeneratorAgent",
        model=ModelConfig(
            provider="dashscope",
            model_name="qwen-plus",
            temperature=0.3,
            max_tokens=4096,
        ),
        system_prompt=(
            "你是接口测试数据生成专家。根据字段Schema生成满足约束的测试数据。"
            "优先使用规则和Faker,仅当字段语义复杂时调用LLM。"
        ),
        tools=["faker", "schema_parser", "mysql_client"],
        capabilities=["data_generation", "schema_analysis", "test_data"],
        enabled=True,
    ),

    # ================================================================ #
    #  AI 接口调试 Agent                                                  #
    # ================================================================ #
    AgentSpec(
        name="api_debug_agent",
        display_name="接口调试分析Agent",
        description="分析 HTTP 接口执行结果,输出问题原因/解决方案/修复建议,支持 LLM + 规则引擎双模式",
        agent_type="llm",
        module_path="app.agents.flows.api_debug_agent",
        class_name="ApiDebugAgent",
        model=ModelConfig(provider="dashscope", model_name="qwen-plus", temperature=0.3, max_tokens=2048),
        system_prompt=(
            "你是接口测试调试专家。根据 HTTP 接口执行结果,分析失败原因并给出修复建议。"
            "输出 JSON 格式,包含 problem_cause/solution/fix_suggestion/confidence/category。"
        ),
        tools=["http_analyzer", "rule_engine", "mysql_client"],
        capabilities=["debug", "failure_analysis", "llm_reasoning"],
        enabled=True,
    ),

    # ================================================================ #
    #  性能测试 Agent (domains/performance)                              #
    # ================================================================ #

    AgentSpec(
        name="performance_plan_agent",
        display_name="性能方案Agent",
        description="根据接口信息和业务量生成性能测试方案 (并发/持续时间/TPS目标/预热)",
        agent_type="llm",
        module_path="app.domains.performance.agents",
        class_name="PerformancePlanAgent",
        model=ModelConfig(provider="dashscope", model_name="qwen-plus", temperature=0.3, max_tokens=2048),
        system_prompt="",
        tools=[],
        capabilities=["performance_planning", "concurrency_estimation"],
        enabled=True,
    ),

    AgentSpec(
        name="performance_script_agent",
        display_name="性能脚本Agent",
        description="根据测试方案生成 Locust Python 脚本或 JMeter XML 配置",
        agent_type="llm",
        module_path="app.domains.performance.agents",
        class_name="PerformanceScriptAgent",
        model=ModelConfig(provider="dashscope", model_name="qwen-coder-plus", temperature=0.2, max_tokens=4096),
        system_prompt="",
        tools=[],
        capabilities=["script_generation", "locust", "jmeter"],
        enabled=True,
    ),

    AgentSpec(
        name="performance_analysis_agent",
        display_name="性能分析Agent",
        description="基于实时指标(TPS/RT/CPU/Memory) + LLM 分析性能瓶颈,不使用RAG",
        agent_type="llm",
        module_path="app.domains.performance.agents",
        class_name="PerformanceAnalysisAgent",
        model=ModelConfig(provider="dashscope", model_name="qwen-plus", temperature=0.3, max_tokens=4096),
        system_prompt="",
        tools=[],
        capabilities=["performance_analysis", "bottleneck_detection"],
        enabled=True,
    ),

    AgentSpec(
        name="performance_diagnostic_agent",
        display_name="性能诊断Agent",
        description="解析jstack/日志/监控数据, 定位线程阻塞/死锁/CPU热点等性能问题根因",
        agent_type="llm",
        module_path="app.domains.performance.agents",
        class_name="PerformanceDiagnosticAgent",
        model=ModelConfig(provider="dashscope", model_name="qwen-plus", temperature=0.3, max_tokens=4096),
        system_prompt="",
        tools=[],
        capabilities=["performance_diagnosis", "jstack_analysis", "deadlock_detection",
                     "thread_analysis", "cpu_hotspot", "log_analysis"],
        enabled=True,
    ),

    # ================================================================ #
    #  代码执行 Agent (domains/code)                                     #
    # ================================================================ #

    AgentSpec(
        name="code_agent",
        display_name="代码执行Agent",
        description="LLM生成代码并安全执行 (分析Excel/处理测试数据/生成统计结果), 代码在Docker沙箱中隔离执行",
        agent_type="llm",
        module_path="app.domains.code.agent",
        class_name="CodeAgent",
        model=ModelConfig(provider="dashscope", model_name="qwen-coder-plus", temperature=0.2, max_tokens=4096),
        system_prompt="",
        tools=["sandbox_executor", "security_checker"],
        capabilities=["code_generation", "code_execution", "data_analysis",
                     "excel_analysis", "data_processing", "statistics"],
        enabled=True,
    ),
]
