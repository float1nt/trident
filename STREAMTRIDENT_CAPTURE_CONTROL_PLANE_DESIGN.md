# StreamTrident 采集侧控制面分阶段改造设计

## 1. 目标与边界

本文档描述 `streamtrident_services` 的采集配置控制面改造。目标是在不改变 flow 数据链路的前提下，让分析侧能够向采集机下发 Suricata 过滤配置，并逐步获得配置生效状态与采集健康信息。

推荐分两阶段实施：

| 阶段 | 目标 | 核心结果 |
|------|------|----------|
| 阶段一：配置下发闭环 | 完成分析侧编排与采集侧执行 | 前端保存配置后，`trident-api` 持久化期望配置，调用采集机 agent，agent 写入 `filter.json` 并重启 Suricata |
| 阶段二：状态回传增强 | 增加可观测状态，不改变 flow 流向 | 分析侧主动读取 agent 状态，前端展示已保存、已下发、已生效、失败原因与采集健康 |

本次控制面改造不包括：

- 不让采集机将 flow 发送到新的 HTTP 接口。flow 仍由 Suricata 写入采集侧 Redis，再由分析侧 worker 消费。
- 不在阶段一实现 `maxTrafficLimitGbps` 的实际限速。该字段继续保存，但 UI 需标记为“配置已保存，限速策略待实现”。
- 不在阶段一实现 Suricata 热加载。过滤配置仍通过重启 Suricata 生效。
- 不将 Docker Socket 暴露到宿主机网络。只有 `suricata-agent` 容器挂载 `/var/run/docker.sock`。

## 2. 当前实现盘点

仓库中已经存在方案 A 的主体骨架，不需要从零创建 API 服务。

### 2.1 已存在的采集侧能力

目录：`streamtrident_services/capture/suricata-agent/`

当前 agent 已提供：

```text
GET  /agent/v1/health
POST /agent/v1/suricata/filter/apply
```

`POST /agent/v1/suricata/filter/apply` 已具备以下逻辑：

1. 可选 Bearer Token 校验。
2. 将配置原子写入 `/etc/suricata-cic/filter.json`。
3. 通过 Docker Socket 重启 `streamtrident-suricata-cic`。

`capture/compose.yaml` 已将 agent 发布到宿主机 `19100`，并挂载 Suricata 配置目录和 Docker Socket。

### 2.2 已存在的分析侧能力

目录：`streamtrident_services/analysis/trident/`

当前 `trident-api` 已提供：

```text
GET  /collection/settings
PUT  /collection/settings
GET  /collection/protocols
POST /collection/settings/apply
```

当前保存流程已经是：

```text
PUT /collection/settings
  -> UPSERT pg_collection_settings
  -> POST ${TRIDENT_SURICATA_AGENT_URLS}/agent/v1/suricata/filter/apply
```

分析侧已支持：

- `TRIDENT_SURICATA_AGENT_URLS`：逗号分隔的 agent 地址列表。
- `TRIDENT_SURICATA_AGENT_TOKEN`：调用 agent 时附带的 Bearer Token。
- agent 调用失败时返回 `502`，并在 `detail.agents[]` 中保留逐 agent 错误。

### 2.3 当前缺口

| 缝隙 | 当前表现 | 影响 |
|------|----------|------|
| 前端仍使用 Mock | `V3-ui-2/src/api/services/SettingService.ts` 只读写内存 Mock | 页面刷新后配置丢失，用户无法触发真实下发 |
| agent 健康信息过少 | `/agent/v1/health` 只返回固定 `ok: true`、容器名和配置路径 | 无法判断 Suricata 是否运行、配置是否实际生效 |
| 配置版本固定 | 分析侧编译出的 Suricata policy 始终为 `version: 1` | 无法判断期望配置与采集侧配置是否一致 |
| 重启后不验证 | agent 写入配置并调用 restart 后直接返回成功 | Suricata 可能因配置错误启动失败，但 API 仍报告成功 |
| 失败状态不持久化 | `pg_collection_settings` 只存期望配置 | 页面无法稳定展示上一次下发失败原因 |
| Redis 队列模式描述不一致 | 当前 split deploy 默认是 Redis `list` 模式 | 健康检查不能只使用 `XLEN`，必须根据 key 类型选择 `LLEN` 或 `XLEN` |

## 3. 推荐总体架构

