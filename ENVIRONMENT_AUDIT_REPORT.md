# 🔍 UI Automation 环境配置审计报告

**审计日期**: 2026-08-09  
**审计范围**: 全部环境配置文件、Docker 服务连接、配置读取链路、第三方服务、启动流程

---

## 一、当前环境架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                    宿主机 (Windows 11)                            │
│                                                                  │
│  ┌──────────────────────┐  ┌──────────────────────────────────┐ │
│  │  React Dev Server    │  │  PyCharm → FastAPI :8000          │ │
│  │  Vite :3000          │  │  CWD=backend/                     │ │
│  │  proxy: /api→:8000   │  │  读取 backend/.env                │ │
│  └──────────────────────┘  │  pydantic-settings env_file=.env  │ │
│                             │  ⚠ 无 load_dotenv() 调用          │ │
│                             └────────────┬─────────────────────┘ │
│                                          │ localhost:xxxx         │
│  ┌───────────────────────────────────────┼──────────────────────┐ │
│  │          Docker Desktop               │                      │ │
│  │                                       │                      │ │
│  │  ┌──────────┐  ┌──────────┐  ┌───────┴──────┐               │ │
│  │  │ MySQL 8  │  │ Redis 7  │  │  Milvus 2.4  │               │ │
│  │  │ :3307→3306│ │ :6379    │  │  :19530      │               │ │
│  │  └──────────┘  └──────────┘  └──────┬───────┘               │ │
│  │                                      │依赖                    │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────┴───────┐               │ │
│  │  │ Neo4j 5  │  │ MinIO    │  │    etcd      │               │ │
│  │  │ :7687    │  │ :9000    │  │   :2379      │               │ │
│  │  │ :7474    │  │ :9001    │  │  (内部)       │               │ │
│  │  └──────────┘  └──────────┘  └──────────────┘               │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  图例: → 端口映射 (宿主机:容器)                                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、.env 文件全景

| 文件 | 用途 | 目标运行模式 | 关键特征 |
|------|------|------------|---------|
| `/.env` | docker-compose | Docker 全容器 | `DB_HOST=mysql`, `REDIS_HOST=redis`, `MILVUS_HOST=milvus` |
| `/backend/.env` | PyCharm 本地开发 | FastAPI 裸机 + Docker 中间件 | `DB_HOST=localhost:3307`, `REDIS_HOST=localhost`, `REDIS_ENABLED=False` |
| `/.env.example` | Docker 模板 | Docker | 含详细注释说明两种模式 |
| `/backend/.env.example` | 本地开发模板 | PyCharm | `REDIS_ENABLED=True` (与 backend/.env 不同!) |
| `/deploy/docker/.env.production` | 生产部署 | K8s/Docker Prod | 独立的生产配置 |

---

## 三、问题列表

### 🔴 严重 (P0) — 会导致功能异常

#### 问题 1: `load_dotenv()` 全局缺失 — os.getenv 读不到 .env 文件值

- **位置**: 整个 backend 代码库
- **详情**: `python-dotenv` 已在 `requirements.txt` 中声明，但**整个 backend 没有任何文件调用 `load_dotenv()`**。pydantic-settings 加载 `.env` 后，值仅存在于 `Settings` 实例中，**不会写入 `os.environ`**。
- **影响范围**（共 14+ 处通过 `os.getenv`/`os.environ` 读取配置的代码）:

  | 文件 | 读取的变量 | 本地模式行为 |
  |------|----------|------------|
  | `alembic/env.py:26-30` | `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` | **全部回退到默认值** → alembic 迁移失败 |
  | `app/db/milvus_client.py:152` | `MILVUS_STANDALONE` | 永远为 `None`（见问题 2） |
  | `app/agents/factory/config.py:59` | `DASHSCOPE_API_KEY`, `DEEPSEEK_API_KEY` 等 | 返回空字符串 → Agent API Key 为空 |
  | `app/llm/providers/openai_compatible.py:202` | `OPENAI_API_KEY` | 返回空字符串 |
  | `app/rag/query/query_processor.py:139-159` | `DASHSCOPE_API_KEY`, `DEEPSEEK_API_KEY`, `LLM_MODEL` | 返回空 → LLM 调用失败 |
  | `app/rag/reranker/llm_reranker.py:69-91` | 同上 | 同上 |
  | `app/rag/embedding/factory.py:13` | `EMBEDDING_PROVIDER` | 使用默认值 `"dashscope"`（恰巧正确） |
  | `app/services/page_knowledge_service.py:200` | `QWEN_API_KEY`, `DASHSCOPE_API_KEY` | 返回空 |

