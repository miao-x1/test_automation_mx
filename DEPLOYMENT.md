# Test-Automation 部署指南

## 架构概览

```
                    ┌─────────────┐
                    │  Nginx:80   │ ← 用户访问入口
                    │ (Frontend)  │
                    └──────┬──────┘
                           │ /api/* → proxy_pass
                    ┌──────▼──────┐
                    │  FastAPI    │
                    │  :8000      │
                    │  (Backend)  │
                    └──┬──┬──┬────┘
           ┌──────────┘  │  └──────────┐
    ┌──────▼──────┐ ┌───▼──┐ ┌───────▼───┐
    │ MySQL :3307 │ │Redis │ │  Milvus   │
    │  (62 表)    │ │:6379 │ │  :19530   │
    └─────────────┘ └──────┘ │+et+minio  │
                             └───────────┘
```

| 服务 | 宿主端口 | 容器端口 | 容器名 | 用途 |
|------|----------|----------|--------|------|
| Frontend (Nginx) | 80 | 80 | test_auto_frontend | React 静态托管 + API 反向代理 |
| Backend (FastAPI) | 8000 | 8000 | test_auto_backend | Python API + Playwright + 35 Agents |
| MySQL | **3307** | 3306 | test_auto_mysql | 主数据库（62 张表） |
| Redis | 6379 | 6379 | test_auto_redis | 执行队列 + 缓存 |
| Milvus | 19530 | 19530 | test_auto_milvus | 向量检索 |
| etcd | - | 2379 | milvus-etcd | Milvus 元数据 |
| MinIO | - | 9000 | test_auto_minio | Milvus 对象存储 |
| Neo4j | 7474 / 7687 | 7474 / 7687 | test_auto_neo4j | 知识图谱 |

> **注意**：MySQL 映射到宿主机 **3307** 端口（非默认 3306），避免与本地 MySQL 冲突。连接字符串中使用 `3307`。

---

## 前置条件

- Docker Desktop 4.20+（含 Docker Compose v2.20+）
- 磁盘空间 > 15GB（后端镜像 ~2.5GB + 基础设施镜像 ~3GB）
- 通义千问 API Key（DashScope）

---

## Docker 一键启动（推荐）

### 1. 配置环境变量

```bash
cd /your/project/path/ui-automation

# 从模板创建 .env
cp .env.example .env

# 编辑 .env，必须修改以下项：
#   SECRET_KEY      — 改为随机字符串（生产环境）
#   QWEN_API_KEY    — 通义千问 API Key（必填）
#   DB_PASSWORD     — 数据库密码（默认 magic1212）
#   NEO4J_PASSWORD  — Neo4j 密码（默认 neo4j_secure_password）
```

### 2. 构建并启动

```bash
# 构建镜像并后台启动（首次约 10-15 分钟）
docker compose up -d --build

# 查看启动状态
docker compose ps

# 实时跟踪后端日志
docker logs test_auto_backend -f
```

**启动流程**（`entrypoint.sh` 自动执行）：

```
[1/4] 等待 MySQL 就绪...
[2/4] 确保数据库存在...
[3/4] 运行 Alembic 迁移...     ← 自动建表，无需手动执行
[4/4] 启动 FastAPI...           ← Uvicorn 单进程启动
```

> 数据库迁移由 `entrypoint.sh` 自动完成，**不需要手动执行 `alembic upgrade head`**。

### 3. 验证服务

```bash
# 前端访问（返回 200）
curl -o /dev/null -w "%{http_code}" http://localhost

# 后端 API 文档（返回 200）
curl -o /dev/null -w "%{http_code}" http://localhost:8000/docs

# Neo4j Web 界面
# 浏览器打开 http://localhost:7474
#   用户名: neo4j  密码: neo4j_secure_password

# MySQL 表数量
docker exec test_auto_mysql mysql -u root -pmagic1212 \
  -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='test_automation';"
```

