# 构建阶段
FROM node:20.19-alpine AS builder

WORKDIR /app

ARG NPM_REGISTRY=https://registry.npmmirror.com
RUN npm config set registry "${NPM_REGISTRY}"

COPY package.json package-lock.json ./
# package-lock 中若残留内网源 npm.sr.ok，构建环境无法解析，统一替换为公共镜像
RUN sed -i 's|https://npm\.sr\.ok|https://registry.npmmirror.com|g' package-lock.json \
    && npm ci

COPY . .
RUN npm run build

# 运行阶段：nginx 官方镜像会在启动时用环境变量渲染 /etc/nginx/templates/*.template
FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

ENV API_AUTH_UPSTREAM=http://host.docker.internal:9080
ENV API_TRIDENT_UPSTREAM=http://host.docker.internal:8090

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
