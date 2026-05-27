# StreamTrident Services Design

本目录按三服务边界组织：

- `suricata/`
- `redis/`
- `trident/`

三者是同一产品链路下的独立服务目录，不共享 Python 包，不互相 import，不放在同一个 `backend/app/modules` 下。

## 1. Service Boundary

```text
suricata/
  -> capture / normalize flow
  -> XADD suricata:cic_flow

redis/
  -> run Redis
  -> manage stream / consumer group / pending status

trident/
  -> consume suricata:cic_flow
  -> later: online preprocessing / inference / persistence
```

当前阶段只实现 Suricata 和 Redis 输入链路，Trident 只保留 consumer 壳子。

## 2. Directory Contract

每个服务目录都必须能独立理解和启动：

```text
service/
├── app/
├── config/
├── README.md
└── requirements.txt
```

允许例外：

- `redis/compose.yaml`：Redis 基础设施启动
- `trident/migrations/`：Trident 后续负责持久化，因此数据库迁移放在 Trident 服务下

## 3. Redis Stream Contract

输入 Stream：

```text
suricata:cic_flow
```

Consumer group：

```text
trident-online
```

每条消息表示一条已形成的 flow feature record。最小字段：

- `event_type`
- `event_time`
- `session_id`
- `flow_uid`
- `src_ip`
- `dst_ip`
- `src_port`
- `dst_port`
- `protocol`
- `source_flow_id`
- `features_json`
- `raw_event_json`

## 4. Current Phase

当前阶段目标：

1. Redis 能独立启动。
2. Redis Stream 和 consumer group 能初始化。
3. Suricata 服务能接收 JSON flow 并写入 `suricata:cic_flow`。
4. Trident worker 能独立消费 Redis Stream，但不实现算法。

## 5. Out Of Scope

- Trident 在线算法
- 前端
- CSV / PCAP replay
- benchmark / stress tools
- `trident_demo` 引用
