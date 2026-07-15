# UI-Automation 部署指南

## 架构概览

```
                    ┌─────────────┐
                    │   Nginx:80  │ ← 用户访问入口
                    │  (Frontend) │
                    └──────┬──────┘
                           │ /api/* → proxy
                    ┌──────▼──────┐
                    │  FastAPI     │
                    │  :8000       │
                    │  (Backend)   │
                    └──┬──┬──┬──┬──┘
           ┌──────────┘  │  │  └──────────┐
    ┌──────▼──────┐ ┌───▼──┐ ┌▼───────┐ ┌▼──────┐
    │ MySQL :3306 │ │Redis │ │Milvus  │ │Neo4j  │
    │  (数据)     │ │:6379 │ │:19530  │ │:7687  │
    └─────────────┘ └──────┘ └────────┘ └───────┘
```

| 服务 | 端口 | 容器名 | 用途 |
|------|------|--------|------|
| Frontend (Nginx) | 80 | ui_auto_frontend | React 静态托管 + API 反向代理 |
| Backend (FastAPI) | 8000 | ui_auto_backend | Python API 服务 |
| MySQL | 3306 | ui_auto_mysql | 主数据库 |
| Redis | 6379 | ui_auto_redis | 执行队列 |
| Milvus | 19530 | ui_auto_milvus | 向量检索（含 etcd + minio） |
| Neo4j | 7474/7687 | ui_auto_neo4j | 知识图谱 |

## 前置条件

- Docker 24.0+
- Docker Compose v2.20+
- 磁盘空间 > 10GB（Milvus 镜像较大）
- 通义千问 API Key（DashScope）

---

## Docker 一键启动（推荐）

### 1. 克隆项目并配置环境变量

```bash
cd /your/project/path/ui-automation

# 从模板创建 .env 文件
cp .env.example .env

# 编辑 .env，必须修改以下项：
#   SECRET_KEY      — 改为随机字符串
#   DB_PASSWORD     — 数据库密码
#   NEO4J_PASSWORD  — Neo4j 密码
#   QWEN_API_KEY    — 通义千问 API Key
vi .env
```

### 2. 构建并启动所有服务

```bash
# 构建镜像并后台启动
docker compose up -d --build

# 查看启动状态
docker compose ps

# 查看日志（实时跟踪）
docker compose logs -f backend
```

首次构建约需 5-10 分钟（下载镜像 + 安装 Playwright Chromium）。

### 3. 初始化数据库

```bash
# 执行数据库迁移（Alembic）
docker compose exec backend alembic upgrade head

# 如果迁移失败，可用 Python 直接建表
docker compose exec backend python -c "from app.db.database import init_db; init_db()"
```

### 4. 验证服务

```bash
# 前端访问
curl http://localhost

# 后端 API
curl http://localhost:8000/api/v1/agents

# Neo4j Web 界面
# 浏览器打开 http://localhost:7474
```

### 5. 停止与清理

```bash
# 停止所有服务（保留数据）
docker compose down

# 停止并删除所有数据卷（彻底清理）
docker compose down -v
```

---

## Linux 裸机部署

### 1. 安装系统依赖

```bash
# Ubuntu / Debian
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv nodejs npm \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libasound2 libatspi2.0-0 libwayland-client0 \
    libgtk-3-0 libpango-1.0-0 libcairo2 fonts-liberation fonts-noto-cjk

# CentOS / RHEL
sudo yum install -y python3.11 nodejs npm \
    nss nspr atk at-spi2-atk cups-libs libdrm \
    libxkbcommon libXcomposite libXdamage libXfixes \
    libXrandr mesa-libgbm alsa-lib at-spi2-core \
    gtk3 pango cairo liberation-fonts google-noto-cjk-fonts
```

### 2. 安装并启动 MySQL 8.0

```bash
# 安装
sudo apt-get install mysql-server

# 启动
sudo systemctl start mysql
sudo systemctl enable mysql

# 创建数据库和用户
sudo mysql <<'SQL'
CREATE DATABASE ui_automation CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'ui_auto'@'%' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON ui_automation.* TO 'ui_auto'@'%';
FLUSH PRIVILEGES;
SQL
```

### 3. 安装并启动 Redis

```bash
sudo apt-get install redis-server
sudo systemctl start redis-server
sudo systemctl enable redis-server
```

### 4. 安装并启动 Milvus Standalone

```bash
# 下载 Milvus 安装脚本
wget https://github.com/milvus-io/milvus/releases/download/v2.4.4/milvus-standalone-docker-compose.yml -O docker-compose-milvus.yml

# 启动 Milvus（依赖 etcd + minio）
docker compose -f docker-compose-milvus.yml up -d
```

### 5. 安装并启动 Neo4j

```bash
# 添加 Neo4j 官方源
wget -O - https://debian.neo4j.com/neotechnology.gpg.key | sudo apt-key add -
echo 'deb https://debian.neo4j.com stable latest' | sudo tee /etc/apt/sources.list.d/neo4j.list

sudo apt-get update
sudo apt-get install neo4j

# 修改配置 /etc/neo4j/neo4j.conf
#   dbms.default_listen_address=0.0.0.0
#   dbms.security.auth_enabled=true

sudo systemctl start neo4j
sudo systemctl enable neo4j
```

### 6. 部署后端