```text
┌──────────────────────────────────────────────────────────────┐
│ V3-ui-2                                                      │
│ SettingService -> /api/collection/*                          │
└──────────────────────────────┬───────────────────────────────┘
                               │ HTTP
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ 分析机：trident-api                                          │
│ - pg_collection_settings：期望配置                           │
│ - pg_collection_agent_state：逐 agent 下发与健康状态（阶段二）│
│ - 编译 Suricata filter policy                                │
└──────────────────────────────┬───────────────────────────────┘
                               │ HTTP :19100
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ 采集机：suricata-agent                                       │
│ - 接收并校验 policy                                          │
│ - 原子写入 filter.json                                       │
│ - 重启并验证 Suricata                                        │
│ - 返回当前 policy 与健康信息（阶段二）                       │
└──────────────────────────────┬───────────────────────────────┘
                               │ Docker Socket
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ 采集机：Suricata -> Redis list/stream -> 分析侧 worker        │
└──────────────────────────────────────────────────────────────┘
```

控制面采用“分析侧主动调用采集侧 agent”的模式。阶段二仍推荐由分析侧主动拉取 agent 状态，而不是让 agent 主动回调分析 API。这样只需要从分析机访问采集机 `19100`，不会新增采集机到分析机的反向 HTTP 防火墙规则。

## 4. 阶段一：配置下发闭环

### 4.1 阶段一验收目标

用户在前端采集配置页点击确认后：

1. 前端调用真实 `PUT /api/collection/settings`。
2. `trident-api` 将期望配置保存到 PostgreSQL。
3. `trident-api` 将过滤策略下发到配置的全部 agent。
4. agent 校验并写入 `filter.json`，重启 Suricata。
5. agent 验证 Suricata 已恢复运行，再返回成功。
6. UI 展示逐 agent 下发结果。

### 4.2 配置模型

前端与分析侧保留现有配置模型：

```json
{
  "maxTrafficLimitGbps": 10,
  "sourceIpRanges": [
    { "startIp": "10.0.0.1", "endIp": "10.0.0.255" }
  ],
  "destIpRanges": [
    { "startIp": "0.0.0.0", "endIp": "255.255.255.255" }
  ],
  "protocols": ["TCP", "UDP", "HTTPS", "DNS"]
}
```

分析侧编译为采集侧 policy：

```json
{
  "version": 12,
  "updatedAt": "2026-06-02T10:30:00Z",
  "sourceIpRanges": [
    { "startIp": "10.0.0.1", "endIp": "10.0.0.255" }
  ],
  "destIpRanges": [
    { "startIp": "0.0.0.0", "endIp": "255.255.255.255" }
  ],
  "protocols": ["dns", "tcp", "tls"]
}
```

`version` 必须是单调递增的配置修订号，不能继续固定为 `1`。推荐在 `pg_collection_settings` 增加 `revision BIGINT NOT NULL DEFAULT 1`，每次保存时递增，并使用该值编译 policy。

`maxTrafficLimitGbps` 暂不进入 Suricata policy。它在阶段一仅作为期望配置保存，后续需单独选择 tc、XDP/eBPF 或采样策略实现。

### 4.3 分析侧 API 调整

#### `GET /collection/settings`

保留现有用途，返回当前期望配置。建议增加修订号：

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "settings": {
      "maxTrafficLimitGbps": 10,
      "sourceIpRanges": [],
      "destIpRanges": [],
      "protocols": []
    },
    "revision": 12
  }
}
```

如果需要降低前端切换成本，可以在阶段一暂时保留原有 `data` 结构，只在 `PUT` 响应中返回 apply 结果；前端状态展示稳定后再统一结构。

#### `PUT /collection/settings`

当前成功响应只返回 settings，需调整为同时返回保存结果与下发结果：

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "settings": {
      "maxTrafficLimitGbps": 10,
      "sourceIpRanges": [],
      "destIpRanges": [],
      "protocols": []
    },
    "revision": 12,
    "apply": {
      "applied": true,
      "agents": [
        {
          "name": "suricata-agent-1",
          "url": "http://172.16.88.12:19100",
          "ok": true,
          "response": {
            "applied": true,
            "version": 12,
            "suricataRunning": true
          }
        }
      ]
    }
  }
}
```

如果任一 agent 下发失败，保留当前 `502` 语义：

```json
{
  "detail": {
    "applied": false,
    "agents": [
      {
        "name": "suricata-agent-1",
        "url": "http://172.16.88.12:19100",
        "ok": false,
        "error": "http 502: ..."
      }
    ]
  }
}
```

