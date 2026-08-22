# 企业级生产部署方案

> AI 驱动的 UI 自动化测试平台 — 生产环境部署指南

## 架构总览

```
                        ┌─────────────────────────────────────────────────┐
                        │              Ingress / Nginx:80                  │
                        │          (TLS + 路由 + WebSocket)               │
                        └────────┬──────────────────────┬─────────────────┘
                                 │                      │
                          /api/* │              /        │
                          /ws/*  │              静态资源  │
                                 ▼                      ▼
                    ┌──────────────────┐    ┌──────────────────┐
                    │  Backend (x2-6)  │    │  Frontend (x2-4) │
                    │  FastAPI :8000   │    │  React + Nginx   │
                    │  + Playwright    │    │  SPA             │
                    └────┬────┬───┬────┘    └──────────────────┘
                         │    │   │
            ┌────────────┘    │   └─────────────┐
            │                 │                 │
            ▼                 ▼                 ▼
    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
    │ Worker (x2-8)│  │   Redis      │  │   MySQL 8.0  │
    │ Agent 执行   │  │   任务队列    │  │   关系数据    │
    │ BRPOP 消费  │◄─┤   + 缓存     │  │              │
    └──────┬───────┘  └──────────────┘  └──────────────┘
           │
    ┌──────┴───────┬──────────────┐
    ▼              ▼              ▼
┌─────────┐ ┌───────────┐ ┌───────────┐
│ Milvus  │ │  Neo4j    │ │  etcd +   │
│ 向量库  │ │  图数据库 │ │  MinIO    │
└─────────┘ └───────────┘ └───────────┘
```

### 服务清单

| 服务 | 镜像 | 端口 | 职责 | 有状态 |
|------|------|------|------|--------|
| Frontend | nginx:alpine | 80 | SPA 静态资源 + 反向代理 | 否 |
| Backend | python:3.11-slim | 8000 | FastAPI API + Agent Registry | 否 |
| Worker | python:3.11-slim | - | Agent 任务执行 (Redis BRPOP) | 否 |
| MySQL | mysql:8.0 | 3306 | 关系数据存储 | 是 |
| Redis | redis:7-alpine | 6379 | 任务队列 + 缓存 | 是 |
| Milvus | milvusdb/milvus:v2.4.4 | 19530 | 向量检索 | 是 |
| etcd | bitnamilegacy/etcd:3.5 | 2379 | Milvus 元数据 | 是 |
| MinIO | minio/minio | 9000 | Milvus 对象存储 | 是 |
| Neo4j | neo4j:5.20.0 | 7687 | 图数据库 | 是 |

---

## 部署方案一: Docker Compose (单机/中小规模)

### 适用场景

- 开发测试环境
- 中小型团队 (≤50人)
- 单机部署 (16GB+ RAM)

### 快速启动

```bash
# 1. 复制环境变量模板
cp deploy/docker/.env.production .env

# 2. 修改敏感配置 (SECRET_KEY, API Key 等)
vim .env

# 3. 启动全部服务
docker compose -f deploy/docker/docker-compose.prod.yml up -d --build

# 4. 查看状态
docker compose -f deploy/docker/docker-compose.prod.yml ps

# 5. 查看日志
docker compose -f deploy/docker/docker-compose.prod.yml logs -f backend
docker compose -f deploy/docker/docker-compose.prod.yml logs -f worker
```

### 服务管理

```bash
# 停止
docker compose -f deploy/docker/docker-compose.prod.yml down

# 停止并清除数据卷 (危险!)
docker compose -f deploy/docker/docker-compose.prod.yml down -v

# 重建单个服务
docker compose -f deploy/docker/docker-compose.prod.yml up -d --build backend
docker compose -f deploy/docker/docker-compose.prod.yml up -d --build worker

# 扩展 Worker 实例
docker compose -f deploy/docker/docker-compose.prod.yml up -d --scale worker=3
```

### 资源需求

| 资源 | 最低 | 推荐 |
|------|------|------|
| CPU | 4 核 | 8 核 |
| 内存 | 8 GB | 16 GB |
| 磁盘 | 30 GB | 100 GB SSD |

