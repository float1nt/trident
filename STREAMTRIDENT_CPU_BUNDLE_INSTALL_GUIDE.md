# StreamTrident CPU 安装包使用说明

## 1. 适用范围

本文档用于在 Ubuntu 服务器上部署 `streamtrident_cpu_bundle` CPU 安装包。

安装包支持两种部署方式：

| 方式 | 说明 | 推荐场景 |
|---|---|---|
| 单机部署 | 采集端、分析端和 UI 运行在同一台服务器 | 首次安装、验证和小规模使用 |
| 分机部署 | 采集端、分析端和 UI 可分别运行在不同服务器 | 生产环境和分布式部署 |

安装包使用 Docker 镜像离线部署。目标服务器不需要编译源码，但必须提前安装
Docker Engine 和 Docker Compose 插件。

---

## 2. 安装包目录

完整安装包应至少包含以下文件：

```text
streamtrident_cpu_bundle/
├── deploy.env
├── images/
│   └── streamtrident-cpu-images.tar
└── scripts/
    ├── check-capture.sh
    ├── common.sh
    ├── export-images.sh
    ├── install.sh
    ├── start-analysis.sh
    ├── start-capture.sh
    ├── start-local.sh
    ├── start-ui.sh
    └── stop-all.sh
```

其中：

- `deploy.env`：部署参数配置文件。
- `images/streamtrident-cpu-images.tar`：离线 Docker 镜像包。
- `scripts/export-images.sh`：在制包机器上导出离线镜像包。
- `scripts/install.sh`：导入离线镜像。
- `scripts/start-local.sh`：单机启动全部服务。
- `scripts/start-capture.sh`：只启动采集端。
- `scripts/start-analysis.sh`：只启动分析端。
- `scripts/start-ui.sh`：只启动前端 UI。
- `scripts/check-capture.sh`：检查采集队列是否存在 flow 数据。
- `scripts/stop-all.sh`：停止当前机器上已启动的 StreamTrident 服务。

启动脚本会自动生成 `streamtrident_cpu_bundle/runtime/` 目录。该目录保存 Docker Compose
文件、采集过滤配置和日志，不需要手动创建。

当前源码工作区可能不包含体积较大的 `images/streamtrident-cpu-images.tar`。正式交付安装包前，
必须在已经具备全部镜像的制包机器上执行：

```bash
cd streamtrident_cpu_bundle
./scripts/export-images.sh
```

脚本会生成：

```text
images/streamtrident-cpu-images.tar
```

部署服务器只需要执行 `install.sh` 导入镜像，不需要运行 `export-images.sh`。

---

## 3. 安装 Docker

以下命令使用 Docker 官方 Ubuntu apt 仓库安装 Docker Engine 和 Compose 插件。

### 3.1 卸载旧版本

如果服务器没有安装过旧版本，命令报错可以忽略。

```bash
sudo apt-get remove -y docker docker-engine docker.io containerd runc
```

### 3.2 安装依赖

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
```

### 3.3 添加 Docker 官方 GPG Key

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

### 3.4 添加 Docker apt 源

```bash
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
```

### 3.5 安装 Docker Engine 和 Compose 插件

```bash
sudo apt-get update
sudo apt-get install -y \
  docker-ce \
  docker-ce-cli \
  containerd.io \
  docker-buildx-plugin \
  docker-compose-plugin
