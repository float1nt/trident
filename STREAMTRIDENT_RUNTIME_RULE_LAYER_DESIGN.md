# StreamTrident 实时规则层扩展设计

## 1. 目标与边界

本文档定义 `streamtrident_services/analysis/trident` 实时规则层的扩展方案。
目标是在**不修改 Suricata 采集字段**的前提下，读取现有 CIC flow 特征，
在学习器内部聚合流级证据，并扩展可识别的攻击类型。

本文档与根目录 `LEARNER_METRIC_AND_RULE_FORMULAS.md` 分工不同：

| 文档 | 范围 |
|---|---|
| `LEARNER_METRIC_AND_RULE_FORMULAS.md` | `trident_stream` 离线研究链路中的拓扑参考规则 |
| `STREAMTRIDENT_RUNTIME_RULE_LAYER_DESIGN.md` | `streamtrident_services/analysis/trident` 实时生产链路中的学习器定性规则 |

本文档是待实施设计。第 2.1 节列出的图谱规则已经落地；第 2.2 节、
`metric_version=5` 和 P0/P1/P2 模块调整均为后续实现目标。

实时规则仍然只给**学习器**定性。单条 flow、主机子图和跨窗口主机画像都是
学习器内部证据，不单独产生最终告警对象。

```text
learner records
  -> topology metrics
  -> flow aggregate metrics
  -> optional host-window state
  -> learner rules
  -> pg_learner.rule_json
  -> pg_learner_snapshot.rule_json
```

本阶段不覆盖以下能力：

- 不增加 SNI、ALPN、JA3/JA4、证书、TLS Session ID 或 Ticket。
- 不对 TLS payload 解密。
- 不接入域名、IP、云厂商、IM、VPN 或矿池威胁情报。
- 不识别必须依赖解密内容的 Webshell、盲注或畸形应用载荷。

---

## 2. 输出攻击类型与一级类别

一级类别固定使用原始业务表格中的命名：

```text
恶意攻击类
数据泄露类
异常行为类
```

### 2.1 已有图谱规则

这些类型已可使用现有拓扑指标输出：

| 内部标签 | 展示名称 | 一级类别 | 主要证据层 |
|---|---|---|---|
| `ENCRYPTED_INTERNAL_SCAN` | 加密探测内网端口 | 恶意攻击类 | 图谱 |
| `ENCRYPTED_PROTOCOL_BRUTE_FORCE` | 加密协议暴力破解 | 恶意攻击类 | 图谱，后续补充流级证据 |
| `P2P_BOTNET_COMMUNICATION` | P2P 僵尸网络通信 | 恶意攻击类 | 图谱 |
| `ENCRYPTED_AUTOMATED_VULNERABILITY_SWEEP` | 加密自动化漏洞刷网 | 恶意攻击类 | 图谱 |
| `ENCRYPTED_MULTI_HOP_PROXY` | 密态非法多跳代理 | 恶意攻击类 | 图谱 |

### 2.2 本文档新增的流级聚合规则

这些类型只依赖现有 CIC flow 字段，可以直接扩展：

| 内部标签 | 展示名称 | 一级类别 | 是否需要跨窗口状态 |
|---|---|---|---|
| `C2_HEARTBEAT_CONNECTION` | 恶意程序保活连线 | 恶意攻击类 | 否 |
| `C2_LONG_SILENT_CONTROL` | 长静默连接远程受控通信 | 恶意攻击类 | 否 |
| `CENTRALIZED_DATA_EXFILTRATION` | 暴力集中式数据外传 | 数据泄露类 | 否 |
| `BATCHED_SLOW_DATA_EXFILTRATION` | 分批慢速窃取数据 | 数据泄露类 | 是 |
| `UNAUTHORIZED_COMMERCIAL_VPN` | 未授权商业 VPN 穿透 | 异常行为类 | 否 |
| `CRYPTOMINING_POOL_CALLBACK` | 加密矿池回连 | 恶意攻击类 | 是 |
| `INTERACTIVE_REVERSE_SHELL` | 远程命令操控设备 | 恶意攻击类 | 否 |
| `RANSOMWARE_KEY_EXFILTRATION` | 勒索密钥快速外发数据 | 数据泄露类 | 否 |
| `API_RESOURCE_EXTORTION` | 接口爬取数据并勒索 | 数据泄露类 | 是 |