### 配置文件清单

| 文件 | 说明 |
|------|------|
| `deploy/docker/docker-compose.prod.yml` | 生产编排 (9 服务) |
| `deploy/docker/.env.production` | 环境变量模板 |
| `deploy/docker/redis/redis.conf` | Redis 生产配置 (AOF + LRU) |
| `deploy/docker/mysql/conf.d/mysql.cnf` | MySQL 生产配置 (InnoDB + 慢查询) |
| `backend/Dockerfile` | 后端镜像 (FastAPI + Playwright) |
| `backend/Dockerfile.worker` | Worker 镜像 (共享后端基础) |
| `backend/entrypoint.sh` | 后端启动脚本 (MySQL 等待 + 迁移 + uvicorn) |
| `backend/entrypoint-worker.sh` | Worker 启动脚本 (MySQL + Redis 等待 + worker_main) |
| `frontend/Dockerfile` | 前端镜像 (多阶段: node build → nginx serve) |
| `frontend/nginx.conf` | Nginx 配置 (SPA + API 代理 + SSE/WS) |

---

## 部署方案二: Kubernetes (大规模/企业级)

### 适用场景

- 生产环境
- 大型团队 (50+ 人)
- 高可用 + 自动伸缩
- 多节点集群

### 前置条件

```bash
# Kubernetes 集群 (1.24+)
kubectl version --client

# Ingress Controller (nginx-ingress 或 traefik)
kubectl get pods -n ingress-nginx

# (可选) cert-manager 用于自动 TLS
kubectl get pods -n cert-manager

# (可选) 镜像仓库 (Harbor / ACR / ECR)
```

### 构建并推送镜像

```bash
# 1. 构建镜像
docker build -t test-automation/backend:latest -f backend/Dockerfile backend/
docker build -t test-automation/worker:latest -f backend/Dockerfile.worker backend/
docker build -t test-automation/frontend:latest -f frontend/Dockerfile frontend/

# 2. 推送到镜像仓库 (替换为实际 registry)
docker tag test-automation/backend:latest registry.example.com/test-automation/backend:latest
docker tag test-automation/worker:latest registry.example.com/test-automation/worker:latest
docker tag test-automation/frontend:latest registry.example.com/test-automation/frontend:latest

docker push registry.example.com/test-automation/backend:latest
docker push registry.example.com/test-automation/worker:latest
docker push registry.example.com/test-automation/frontend:latest
```

### 部署到 K8s

```bash
# 1. 修改 kustomization.yaml 中的镜像地址
vim deploy/k8s/kustomization.yaml

# 2. 修改 Secret 中的敏感配置
vim deploy/k8s/02-secret.yaml

# 3. 修改 Ingress 中的域名
vim deploy/k8s/10-ingress.yaml

# 4. 一键部署
kubectl apply -k deploy/k8s/

# 5. 查看部署状态
kubectl get pods -n test-automation
kubectl get svc -n test-automation
kubectl get ingress -n test-automation

# 6. 查看 Pod 日志
kubectl logs -n test-automation -l app=backend -f
kubectl logs -n test-automation -l app=worker -f
```

### 分步部署 (调试用)

```bash
# 基础设施层
kubectl apply -f deploy/k8s/00-namespace.yaml
kubectl apply -f deploy/k8s/01-configmap.yaml
kubectl apply -f deploy/k8s/02-secret.yaml

# 数据库层 (等待 Ready)
kubectl apply -f deploy/k8s/03-mysql.yaml
kubectl apply -f deploy/k8s/04-redis.yaml
kubectl apply -f deploy/k8s/05-milvus.yaml
kubectl apply -f deploy/k8s/06-neo4j.yaml

# 等待数据库就绪
kubectl wait --for=condition=Ready pod -l app=mysql -n test-automation --timeout=300s
kubectl wait --for=condition=Ready pod -l app=redis -n test-automation --timeout=120s
kubectl wait --for=condition=Ready pod -l app=milvus -n test-automation --timeout=300s
kubectl wait --for=condition=Ready pod -l app=neo4j -n test-automation --timeout=300s

# 应用层
kubectl apply -f deploy/k8s/07-backend.yaml
kubectl apply -f deploy/k8s/08-worker.yaml
kubectl apply -f deploy/k8s/09-frontend.yaml

# 入口 + 自动伸缩
kubectl apply -f deploy/k8s/10-ingress.yaml
kubectl apply -f deploy/k8s/11-hpa.yaml
```