```

### 3.6 启动 Docker

```bash
sudo systemctl enable --now docker
sudo docker version
sudo docker compose version
```

### 3.7 允许当前用户直接运行 Docker

安装包脚本直接调用 `docker` 命令。建议将当前用户加入 `docker` 组：

```bash
sudo usermod -aG docker "$USER"
newgrp docker
docker ps
```

如果当前终端仍然没有权限，请退出 SSH 后重新登录。

Docker 官方文档：
[Install Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/)

---

## 4. 部署前配置

进入安装包目录：

```bash
cd streamtrident_cpu_bundle
```

编辑配置文件：

```bash
vi deploy.env
```

### 4.1 核心配置项

| 配置项 | 默认用途 | 说明 |
|---|---|---|
| `CAPTURE_HOST` | 采集端主机 IP | 单机部署填 `127.0.0.1`；分机部署填采集服务器真实 IP |
| `SURICATA_IFACE` | 抓包网卡 | 必须改为采集服务器真实网卡，例如 `eth0`、`ens35` 或 `enp3s0` |
| `REDIS_HOST_PORT` | `16379` | 采集端 Redis 对外端口 |
| `SURICATA_AGENT_HOST_PORT` | `19100` | 采集规则管理接口端口 |
| `TRIDENT_API_HOST_PORT` | `8090` | 分析端 API 对外端口 |
| `UI_HOST_PORT` | `8088` | 前端 UI 对外端口 |
| `TRIDENT_WORKER_MODE` | `cold_start` | 首次建模使用 `cold_start`；模型稳定后切换为 `inference` |
| `ANALYSIS_HOST` | 分析端主机 IP | 单机部署填 `127.0.0.1`；UI 分机部署时填分析服务器真实 IP |

### 4.2 查询真实网卡

在采集服务器执行：

```bash
ip -br link
ip route
```

选择承载目标流量的真实网卡，将其写入：

```bash
SURICATA_IFACE=ens37
```

不要直接照抄示例网卡名。网卡配置错误时，容器可能正常运行，但采集队列不会产生 flow。

### 4.3 单机部署配置示例

```dotenv
CAPTURE_HOST=127.0.0.1
SURICATA_IFACE=ens37

REDIS_HOST_PORT=16379
SURICATA_AGENT_HOST_PORT=19100
TRIDENT_API_HOST_PORT=8090
UI_HOST_PORT=8088

TRIDENT_WORKER_MODE=cold_start

CAPTURE_REDIS_HOST=${CAPTURE_HOST}
CAPTURE_REDIS_PORT=${REDIS_HOST_PORT}
TRIDENT_SURICATA_AGENT_URLS=http://${CAPTURE_HOST}:${SURICATA_AGENT_HOST_PORT}

ANALYSIS_HOST=127.0.0.1
API_AUTH_UPSTREAM=http://${ANALYSIS_HOST}:${TRIDENT_API_HOST_PORT}
API_TRIDENT_UPSTREAM=http://${ANALYSIS_HOST}:${TRIDENT_API_HOST_PORT}
```

---

## 5. 单机部署

单机部署会依次启动采集端、分析端和 UI。

### 5.1 导入离线镜像

```bash
cd streamtrident_cpu_bundle
./scripts/install.sh
```

脚本默认读取：

```text
images/streamtrident-cpu-images.tar
```

如果镜像包存放在其他位置，可以显式传入路径：

```bash
./scripts/install.sh /path/to/streamtrident-cpu-images.tar
```

### 5.2 启动全部服务

确认 `deploy.env` 已修改后执行：

```bash
./scripts/start-local.sh
```

启动完成后访问：

```text
UI:          http://<服务器IP>:8088
Trident API: http://<服务器IP>:8090
```

### 5.3 检查容器

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

单机部署正常时，应看到以下主要容器：

```text
streamtrident-redis
streamtrident-suricata-cic
streamtrident-suricata-agent
streamtrident-clickhouse
streamtrident-postgres
streamtrident-worker
streamtrident-api
v3-ui-2
```

`streamtrident-redis-admin` 和 `streamtrident-migrate` 是一次性任务容器，成功执行后退出属于正常现象。

### 5.4 检查采集 flow

```bash
./scripts/check-capture.sh
```

脚本会依次检查：

1. Redis 是否可连接。
2. `suricata:cic_flow` 队列长度。
3. 最新一条 flow 数据。
4. 本机采集容器状态。

如果队列长度大于 `0`，说明采集端已经向 Redis 写入 flow。

---

## 6. 分机部署

分机部署可以将采集端、分析端和 UI 安装在不同服务器。每台服务器都需要：

1. 安装 Docker Engine 和 Docker Compose 插件。
2. 解压完整 `streamtrident_cpu_bundle`。
3. 执行 `./scripts/install.sh` 导入镜像。
4. 根据本机角色修改 `deploy.env`。

假设服务器规划如下：

| 角色 | 示例 IP |
|---|---|
| 采集端 | `172.16.89.46` |
| 分析端 | `172.16.89.45` |
| UI 端 | `172.16.89.44` |

### 6.1 启动采集端

在采集服务器修改：

```dotenv
CAPTURE_HOST=172.16.89.46
SURICATA_IFACE=ens37
REDIS_HOST_PORT=16379
SURICATA_AGENT_HOST_PORT=19100
```

启动：

```bash
./scripts/start-capture.sh
./scripts/check-capture.sh
```

### 6.2 启动分析端

在分析服务器修改：

```dotenv
CAPTURE_HOST=172.16.89.46
CAPTURE_REDIS_HOST=${CAPTURE_HOST}
CAPTURE_REDIS_PORT=16379
TRIDENT_SURICATA_AGENT_URLS=http://${CAPTURE_HOST}:19100