```bash
cd /your/project/path/ui-automation/backend

# 创建虚拟环境
python3.11 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt -r requirements-docker.txt

# 安装 Playwright Chromium
playwright install chromium

# 配置环境变量
cp .env.example .env
vi .env  # 修改数据库地址、API Key 等

# 数据库迁移
alembic upgrade head

# 启动（生产环境推荐 gunicorn + uvicorn worker）
pip install gunicorn
gunicorn app.main:app \
    -k uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000 \
    --workers 4 \
    --timeout 600
```

### 7. 部署前端

```bash
cd /your/project/path/ui-automation/frontend

# 安装依赖
npm install

# 构建
npm run build

# 安装 Nginx
sudo apt-get install nginx

# 复制构建产物
sudo cp -r dist/* /var/www/html/

# 配置 Nginx
sudo cp nginx.conf /etc/nginx/sites-available/ui-automation
sudo ln -s /etc/nginx/sites-available/ui-automation /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

---

## Windows 部署

### 方式一：Docker Desktop（推荐）

1. 安装 [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/)
2. 启动 Docker Desktop，确保状态为 Running
3. 打开 PowerShell：

```powershell
cd C:\your\project\path\ui-automation

# 复制环境变量
Copy-Item .env.example .env

# 编辑 .env 文件
notepad .env

# 构建并启动
docker compose up -d --build

# 查看状态
docker compose ps
```

4. 数据库迁移：

```powershell
docker compose exec backend alembic upgrade head
```

5. 访问 http://localhost

### 方式二：本地开发环境

1. 安装 [Python 3.11](https://www.python.org/downloads/)、[Node.js 18+](https://nodejs.org/)、[MySQL 8.0](https://dev.mysql.com/downloads/installer/)

2. 启动 MySQL 和 Redis（可通过 Windows 服务管理器）

3. 后端：

```powershell
cd C:\your\project\path\ui-automation\backend

python -m venv venv
.\venv\Scripts\Activate.ps1

pip install -r requirements.txt -r requirements-docker.txt
playwright install chromium

Copy-Item .env.example .env
# 编辑 .env，设置 DB_HOST=localhost 等

alembic upgrade head

python -m app.main
```

4. 前端：

```powershell
cd C:\your\project\path\ui-automation\frontend

npm install
npm run dev
```

5. 访问 http://localhost:3000

---

## 环境变量说明

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SECRET_KEY` | JWT 密钥，生产环境必须修改 | change-this-... |
| `DB_HOST` | MySQL 地址 | mysql (Docker) / localhost (裸机) |
| `DB_PASSWORD` | MySQL 密码 | ui_auto_secure_password |
| `REDIS_HOST` | Redis 地址 | redis (Docker) / localhost (裸机) |
| `MILVUS_HOST` | Milvus 地址 | milvus (Docker) / localhost (裸机) |
| `MILVUS_STANDALONE` | 设为 1 强制 Standalone 模式 | 1 |
| `NEO4J_URI` | Neo4j Bolt 连接 | bolt://neo4j:7687 |
| `NEO4J_PASSWORD` | Neo4j 密码 | neo4j_secure_password |
| `QWEN_API_KEY` | 通义千问 API Key（必填） | sk-xxx |
| `QWEN_MODEL` | 模型名称 | qwen-vl-plus |
| `EMBEDDING_DIM` | 向量维度 | 1024 |
| `APP_ENV` | 运行环境 | production |

完整变量列表见 `.env.example`。

---

## 常见问题

### Q: Milvus 启动失败

Milvus 依赖 etcd 和 minio。确保这三个容器都已健康：

```bash
docker compose ps etcd minio milvus
docker compose logs milvus
```

### Q: Playwright 脚本执行报错

Docker 环境中已预装 Chromium。如果仍报错，手动安装：

```bash
docker compose exec backend playwright install --with-deps chromium
```

### Q: 前端访问显示 502

后端可能还在启动中。检查后端日志：

```bash
docker compose logs backend
```

### Q: 数据库连接失败

确认 MySQL 已健康，且 `.env` 中的 `DB_HOST` 在 Docker 模式下设为 `mysql`，裸机模式下设为 `localhost`。

### Q: Neo4j 连接超时

Neo4j 首次启动较慢（30-60 秒）。等待 health check 通过后再启动 backend：

```bash
docker compose up -d neo4j
docker compose ps neo4j  # 等待显示 healthy
docker compose up -d backend
```

### Q: 如何修改后端端口

修改 `docker-compose.yml` 中 backend 的端口映射：

```yaml
backend:
  ports:
    - "9000:8000"  # 宿主机 9000 → 容器 8000
```

同时修改 `frontend/nginx.conf` 中的 `proxy_pass` 指向新端口。

---

## 运维命令速查

```bash
# 查看所有服务状态
docker compose ps

# 查看指定服务日志
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f mysql

# 重启单个服务
docker compose restart backend

# 重新构建单个服务
docker compose up -d --build backend

# 进入容器
docker compose exec backend bash
docker compose exec mysql mysql -u root -p

# 查看数据卷
docker volume ls | grep ui_auto

# 备份 MySQL
docker compose exec mysql mysqldump -u root -p${DB_PASSWORD} ui_automation > backup.sql

# 恢复 MySQL
docker compose exec -T mysql mysql -u root -p${DB_PASSWORD} ui_automation < backup.sql
```
