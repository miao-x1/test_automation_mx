# PyCharm 本地调试环境配置指南

## 目标

在 PyCharm 中运行前后端代码（支持断点调试），数据库服务在 Docker 中运行。

## 架构

```
┌─────────────────────────────────────────────────┐
│  你的电脑                                         │
│                                                   │
│  ┌──────────┐    ┌──────────┐    ┌────────────┐  │
│  │ PyCharm  │    │  Vite    │    │  Docker    │  │
│  │ 后端     │    │ 前端     │    │  数据库     │  │
│  │ :8000    │    │ :3000    │    │            │  │
│  └────┬─────┘    └────┬─────┘    └──────┬─────┘  │
│       │               │                  │        │
│       │ localhost     │ localhost        │        │
│       └───────────────┴──────────────────┘        │
│                       │                           │
│              前端 /api/* → localhost:8000           │
└─────────────────────────────────────────────────┘
```

## 第一步：启动 Docker 数据库

```powershell
# 方式一：使用一键脚本
.\dev-start.ps1 -DockerOnly

# 方式二：手动启动
docker compose -f docker-compose.dev.yml up -d
```

> **重要**：使用 `docker-compose.dev.yml`（仅数据库），不要使用 `docker-compose.yml`（包含前后端容器，会占用 8000/80 端口）。

验证数据库就绪：
```powershell
docker compose -f docker-compose.dev.yml ps
# 所有容器应显示 "healthy"
```

## 第二步：在 PyCharm 中运行后端

1. 打开 PyCharm，加载项目根目录
2. 运行配置已预置：选择 **"Backend (FastAPI)"** 运行配置
3. 点击 Debug（虫子图标）启动调试模式

或手动创建运行配置：
- **Script**: `backend/app/main.py`
- **Working directory**: `backend/`
- **Environment variables**: `UVICORN_RELOAD=false`（关闭 reload，否则断点失效）

> 后端启动后访问 http://localhost:8000/docs 查看 API 文档

## 第三步：启动前端

```powershell
cd frontend
npm install   # 首次运行需要安装依赖
npm run dev   # 启动 Vite 开发服务器
```

> 前端启动后访问 http://localhost:3000

## 停止服务

```powershell
# 停止所有
.\dev-start.ps1 -Stop

# 或手动停止
docker compose -f docker-compose.dev.yml down
```

---

## 已修复的问题

### 1. 端口冲突（核心问题）

**问题**：`docker-compose.yml` 包含 backend（:8000）和 frontend（:80）容器。运行 `docker compose up -d` 会启动所有服务，导致 PyCharm 无法绑定 8000 端口。

**修复**：创建 `docker-compose.dev.yml`，仅包含 MySQL/Redis/Milvus/Neo4j 数据库服务。

### 2. SSE 端点数据库连接泄漏

**问题**：3 个 SSE 端点使用 `Depends(get_db)`，数据库连接在整个 SSE 流期间不释放。打开 2-3 个带 SSE 的功能后，连接池（30 个连接）耗尽，后续所有 API 请求超时，前端显示"页面加载失败"。

涉及文件：
- `backend/app/api/execution.py` — `execution_stream`
- `backend/app/api/page.py` — `run_crawl`
- `backend/app/api/task.py` — `analyze_task`

**修复**：改为手动 `SessionLocal()`，校验完成后立即 `db.close()`，再返回 SSE 流。

### 3. uvicorn reload 导致断点失效

**问题**：`main.py` 中 `reload=True`，uvicorn 会启动子进程运行实际服务，PyCharm 断点无法附加到子进程。

**修复**：改为通过环境变量 `UVICORN_RELOAD` 控制，默认 `false`（关闭 reload 以支持断点调试）。

### 4. RouteErrorBoundary 不自动复位

**问题**：前端所有业务路由共用一个 `RouteErrorBoundary`。某个页面因 API 错误抛出异常后，边界进入 `hasError=true` 状态，切换到其他路由时不会自动恢复，导致**所有后续页面都显示"页面加载失败"**。

**修复**：在 `componentDidUpdate` 中检测 `children` 变化（路由切换），自动复位错误状态。

### 5. ProfilePage 部分可选链崩溃

**问题**：`stats?.tasks.total` 中 `?.` 只保护了 `stats`，未保护 `.tasks`。当后端返回不完整数据时，`.total` 访问会抛出 TypeError。

**修复**：改为 `stats?.tasks?.total`。

---

## 环境配置说明

### backend/.env（PyCharm 读取）

| 配置项 | 值 | 说明 |
|--------|------|------|
| USE_SQLITE | False | 使用 MySQL（Docker） |
| DB_HOST | localhost | Docker 端口映射 |
| DB_PORT | 3307 | Docker MySQL 映射端口 |
| REDIS_HOST | localhost | Docker 端口映射 |
| REDIS_PORT | 6379 | Docker Redis 映射端口 |
| MILVUS_HOST | localhost | Docker 端口映射 |
| MILVUS_PORT | 19530 | Docker Milvus 映射端口 |
| NEO4J_URI | bolt://localhost:7687 | Docker 端口映射 |
| REDIS_ENABLED | True | 启用 Redis 执行队列 |
| MILVUS_STANDALONE | true | 使用 Docker Milvus |

### 端口清单

| 服务 | 端口 | 运行位置 |
|------|------|---------|
| 后端 API | 8000 | PyCharm |
| 前端 Dev | 3000 | Vite |
| MySQL | 3307 | Docker |
| Redis | 6379 | Docker |
| Milvus | 19530 | Docker |
| Neo4j HTTP | 7474 | Docker |
| Neo4j Bolt | 7687 | Docker |

### 前端 API 代理

Vite 配置（`frontend/vite.config.ts`）将 `/api/*` 请求代理到 `http://localhost:8000`，并去掉 `/api` 前缀。

---

## 常见问题

### Q: 后端启动报错 "Can't connect to MySQL server"

A: Docker 数据库未启动。运行 `docker compose -f docker-compose.dev.yml up -d`。

### Q: 断点不生效

A: 确保运行配置中 `UVICORN_RELOAD=false`，且使用 Debug 模式（非 Run）启动。

### Q: 前端页面白屏/加载失败

A: 检查后端是否在 8000 端口运行。打开浏览器控制台查看具体错误。修复后的 RouteErrorBoundary 会在切换路由时自动恢复。

### Q: 某些功能超时

A: R2R 知识服务（localhost:7272）未在 Docker 中运行。如需使用知识库功能，需单独启动 R2R 服务，或将 `backend/.env` 中 `KNOWLEDGE_PROVIDER` 改为 `local`。