### 4. 停止与清理

```bash
# 停止所有服务（保留数据）
docker compose down

# 停止并删除所有数据卷（彻底清理）
docker compose down -v

# 清理未使用的镜像（释放磁盘）
docker system prune -af
```

---

## 代码更新流程

| 改了什么 | 命令 |
|----------|------|
| 后端 Python 代码 | `docker compose up -d --build backend` |
| 后端依赖（`requirements.txt`） | 同上 |
| 前端代码 | `docker compose up -d --build frontend` |
| 环境变量（`.env`） | `docker compose up -d --force-recreate` |
| `docker-compose.yml` | `docker compose up -d` |
| Dockerfile | `docker compose up -d --build` |

---

## 本地开发部署

### 1. 安装系统依赖

**Ubuntu / Debian:**
```bash
sudo apt-get install -y python3.11 python3.11-venv nodejs npm \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libasound2 libatspi2.0-0 libwayland-client0 \
    libgtk-3-0 libpango-1.0-0 libcairo2 fonts-liberation fonts-noto-cjk
```

**CentOS / RHEL:**
```bash
sudo yum install -y python3.11 nodejs npm \
    nss nspr atk at-spi2-atk cups-libs libdrm \
    libxkbcommon libXcomposite libXdamage libXfixes \
    libXrandr mesa-libgbm alsa-lib at-spi2-core \
    gtk3 pango cairo liberation-fonts google-noto-cjk-fonts
```

### 2. 启动 MySQL 8.0

```bash
sudo apt-get install mysql-server
sudo systemctl start mysql && sudo systemctl enable mysql

sudo mysql <<'SQL'
CREATE DATABASE test_automation CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'root'@'%' IDENTIFIED BY 'magic1212';
GRANT ALL PRIVILEGES ON test_automation.* TO 'root'@'%';
FLUSH PRIVILEGES;
SQL
```

### 3. 启动 Redis

```bash
sudo apt-get install redis-server
sudo systemctl start redis-server && sudo systemctl enable redis-server
```

### 4. 启动 Milvus Standalone

```bash
wget https://github.com/milvus-io/milvus/releases/download/v2.4.4/milvus-standalone-docker-compose.yml -O docker-compose-milvus.yml
docker compose -f docker-compose-milvus.yml up -d
```

### 5. 启动 Neo4j

```bash
wget -O - https://debian.neo4j.com/neotechnology.gpg.key | sudo apt-key add -
echo 'deb https://debian.neo4j.com stable latest' | sudo tee /etc/apt/sources.list.d/neo4j.list
sudo apt-get update && sudo apt-get install neo4j

# 修改 /etc/neo4j/neo4j.conf:
#   dbms.default_listen_address=0.0.0.0
#   dbms.security.auth_enabled=true

sudo systemctl start neo4j && sudo systemctl enable neo4j
```

### 6. 部署后端

