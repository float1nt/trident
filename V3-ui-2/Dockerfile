# 构建阶段
FROM node:20-alpine AS builder

WORKDIR /app

# 设置 npm 镜像源为淘宝镜像
RUN npm config set registry https://registry.npmmirror.com

# 复制 package 文件
COPY react-ui/package*.json ./

# 安装依赖（切换 npm 镜像源并关闭严格 SSL 以规避自签名证书问题）
# 替换 package-lock.json 中的 npm.sr.ok 为 registry.npmmirror.com
RUN npm config set registry https://registry.npmmirror.com \
    && npm config set strict-ssl false \
    && sed -i 's|https://npm\.sr\.ok|https://registry.npmmirror.com|g' package-lock.json \
    && npm ci

# 复制源代码
COPY react-ui/ ./

# 构建应用
RUN npm run build

# 生产阶段 - 使用 nginx 提供静态文件服务
FROM nginx:alpine

# 复制构建产物到 nginx 目录
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制 nginx 配置文件
COPY react-ui/nginx.conf /etc/nginx/conf.d/default.conf

# 暴露端口
EXPOSE 80

# 启动 nginx
CMD ["nginx", "-g", "daemon off;"]