ANALYSIS_HOST=172.16.89.45
TRIDENT_API_HOST_PORT=8090
TRIDENT_WORKER_MODE=cold_start
```

启动：

```bash
./scripts/start-analysis.sh
./scripts/check-capture.sh
```

在分析端执行 `check-capture.sh` 时，本机没有采集容器属于正常现象。重点检查 Redis 是否可连接、
队列中是否存在 flow。

### 6.3 启动 UI

在 UI 服务器修改：

```dotenv
ANALYSIS_HOST=172.16.89.45
TRIDENT_API_HOST_PORT=8090
UI_HOST_PORT=8088

API_AUTH_UPSTREAM=http://${ANALYSIS_HOST}:${TRIDENT_API_HOST_PORT}
API_TRIDENT_UPSTREAM=http://${ANALYSIS_HOST}:${TRIDENT_API_HOST_PORT}
```

启动：

```bash
./scripts/start-ui.sh
```

浏览器访问：

```text
http://172.16.89.44:8088
```

---

## 7. 网络端口

### 7.1 对外端口

| 所在服务器 | 默认端口 | 用途 | 建议放通来源 |
|---|---:|---|---|
| 采集端 | `16379/tcp` | Redis CIC flow 队列 | 仅分析端 |
| 采集端 | `19100/tcp` | Suricata Agent 管理接口 | 仅分析端 |
| 分析端 | `8090/tcp` | Trident API | 仅 UI 端和管理网 |
| UI 端 | `8088/tcp` | Web UI | 需要访问平台的用户网段 |

### 7.2 分析端数据库端口

分析端 Compose 默认还会暴露：

| 默认端口 | 服务 |
|---:|---|
| `18123/tcp` | ClickHouse HTTP |
| `19000/tcp` | ClickHouse Native |
| `15432/tcp` | PostgreSQL |

这些端口不应直接暴露到公网。生产环境请使用防火墙限制访问来源。

Ubuntu 使用 UFW 时，可参考：

```bash
sudo ufw allow from <分析端IP> to any port 16379 proto tcp
sudo ufw allow from <分析端IP> to any port 19100 proto tcp
sudo ufw allow from <UI端IP> to any port 8090 proto tcp
sudo ufw allow from <用户网段> to any port 8088 proto tcp
```

---

## 8. 冷启动与推理模式

首次部署时使用：

```dotenv
TRIDENT_WORKER_MODE=cold_start
```

冷启动阶段，分析端会根据实时 flow 建立正常基线学习器。配置中默认启用：

```text
cold_start_exit_on_complete: true
```

冷启动完成后，Worker 会退出。此时将分析服务器 `deploy.env` 修改为：

```dotenv
TRIDENT_WORKER_MODE=inference
```

然后重新生成分析端 Compose 并启动：

```bash
./scripts/start-analysis.sh
```

检查 Worker：

```bash
docker ps --filter name=streamtrident-worker
docker logs --tail 200 streamtrident-worker
```

---

## 9. 常用运维命令

### 9.1 查看容器状态

```bash
docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

### 9.2 查看日志

```bash
docker logs --tail 200 streamtrident-suricata-cic
docker logs --tail 200 streamtrident-worker
docker logs --tail 200 streamtrident-api
docker logs --tail 200 v3-ui-2
```

安装包还会在以下目录保留日志：

```text
runtime/capture/suricata/logs/
runtime/analysis/trident/logs/
```

### 9.3 检查采集队列

```bash
./scripts/check-capture.sh
```

### 9.4 停止当前机器上的服务

```bash
./scripts/stop-all.sh
```

脚本会按照 UI、分析端、采集端的顺序执行 `docker compose down`。

### 9.5 重新启动