### 扩缩容

```bash
# 手动扩容 Backend
kubectl scale deployment backend -n test-automation --replicas=4

# 手动扩容 Worker
kubectl scale deployment worker -n test-automation --replicas=6

# 查看 HPA 状态
kubectl get hpa -n test-automation
```

### K8s 配置文件清单

| 文件 | 说明 |
|------|------|
| `00-namespace.yaml` | 命名空间 |
| `01-configmap.yaml` | 非敏感配置 (应用/MySQL/Redis/Nginx) |
| `02-secret.yaml` | 敏感配置 (密钥/密码/API Key) |
| `03-mysql.yaml` | MySQL StatefulSet + Service + PVC |
| `04-redis.yaml` | Redis StatefulSet + Service + PVC |
| `05-milvus.yaml` | etcd + MinIO + Milvus (全套 StatefulSet) |
| `06-neo4j.yaml` | Neo4j StatefulSet + Service + PVC |
| `07-backend.yaml` | Backend Deployment + Service + 4个PVC |
| `08-worker.yaml` | Worker Deployment (无 Service) |
| `09-frontend.yaml` | Frontend Deployment + Service |
| `10-ingress.yaml` | Ingress 路由 (TLS + WebSocket) |
| `11-hpa.yaml` | 3个HPA (Backend 2-6 / Worker 2-8 / Frontend 2-4) |
| `kustomization.yaml` | Kustomize 统一入口 |

---

## Agent Worker 架构

### 分布式任务队列

```
API 请求 → Backend (TaskDispatcher) → Redis List (LPUSH)
                                          │
                          ┌───────────────┼───────────────┐
                          ▼               ▼               ▼
                    Worker-1         Worker-2         Worker-N
                    (BRPOP)          (BRPOP)          (BRPOP)
                          │               │               │
                          ▼               ▼               ▼
                    AgentFactory    AgentFactory    AgentFactory
                    → execute()     → execute()     → execute()
                          │               │               │
                          └───────┬───────┴───────┬───────┘
                                  ▼               ▼
                            MySQL 持久化    Redis 结果发布
```

### 队列设计

| 优先级 | Redis Key | 场景 |
|--------|-----------|------|
| urgent | `runtime:task_queue:urgent` | 紧急任务 |
| high | `runtime:task_queue:high` | 高优先级 |
| normal | `runtime:task_queue:normal` | 常规任务 |
| low | `runtime:task_queue:low` | 后台任务 |

### Worker 心跳

每个 Worker 每 10 秒向 Redis 写入心跳:
```
runtime:worker:heartbeat:<worker_id>
TTL: 30s
```

### 新增文件

| 文件 | 说明 |
|------|------|
| `backend/app/worker_main.py` | Worker 独立入口 (BRPOP + Agent 执行 + 结果回写) |
| `backend/Dockerfile.worker` | Worker Docker 镜像 |
| `backend/entrypoint-worker.sh` | Worker 启动脚本 |

---

## 环境配置

### 必填配置 (生产环境)

```bash
# 安全密钥 (64 字符随机串)
SECRET_KEY=<openssl rand -hex 32>

# 数据库密码
DB_PASSWORD=<strong-password>
NEO4J_PASSWORD=<strong-password>

# LLM API Key (至少一个)
QWEN_API_KEY=sk-xxx
DEEPSEEK_API_KEY=sk-xxx
```

### 可选配置

```bash
# Redis 密码 (生产环境建议设置)
REDIS_PASSWORD=<redis-password>

# 知识服务 (R2R)
R2R_BASE_URL=http://r2r-service:7272
R2R_API_KEY=xxx

# Ollama 本地模型
OLLAMA_HOST=http://ollama:11434

# Worker 并发数
WORKER_CONCURRENCY=4
```

