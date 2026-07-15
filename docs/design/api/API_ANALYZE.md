# 接口测试升级

## 新增页面
ApiAnalyzePage — 路由 /api-test/analyze

## 功能
- 输入会话ID加载API分析结果
- 表格展示: 接口名、方法、路径、优先级、依赖
- 详情Drawer: 请求头、请求体Schema、响应体Schema
- 确认并生成用例

## 数据源
GET /workflow/result?session_id={id}&agent=APIExtraction

## 支持人工修正
- 查看提取结果
- 确认后触发生成