注意：数据库中的期望配置已经保存成功，`502` 只表示“保存成功但未完成全部下发”。前端文案必须区分这两件事。

#### `POST /collection/settings/apply`

保留手动重试能力。接口从 PostgreSQL 读取当前期望配置和 revision，再次下发到全部 agent。

### 4.4 采集侧 agent 调整

继续使用 `streamtrident_services/capture/suricata-agent`，不要另起重复服务。

#### `POST /agent/v1/suricata/filter/apply`

请求体沿用现有 `SuricataFilterPolicy`，但增加严格校验：

- 校验 IPv4 格式。
- 校验 `startIp <= endIp`。
- 校验协议仅允许分析侧编译后的协议集合。
- 校验 `version >= 1`。
- 限制 IP 段数量，建议每个方向最多 `256` 条，避免生成过大的运行配置。
- 限制请求体大小，建议由反向代理或 FastAPI 中间件限制为 `256 KiB`。

推荐执行流程：

```text
校验 policy
  -> 将旧 filter.json 复制为 filter.json.previous
  -> 原子写入新 filter.json
  -> restart Suricata
  -> 轮询 Docker inspect，确认容器 running
  -> 成功：返回 version 与 policy hash
  -> 失败：恢复 previous，重新 restart，返回 502
```

agent 必须使用互斥锁串行执行 apply，避免两个请求并发写文件和重启容器。

建议响应：

```json
{
  "applied": true,
  "version": 12,
  "policyHash": "sha256:...",
  "container": "streamtrident-suricata-cic",
  "suricataRunning": true,
  "appliedAt": "2026-06-02T10:30:03Z"
}
```

#### Suricata 配置生效路径

当前 `suricata/docker/entrypoint.sh` 已在容器启动时读取：

```text
/etc/suricata-cic/filter.json
```

并将 IP 范围、协议转换为 CIC flow 输出过滤配置。因此阶段一不需要修改 flow 处理链路，只需要确保 agent 重启后验证 Suricata 正常运行。

`capture-filter.json` 与 `filter.json` 用途不同：

| 文件 | 用途 | 阶段一策略 |
|------|------|------------|
| `capture-filter.json` | 生成 AF_PACKET BPF，减少进入 Suricata 的包 | 保持静态运维配置 |
| `filter.json` | 控制 CIC flow 输出过滤 | 由分析侧动态下发 |

不要在阶段一将 UI 配置同时写入 `capture-filter.json`。BPF 变更影响更底层的抓包范围，应单独评审。

### 4.5 前端调整

修改 `V3-ui-2/src/api/services/SettingService.ts`：

```text
GET /collection/settings
PUT /collection/settings
GET /collection/protocols
POST /collection/settings/apply
```

统一通过现有 `src/utils/request.ts` 和 `/api` 代理访问 `trident-api`。

采集配置页增加下发结果区域：

| 状态 | UI 表现 |
|------|---------|
| 保存并全部下发成功 | 绿色提示：配置已保存并生效 |
| 保存成功，但一个或多个 agent 失败 | 黄色或红色提示：期望配置已保存，部分采集机未生效；展示 agent 名称、地址和错误 |
| 未配置 agent URL | 提示分析侧缺少 `TRIDENT_SURICATA_AGENT_URLS` |
| 用户点击重试 | 调用 `POST /collection/settings/apply`，不重复修改表单内容 |

同时补充 `src/utils/request.ts` 对 HTTP `502` 的专门处理。当前默认分支只能展示通用错误，无法友好展示 `detail.agents[]`。

### 4.6 阶段一数据库变更

新增 PostgreSQL migration：

```sql
ALTER TABLE pg_collection_settings
    ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL DEFAULT 1;

ALTER TABLE pg_collection_settings
    ADD COLUMN IF NOT EXISTS last_apply_json JSONB;

ALTER TABLE pg_collection_settings
    ADD COLUMN IF NOT EXISTS last_apply_at TIMESTAMPTZ;
```

保存配置时递增 revision。每次 apply 后，无论成功或失败，都将逐 agent 结果写入 `last_apply_json`，便于页面刷新后继续显示最近一次下发结果。

### 4.7 阶段一部署配置

采集机：

```dotenv
SURICATA_IFACE=ens35
REDIS_HOST_PORT=16379
SURICATA_AGENT_HOST_PORT=19100
TRIDENT_SURICATA_AGENT_TOKEN=<shared-secret>
```

