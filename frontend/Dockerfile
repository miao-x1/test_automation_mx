# ================================================================== #
#  Frontend Dockerfile — React + Vite + Nginx                        #
# ================================================================== #

# ---------- 阶段1: 构建 ----------
FROM node:18-alpine AS builder

WORKDIR /app

# 复制依赖文件
COPY package.json package-lock.json* ./

# 安装依赖
RUN npm ci || npm install

# 复制源码
COPY . .

# 构建
RUN npm run build

# ---------- 阶段2: 运行 ----------
FROM nginx:alpine

# 复制 nginx 配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 暴露端口
EXPOSE 80

# 启动 nginx
CMD ["nginx", "-g", "daemon off;"]
