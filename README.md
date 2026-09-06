# AI 测试平台

用自然语言、页面 URL 和截图，直接跑真实的浏览器自动化测试。

打开平台后先进入工作空间，选好团队和项目。之后在创建测试页填写任务名称和测试要求，可附上 URL、截图或文档，点「开始智能测试」。系统会分析页面、识别元素、生成步骤和定位器，再用 Playwright 在真实浏览器里执行，过程通过 SSE 回传，结果写回当前项目。

顶栏的「当前项目」决定新任务记到哪里，任务列表、执行记录和报告也只看这个项目。个人中心、账号和 AI 配置都在左侧栏，换页时侧栏保持不变。

核心链路：

```
URL + 截图 + 测试要求
  → 分析页面 / 识别元素
  → 生成步骤和定位器
  → Playwright 执行
  → 校验 + SSE + 真实结果
```

---

## 快速开始

### 方式一：Docker 一键启动（推荐）

**前置条件**：Docker Desktop 已安装并运行

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env，至少修改 QWEN_API_KEY 和 SECRET_KEY

# 2. 构建并启动全部服务（首次约 10-15 分钟）
docker compose up -d --build

# 3. 查看状态（等待全部 healthy）
docker compose ps

# 4. 查看后端日志
docker logs test_auto_backend -f
```

启动完成后访问：

| 服务 | 地址 |
|------|------|
| 前端界面 | http://localhost |
| 后端 API 文档 | http://localhost:8000/docs |
| Neo4j 浏览器 | http://localhost:7474 |

> 数据库迁移由 `entrypoint.sh` 自动执行，无需手动运行 Alembic。

### 方式二：本地开发

**环境要求**：Python 3.11+ / Node.js 18+ / MySQL 8.0+ / Redis 7+

```bash
# 后端
cd backend
python -m venv venv
source venv/bin/activate    # Windows: .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
cp .env.example .env        # 编辑 .env，设置 DB_HOST=localhost 等
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 前端
cd frontend
npm install && npm run dev
```

开发模式访问：http://localhost:3000（前端 dev server）

---

## 架构

```
┌──────────────────────────────────────────────────┐
│  Frontend  React 18 + Ant Design 5 + TypeScript   │
│  Nginx:80  静态托管 + /api/* 反向代理             │
└──────────────────┬───────────────────────────────┘
                   │ HTTP / SSE
┌──────────────────▼───────────────────────────────┐
│  Backend  FastAPI + Uvicorn :8000                 │
│  ┌─ Workflow ─────────────────────────────────┐   │
│  │ Requirement → Generation → Execution       │   │
│  └─────────────────────────────────────────────┘   │
│  ┌─ 35 Agents ────────────────────────────────┐   │
│  │ 需求理解 / 用例生成 / 脚本生成 / 执行 / RAG  │   │
│  │ 知识图谱 / 页面爬取 / 视觉分析 / 定时调度    │   │
│  └─────────────────────────────────────────────┘   │
│  ┌─ MCP Server ───────────────────────────────┐   │
│  │ 4 个工具: 生成用例 / 生成脚本 / 分析页面 / 执行  │   │
│  └─────────────────────────────────────────────┘   │
└──────────────────┬───────────────────────────────┘
        ┌──────────┼──────────┬──────────┐
        ▼          ▼          ▼          ▼
   ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
   │ MySQL  │ │ Redis  │ │ Milvus │ │ Neo4j  │
   │ :3307  │ │ :6379  │ │ :19530 │ │ :7687  │
   │ 62 表  │ │ 队列   │ │ 向量   │ │ 图谱   │
   └────────┘ └────────┘ └────────┘ └────────┘
```

### Docker 容器架构

| 容器 | 镜像 | 端口 | 用途 |
|------|------|------|------|
| `test_auto_frontend` | Nginx Alpine | 80 → 80 | React 静态托管 + API 反代 |
| `test_auto_backend` | Python 3.11-slim | 8000 → 8000 | FastAPI + Playwright + 35 Agents |
| `test_auto_mysql` | MySQL 8.0 | 3307 → 3306 | 主数据库（62 张表） |
| `test_auto_redis` | Redis 7 Alpine | 6379 → 6379 | 执行队列 + 缓存 |
| `test_auto_milvus` | Milvus v2.4.4 | 19530 → 19530 | 向量检索 |
| `test_auto_neo4j` | Neo4j 5.20 | 7474 / 7687 | 知识图谱 |
| `test_auto_minio` | MinIO | 9000 | Milvus 对象存储 |
| `milvus-etcd` | etcd 3.5 | 2379 | Milvus 元数据 |

---

## 目录结构

```
backend/
├── app/
│   ├── api/                 # 路由层（30+ 控制器）
│   ├── agent/               # AI Agent 层（35 个 Agent）
│   │   ├── case/            #   用例生成
│   │   ├── execution/       #   执行引擎
│   │   ├── rag/              #   RAG 检索
│   │   ├── requirement/     #   需求解析
│   │   ├── script/          #   脚本生成
│   │   ├── vision/          #   视觉/页面爬取
│   │   └── scheduling/      #   定时调度
│   ├── agents/factory/      # Agent 注册中心（YAML 配置驱动）
│   ├── core/                # 配置、认证、LLM 客户端
│   ├── db/                  # 数据库连接（MySQL/Milvus/Neo4j）
│   ├── mcp/                 # MCP Server（4 个工具）
│   ├── models/              # SQLAlchemy 数据模型
│   ├── prompts/             # AI Prompt 模板
│   ├── rag/                 # RAG 管线（分块/嵌入/检索/重排）
│   ├── runtime/             # Agent 运行时
│   ├── services/            # 业务编排
│   └── tools/               # 工具集（Playwright/DB/Swagger）
├── alembic/                 # 数据库迁移（22 个版本）
├── Dockerfile
├── entrypoint.sh            # 启动脚本（等 MySQL → 建库 → 迁移 → 启动）
├── requirements.txt
└── requirements-docker.txt  # Docker 额外依赖

frontend/
├── src/
│   ├── components/          # 公共组件
│   ├── pages/               # 页面
│   ├── stores/              # Zustand 状态管理
│   └── services/            # API 调用
├── Dockerfile
├── nginx.conf               # Nginx 配置（反代 + SPA）
└── package.json

docker-compose.yml            # 8 容器编排
.env                          # 环境变量
```

---

## 常用运维命令

```bash
# 启动全部
docker compose up -d

# 构建并启动（代码变更后）
docker compose up -d --build

# 只重建后端（改了后端代码）
docker compose up -d --build backend

# 只重建前端（改了前端代码）
docker compose up -d --build frontend

# 环境变量变更后强制重建
docker compose up -d --force-recreate

# 查看状态
docker compose ps

# 查看日志
docker logs test_auto_backend -f
docker logs test_auto_frontend -f

# 停止全部（保留数据）
docker compose down

# 停止并删除数据（彻底重置）
docker compose down -v

# 进入容器
docker exec -it test_auto_backend bash
docker exec -it test_auto_mysql mysql -u root -p

# 备份 MySQL
docker exec test_auto_mysql mysqldump -u root -p test_automation > backup.sql

# 重置数据库
docker exec test_auto_mysql mysql -u root -p -e "DROP DATABASE IF EXISTS test_automation; CREATE DATABASE test_automation CHARACTER SET utf8mb4;"
docker restart test_auto_backend
```

---

## 开发规范

- **Case First**：用例必须完整可执行，套件只是可选组合
- **Agent 禁止**：禁止直接操作数据库 / HTTP / 文件，统一输入 GenerationContext，输出 DTO
- **信息架构**：用户视角术语优先（测试用例非测试资产，测试设计非创建测试）
- **状态管理**：Zustand + persist，页面切换不丢数据
- **页面行为**：禁止页面跳页面，用 Drawer / Modal / SidePanel

---

## 技术栈

| 层 | 技术 |
|----|------|
| 前端 | React 18 + TypeScript + Ant Design 5 + Zustand + Vite |
| 后端 | Python 3.11 + FastAPI + Uvicorn + SQLAlchemy 2.0 + Alembic |
| AI | DashScope（通义千问）+ MCP Protocol + AutoGen |
| 数据库 | MySQL 8.0 + Milvus 2.4 + Neo4j 5 + Redis 7 |
| 测试 | Playwright（Chromium）|
| 部署 | Docker + Docker Compose + Nginx |