`ENCRYPTED_PROTOCOL_BRUTE_FORCE` 和 `ENCRYPTED_INTERNAL_SCAN` 已存在，但本设计会
补充流级证据，提高区分度。

---

## 3. 当前数据链路与必要调整

### 3.1 当前行为

Redis 消息进入 `FlowLoader` 时，原始 CIC 特征先写入：

```text
FlowRecord.features_json
```

随后 `OnlineEngine.process_window()` 调用 `preprocess_records()`。当
`feature_profile=compact_stats_no_env` 时，`features_json` 会被重写为紧凑特征集合。

这会丢弃部分规则需要、但 AE 模型不需要的字段。例如：

```text
RST Flag Count
Flow IAT Max
Flow IAT Min
Idle Max
Idle Min
Fwd Packet Length Max
Total Fwd Packet 以外的补充统计字段
```

### 3.2 设计要求：模型特征与规则特征分离

新增两个字段集合：

```python
MODEL_FEATURE_COLUMNS = COMPACT_STATS_FEATURES
RULE_FEATURE_COLUMNS = [
    "Flow Duration",
    "Total Fwd Packet",
    "Total Bwd packets",
    "Total Length of Fwd Packet",
    "Total Length of Bwd Packet",
    "Fwd Packet Length Mean",
    "Fwd Packet Length Std",
    "Fwd Packet Length Max",
    "Bwd Packet Length Mean",
    "Bwd Packet Length Std",
    "Bwd Packet Length Max",
    "Flow Bytes/s",
    "Flow Packets/s",
    "Flow IAT Mean",
    "Flow IAT Std",
    "Flow IAT Max",
    "Flow IAT Min",
    "Fwd IAT Mean",
    "Fwd IAT Std",
    "Bwd IAT Mean",
    "Bwd IAT Std",
    "SYN Flag Count",
    "RST Flag Count",
    "ACK Flag Count",
    "PSH Flag Count",
    "Down/Up Ratio",
    "Active Mean",
    "Active Max",
    "Idle Mean",
    "Idle Max",
    "Fwd Bulk Rate Avg",
    "Bwd Bulk Rate Avg",
]
```

推荐实现方式：

```text
FlowRecord.features_json
  保留 RULE_FEATURE_COLUMNS，供规则层读取

OnlineEngine._records_to_matrix()
  只从 MODEL_FEATURE_COLUMNS 构建 AE 输入矩阵
```

不要为了 AE 输入紧凑而破坏规则字段。ClickHouse 中的 `features_json` 也应保存
规则字段投影，使 `app.rebuild_learner_rules` 能够重建历史规则。

### 3.3 规则计算范围

实时审计使用单个学习器最近最多 `10000` 条已分配流：

```text
F_learner_recent =
  learner_record_histories[learner_name][-10000:]
```

历史重建使用 ClickHouse 中该学习器最近最多 `10000` 条已分配流：

```text
WHERE assigned_learner = learner_name
  AND is_unknown = 0
ORDER BY event_time DESC
LIMIT 10000
```

---

## 4. 通用定义

对一个学习器的流集合：

```text
F = {f_1, f_2, ..., f_n}
n = |F|
```

定义：

```text
ratio(condition) = count(f in F where condition(f)) / max(1, n)

P95(X) = X 的 95 分位数
Median(X) = X 的中位数

CV(X) =
  std(X) / max(abs(mean(X)), eps)

SafeRatio(a, b, cap) =
  min(cap, a / max(b, eps))
```

统一时间单位：

| CIC 字段 | 设计单位 |
|---|---|
| `Flow Duration` | 微秒 |
| `Flow IAT *` | 微秒 |
| `Idle *` | 微秒 |
| `Active *` | 微秒 |

所有规则阈值必须在代码中集中配置，并标注版本。本文给出的阈值是首版工程默认值，
上线前需使用真实业务流量重新标定。

---

## 5. 学习器级流聚合指标

新增：

```text
learner_metric_json.flow_aggregate
```

### 5.1 连接时长与静默

| 指标 | 公式 | 用途 |
|---|---|---|
| `duration_p95_us` | `P95(Flow Duration)` | 长连接 |
| `long_connection_ratio` | `ratio(Flow Duration >= 300_000_000)` | 超过 5 分钟的流占比 |
| `very_long_connection_ratio` | `ratio(Flow Duration >= 3_600_000_000)` | 超过 1 小时的流占比 |
| `idle_p95_us` | `P95(Idle Max)` | 长静默 |
| `long_idle_ratio` | `ratio(Idle Max >= 300_000_000)` | 超过 5 分钟静默的流占比 |
| `idle_active_alternation_ratio` | `ratio(Idle Max >= 10 * max(Active Mean, eps))` | 长静默后短暂活动 |