```bash
cd backend

python3.11 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
playwright install chromium

cp .env.example .env
# 编辑 .env:
#   USE_SQLITE=False
#   DB_HOST=localhost  DB_PORT=3306  DB_USER=root  DB_PASSWORD=magic1212
#   REDIS_HOST=localhost
#   MILVUS_HOST=localhost  MILVUS_STANDALONE=1
#   NEO4J_URI=bolt://localhost:7687
#   QWEN_API_KEY=sk-xxx

alembic upgrade head

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 7. 部署前端

```bash
cd frontend
npm install && npm run dev
```

开发模式访问：http://localhost:5173

### 8. 生产部署前端（Nginx）

```bash
cd frontend
npm run build
sudo cp -r dist/* /var/www/html/
sudo cp nginx.conf /etc/nginx/sites-available/test-automation
sudo ln -s /etc/nginx/sites-available/test-automation /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

---

## Windows 部署

### 方式一：Docker Desktop（推荐）

1. 安装 [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/)
2. 启动 Docker Desktop，确保状态为 Running
3. PowerShell：

```powershell
cd C:\your\project\path\ui-automation

Copy-Item .env.example .env
notepad .env  # 修改 QWEN_API_KEY、SECRET_KEY

docker compose up -d --build

# 查看状态
docker compose ps

# 查看后端日志
docker logs test_auto_backend -f
```

4. 访问 http://localhost

### 方式二：本地开发

```powershell
# 后端
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1

pip install -r requirements.txt
playwright install chromium

Copy-Item .env.example .env
# 编辑 .env: DB_HOST=localhost, REDIS_HOST=localhost, MILVUS_HOST=localhost

alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 前端
cd ..\frontend
npm install
npm run dev
```

访问 http://localhost:5173

---

## 环境变量说明

| 变量 | 说明 | Docker 默认值 | 裸机默认值 |
|------|------|---------------|------------|
| `USE_SQLITE` | 使用 SQLite（必须为 False 才能用 MySQL） | `False` | `False` |
| `DB_HOST` | MySQL 地址 | `mysql` | `localhost` |
| `DB_PORT` | MySQL 端口 | `3306`（容器内） | `3307`（宿主映射） |
| `DB_USER` | MySQL 用户 | `root` | `root` |
| `DB_PASSWORD` | MySQL 密码 | `magic1212` | `magic1212` |
| `DB_NAME` | 数据库名 | `test_automation` | `test_automation` |
| `REDIS_HOST` | Redis 地址 | `redis` | `localhost` |
| `REDIS_PORT` | Redis 端口 | `6379` | `6379` |
| `MILVUS_HOST` | Milvus 地址 | `milvus` | `localhost` |
| `MILVUS_PORT` | Milvus 端口 | `19530` | `19530` |
| `MILVUS_STANDALONE` | Milvus Standalone 模式 | `1` | `1` |
| `NEO4J_URI` | Neo4j Bolt 连接 | `bolt://neo4j:7687` | `bolt://localhost:7687` |
| `NEO4J_USER` | Neo4j 用户 | `neo4j` | `neo4j` |
| `NEO4J_PASSWORD` | Neo4j 密码 | `neo4j_secure_password` | `neo4j_secure_password` |
| `QWEN_API_KEY` | 通义千问 API Key（必填） | `sk-xxx` | `sk-xxx` |
| `QWEN_MODEL` | 模型名称 | `qwen-vl-plus` | `qwen-vl-plus` |
| `EMBEDDING_PROVIDER` | Embedding 服务 | `dashscope` | `dashscope` |
| `EMBEDDING_DIM` | 向量维度 | `1024` | `1024` |
| `SECRET_KEY` | JWT 密钥 | `change-this-...` | 同左 |
| `APP_ENV` | 运行环境 | `production` | `development` |
| `LOG_LEVEL` | 日志级别 | `INFO` | `INFO` |

完整变量列表见 `.env.example`。

---

## 常见问题

### Q: MySQL 端口为什么是 3307？

Docker Compose 将 MySQL 映射到宿主机 **3307** 端口，避免与本地已安装的 MySQL（默认 3306）冲突。容器内部仍然是 3306，不影响任何功能。

用客户端连接 MySQL：

```bash
mysql -h 127.0.0.1 -P 3307 -u root -pmagic1212 test_automation
```

### Q: Milvus 启动失败

Milvus 依赖 etcd 和 minio。确保三个容器都健康：

```bash
docker compose ps etcd minio milvus
docker compose logs milvus
```

### Q: Playwright 脚本执行报错

Docker 环境中已预装 Chromium + FFmpeg + Headless Shell。如果仍报错，手动安装：

```bash
docker exec test_auto_backend playwright install --with-deps chromium
```

### Q: Playwright 构建时下载失败（网络问题）

Dockerfile 中已配置 3 次重试 + `exit 0` 容错。如果仍然失败，可以：

```bash
# 使用代理
docker build --build-arg HTTPS_PROXY=http://your-proxy:port -t ui-automation-backend .

# 或跳过 Playwright（牺牲截图功能）
docker exec test_auto_backend playwright install chromium
```

### Q: 前端访问显示 502

后端可能还在启动中（初始化 35 个 Agent 需要约 10-15 秒）。检查后端日志：

```bash
docker logs test_auto_backend --tail 20
```

看到 `Uvicorn running on http://0.0.0.0:8000` 即可正常访问。

### Q: 数据库连接失败

1. 确认 MySQL 容器健康：`docker compose ps mysql`
2. 确认 `.env` 中 `USE_SQLITE=False`（否则会用 SQLite）
3. 确认 `DB_HOST=mysql`（Docker 内部网络）
4. 确认 `DB_PASSWORD` 与 `docker-compose.yml` 中的 `MYSQL_ROOT_PASSWORD` 一致

### Q: 后端启动后立刻退出

检查日志中的 Python 异常：

```bash
docker logs test_auto_backend 2>&1 | grep -E "Error|Traceback|Import"
```

常见原因：依赖版本冲突（检查 `requirements.txt` 版本约束是否过严）。

### Q: Redis Worker 阻塞导致 API 无响应

Redis 的 `brpop` 是同步阻塞调用，会阻塞 asyncio 事件循环。已修复为 `asyncio.to_thread` 异步执行。如果再次出现：

```bash
# 检查是否有 brpop 同步调用
grep -r "brpop" backend/app/services/
# 确保使用: await asyncio.to_thread(r.brpop, key, timeout)
```

### Q: `create_all` 与 Alembic 冲突（Duplicate column）

`init_db()` 中的 `create_all` 会与 Alembic 迁移冲突。已修复为 warning 不阻断启动。如果再次出现 Duplicate column 错误，说明 `init_db` 的 `except` 块重新 `raise` 了，需要改回 `log.warning`。

### Q: Neo4j 连接超时

Neo4j 首次启动较慢（30-60 秒）。Docker Compose 已配置 health check，会自动等待。

### Q: 如何修改后端端口

修改 `docker-compose.yml` 中 backend 的端口映射：

```yaml
backend:
  ports:
    - "9000:8000"  # 宿主机 9000 → 容器 8000
```

同时修改 `frontend/nginx.conf` 中的 `proxy_pass` 指向新端口。

### Q: Docker Desktop 一直刷新 / 启动失败

```bash
# 重启 Docker 引擎
wsl --shutdown
# 重新启动 Docker Desktop

# 或清理 Docker 数据
docker system prune -af --volumes
```

---

## 运维命令速查

```bash
# 查看所有服务状态
docker compose ps

# 查看指定服务日志
docker logs test_auto_backend -f
docker logs test_auto_frontend -f
docker logs test_auto_mysql -f

# 重启单个服务
docker restart test_auto_backend

# 重新构建单个服务
docker compose up -d --build backend

# 进入容器
docker exec -it test_auto_backend bash
docker exec -it test_auto_mysql mysql -u root -pmagic1212

# 查看数据卷
docker volume ls | grep test_auto

# 备份 MySQL
docker exec test_auto_mysql mysqldump -u root -pmagic1212 test_automation > backup.sql

# 恢复 MySQL
docker exec -i test_auto_mysql mysql -u root -pmagic1212 test_automation < backup.sql

# 重置数据库（慎用）
docker exec test_auto_mysql mysql -u root -pmagic1212 \
  -e "DROP DATABASE IF EXISTS test_automation; CREATE DATABASE test_automation CHARACTER SET utf8mb4;"
docker restart test_auto_backend

# 查看后端容器内文件
docker exec test_auto_backend ls -la /app/
docker exec test_auto_backend cat /app/requirements.txt

# 检查后端进程
docker exec test_auto_backend ps aux
```