- **修改建议**:
  ```python
  # 方案 A (推荐): 在 config.py 最顶部添加，确保在任何 Settings 实例化之前执行
  from dotenv import load_dotenv
  load_dotenv()  # 将 .env 注入 os.environ
  
  # 方案 B: 将所有 os.getenv 调用迁移为 settings.FIELD_NAME
  ```

#### 问题 2: `MILVUS_STANDALONE` 不在 Pydantic Settings 中 — 配置被静默丢弃

- **位置**: `backend/app/core/config.py:16` (`extra="ignore"`) + `backend/app/db/milvus_client.py:152`
- **详情**: Settings 类没有 `MILVUS_STANDALONE` 字段，`extra="ignore"` 导致该变量被**静默丢弃**。同时也没有 `load_dotenv()` 将其注入 `os.environ`。`milvus_client.py:152` 读 `os.environ.get("MILVUS_STANDALONE")` 永远返回 `None`。
- **影响**: Milvus 模式选择的三个条件中 `MILVUS_STANDALONE` 永久失效，仅靠 `MILVUS_PORT != 19530` 兜底。如果有人修改端口配置，可能意外触发 Milvus Lite 模式（本地文件模式），导致连接到错误的 Milvus 实例。
- **修改建议**:
  ```python
  # config.py 添加字段
  MILVUS_STANDALONE: bool = Field(default=False, description="强制使用Milvus Standalone模式")
  
  # milvus_client.py 改为
  if settings.MILVUS_HOST in ("localhost", "127.0.0.1") \
     and not settings.MILVUS_STANDALONE \
     and settings.MILVUS_PORT != 19530:
  ```

#### 问题 3: `REDIS_ENABLED=False` — 本地开发禁用了 Redis 执行队列

- **位置**: `backend/.env` 第 60 行
- **详情**: `backend/.env` 中 `REDIS_ENABLED=False`，但在 `backend/.env.example` 中是 `True`。这意味着从 `.env.example` 复制模板后会启用 Redis，但当前实际 `.env` 禁用了 Redis。
- **影响**: 执行队列（`RedisExecutionQueue`）退化为 `asyncio.Queue`（内存队列），进程重启后队列数据丢失；分布式 Worker 无法工作。
- **修改建议**: 将 `backend/.env` 中 `REDIS_ENABLED` 改为 `True`

### 🟠 重要 (P1) — 功能受限或存在安全风险

#### 问题 4: 真实 API Key 硬编码在 .env 文件中

- **位置**: `/.env` 第 27 行 和 `backend/.env` 第 48 行
- **详情**: 两个文件都包含真实 DashScope API Key: `QWEN_API_KEY=sk-6a2cf760af454964b25b3296325f9972`
- **影响**: 如果 `.env` 文件被误提交到 Git，密钥将泄露。当前 `.gitignore` 应该已排除 `.env`，但如果规则失效后果严重。
- **修改建议**: 
  1. 确认 `.gitignore` 包含 `.env`（不含 `!` 前缀）
  2. 考虑在 DashScope 控制台轮换此密钥
  3. 使用 `backend/.env.local` (加入 `.gitignore`) 存放真实密钥

#### 问题 5: `SECRET_KEY` 缺失 — JWT 签名使用硬编码默认值

- **位置**: `backend/.env`（未定义）+ `backend/app/core/config.py:26` + `backend/app/core/auth.py:29`
- **详情**: `backend/.env` 中没有 `SECRET_KEY`。`config.py` 的默认值是 `"test-automation-secret-key-change-in-production"`，`auth.py` 又独立 fallback 到相同字符串。根目录 `.env` 中有定义，但 PyCharm 模式不会读取。
- **影响**: JWT Token 使用可预测的密钥签名，任何人可以用此密钥伪造 Token。
- **修改建议**: 在 `backend/.env` 中添加 `SECRET_KEY=<random-64-char-string>`

#### 问题 6: `alembic/env.py` 独立构建数据库 URL — 与 Settings 脱钩

