# React UI 2 项目

基于 React + Vite + Tailwind CSS + Zustand + Immer + React Router 的数据流动治理平台前端壳工程（不含 AI 分类模块）。

## 技术栈

- **React 18** - UI 框架
- **Vite** - 构建工具
- **TypeScript** - 类型支持
- **Tailwind CSS** - 样式框架
- **Zustand** - 状态管理
- **Immer** - 不可变数据更新
- **React Router** - 路由管理
- **Axios** - HTTP 客户端

## 安装依赖

```bash
cd react-ui-2
npm install
```

## 开发

```bash
npm run dev
```

应用将在 `http://localhost:5175` 启动。

## 构建

```bash
npm run build
```

## 预览构建结果

```bash
npm run preview
```

## 项目结构

```
react-ui-2/
├── src/
│   ├── api/           # API 接口（AuthService）
│   ├── components/    # 公共组件（侧栏、顶栏、面包屑等）
│   ├── stores/        # Zustand 状态管理
│   ├── utils/         # 工具函数
│   ├── views/         # 页面（登录、总览占位、各侧栏占位页）
│   ├── router/        # 路由配置
│   ├── App.tsx
│   └── main.tsx
├── index.html
├── package.json
├── vite.config.ts
└── tailwind.config.js
```

## 与 react-ui 的差异

- 不包含 AI 分类模块（任务列表、标注详情、训练/预测等）
- 侧栏无「AI分类」入口
- 登录后默认进入总览

## 单独部署（Docker）

后端在宿主机或其它机器运行时，仅部署本前端：

```bash
cd V3-ui-2
cp .env.example .env   # 按实际后端地址修改 API_*_UPSTREAM
docker compose up -d --build
```

浏览器访问：`http://<主机>:8088`（端口由 `UI_HOST_PORT` 控制）。

- 构建在镜像内完成，生产请求走同域 `/api`，由 Nginx 转发（见 `nginx.conf.template`）
- 默认通过 `host.docker.internal` 访问宿主机上的 `9080`（认证）、`8090`（业务 API）
- Linux 需 Docker 20.10+；`compose.yaml` 已配置 `extra_hosts: host-gateway`

常用命令：

```bash
docker compose logs -f v3-ui-2
docker compose down
docker compose up -d --build   # 代码变更后重新构建
```

## 注意事项

1. 开发环境 API 代理在 `vite.config.ts` 中
2. 生产环境 API 代理在 `nginx.conf.template`，通过 `API_AUTH_UPSTREAM` / `API_TRIDENT_UPSTREAM` 配置
3. 与 `react-ui` 默认使用不同开发端口（5175），可同时启动
