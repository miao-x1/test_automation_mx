#!/bin/bash
set -e

echo "========== Test-Automation Backend 启动 =========="

# 1. 等待 MySQL 就绪
echo "[1/4] 等待 MySQL 就绪..."
until python -c "
import pymysql, os
pymysql.connect(
    host=os.getenv('DB_HOST', 'mysql'),
    port=int(os.getenv('DB_PORT', 3306)),
    user=os.getenv('DB_USER', 'root'),
    password=os.getenv('DB_PASSWORD', ''),
)
" 2>/dev/null; do
    echo "  MySQL 未就绪，等待中..."
    sleep 2
done
echo "  MySQL 已就绪"

# 2. 创建数据库（如果不存在）
echo "[2/4] 确保数据库存在..."
python -c "
import pymysql, os
conn = pymysql.connect(
    host=os.getenv('DB_HOST', 'mysql'),
    port=int(os.getenv('DB_PORT', 3306)),
    user=os.getenv('DB_USER', 'root'),
    password=os.getenv('DB_PASSWORD', ''),
)
db_name = os.getenv('DB_NAME', 'test_automation')
cur = conn.cursor()
cur.execute(f'CREATE DATABASE IF NOT EXISTS \`{db_name}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
conn.commit()
cur.close()
conn.close()
print(f'  数据库 {db_name} 已就绪')
"

# 3. 运行数据库迁移
echo "[3/4] 运行 Alembic 迁移..."
alembic upgrade head || echo "  跳过迁移（可能已最新）"

# 4. 启动应用
echo "[4/4] 启动 FastAPI..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