- **位置**: `backend/alembic/env.py:24-38`
- **详情**: Alembic 的 `_build_database_url()` 通过 `os.getenv()` 独立读取配置并构建连接字符串，完全绕过 `Settings.DATABASE_URL`。由于没有 `load_dotenv()`，所有值回退到默认值：`localhost:3306`，密码为空字符串。
- **影响**: 
  - 如果使用非默认端口（如 3307）或非空密码，`alembic upgrade head` 将**连接失败**
  - Docker 模式正常（docker-compose 注入环境变量到容器 OS 环境）
  - PyCharm 本地模式：**alembic 迁移很可能失败**
- **修改建议**: 
  ```python
  # alembic/env.py 改为
  from app.core.config import settings
  def _build_database_url() -> str:
      return settings.DATABASE_URL
  ```
  注意：需要确保导入 settings 时 `load_dotenv()` 已经执行。

#### 问题 7: `env_file=".env"` 是相对路径 — 依赖 CWD

- **位置**: `backend/app/core/config.py:13`
- **详情**: `env_file=".env"` 是相对路径，pydantic-settings 相对于**当前工作目录 (CWD)** 解析。这在 PyCharm 中取决于 "Working directory" 运行配置。
- **影响**: 
  - CWD = `backend/` → 加载 `backend/.env` ✅ (正确)
  - CWD = 项目根目录 → 加载 `/.env` ❌ (Docker 配置，DB_HOST=mysql 等容器内地址)
- **修改建议**:
  ```python
  # 使用绝对路径，不受 CWD 影响
  import os
  _ENV_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
  model_config = SettingsConfigDict(env_file=_ENV_FILE, ...)
  ```

### 🟡 一般 (P2) — 不一致或潜在风险

#### 问题 8: NEO4J_PASSWORD 默认值不一致

- **位置**: `config.py:107` vs `.env` 文件
- **详情**: config.py 默认 `NEO4J_PASSWORD="password"`，但所有 `.env` 文件和 `docker-compose.yml` 使用 `neo4j_secure_password`。
- **影响**: 如果后端 `.env` 中没有 `NEO4J_PASSWORD` 行，config.py 的默认值 `"password"` 会覆盖预期值，导致 Neo4j 认证失败。
- **修改建议**: 将 config.py 默认值改为 `"neo4j_secure_password"` 或空字符串。

#### 问题 9: `admin.py` 引用不存在的 Settings 字段

- **位置**: `backend/app/api/admin.py:365-383`
- **详情**: `getattr(app_settings, "MYSQL_HOST", "localhost")`, `"MYSQL_PORT"`, `"MYSQL_DATABASE"` — 这些字段在 `Settings` 类中不存在（正确名称是 `DB_HOST`, `DB_PORT`, `DB_NAME`）。
- **影响**: 始终回退到默认值 `localhost:3306/test_automation`，admin 面板可能显示错误的数据库信息。
- **修改建议**: 改为 `settings.DB_HOST`, `settings.DB_PORT`, `settings.DB_NAME`

#### 问题 10: `knowledge/client.py` 导入不存在的 `redis_client`

- **位置**: `backend/app/services/knowledge/client.py:74`
- **详情**: `from app.db.database import redis_client` — 但 `database.py` 中没有定义 `redis_client`。
- **影响**: 导入结果为 `None`，知识缓存始终退化为内存缓存。
- **修改建议**: 在 `database.py` 中添加 Redis 客户端初始化，或修改 `knowledge/client.py` 使用 `settings.redis_url` 自行创建连接。

#### 问题 11: Docker Compose 根 .env 的 DB_PORT 值异常

- **位置**: `/.env` 第 14 行
- **详情**: 根 `.env` 写的是 `DB_PORT=3307`（宿主机映射端口），但 docker-compose backend 服务通过 `environment:` 覆盖了 `DB_HOST=mysql`（容器间通信使用容器网络）。容器内通信应该用 `3306` 而非 `3307`。
- **影响**: 当前因 docker-compose.yml 中 `environment:` 段没有覆盖 `DB_PORT`，backend 容器内使用的 DB_PORT 是 `.env` 中的 `3307`。容器内的 3307 端口没有服务监听，MySQL 在容器内监听的是 3306。
- **修改建议**: 在 `docker-compose.yml` 的 backend 服务 `environment:` 中添加 `DB_PORT=3306`，或将根 `.env` 中 `DB_PORT` 改为 `3306`。