### 5.2 周期与时间间隔

单条 flow 内的周期稳定度：

```text
flow_iat_cv(f) =
  Flow IAT Std(f) / max(abs(Flow IAT Mean(f)), eps)
```

学习器聚合指标：

| 指标 | 公式 | 用途 |
|---|---|---|
| `stable_iat_ratio` | `ratio(flow_iat_cv <= 0.15)` | 心跳和自动化任务 |
| `very_stable_iat_ratio` | `ratio(flow_iat_cv <= 0.05)` | 高精度周期行为 |
| `small_iat_mean_ratio` | `ratio(Flow IAT Mean <= 1_500_000)` | 高频 API 请求 |
| `event_interval_cv` | 对学习器相邻 `event_time` 间隔计算 `CV` | 跨 flow 固定周期 |
| `fixed_interval_event_ratio` | 相邻 `event_time` 间隔落在中位数 ±5% 内的比例 | 定时请求 |

注意：`Flow IAT Mean/Std` 只能描述**单条 flow 内部**的包间隔。检测跨连接心跳时，
必须同时使用 `event_time` 相邻间隔，不能只依赖单条 flow 的 IAT。

### 5.3 字节、包长与方向

对每条 flow：

```text
fwd_bytes(f) = Total Length of Fwd Packet
bwd_bytes(f) = Total Length of Bwd Packet
total_bytes(f) = fwd_bytes(f) + bwd_bytes(f)

outbound_ratio(f) =
  SafeRatio(fwd_bytes(f), bwd_bytes(f), 100)

packet_direction_imbalance(f) =
  1 - min(FwdPackets(f), BwdPackets(f))
        / max(FwdPackets(f) + BwdPackets(f), 1)
```

说明：这里的 `outbound` 表示 CIC flow 的前向方向。若业务需要严格区分企业内网出向，
还必须结合 `src_ip` 是否属于受管内网网段。不能把所有前向方向自动等价为企业出向。

| 指标 | 公式 | 用途 |
|---|---|---|
| `fwd_bwd_bytes_ratio` | `SafeRatio(sum(fwd_bytes), sum(bwd_bytes), 100)` | 集中式外传 |
| `outbound_heavy_ratio` | `ratio(outbound_ratio >= 20)` | 出向显著大于入向 |
| `large_fwd_packet_ratio` | `ratio(Fwd Packet Length Mean >= 1200)` | 持续大包 |
| `tiny_bidirectional_flow_ratio` | `ratio(total_bytes <= 512 AND FwdPackets > 0 AND BwdPackets > 0)` | 心跳、矿池 |
| `small_bidirectional_packet_ratio` | `ratio(Fwd Packet Length Mean <= 256 AND Bwd Packet Length Mean <= 256)` | 小包交互 |
| `packet_direction_imbalance` | `1 - sum(min(FwdPackets, BwdPackets)) / sum(FwdPackets + BwdPackets)` | 学习器整体方向不平衡 |
| `full_duplex_bytes_balance_ratio` | `ratio(0.33 <= fwd_bytes / max(total_bytes, 1) <= 0.67)` | VPN 双向流 |
| `bidirectional_bulk_ratio` | `ratio(fwd_bytes >= 1 MiB AND bwd_bytes >= 1 MiB)` | 双向高流量 |

### 5.4 速率、短连接与 TCP 标志

| 指标 | 公式 | 用途 |
|---|---|---|
| `low_rate_long_connection_ratio` | `ratio(Flow Duration >= 300s AND Flow Bytes/s <= 1024)` | 矿池、反弹 Shell |
| `high_rate_outbound_ratio` | `ratio(fwd_bytes >= 1 MiB AND Flow Bytes/s >= 1 MiB/s)` | 集中式外传 |
| `short_connection_ratio` | `ratio(Flow Duration <= 2_000_000)` | 扫描、暴力破解、密钥外发 |
| `syn_only_short_ratio` | `ratio(short AND SYN > 0 AND ACK = 0)` | 扫描握手 |
| `rst_flow_ratio` | `ratio(RST Flag Count > 0)` | 暴力破解 |
| `psh_flow_ratio` | `ratio(PSH Flag Count > 0)` | 交互型连接辅助证据 |

