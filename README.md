test_automation_mx

AI-driven UI Automation Testing Platform

技术栈:
FastAPI
React + TypeScript
Playwright
RAG
Milvus
Neo4j
AutoGen
MySQL

功能:
- AI需求分析
- UI元素识别
- 自动生成测试用例
- 自动生成Playwright脚本
- 自动执行测试
- 测试报告生成
> 需求 → AI生成用例 → 执行 → 报告，全流程闭环

---

## 快速开始

### 环境要求

- Python 3.11+ / Node.js 18+ / MySQL 8.0+

### 启动

```bash
# 后端
cd backend
pip install -r requirements.txt
copy .env.example .env
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 前端
cd frontend
npm install && npm run dev
```

访问：http://localhost:5173 | API文档：http://localhost:8000/docs

---

## 架构

```
┌──────────────────────────────────────────────┐
│  Frontend  React 18 + Ant Design 5 + TS      │
└──────────────────┬───────────────────────────┘
                   │ HTTP / SSE
┌──────────────────▼───────────────────────────┐
│  Backend  FastAPI + Uvicorn                   │
│  ┌─ Workflow ─────────────────────────────┐  │
│  │ Requirement → Generation → Publish     │  │
│  │ → Execution                             │  │
│  └─────────────────────────────────────────┘  │
│  ┌─ Generation ───────────────────────────┐  │
│  │ ReqAgent │ RagAgent │ CaseAgent        │  │
│  │ ReviewAgent │ MindmapAgent             │  │
│  └─────────────────────────────────────────┘  │
│  ┌─ Execution ────────────────────────────┐  │
│  │ Dispatcher → Queue → Runner → Report   │  │
│  └─────────────────────────────────────────┘  │
└──────────────────┬───────────────────────────┘
        ┌──────────┼──────────┐
        ▼          ▼          ▼
   ┌────────┐ ┌────────┐ ┌────────┐
   │ MySQL  │ │ Milvus │ │ Neo4j  │
   └────────┘ └────────┘ └────────┘
```

---

## 目录

```
backend/app/
├── api/                 # 路由层
├── services/            # 业务编排
│   ├── workflow/        # 工作流引擎
│   ├── generation/      # 生成Agent
│   ├── execution/       # 执行引擎
│   └── knowledge/       # RAG客户端
├── agent/               # AI推理层
├── models/              # 数据模型
└── db/                  # 数据库连接

frontend/src/
├── pages/               # 页面组件
├── stores/              # zustand状态管理
├── services/            # API调用
└── components/          # 公共组件
```

---

## 开发规范

- **Case First**：用例必须完整可执行，套件只是可选组合
- **Agent禁止**：禁止直接操作数据库/HTTP/文件，统一输入GenerationContext，输出DTO
- **信息架构**：用户视角术语优先（测试用例非测试资产，测试设计非创建测试）
- **状态管理**：zustand + persist，页面切换不丢数据
- **页面行为**：禁止页面跳页面，用Drawer/Modal/SidePanel