#### 问题 12: 前端 Vite 端口不是标准 5173

- **位置**: `frontend/vite.config.ts:11`
- **详情**: Vite 配置 `server.port: 3000`，而 Vite 默认是 5173。README 中写的是 "http://localhost:5173（前端 dev server）"。
- **影响**: README 与实际配置不一致，用户按 README 操作会访问错误端口。
- **修改建议**: 统一端口号，要么改 vite.config.ts 为 5173，要么更新 README 为 3000。

---

## 四、Docker 服务连接对照表

### 当前模式: FastAPI 在 PyCharm (宿主机) 运行，Docker 中间件在 Docker Desktop 运行

| 服务 | 容器名 | 容器内端口 | 宿主机映射 | backend/.env 配置 | 状态 |
|------|--------|----------|----------|------------------|------|
| MySQL | `test_auto_mysql` | 3306 | **3307** | `DB_HOST=localhost:3307` | ✅ 正确 |
| Redis | `test_auto_redis` | 6379 | 6379 | `REDIS_HOST=localhost:6379` | ✅ 正确 |
| Milvus | `test_auto_milvus` | 19530 | 19530 | `MILVUS_HOST=localhost:19530` | ✅ 正确 |
| Neo4j Bolt | `test_auto_neo4j` | 7687 | 7687 | `NEO4J_URI=bolt://localhost:7687` | ✅ 正确 |
| Neo4j HTTP | `test_auto_neo4j` | 7474 | 7474 | — | ✅ 浏览器访问 |
| MinIO API | `test_auto_minio` | 9000 | (未映射) | — | ✅ 仅 Milvus 内部使用 |
| MinIO Console | `test_auto_minio` | 9001 | (未映射) | — | ⚠ 宿主机无法访问 Web UI |
| etcd | `milvus-etcd` | 2379 | (未映射) | — | ✅ 仅 Milvus 内部使用 |

**结论**: 对于 "PyCharm + Docker Desktop" 模式，`backend/.env` 中的连接配置**基本正确**。

---

## 五、配置读取链路分析

```
FastAPI 启动 → from app.core.config import settings
                   ↓
              Settings() 实例化
                   ↓
              pydantic-settings 读取 env_file=".env"
              (相对路径，依赖 CWD)
                   ↓
              .env 中的值 → Settings 实例属性 (settings.DB_HOST 等)
              ⚠ NOT → os.environ
                   ↓
         ┌─────────────────────────────────────┐
         │  路径 A: settings.FIELD_NAME        │  路径 B: os.getenv("KEY")
         │  ✅ 能读到 .env 值                  │  ❌ 读不到 .env 值
         │                                     │
         │  database.py ✅                     │  alembic/env.py ❌
         │  neo4j_client.py ✅                 │  milvus_client.py ❌
         │  大部分 agent ✅                     │  agents/factory/config.py ❌
         │  config.py DATABASE_URL ✅          │  llm/providers/* ❌
         │                                     │  rag/query/* ❌
         └─────────────────────────────────────┘  rag/reranker/* ❌
                                                  rag/embedding/factory.py ❌
                                                  services/page_knowledge_service.py ❌
```

---

## 六、第三方服务配置检查

### 1. DeepSeek API
- Key: `DEEPSEEK_API_KEY=` (空) — **未配置**
- URL: 硬编码 `https://api.deepseek.com/v1/chat/completions` (多处)
- 状态: 可选服务，未配置时 LLM Gateway 回退链跳过 DeepSeek

### 2. Embedding 服务
- Provider: `dashscope` (通义千问)
- 无 API Key 时 → **静默降级为 Mock Embedding** (确定性假向量)
- 这是一个设计特性，但**无告警日志** — 开发者可能不知道正在使用 Mock

### 3. LLM Gateway (核心调用链)
- 默认链: `qwen:qwen-plus → deepseek:deepseek-chat → ollama:qwen2.5:7b → mock`
- Mock 始终作为最后兜底，确保调用不会失败但返回假数据

### 4. Playwright
- Docker: Dockerfile 中安装 Chromium，路径 `/ms-playwright`
- PyCharm 本机: **需要手动执行** `playwright install chromium`
  - 浏览器默认安装到 `%USERPROFILE%\AppData\Local\ms-playwright\`
  - `backend/.env` 中**未设置** `PLAYWRIGHT_BROWSERS_PATH`
  - 代码中 `execution_agent.py:117` 通过 `os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")` 读取
  - 无此变量时使用 Playwright 默认路径 ✅