### 5.5 payload 样本辅助指标

现有采集器可以保存最多 `256` 字节 payload 样本。payload 仅作为辅助证据：

| 指标 | 公式 | 用途 |
|---|---|---|
| `payload_sample_available_ratio` | 有 payload 样本的流占比 | 证据完整度 |
| `payload_sample_entropy_p95` | payload 样本 Shannon entropy 的 P95 | 高熵密钥包辅助证据 |
| `payload_single_outbound_ratio` | 单向 payload 样本流占比 | 勒索密钥外发辅助证据 |

payload 保留策略目前只在冷启动完成后保留 unknown 或非良性学习器的样本。因此，
`RANSOMWARE_KEY_EXFILTRATION` 的首版规则不能强制依赖 payload 熵，否则会漏掉首次流。

---

## 6. 跨窗口主机状态

以下攻击不能只看单次学习器审计，需要在学习器内部维护主机窗口状态：

```text
host_window_state[(learner_name, subject_ip)]
```

推荐保留最近 `7d` 的按分钟 bucket：

```json
{
  "learner_name": "NEW_12",
  "subject_ip": "10.0.0.8",
  "minute_buckets": [
    {
      "minute": "2026-06-02T10:30:00Z",
      "flow_count": 8,
      "fwd_bytes": 10485760,
      "bwd_bytes": 1024,
      "large_fwd_flow_count": 4,
      "event_interval_cv": 0.02
    }
  ]
}
```

新增指标：

| 指标 | 公式 | 用途 |
|---|---|---|
| `active_exfil_window_count_24h` | 24 小时内出现出向大包的分钟 bucket 数 | 分批外传 |
| `active_exfil_day_count_7d` | 7 天内出现出向大包的自然日数 | 长期慢速外传 |
| `external_dst_ip_rotation_count_24h` | 24 小时内不同外部目标 IP 数 | 慢速外传目标轮换 |
| `fixed_interval_window_count_24h` | 24 小时内满足固定间隔请求的 bucket 数 | API 资源勒索 |
| `non_443_low_rate_window_count_24h` | 24 小时内非 443 低速小包 bucket 数 | 矿池回连 |

---

## 7. 规则公式

### 7.1 `C2_HEARTBEAT_CONNECTION`

展示名称：恶意程序保活连线  
一级类别：恶意攻击类

规则：

```text
stable_period =
  stable_iat_ratio >= 0.70
  OR (
    event_interval_cv <= 0.15
    AND fixed_interval_event_ratio >= 0.70
  )

small_payload =
  tiny_bidirectional_flow_ratio >= 0.60
  OR small_bidirectional_packet_ratio >= 0.70

C2_HEARTBEAT_CONNECTION =
  recent_record_count >= 20
  AND stable_period
  AND small_payload
```

防误报：

- 健康检查、监控探针和已登记 IoT 上报源进入白名单。
- 单独命中心跳规则时可以降低风险级别；与未知学习器、外部目标或非常用端口同时命中时升级。

### 7.2 `C2_LONG_SILENT_CONTROL`

展示名称：长静默连接远程受控通信  
一级类别：恶意攻击类

规则：

```text
C2_LONG_SILENT_CONTROL =
  recent_record_count >= 5
  AND (
    very_long_connection_ratio >= 0.20
    OR long_connection_ratio >= 0.60
  )
  AND long_idle_ratio >= 0.40
  AND idle_active_alternation_ratio >= 0.40
  AND small_bidirectional_packet_ratio >= 0.50
```

### 7.3 `CENTRALIZED_DATA_EXFILTRATION`

展示名称：暴力集中式数据外传  
一级类别：数据泄露类

规则：

```text
CENTRALIZED_DATA_EXFILTRATION =
  recent_record_count >= 5
  AND src_private_ip_share >= 70
  AND dst_public_ip_share >= 70
  AND fwd_bwd_bytes_ratio >= 20
  AND outbound_heavy_ratio >= 0.60
  AND (
    large_fwd_packet_ratio >= 0.60
    OR high_rate_outbound_ratio >= 0.40
  )
```

### 7.4 `BATCHED_SLOW_DATA_EXFILTRATION`