分析机：

```dotenv
CAPTURE_REDIS_HOST=172.16.88.12
CAPTURE_REDIS_PORT=16379
TRIDENT_SURICATA_AGENT_URLS=http://172.16.88.12:19100
TRIDENT_SURICATA_AGENT_TOKEN=<shared-secret>
```

防火墙只允许分析机访问采集机：

```bash
sudo ufw allow from ANALYSIS_IP to any port 16379 proto tcp
sudo ufw allow from ANALYSIS_IP to any port 19100 proto tcp
```

生产部署必须设置非空 token。开发环境可以暂时允许空 token。

## 5. 阶段二：状态回传与健康展示

### 5.1 阶段二验收目标

前端能够区分：

```text
已保存 -> 已下发 -> 采集侧已生效
                  -> 下发失败
                  -> 状态未知 / agent 离线
```

并显示：

- agent 地址。
- 采集网卡。
- Suricata 是否运行。
- 当前生效的 filter version 和 policy hash。
- Redis 队列类型与长度。
- 最近一次健康采样时间。
- 最近一次错误。

### 5.2 状态回传方式

推荐分析侧主动拉取：

```text
trident-api -> GET http://capture-host:19100/agent/v1/status
```

不推荐优先实现 agent 主动回调：

```text
agent -> POST /collection/agents/report
```

主动拉取的优点：

- 复用阶段一已开放的 `19100`。
- 不新增采集机到分析机的 HTTP 防火墙规则。
- agent 不需要持有分析侧 API 地址和认证信息。
- 多采集机状态汇总逻辑集中在分析侧。

未来如果采集机数量明显增加，或需要秒级主动告警，再增加 report 模式。

### 5.3 agent 状态 API

新增：

```text
GET /agent/v1/status
```

该接口需要 Bearer Token，与 apply 使用同一认证逻辑。响应示例：

```json
{
  "ok": true,
  "agentId": "capture-172.16.88.12",
  "hostname": "capture-node-01",
  "sampledAt": "2026-06-02T10:35:00Z",
  "iface": "ens35",
  "filter": {
    "version": 12,
    "policyHash": "sha256:...",
    "updatedAt": "2026-06-02T10:30:00Z"
  },
  "suricata": {
    "container": "streamtrident-suricata-cic",
    "running": true,
    "status": "running"
  },
  "redis": {
    "host": "redis",
    "port": 6379,
    "key": "suricata:cic_flow",
    "type": "list",
    "length": 128
  }
}
```

Redis 队列长度的实现必须兼容两种模式：

```text
TYPE key == list   -> LLEN key
TYPE key == stream -> XLEN key
TYPE key == none   -> length = 0
其他类型           -> 返回 degraded 状态和错误信息
```

agent 只返回采样时刻与累计队列长度。速率建议由分析侧根据相邻采样计算，避免 agent 重启后丢失内存状态：

```text
queue_delta_per_second =
  (current.length - previous.length) / elapsed_seconds
```

注意：默认 `list` 模式下 worker 会 pop 数据，因此队列长度变化只能反映积压趋势，不能准确代表 Suricata 产出速率。若需要精确 flow ingest rate，应增加独立累计计数器，而不是仅依赖 `LLEN`。

### 5.4 分析侧状态 API

新增：

```text
GET  /collection/agents/status
POST /collection/agents/refresh
```

`GET /collection/agents/status` 返回数据库缓存状态，适合页面轮询。

`POST /collection/agents/refresh` 立即请求全部配置的 agent，将结果写入 PostgreSQL，再返回汇总结果。页面首次打开或用户点击刷新时调用。

推荐响应：

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "desiredRevision": 12,
    "agents": [
      {
        "name": "suricata-agent-1",
        "url": "http://172.16.88.12:19100",
        "reachable": true,
        "effective": true,
        "status": {
          "iface": "ens35",
          "suricata": { "running": true },
          "filter": { "version": 12 },
          "redis": { "type": "list", "length": 128 }
        },
        "sampledAt": "2026-06-02T10:35:00Z",
        "error": null
      }
    ]
  }
}
```

其中：

```text
effective = reachable
            AND status.suricata.running
            AND status.filter.version == desiredRevision
