#!/bin/bash
set -e

echo "========== Agent Worker 启动 =========="

# 1. 等待 MySQL 就绪
echo "[1/3] 等待 MySQL 就绪..."
until python -c "
import pymysql, os
pymysql.connect(
    host=os.getenv('DB_HOST', 'mysql'),
    port=int(os.getenv('DB_PORT', 3306)),
    user=os.getenv('DB_USER', 'root'),
    password=os.getenv('DB_PASSWORD', ''),
)
" 2>/dev/null; do
    echo "  MySQL 未就绪, 等待中..."
    sleep 2
done
echo "  MySQL 已就绪"

# 2. 等待 Redis 就绪
echo "[2/3] 等待 Redis 就绪..."
until python -c "
import redis, os
r = redis.from_url(
    f'redis://{os.getenv(\"REDIS_HOST\", \"redis\")}:{os.getenv(\"REDIS_PORT\", \"6379\")}/{os.getenv(\"REDIS_DB\", \"0\")}',
    socket_timeout=2, socket_connect_timeout=2,
)
r.ping()
" 2>/dev/null; do
    echo "  Redis 未就绪, 等待中..."
    sleep 2
done
echo "  Redis 已就绪"

# 3. 运行数据库迁移 (Worker 也可执行,确保表结构最新)
echo "[3/3] 运行 Alembic 迁移..."
alembic upgrade head || echo "  跳过迁移 (可能已最新或被 Backend 执行)"

# 启动 Worker
CONCURRENCY="${WORKER_CONCURRENCY:-4}"
WORKER_ID="${WORKER_ID:-}"

echo "========== 启动 Agent Worker (并发: $CONCURRENCY) =========="

if [ -n "$WORKER_ID" ]; then
    exec python -m app.worker_main --worker-id "$WORKER_ID" --concurrency "$CONCURRENCY"
else
    exec python -m app.worker_main --concurrency "$CONCURRENCY"
fi