展示名称：分批慢速窃取数据  
一级类别：数据泄露类

规则：

```text
BATCHED_SLOW_DATA_EXFILTRATION =
  src_private_ip_share >= 70
  AND dst_public_ip_share >= 70
  AND active_exfil_window_count_24h >= 6
  AND active_exfil_day_count_7d >= 2
  AND external_dst_ip_rotation_count_24h >= 2
  AND fwd_bwd_bytes_ratio >= 8
```

说明：

- 该规则必须使用跨窗口主机状态。
- IP 轮换不是强制的攻击特征，但在首版中用于降低备份任务误报。

### 7.5 `UNAUTHORIZED_COMMERCIAL_VPN`

展示名称：未授权商业 VPN 穿透  
一级类别：异常行为类

规则：

```text
UNAUTHORIZED_COMMERCIAL_VPN =
  recent_record_count >= 5
  AND long_connection_ratio >= 0.50
  AND full_duplex_bytes_balance_ratio >= 0.60
  AND bidirectional_bulk_ratio >= 0.30
  AND dst_public_ip_share >= 70
```

防误报：

- 远程办公出口、视频会议、数据库同步和合法专线进入白名单。
- 没有资产策略白名单时，此规则只适合输出中等风险。

### 7.6 `CRYPTOMINING_POOL_CALLBACK`

展示名称：加密矿池回连  
一级类别：恶意攻击类

规则：

```text
CRYPTOMINING_POOL_CALLBACK =
  src_private_ip_share >= 70
  AND dst_public_ip_share >= 70
  AND dst_443_share <= 20
  AND low_rate_long_connection_ratio >= 0.50
  AND tiny_bidirectional_flow_ratio >= 0.50
  AND non_443_low_rate_window_count_24h >= 3
```

### 7.7 `INTERACTIVE_REVERSE_SHELL`

展示名称：远程命令操控设备  
一级类别：恶意攻击类

规则：

```text
INTERACTIVE_REVERSE_SHELL =
  recent_record_count >= 3
  AND long_connection_ratio >= 0.40
  AND low_rate_long_connection_ratio >= 0.40
  AND small_bidirectional_packet_ratio >= 0.60
  AND psh_flow_ratio >= 0.30
  AND dst_443_share >= 50
```

边界：

- 当前 CIC 聚合字段只能近似描述交互式小包连接。
- “人类打字速度分布”和“入向紧随出向”需要包级序列，首版不作为硬条件。

### 7.8 `RANSOMWARE_KEY_EXFILTRATION`

展示名称：勒索密钥快速外发数据  
一级类别：数据泄露类

规则：

```text
RANSOMWARE_KEY_EXFILTRATION =
  short_connection_ratio >= 0.70
  AND src_private_ip_share >= 70
  AND dst_public_ip_share >= 70
  AND ratio(
    Flow Duration < 2_000_000
    AND 256 <= fwd_bytes <= 512
    AND bwd_bytes <= 64
  ) >= 0.50
```

增强证据：

```text
payload_sample_entropy_p95 >= 7.0 bits/byte
```

payload 熵只提高置信度，不作为首版硬条件。

### 7.9 `API_RESOURCE_EXTORTION`

展示名称：接口爬取数据并勒索  
一级类别：数据泄露类

规则：

```text
API_RESOURCE_EXTORTION =
  dst_443_share >= 70
  AND very_stable_iat_ratio >= 0.60
  AND fixed_interval_event_ratio >= 0.80
  AND event_interval_cv <= 0.05
  AND fixed_interval_window_count_24h >= 6
```

边界：

- 当前没有 URL 路径，首版只能识别固定 HTTPS 服务上的自动化资源抓取行为。
- 监控任务、同步任务和定时批处理必须进入白名单。

### 7.10 增强 `ENCRYPTED_PROTOCOL_BRUTE_FORCE`

展示名称：加密协议暴力破解  
一级类别：恶意攻击类

现有图谱规则保持不变，新增流级支撑条件：

```text
bruteforce_flow_support =
  short_connection_ratio >= 0.60
  AND rst_flow_ratio >= 0.30
  AND dst_port_top1_concentration >= 70

ENCRYPTED_PROTOCOL_BRUTE_FORCE =
  existing_graph_rule
  AND (
    bruteforce_flow_support
    OR edge_reuse_ratio >= 65
  )
```