修改 `deploy.env` 后，重新执行对应角色的启动脚本即可。启动脚本会重新生成
`runtime/` 下的 Compose 和配置文件。

单机部署：

```bash
./scripts/start-local.sh
```

分机部署：

```bash
./scripts/start-capture.sh
./scripts/start-analysis.sh
./scripts/start-ui.sh
```

---

## 10. 故障排查

### 10.1 `Image tar not found`

现象：

```text
Image tar not found: .../images/streamtrident-cpu-images.tar
```

处理：

1. 检查镜像包是否存在。
2. 将镜像包放入 `images/streamtrident-cpu-images.tar`。
3. 或执行 `./scripts/install.sh /实际路径/streamtrident-cpu-images.tar`。

### 10.2 Docker 权限不足

现象：

```text
permission denied while trying to connect to the Docker daemon socket
```

处理：

```bash
sudo usermod -aG docker "$USER"
newgrp docker
docker ps
```

如果仍然失败，请退出 SSH 后重新登录。

### 10.3 Redis 无法连接

执行：

```bash
./scripts/check-capture.sh
```

如果提示 Redis 无法连接，请检查：

1. 采集端 `streamtrident-redis` 是否运行。
2. `CAPTURE_HOST`、`CAPTURE_REDIS_HOST` 和 `CAPTURE_REDIS_PORT` 是否正确。
3. 防火墙是否允许分析端访问采集端 `16379/tcp`。
4. 分机部署时是否将 `CAPTURE_HOST` 错误填写为 `127.0.0.1`。

### 10.4 Redis 可连接，但队列没有 flow

如果 `LLEN suricata:cic_flow = 0`，请检查：

1. `SURICATA_IFACE` 是否为真实抓包网卡。
2. 采集服务器当前是否存在网络流量。
3. `streamtrident-suricata-cic` 容器日志是否报错。

```bash
ip -br link
docker logs --tail 200 streamtrident-suricata-cic
```

### 10.5 UI 无法访问

检查：

```bash
docker ps --filter name=v3-ui-2
docker logs --tail 200 v3-ui-2
curl -I http://127.0.0.1:8088
```

分机部署还需确认：

1. UI 端 `ANALYSIS_HOST` 是否指向分析服务器。
2. UI 端是否能访问分析服务器 `8090/tcp`。
3. 用户浏览器所在网段是否允许访问 UI 服务器 `8088/tcp`。

### 10.6 API 无法访问

检查：

```bash
docker ps --filter name=streamtrident-api
docker logs --tail 200 streamtrident-api
curl -I http://127.0.0.1:8090
```

### 10.7 Worker 未持续运行

首次冷启动完成后，Worker 自动退出可能是正常行为。查看日志：

```bash
docker logs --tail 200 streamtrident-worker
```

如果冷启动已经完成，请将：

```dotenv
TRIDENT_WORKER_MODE=inference
```

写入 `deploy.env`，然后重新运行：

```bash
./scripts/start-analysis.sh
```

---

## 11. 生产环境安全提醒

默认脚本以便于部署验证为目标。正式上线前至少完成以下加固：

1. 使用防火墙限制 Redis、Suricata Agent、ClickHouse 和 PostgreSQL 端口来源。
2. 不要将 `16379`、`19100`、`18123`、`19000` 和 `15432` 暴露到公网。
3. 根据实际网络范围缩小采集过滤规则。
4. 定期备份分析端 Docker Volume 中的 ClickHouse、PostgreSQL 和模型数据。
5. 限制能够访问 Docker Socket 的用户。`suricata-agent` 需要挂载
   `/var/run/docker.sock`，因此采集端应视为高权限服务器管理。

---

## 12. 安装验收清单

部署完成后逐项确认：

```text
[ ] docker version 正常
[ ] docker compose version 正常
[ ] ./scripts/install.sh 成功导入离线镜像
[ ] SURICATA_IFACE 已修改为真实网卡
[ ] docker ps 可看到当前机器对应角色的容器
[ ] ./scripts/check-capture.sh 可以连接 Redis
[ ] suricata:cic_flow 队列中存在 flow
[ ] 分析端 API 可以访问
[ ] UI 页面可以访问
[ ] 首次建模使用 cold_start
[ ] 冷启动完成后已切换 inference
[ ] 防火墙只放通必要来源
```