```

### 5.5 阶段二数据库变更

新增表：

```sql
CREATE TABLE IF NOT EXISTS pg_collection_agent_state (
    session_id VARCHAR(256) NOT NULL,
    agent_name VARCHAR(256) NOT NULL,
    agent_url TEXT NOT NULL,
    reachable BOOLEAN NOT NULL DEFAULT FALSE,
    effective BOOLEAN NOT NULL DEFAULT FALSE,
    desired_revision BIGINT,
    effective_revision BIGINT,
    status_json JSONB,
    last_error TEXT,
    sampled_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (session_id, agent_name)
);
```

状态缓存属于控制面，不应写入 ClickHouse。

### 5.6 定时刷新策略

阶段二第一版使用以下策略即可：

- 页面打开时调用一次 `POST /collection/agents/refresh`。
- 页面可每 `15` 秒调用一次 `GET /collection/agents/status`。
- 运维需要后台持续采样时，再增加独立轻量 poller 进程，每 `10` 到 `30` 秒刷新一次 agent 状态。

不要在 FastAPI 请求处理线程中创建无法管理生命周期的无限循环。后台 poller 应作为独立命令或独立 compose service。

## 6. 失败处理设计

### 6.1 保存成功、下发失败

这是合法且必须显式展示的状态：

```text
PostgreSQL desired config: revision 12
capture effective config:  revision 11
```

系统保留 revision 12 作为期望配置，页面展示“未生效”，允许用户重试 apply。

### 6.2 新配置导致 Suricata 无法运行

agent 需要自动回滚：

1. 恢复 `filter.json.previous`。
2. 再次重启 Suricata。
3. 返回 `502`，说明新配置未生效且已恢复旧版本。
4. 如果旧版本也无法恢复运行，返回更高优先级错误，提示需要运维介入。

### 6.3 多 agent 部分成功

不做跨采集机分布式事务。逐 agent 记录结果并返回：

```text
agent-1 -> revision 12 成功
agent-2 -> revision 11，连接超时
```

前端显示部分生效，并提供整体重试。重试必须是幂等的：同一 revision 重复写入与重启允许成功。

## 7. 安全设计

- 阶段一生产部署必须设置 `TRIDENT_SURICATA_AGENT_TOKEN`。
- apply 与 status 均校验 Bearer Token。
- 采集机防火墙仅允许指定分析机访问 `19100` 和 `16379`。
- agent 不接受任意容器名、任意文件路径或任意 Docker API 路径。容器名和配置路径只能来自 agent 环境变量。
- 日志不得打印 token。
- policy 请求体限制大小，IP 段数量限制上限。
- Docker Socket 权限风险需写入部署说明：agent 是高权限控制面，只允许在可信管理网络暴露。

## 8. 代码修改清单

### 阶段一

| 文件或目录 | 修改内容 |
|------------|----------|
| `streamtrident_services/capture/suricata-agent/app/main.py` | policy 严格校验、apply 锁、policy hash、Docker inspect、重启验证、失败回滚 |
| `streamtrident_services/capture/suricata-agent/tests/` | 新增 agent API 单元测试 |
| `streamtrident_services/analysis/trident/app/collection_settings.py` | revision 编译、保存 apply 结果、保留逐 agent 错误 |
| `streamtrident_services/analysis/trident/app/api.py` | `PUT` 返回 settings 与 apply 结果 |
| `streamtrident_services/analysis/trident/migrations/postgres/005_pg_collection_settings_apply_state.sql` | 增加 revision 与最近 apply 状态 |
| `V3-ui-2/src/api/services/SettingService.ts` | 移除 Mock 调用，接入真实 API |
| `V3-ui-2/src/views/setting/SettingView.tsx` | 展示保存与逐 agent 下发结果，增加手动重试 |
| `V3-ui-2/src/utils/request.ts` | 增加 `502 detail.agents[]` 的友好错误处理 |
| `streamtrident_services/docs/SPLIT_DEPLOY.md` | 补充 token、防火墙和 curl 验收命令 |

### 阶段二

| 文件或目录 | 修改内容 |
|------------|----------|
| `streamtrident_services/capture/suricata-agent/app/main.py` | 新增 `/agent/v1/status`、Docker 状态读取、Redis 队列采样 |
| `streamtrident_services/capture/compose.yaml` | 为 agent 增加 iface、Redis host、port、queue key、queue mode 环境变量 |
| `streamtrident_services/analysis/trident/app/collection_agent_state.py` | agent 状态拉取、缓存、effective 判断 |
| `streamtrident_services/analysis/trident/app/api.py` | 新增 `/collection/agents/status` 与 `/collection/agents/refresh` |
| `streamtrident_services/analysis/trident/migrations/postgres/006_pg_collection_agent_state.sql` | 新增 agent 状态表 |
| `V3-ui-2/src/views/setting/SettingView.tsx` | 展示已保存、已下发、已生效、健康信息 |
| `streamtrident_services/analysis/compose.yaml` | 可选：增加独立 agent status poller service |

## 9. 测试与验收

### 9.1 阶段一单元测试

采集侧 agent：

- 合法 policy 能原子写入配置并触发 restart。
- 非法 IP、反向 IP 范围、非法协议、非法 version 返回 `422`。
- token 错误返回 `401`。
- restart 后容器未恢复运行时回滚旧配置并返回 `502`。
- 并发 apply 被串行化。

分析侧：

- 保存配置后 revision 单调递增。
- policy 协议映射保持 `HTTPS -> tls`。
- 一个或多个 agent 失败时，API 返回 `502` 且保留逐 agent 结果。
- `POST /collection/settings/apply` 使用当前 revision 重试，不创建新 revision。

前端：

- `SettingService` 请求真实 API。
- 成功时展示全部 agent 生效。
- `502` 时展示“保存成功但下发失败”和逐 agent 错误。

### 9.2 阶段二单元测试

- agent status 能识别 Docker running 与 stopped。
- Redis `list` 使用 `LLEN`。
- Redis `stream` 使用 `XLEN`。
- Redis key 不存在时返回长度 `0`。
- 分析侧正确判断 `effective_revision == desired_revision`。
- agent 不可达时保留最近一次状态，并更新 `last_error`。

### 9.3 分机部署验收

采集机：

```bash
cd streamtrident_services/capture
cp .env.split .env
./start.sh
```

分析机验证 agent：

```bash
curl -sS \
  -H "Authorization: Bearer ${TRIDENT_SURICATA_AGENT_TOKEN}" \
  http://172.16.88.12:19100/agent/v1/health