### 7.11 增强 `ENCRYPTED_INTERNAL_SCAN`

展示名称：加密探测内网端口  
一级类别：恶意攻击类

现有图谱规则保持不变，新增流级支撑条件：

```text
scan_flow_support =
  short_connection_ratio >= 0.60
  AND syn_only_short_ratio >= 0.30

ENCRYPTED_INTERNAL_SCAN =
  existing_graph_rule
  AND (
    scan_flow_support
    OR host_max_out_degree_ratio >= 65
  )
```

---

## 8. 规则优先级与冲突处理

同一学习器可以命中多个规则。`rule_json.attack_types[]` 全量保存命中类型，
第一项作为页面默认展示类型。

建议优先级：

| 优先级 | 攻击类型 |
|---:|---|
| 100 | `RANSOMWARE_KEY_EXFILTRATION` |
| 95 | `CENTRALIZED_DATA_EXFILTRATION` |
| 90 | `BATCHED_SLOW_DATA_EXFILTRATION` |
| 85 | `ENCRYPTED_INTERNAL_SCAN` |
| 82 | `ENCRYPTED_PROTOCOL_BRUTE_FORCE` |
| 80 | `API_RESOURCE_EXTORTION` |
| 78 | `INTERACTIVE_REVERSE_SHELL` |
| 75 | `C2_LONG_SILENT_CONTROL` |
| 72 | `C2_HEARTBEAT_CONNECTION` |
| 70 | `CRYPTOMINING_POOL_CALLBACK` |
| 65 | `UNAUTHORIZED_COMMERCIAL_VPN` |

已存在的纯图谱规则继续参与排序：

```text
P2P_BOTNET_COMMUNICATION
ENCRYPTED_AUTOMATED_VULNERABILITY_SWEEP
ENCRYPTED_MULTI_HOP_PROXY
```

冲突处理原则：

1. 数据泄露类精确规则优先于通用 VPN 或 C2 形态。
2. 扫描规则优先于通用自动化周期规则。
3. 矿池规则要求非 443 外部目标，避免与反弹 Shell 冲突。
4. 页面默认展示最高优先级类型，但保留全部命中规则和证据。

---

## 9. 输出结构

### 9.1 `learner_metric_json`

```json
{
  "metric_version": 5,
  "flow_count": 1250,
  "recent_record_count": 10000,
  "topology": {},
  "flow_aggregate": {
    "duration_p95_us": 420000000,
    "long_connection_ratio": 0.72,
    "stable_iat_ratio": 0.81,
    "fwd_bwd_bytes_ratio": 24.6,
    "rst_flow_ratio": 0.04
  },
  "host_window_state_summary": {
    "active_exfil_window_count_24h": 8,
    "active_exfil_day_count_7d": 3
  }
}
```

### 9.2 `rule_json`

```json
{
  "version": 2,
  "rule_set": {
    "id": "learner_attack_rules",
    "version": "2026-06-flow-aggregate-v1"
  },
  "target": {
    "learner_name": "NEW_12"
  },
  "attack_types": [
    {
      "attack_type": "CENTRALIZED_DATA_EXFILTRATION",
      "attack_category": "数据泄露类",
      "confidence": 0.91,
      "evidence_rules": [
        "learner_centralized_data_exfiltration"
      ],
      "explain": "长会话中出向流量显著高于入向，并持续传输较大报文。"
    }
  ],
  "evidence": {
    "learner_metric_json": {},
    "host_evidence_json": {},
    "flow_aggregate_json": {},
    "host_window_state_summary": {}
  },
  "rules": [
    {
      "rule_id": "learner_centralized_data_exfiltration",
      "rule_version": "v1",
      "target_attack_type": "CENTRALIZED_DATA_EXFILTRATION",
      "attack_category": "数据泄露类",
      "match": "strong",
      "source": "flow_aggregate_json"
    }
  ]
}
```

---

## 10. 正常流量兜底

`BENIGN_NORMAL` 只能作为未命中攻击规则后的兜底，不应通过过严条件把大量正常实时流量
推入 `UNKNOWN_SUSPECTED`。

首版建议：

```text
BENIGN_NORMAL =
  no_attack_rule_matched
  AND packet_direction_imbalance <= 65
  AND edge_reuse_ratio <= 60
  AND host_max_in_degree_ratio <= 70
  AND host_max_out_degree_ratio <= 70

UNKNOWN_SUSPECTED =
  no_attack_rule_matched
  AND NOT BENIGN_NORMAL
```

