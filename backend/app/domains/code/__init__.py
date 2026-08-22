"""
代码执行域模块 (domains/code)

CodeAgent: LLM 生成代码 → 安全检查 → Sandbox 执行 → 返回结果

支持的任务类型:
  - 分析 Excel 数据
  - 处理测试数据 (清洗 / 转换 / 格式化)
  - 生成统计结果 (描述统计 / 频率分析 / 分组聚合)
  - 数据可视化 (matplotlib 图表)
  - 通用 Python 计算

架构:
  agent.py — CodeAgent (LLM 代码生成 + 安全检查 + 沙箱执行)
"""
