# ================================================================== #
#  Backend Dockerfile — FastAPI + Playwright                         #
# ================================================================== #
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖（Playwright Chromium 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libatspi2.0-0 \
    libwayland-client0 \
    libgtk-3-0 \
    libpango-1.0-0 \
    libcairo2 \
    fonts-liberation \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .
COPY requirements-docker.txt .

# 配置 pip 镜像源 + 超时
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip config set global.timeout 300

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -r requirements-docker.txt || true

# 安装 Playwright 浏览器（Chromium）— 带重试，失败不阻断构建
RUN for i in 1 2 3; do \
        playwright install chromium && break || \
        echo "Playwright download attempt $i failed, retrying..." && sleep 3; \
    done; exit 0

# 复制项目代码
COPY . .

# 创建必要目录
RUN mkdir -p uploads logs reports data

# 复制启动脚本
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# 暴露端口
EXPOSE 8000

# 启动命令（先迁移数据库，再启动应用）
CMD ["/app/entrypoint.sh"]