---

## 七、启动流程模拟与风险分析

### 步骤 1: `docker compose up -d`

```bash
cd C:\ui-automation
docker compose up -d
```

**前提条件**:
- ✅ Docker Desktop 已运行
- ✅ 根目录 `.env` 存在

**风险**:
- ⚠ 问题 11: `DB_PORT=3307` — 如果按 `.env.example` 新建 `.env`，需要手动修正。或者 `docker-compose.yml` 中 backend 的 `environment:` 段需要添加 `DB_PORT=3306`
- ⚠ 首次启动需要拉取多个镜像（MySQL 8.0, Redis 7, Milvus 2.4.4, Neo4j 5.20, MinIO, etcd），约需 10-15 分钟
- ✅ 已有 `depends_on` + `healthcheck` 确保启动顺序

### 步骤 2: 启动 FastAPI (PyCharm)

**前提条件**:
- ✅ Docker 服务已全部 healthy
- ✅ `cd backend && pip install -r requirements.txt` 已执行
- ⚠ 需要 `playwright install chromium`（如使用浏览器相关 Agent）

**PyCharm 运行配置**:
- Script: `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`
- Working directory: `C:\ui-automation\backend` ← **必须设置为 backend/**

**风险**:
- 🔴 问题 1: `os.getenv` 全局失效 → Alembic 迁移可能失败，部分 Agent API Key 为空
- 🔴 问题 5: `SECRET_KEY` 缺失 → 使用硬编码默认值
- 🟠 问题 3: `REDIS_ENABLED=False` → Redis 队列被禁用
- 🟠 问题 7: 如果 CWD 设置错误 → 读取到根目录 `.env`（Docker 配置），连接失败
- 🟡 需要手动 `alembic upgrade head` 或等 `entrypoint.sh`（本地没有）

### 步骤 3: 启动 React (本地)

```bash
cd C:\ui-automation\frontend
npm install
npm run dev
```

**风险**:
- 🟡 问题 12: Vite 在 `:3000` 启动，README 写的是 `:5173`，混淆
- ✅ Vite proxy 将 `/api` → `http://localhost:8000`，配置正确

---

## 八、推荐配置管理方案

### 目标架构

```
C:\ui-automation\
├── .env                          # docker-compose 专用 (提交 .env.example 模板)
├── .env.example                  # Docker 模式模板 (已存在，保持)
│
├── backend\
│   ├── .env                      # PyCharm 本地开发 (gitignore)
│   ├── .env.example              # 本地开发模板 (提交，已存在)
│   └── app/core/config.py        # ← 添加 load_dotenv()
│
├── deploy/
│   ├── docker/.env.production    # 生产 Docker 部署
│   └── k8s/*.yaml                # K8s ConfigMap/Secret
```

### 职责划分

| 文件 | 负责 | 消费者 |
|------|------|--------|
| `/.env` | Docker Compose 变量替换 | `docker-compose.yml` `${VAR}` |
| `/.env.example` | Docker 模式模板（含详细注释） | 开发者复制为 `/.env` |
| `backend/.env` | 本地 PyCharm 开发 | pydantic-settings + os.environ |
| `backend/.env.example` | 本地开发模板 | 开发者复制为 `backend/.env` |
| `deploy/docker/.env.production` | 生产环境 | 生产 docker-compose |

### 推荐 backend/.env 结构

```env
# ===== 应用 =====
APP_NAME=Test-Automation
APP_VERSION=1.0.0
APP_ENV=development
DEBUG=True
HOST=0.0.0.0
PORT=8000
SECRET_KEY=<生成随机64字符密钥>

# ===== MySQL (Docker 宿主机映射) =====
USE_SQLITE=False
DB_HOST=localhost
DB_PORT=3307
DB_USER=root
DB_PASSWORD=magic1212
DB_NAME=test_automation
DB_ECHO=False

# ===== Redis =====
REDIS_ENABLED=True          # ← 改为 True
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_DB=0

# ===== Milvus =====
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_STANDALONE=1         # ← 需在 Settings 中添加此字段

# ===== Neo4j =====
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=neo4j_secure_password

# ===== AI 模型 =====
QWEN_API_KEY=<你的DashScope密钥>
QWEN_API_URL=https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
QWEN_MODEL=qwen-vl-plus
EMBEDDING_PROVIDER=dashscope
EMBEDDING_MODEL=text-embedding-v3
EMBEDDING_DIM=1024

# DeepSeek (可选)
DEEPSEEK_API_KEY=
DEEPSEEK_API_URL=https://api.deepseek.com/v1/chat/completions

# OpenAI (可选)
OPENAI_API_KEY=
OPENAI_API_URL=https://api.openai.com/v1/chat/completions

# ===== 知识服务 =====
KNOWLEDGE_PROVIDER=r2r
R2R_BASE_URL=http://localhost:7272
R2R_API_KEY=

# ===== Playwright =====
# 本地开发不需要设置，使用默认路径
# PLAYWRIGHT_BROWSERS_PATH=

# ===== Agent =====
AGENT_TYPE=autogen           # ← 从 mock 改为实际 agent 类型
AGENT_TIMEOUT=300

# ===== 日志/文件 =====
LOG_LEVEL=INFO
LOG_PATH=logs
UPLOAD_DIR=uploads
MAX_UPLOAD_SIZE=10485760
REPORT_DIR=reports
```

---

## 九、推荐修复优先级

| 优先级 | 问题编号 | 修复操作 | 影响范围 |
|--------|---------|---------|---------|
| 🔴 P0 | #1 | 在 `config.py` 顶部添加 `load_dotenv()` | 全局 — 修复所有 os.getenv 调用 |
| 🔴 P0 | #2 | 在 Settings 类中添加 `MILVUS_STANDALONE` 字段 | Milvus 连接 |
| 🔴 P0 | #11 | docker-compose.yml backend 添加 `DB_PORT=3306` | Docker 全容器模式 |
| 🟠 P1 | #3 | `backend/.env` 中 `REDIS_ENABLED` 改为 `True` | 执行队列 |
| 🟠 P1 | #5 | `backend/.env` 中添加 `SECRET_KEY` | JWT 安全 |
| 🟠 P1 | #6 | alembic/env.py 改为使用 `settings.DATABASE_URL` | 数据库迁移 |
| 🟠 P1 | #7 | config.py 使用绝对路径指定 `.env` 位置 | CWD 依赖 |
| 🟡 P2 | #4 | 确认 .gitignore 防护，考虑轮换 API Key | 安全 |
| 🟡 P2 | #8 | 统一 NEO4J_PASSWORD 默认值 | Neo4j 连接 |
| 🟡 P2 | #9 | admin.py 修正字段名 | Admin 面板 |
| 🟡 P2 | #10 | 添加 Redis 客户端到 database.py | 知识缓存 |
| 🟡 P2 | #12 | 统一 Vite 端口号 | 开发体验 |

---

## 十、最终启动步骤（修正后）

### 首次启动:

```bash
# 1. 启动 Docker 中间件
cd C:\ui-automation
docker compose up -d mysql redis milvus neo4j

# 2. 等待 healthy
docker compose ps

# 3. 后端环境准备
cd backend
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium

# 4. 确认 backend/.env 配置正确（参见第八节推荐结构）

# 5. 数据库迁移
alembic upgrade head

# 6. 启动 FastAPI (PyCharm)
# Working directory: C:\ui-automation\backend
# Script: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 7. 启动前端
cd ..\frontend
npm install
npm run dev          # → http://localhost:3000

# 8. 验证
# - 后端: http://localhost:8000/docs
# - 前端: http://localhost:3000
# - Neo4j: http://localhost:7474
```

### 日常启动:

```bash
docker compose up -d                    # 启动中间件
# PyCharm → Run FastAPI                 # 启动后端
cd frontend && npm run dev              # 启动前端
```

---

## 附录: 需要查看但不确定的文件

1. **`backend/.gitignore`** — 确认 `.env` 是否被正确排除
2. **`backend/app/bootstrap/initializer.py`** — ApplicationContainer 初始化逻辑，决定哪些服务实际启动
3. **`backend/app/llm/gateway.py`** — LLM Gateway 完整逻辑，确认路由和回退链
4. **PyCharm 运行配置** — 确认 Working Directory 和 Environment Variables 设置
5. **DashScope 控制台** — 确认当前 API Key 是否仍然有效，建议轮换

---

*报告结束*