```

阶段一验证下发：

```bash
curl -sS -X PUT http://127.0.0.1:9090/collection/settings \
  -H 'Content-Type: application/json' \
  -d '{
    "maxTrafficLimitGbps": 10,
    "sourceIpRanges": [{"startIp":"10.0.0.1","endIp":"10.0.0.255"}],
    "destIpRanges": [{"startIp":"0.0.0.0","endIp":"255.255.255.255"}],
    "protocols": ["TCP","UDP","HTTPS","DNS"]
  }'
```

采集机检查：

```bash
cat streamtrident_services/capture/suricata/config/filter.json
docker inspect -f '{{.State.Running}}' streamtrident-suricata-cic
```

阶段二验证状态：

```bash
curl -sS \
  -H "Authorization: Bearer ${TRIDENT_SURICATA_AGENT_TOKEN}" \
  http://172.16.88.12:19100/agent/v1/status

curl -sS -X POST http://127.0.0.1:9090/collection/agents/refresh
curl -sS http://127.0.0.1:9090/collection/agents/status
```

## 10. 实施顺序

### 阶段一

1. 为 `pg_collection_settings` 增加 revision 与最近 apply 状态。
2. 加固已有 `suricata-agent` apply 接口：校验、锁、验证、回滚。
3. 调整 `trident-api` 保存与重试响应。
4. 将前端 `SettingService` 从 Mock 切换到真实 API。
5. 在配置页展示逐 agent 下发结果。
6. 更新 split deploy 文档并完成分机验收。

### 阶段二

1. 为 agent 增加 `/agent/v1/status`。
2. 新增 `pg_collection_agent_state` 与分析侧状态聚合逻辑。
3. 增加 `/collection/agents/status` 与 `/collection/agents/refresh`。
4. 在前端展示期望 revision、实际 revision、健康状态与失败原因。
5. 根据运维需要决定是否增加独立 poller。

## 11. 后续议题

以下事项应单独设计，不阻塞阶段一和阶段二：

- `maxTrafficLimitGbps` 的实际执行方式。
- UI 配置是否需要同步到 AF_PACKET BPF `capture-filter.json`。
- 多分析节点部署时的 agent 状态 poller 主节点选举。
- 更精确的 Suricata flow 产出累计计数器与速率指标。
- HTTPS、mTLS 或内网 API Gateway。

