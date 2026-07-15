"""
需求解析Agent模块

InputRouterAgent 根据输入类型路由到对应的解析Agent：
- PDFParserAgent: PDF文档解析
- ImageAnalyzerAgent: 图片/UI截图分析
- VideoAnalyzerAgent: 视频需求分析
- SwaggerParserAgent: Swagger/OpenAPI文档解析
- DatabaseSchemaAgent: 数据库Schema解析

所有Agent输出统一的 RequirementContext 格式。
"""