---

## 监控与运维

### 健康检查端点

| 服务 | 端点 | 方法 |
|------|------|------|
| Backend | `http://backend:8000/api/health` | HTTP GET |
| MySQL | `mysqladmin ping` | TCP |
| Redis | `redis-cli ping` | TCP |
| Milvus | `http://milvus:9091/healthz` | HTTP GET |
| Neo4j | `cypher-shell "RETURN 1"` | TCP |

### 日志管理

```bash
# Docker Compose
docker compose -f deploy/docker/docker-compose.prod.yml logs -f
docker compose -f deploy/docker/docker-compose.prod.yml logs -f backend worker

# Kubernetes
kubectl logs -n test-automation -l app=backend -f --tail=100
kubectl logs -n test-automation -l app=worker -f --tail=100

# 日志持久化 (K8s)
# 建议配置 Fluentd/Filebeat 采集到 ELK 或 Loki
```

### 数据库迁移

```bash
# Docker Compose (自动执行, 也可手动)
docker exec -it prod_backend alembic upgrade head

# Kubernetes
kubectl exec -it -n test-automation deploy/backend -- alembic upgrade head
```

### 备份策略

```bash
# MySQL 备份
docker exec prod_mysql mysqldump -u root -p test_automation > backup_$(date +%Y%m%d).sql

# Redis 持久化 (AOF 自动)
# 数据卷: redis_data

# Milvus 备份
# 数据卷: milvus_data + etcd_data + minio_data

# Neo4j 备份
docker exec prod_neo4j neo4j-admin dump --database=neo4j --to=/data/backup.dump

# K8s: 使用 Velero 或 Volume Snapshot
kubectl get pvc -n test-automation
```

### 故障排查

```bash
# Pod 未就绪
kubectl describe pod <pod-name> -n test-automation
kubectl logs <pod-name> -n test-automation

# 服务不可达
kubectl get svc -n test-automation
kubectl get endpoints -n test-automation

# 数据库连接失败
kubectl exec -it deploy/backend -n test-automation -- python -c "
import pymysql, os
pymysql.connect(host='mysql', port=3306, user='root', password=os.getenv('DB_PASSWORD'))
print('MySQL OK')
"

# Redis 连接失败
kubectl exec -it deploy/backend -n test-automation -- python -c "
import redis
r = redis.from_url('redis://redis:6379/0')
r.ping()
print('Redis OK')
"

# Worker 队列状态
kubectl exec -it deploy/backend -n test-automation -- python -c "
import redis
r = redis.from_url('redis://redis:6379/0')
for key in ['runtime:task_queue:urgent', 'runtime:task_queue:high', 'runtime:task_queue:normal', 'runtime:task_queue:low']:
    print(f'{key}: {r.llen(key)} tasks')
for key in r.keys('runtime:worker:heartbeat:*'):
    print(f'Worker: {r.get(key)}')
"
```

---

## 部署检查清单

### 部署前

- [ ] 修改 `SECRET_KEY` 为随机 64 字符串
- [ ] 修改 `DB_PASSWORD` 和 `NEO4J_PASSWORD`
- [ ] 配置至少一个 LLM API Key (`QWEN_API_KEY` / `DEEPSEEK_API_KEY`)
- [ ] 确认服务器满足最低资源需求 (4核 / 8GB / 30GB)
- [ ] 确认 Docker / Kubernetes 集群可用

### 部署后

- [ ] 所有 Pod/Container 状态为 Running
- [ ] Backend 健康检查通过 (`/api/health` 返回 200)
- [ ] 前端页面可访问
- [ ] 数据库迁移完成 (`alembic upgrade head` 无报错)
- [ ] Agent 注册完成 (Backend 日志显示 "Agent 注册完成")
- [ ] Worker 心跳正常 (Redis 中有 `runtime:worker:heartbeat:*` 键)
- [ ] 创建初始管理员账号