不要将 `temporal_burst` 作为 `BENIGN_NORMAL` 的硬门槛。实时 flush 会让正常短批次产生较高
`temporal_burst`，导致系统性误报。

---

## 11. 模块调整

建议在现有目录中增加：

```text
streamtrident_services/analysis/trident/app/runtime/
├── preprocessing.py              # 分离 MODEL_FEATURE_COLUMNS 与 RULE_FEATURE_COLUMNS
├── flow_aggregate_metrics.py     # 新增：计算学习器流级聚合指标
├── host_window_state.py          # 新增：跨窗口主机状态
├── quality.py                    # 合并拓扑、流级、跨窗口证据并匹配规则
└── online_engine.py              # 调用聚合器，维护最近流与状态
```

职责：

| 模块 | 职责 |
|---|---|
| `preprocessing.py` | 归一化字段；模型特征与规则特征分离 |
| `flow_aggregate_metrics.py` | 对单个学习器最近流计算流级聚合指标 |
| `host_window_state.py` | 维护按学习器、主机和分钟聚合的有限窗口状态 |
| `quality.py` | 执行规则，不直接访问数据库 |
| `online_engine.py` | 管理输入、调用计算器和持久化所需输出 |

---

## 12. 实施顺序

### P0：字段保留与基础指标

1. 分离 `MODEL_FEATURE_COLUMNS` 和 `RULE_FEATURE_COLUMNS`。
2. 确保 ClickHouse `features_json` 保存规则字段投影。
3. 新增 `flow_aggregate_metrics.py`。
4. 增强 `ENCRYPTED_INTERNAL_SCAN` 和 `ENCRYPTED_PROTOCOL_BRUTE_FORCE`。

### P1：无需跨窗口状态的规则

依次实现：

```text
C2_HEARTBEAT_CONNECTION
C2_LONG_SILENT_CONTROL
CENTRALIZED_DATA_EXFILTRATION
UNAUTHORIZED_COMMERCIAL_VPN
INTERACTIVE_REVERSE_SHELL
RANSOMWARE_KEY_EXFILTRATION
```

### P2：跨窗口状态

新增 `host_window_state.py`，然后实现：

```text
BATCHED_SLOW_DATA_EXFILTRATION
CRYPTOMINING_POOL_CALLBACK
API_RESOURCE_EXTORTION
```

---

## 13. 测试与标定

### 13.1 单元测试

每个指标至少覆盖：

- 缺失字段时返回 `null` 或标记 `sample_insufficient`，不能假装为正常值。
- 零字节、零包和除零处理。
- P95、ratio 和 CV 的边界值。
- `MODEL_FEATURE_COLUMNS` 精简后，`RULE_FEATURE_COLUMNS` 仍然保留。
- 实时审计与 `app.rebuild_learner_rules` 使用相同字段和公式。

每个规则至少覆盖：

- 强命中样本。
- 单一关键条件不满足时不命中。
- 与容易混淆规则同时满足时，优先级正确。
- `attack_category` 使用原表格类别名称。

### 13.2 真实流量标定

上线前必须使用至少一周真实业务流量统计：

```text
每个 flow_aggregate 指标的 P50 / P90 / P95 / P99
每个规则的命中学习器数量
每个规则命中的主机数量
BENIGN_NORMAL / UNKNOWN_SUSPECTED 比例
人工复核后的误报率
```

初始阈值只作为工程默认值。完成真实流量标定后，将规则集版本升级：

```text
2026-06-flow-aggregate-v1
  -> 2026-06-flow-aggregate-v2
```

---

## 14. 已知限制

1. `outbound` 方向必须结合受管内网网段判断，不能仅依赖 CIC flow 发起方向。
2. CIC flow 聚合字段无法完整还原 SPLT 包长序列和 IPT 包间隔序列。
3. 反弹 Shell 的人类打字速度、请求响应跟随关系需要包级序列才能精确确认。
4. API 资源勒索在没有 URL 路径时只能识别自动化 HTTPS 抓取形态。
5. VPN、心跳、定时 API 和矿池规则均需要白名单降低正常业务误报。
6. payload 样本只保留最多 `256` 字节，且受 payload 保留策略影响。
7. 跨窗口规则必须限制状态大小，并设置 TTL，避免长期运行内存无限增长。
