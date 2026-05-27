# StreamTrident 学习器规则层定性文档

本文档定义 StreamTrident 的学习器规则层。规则层的目标只有一个：**给学习器定性**。

规则层不再拆成独立的“主机规则”和“学习器规则”。主机级特征、流级特征、拓扑特征都只是单个学习器内部的证据来源，最终输出必须写回学习器：

```text
pg_learner.rule_json
pg_learner.rule_set_id
pg_learner.rule_set_version
pg_learner_snapshot.rule_json
```

---

## 1. 核心口径

统一口径如下：

```text
学习器定性规则
  ├── learner topology features  学习器整体拓扑特征
  ├── host features              学习器内部主机视角特征
  └── flow features              学习器内部流级特征，后续发展方向
```

其中：

- `learner topology features`：对该 learner 的全部 flow 计算 v4 拓扑指标。
- `host features`：在该 learner 内部，按主机/IP 子图计算主机视角证据。
- `flow features`：在该 learner 内部，对单条 flow/request 识别 XSS、SQLi 等细粒度证据，后续实现。

最终输出仍然是学习器级攻击类型：

```text
learner_name -> PORT_SCAN / HOST_SCAN / DDOS_VICTIM / DOS_ATTACKER / ...
```

主机证据和流级证据可以进入 `rule_json.evidence`，但不能作为独立于学习器的最终规则对象。

---

## 2. 输入范围

所有规则计算都必须限制在单个学习器内部。

```text
F_learner = ch_flow 中 assigned_learner = learner_name 的 flow 集合
```

在 `F_learner` 内部，可以继续按主机切分：

```text
F_host_source(ip)      = {f in F_learner | f.src_ip = ip}
F_host_destination(ip) = {f in F_learner | f.dst_ip = ip}
```

禁止直接用全局主机画像给学习器下结论。主机证据必须来自当前 learner 内部。

历史查询必须读取当时的学习器快照：

```text
pg_learner_snapshot.rule_json
pg_learner_snapshot.learner_metric_json
pg_learner_snapshot.topology_json
```

不能用当前 `pg_learner` 状态解释历史时间段。

---

## 3. 数据流

规则层在 Live flush 中执行。P0 可以先不启用规则，但数据流设计必须按下面的边界预留。

```text
learner flows
  -> learner_metric_builder
       生成 learner_metric_json
  -> learner_host_feature_builder
       在该 learner 内部按 host_ip 生成 host_evidence_json
  -> flow_feature_builder       # 后续
       在该 learner 内部生成 flow_evidence_json
  -> rule_engine
       读取规则配置并匹配攻击类型
  -> rule_result_builder
       生成 pg_learner.rule_json
```

关键约束：

- `learner_metric_json` 面向学习器整体。
- `host_evidence_json` 面向学习器内部 top host 子图。
- `flow_evidence_json` 是后续发展方向，主要处理主机聚合后容易被稀释的攻击。
- `rule_engine` 只执行规则，不访问数据库。
- `rule_result_builder` 只聚合命中结果，不重新计算指标。

---

## 4. 模块结构

放在 `trident/services/` 下：

```text
trident/services/
├── learner_metric_builder.py       # 对 learner 全部 flow 计算 v4 指标
├── learner_host_feature_builder.py # 对 learner 内部 host 子图计算主机证据
├── flow_feature_builder.py         # 后续：对 learner 内部 flow/request 计算流级证据
├── rule_config_loader.py           # 加载并校验规则配置
├── rule_engine.py                  # 执行学习器定性规则
├── rule_result_builder.py          # 生成 rule_json
└── risk_scorer.py                  # 可选：基于 rule_json 计算 risk_*
```

职责边界：

| 模块 | 职责 | 禁止 |
|------|------|------|
| `learner_metric_builder` | 对 learner 全部 flow 计算 v4 拓扑指标 | 输出攻击类型 |
| `learner_host_feature_builder` | 在 learner 内部计算主机视角证据 | 跨 learner 聚合 |
| `flow_feature_builder` | 后续计算流级证据 | 第一版强行识别 payload 攻击 |
| `rule_config_loader` | 读取 YAML、校验 schema | 执行规则 |
| `rule_engine` | 根据配置比较指标、生成命中结果 | 访问数据库 |
| `rule_result_builder` | 聚合攻击类型、证据、解释，生成 `rule_json` | 重新计算指标 |

---

## 5. v4 指标计算公式

所有指标统一输出 `score_0_100`。这些分数表示特征强度，不是风险分，也不是真值标签。

### 5.1 基础定义

```text
SrcEP = (src_ip, src_port)
DstEP = (dst_ip, dst_port)
EndpointEdge = (SrcEP, DstEP)
HostEdge = (src_ip, dst_ip)
n = flow_count
```

归一化熵：

```text
H_norm(X) =
  0                                           if unique(X) <= 1
  -sum_i p_i * ln(p_i) / ln(unique(X)) * 100  otherwise
```

Top1 集中度：

```text
Top1Share(X) = max_count(X) / n * 100
```

丰富度：

```text
Richness(X, cap) =
  min(100, ln(1 + unique(X)) / ln(1 + min(n, cap)) * 100)
```

有向度占比：

```text
MaxInDegreeRatio(G)  = max_in_degree(G)  / max(1, node_count(G) - 1) * 100
MaxOutDegreeRatio(G) = max_out_degree(G) / max(1, node_count(G) - 1) * 100
```

### 5.2 指标公式

| 指标 | 计算公式 | 直觉 |
|------|----------|------|
| `dst_port_entropy` | `H_norm(dst_port)` | 目的端口分散程度 |
| `dst_port_richness` | `Richness(dst_port, 65536)` | 目的端口种类丰富度 |
| `src_port_entropy` | `H_norm(src_port)` | 源端口分散程度 |
| `dst_port_top1_concentration` | `Top1Share(dst_port)` | 单一目的端口占比 |
| `endpoint_edge_entropy` | `H_norm(EndpointEdge)` | endpoint 边分散程度 |
| `top1_endpoint_edge_share` | `Top1Share(EndpointEdge)` | 单条 endpoint 边占比 |
| `edge_reuse_ratio` | `min(100, ln(1 + n / unique(EndpointEdge)) / ln(101) * 100)` | 边复用强度 |
| `host_edge_entropy` | `H_norm(HostEdge)` | 主机边分散程度 |
| `dst_host_concentration` | `Top1Share(dst_ip)` | 单一目的主机集中度 |
| `host_max_in_degree_ratio` | `MaxInDegreeRatio(HostEdge graph)` | 主机图最大入向 hub |
| `host_max_out_degree_ratio` | `MaxOutDegreeRatio(HostEdge graph)` | 主机图最大出向 hub |
| `max_in_degree_ratio` | `MaxInDegreeRatio(EndpointEdge graph)` | endpoint 图最大入向 hub |
| `max_out_degree_ratio` | `MaxOutDegreeRatio(EndpointEdge graph)` | endpoint 图最大出向 hub |
| `src_dst_endpoint_asymmetry` | `abs(unique(SrcEP) - unique(DstEP)) / max(1, unique(SrcEP union DstEP)) * 100` | 源/目的 endpoint 规模不对称 |
| `src_endpoint_concentration` | `Top1Share(SrcEP)` | 单一源 endpoint 占比 |
| `dst_endpoint_concentration` | `Top1Share(DstEP)` | 单一目的 endpoint 占比 |
| `leaf_ratio` | `leaf_node_count(undirected EndpointEdge graph) / node_count * 100` | 星型或叶子节点比例 |
| `edge_per_node` | `min(100, ln(1 + edge_count / node_count) / ln(11) * 100)` | 单节点平均边复杂度 |
| `low_reciprocity` | `(1 - reciprocal_edge_flow_count / max(1, n)) * 100` | 单向性强度 |
| `temporal_burst` | `0.5 * HHI(local_time_bins) + 0.5 * (1 - active_span / window_span) * 100` | 短时突发程度 |
| `temporal_global_spread` | `H_norm(global_time_bins)` | 跨窗口时间分散程度 |
| `temporal_intra_uniformity` | `H_norm(local_time_bins)` | 当前窗口内部均匀程度 |

时间指标说明：

```text
HHI(local_time_bins) = sum_i (count_i / n)^2 * 100
active_span = max(last_seen_ts) - min(first_seen_ts)
window_span = current_window_end - current_window_start
```

如果某个字段缺失或样本数不足，指标应输出 `null` 或 `sample_insufficient=true`，不能用 0 假装正常。

---

## 6. host_evidence_json

主机特征层输出 `host_evidence_json`，供学习器规则使用。它是学习器内部证据，不是独立规则结果。

示例：

```json
{
  "metric_version": 4,
  "learner_name": "NEW_12",
  "window_index": 1024,
  "top_source_hosts": [
    {
      "host_ip": "10.0.0.5",
      "flow_count": 1200,
      "metrics": {
        "host_max_out_degree_ratio": 86.0,
        "dst_port_richness": 32.0,
        "host_edge_entropy": 74.0,
        "low_reciprocity": 68.0
      },
      "evidence_types": ["HOST_SCAN"]
    }
  ],
  "top_destination_hosts": [
    {
      "host_ip": "10.0.0.9",
      "flow_count": 2400,
      "metrics": {
        "host_max_in_degree_ratio": 88.0,
        "dst_host_concentration": 92.0,
        "endpoint_edge_entropy": 84.0,
        "temporal_burst": 71.0
      },
      "evidence_types": ["DDOS_VICTIM"]
    }
  ],
  "summary": {
    "max_host_out_degree_score": 86.0,
    "max_host_in_degree_score": 88.0,
    "max_temporal_burst_score": 71.0,
    "host_scan_evidence_count": 1,
    "ddos_victim_evidence_count": 1
  }
}
```

`summary` 字段建议按下面方式生成：

```text
max_host_out_degree_score =
  max(top_source_hosts[*].metrics.host_max_out_degree_ratio)

max_host_in_degree_score =
  max(top_destination_hosts[*].metrics.host_max_in_degree_ratio)

max_temporal_burst_score =
  max(top_source_hosts[*].metrics.temporal_burst,
      top_destination_hosts[*].metrics.temporal_burst)

host_scan_evidence_count =
  count(host in top_source_hosts where "HOST_SCAN" in host.evidence_types)

ddos_victim_evidence_count =
  count(host in top_destination_hosts where "DDOS_VICTIM" in host.evidence_types)
```

前端可以展示 `top_source_hosts` 和 `top_destination_hosts` 作为解释证据。前端如果需要查询某个 IP 的历史拓扑，仍应按时间段读取 `ch_flow` 和对应 `pg_learner_snapshot`，不能只用当前 `topology_json`。

---

## 7. 攻击类型与规则公式

本节定义第一版中高可信度的学习器攻击类型规则。所有规则都输出到学习器，不输出独立主机对象。

### 7.1 `PORT_SCAN`

含义：端口扫描。典型表现为目的端口大量展开，单一目的端口不占主导，endpoint 边分散。

学习器整体规则：

```text
PORT_SCAN strong:
  s(dst_port_entropy) >= 90
  且 s(dst_port_richness) >= 70
  且 s(dst_port_top1_concentration) <= 15
  且 s(dst_endpoint_concentration) <= 15
  且 s(endpoint_edge_entropy) >= 90
  且 s(low_reciprocity) <= 75

PORT_SCAN weak:
  s(dst_port_entropy) >= 80
  且 s(dst_port_richness) >= 60
  且 s(dst_port_top1_concentration) <= 25
```

主机证据规则，在 `F_host_source(ip)` 上计算：

```text
PORT_SCAN host evidence strong:
  s(dst_port_entropy) >= 90
  且 s(dst_port_richness) >= 70
  且 s(dst_port_top1_concentration) <= 15
  且 s(endpoint_edge_entropy) >= 85

PORT_SCAN host evidence weak:
  s(dst_port_entropy) >= 80
  且 s(dst_port_richness) >= 60
  且 s(dst_port_top1_concentration) <= 25
```

学习器定性：

```text
learner -> PORT_SCAN:
  learner_metric_json 命中 PORT_SCAN
  或 host_evidence_json 中存在 PORT_SCAN host evidence
```

### 7.2 `HOST_SCAN`

含义：主机扫描或横向探测。典型表现为单一源主机连接大量目的主机，目的端口通常集中在少数服务端口。

主机证据规则，在 `F_host_source(ip)` 上计算：

```text
HOST_SCAN host evidence strong:
  s(host_max_out_degree_ratio) >= 80
  且 s(dst_port_richness) <= 45
  且 s(host_edge_entropy) >= 70

HOST_SCAN host evidence weak:
  s(host_max_out_degree_ratio) >= 65
  且 s(max_out_degree_ratio) >= 60
  且 s(dst_port_top1_concentration) >= 50
```

学习器定性：

```text
learner -> HOST_SCAN:
  s(learner_metric_json.host_max_out_degree_ratio) >= 65
  或 host_evidence_json.summary.host_scan_evidence_count >= 1
```

### 7.3 `DDOS_VICTIM`

含义：DDoS 受害目标。典型表现为很多源主机或源 endpoint 指向同一目的主机。

固定服务攻击核心：

```text
hasFixedTargetServiceCore:
  s(dst_port_entropy) <= 12
  且 s(dst_port_richness) <= 30
  且 s(dst_port_top1_concentration) >= 95
  且 s(endpoint_edge_entropy) >= 80
  且 s(src_port_entropy) >= 80

hasFixedTargetSupport:
  s(dst_host_concentration) >= 65
  或 s(max_in_degree_ratio) >= 75
  或 s(host_max_in_degree_ratio) >= 75
```

学习器整体规则：

```text
DDOS_VICTIM strong:
  hasFixedTargetServiceCore
  且 hasFixedTargetSupport
  且 s(temporal_burst) >= 60

DDOS_VICTIM weak:
  hasFixedTargetServiceCore
  且 hasFixedTargetSupport
```

主机证据规则，在 `F_host_destination(ip)` 上计算：

```text
DDOS_VICTIM host evidence strong:
  s(host_max_in_degree_ratio) >= 80
  且 s(dst_host_concentration) >= 80
  且 s(endpoint_edge_entropy) >= 80
  且 s(temporal_burst) >= 60

DDOS_VICTIM host evidence weak:
  s(host_max_in_degree_ratio) >= 65
  且 s(dst_host_concentration) >= 65
  且 (s(max_in_degree_ratio) >= 70 或 s(endpoint_edge_entropy) >= 75)
```

学习器定性：

```text
learner -> DDOS_VICTIM:
  learner_metric_json 命中 DDOS_VICTIM
  或 host_evidence_json.summary.ddos_victim_evidence_count >= 1
```

### 7.4 `DOS_ATTACKER`

含义：DoS 攻击源。典型表现为单一源主机对少数目的主机或目的 endpoint 产生大量复用边。

主机证据规则，在 `F_host_source(ip)` 上计算：

```text
DOS_ATTACKER host evidence strong:
  s(dst_host_concentration) >= 80
  且 s(dst_port_top1_concentration) >= 80
  且 s(edge_reuse_ratio) >= 70
  且 s(temporal_burst) >= 60

DOS_ATTACKER host evidence weak:
  s(dst_host_concentration) >= 65
  且 s(dst_endpoint_concentration) >= 60
  且 s(edge_reuse_ratio) >= 55
```

学习器定性：

```text
learner -> DOS_ATTACKER:
  host_evidence_json 中存在 DOS_ATTACKER host evidence
  或 learner_metric_json 中固定目标集中、边复用高、时间突发高
```

### 7.5 `DRDOS_REFLECTION_FAMILY`

含义：反射放大型攻击族嫌疑。典型表现为端口和 endpoint 边高度展开、边复用低、单向性强。

学习器整体规则：

```text
isDiffuseOneWayAttack:
  s(dst_port_entropy) >= 90
  且 s(dst_port_richness) >= 90
  且 s(dst_port_top1_concentration) <= 10
  且 s(endpoint_edge_entropy) >= 95
  且 s(edge_reuse_ratio) <= 25
  且 s(low_reciprocity) >= 85

DRDOS_REFLECTION_FAMILY strong:
  isDiffuseOneWayAttack

DRDOS_REFLECTION_FAMILY weak:
  s(dst_port_entropy) >= 80
  且 s(endpoint_edge_entropy) >= 85
  且 s(low_reciprocity) >= 70
```

主机证据规则，在 `F_host_destination(ip)` 或 `F_host_source(ip)` 上计算：

```text
DRDOS_REFLECTION_FAMILY host evidence strong:
  s(dst_port_entropy) >= 90
  且 s(dst_port_richness) >= 85
  且 s(endpoint_edge_entropy) >= 90
  且 s(edge_reuse_ratio) <= 30
  且 s(low_reciprocity) >= 80
```

子形态只作为解释字段，不作为第一版强输出攻击类型：

| 子形态解释 | 附加条件 |
|------------|----------|
| `DRDOS_DNS_LDAP_NTP_LIKE` | `65 <= s(src_port_entropy) <= 85` |
| `DRDOS_SNMP_SSDP_TFTP_LIKE` | `85 < s(src_port_entropy) < 98` |
| `DRDOS_UDP_SYN_LIKE` | `s(src_port_entropy) >= 98` |

### 7.6 `SLOW_DOS_SUSPECTED`

含义：慢速 DoS 嫌疑。纯拓扑指标只能输出 suspected，不应高置信宣称具体工具类型。

规则公式：

```text
SLOW_DOS_SUSPECTED strong:
  s(dst_port_entropy) <= 20
  且 s(dst_port_top1_concentration) >= 80
  且 (s(dst_host_concentration) >= 65 或 s(host_max_in_degree_ratio) >= 65)
  且 s(low_reciprocity) >= 68

SLOW_DOS_SUSPECTED weak:
  s(dst_port_top1_concentration) >= 70
  且 s(low_reciprocity) >= 60
```

### 7.7 `WEB_DDOS_SUSPECTED`

含义：Web DDoS 嫌疑。典型表现为 HTTP/HTTPS 服务端口占主导，但端口熵不完全为 0，入向和出向 endpoint 结构都复杂。

规则公式：

```text
WEB_DDOS_SUSPECTED strong:
  35 <= s(dst_port_entropy) <= 65
  且 50 <= s(dst_port_top1_concentration) <= 85
  且 s(max_in_degree_ratio) >= 80
  且 s(max_out_degree_ratio) >= 80
  且 s(endpoint_edge_entropy) >= 85

WEB_DDOS_SUSPECTED weak:
  30 <= s(dst_port_entropy) <= 70
  且 s(max_in_degree_ratio) >= 65
  且 s(endpoint_edge_entropy) >= 75
```

### 7.8 `BRUTE_FORCE_SUSPECTED`

含义：暴力破解嫌疑。纯流拓扑只能给嫌疑，最好后续结合登录失败日志、应用日志或协议字段。

规则公式：

```text
BRUTE_FORCE_SUSPECTED strong:
  s(dst_port_entropy) <= 25
  且 s(dst_port_top1_concentration) >= 80
  且 s(edge_reuse_ratio) >= 65
  且 s(temporal_burst) >= 50

BRUTE_FORCE_SUSPECTED weak:
  s(dst_port_top1_concentration) >= 70
  且 s(edge_reuse_ratio) >= 50
```

---

## 8. flow 级规则方向

流级证据是后续发展方向，用于处理主机聚合后容易被稀释的攻击：

```text
XSS
SQL_INJECTION
COMMAND_INJECTION
WEB_SHELL_UPLOAD
MALFORMED_HTTP
```

未来 flow 级结果也应汇总进学习器：

```text
flow_evidence_json:
  xss_flow_count
  sqli_flow_count
  web_attack_flow_share
```

然后由学习器规则决定：

```text
learner -> XSS:
  flow_evidence_json.xss_flow_count >= threshold
```

第一版不依赖 payload，因此不把 XSS、SQLi 作为高可信攻击类型输出。

---

## 9. 规则配置

规则配置放在：

```text
streamtrident_backend/config/rules/
```

第一版建议：

```text
config/rules/
└── learner_attack_rules.2026-05-27.v1.yaml
```

配置示例：

```yaml
rule_set:
  id: learner_attack_rules
  version: 2026-05-27.v1
  description: "学习器攻击类型规则第一版"

attack_types:
  - id: PORT_SCAN
    description: "端口扫描"
  - id: HOST_SCAN
    description: "主机扫描或横向探测"
  - id: DDOS_VICTIM
    description: "DDoS 受害目标"

rules:
  - id: learner_port_scan_core
    version: v1
    enabled: true
    target_attack_type: PORT_SCAN
    source: learner_metric_json
    metric: dst_port_richness
    operator: ">="
    weak_threshold: 60
    strong_threshold: 70
    weight: 0.8
    explain: "该学习器内部目的端口大范围展开，符合端口扫描核心特征"

  - id: learner_host_scan_host_evidence
    version: v1
    enabled: true
    target_attack_type: HOST_SCAN
    source: host_evidence_json
    metric: summary.max_host_out_degree_score
    operator: ">="
    weak_threshold: 65
    strong_threshold: 80
    weight: 0.9
    explain: "该学习器内部存在主机出向 hub，符合主机扫描或横向探测特征"
```

必填字段：

| 字段 | 含义 |
|------|------|
| `rule_set.id` | 规则集 ID |
| `rule_set.version` | 规则集版本 |
| `rules[].id` | 单条规则 ID |
| `rules[].version` | 单条规则版本 |
| `rules[].target_attack_type` | 命中后贡献的学习器攻击类型 |
| `rules[].source` | `learner_metric_json` / `host_evidence_json` / 后续 `flow_evidence_json` |
| `rules[].metric` | 指标路径 |
| `rules[].operator` | 比较符 |
| `rules[].weak_threshold` | 弱匹配阈值 |
| `rules[].strong_threshold` | 强匹配阈值 |
| `rules[].weight` | 攻击类型聚合权重 |
| `rules[].explain` | 解释文本 |

---

## 10. rule_json 输出

规则执行结果写入学习器当前态和学习器快照。

```json
{
  "rule_set": {
    "id": "learner_attack_rules",
    "version": "2026-05-27.v1"
  },
  "target": {
    "session_id": "trident-prod-001",
    "learner_name": "NEW_12",
    "window_index": 1024
  },
  "attack_types": [
    {
      "attack_type": "HOST_SCAN",
      "confidence": 0.86,
      "evidence_rules": [
        "learner_host_scan_host_evidence"
      ],
      "explain": "该学习器内部存在主机出向 hub，符合主机扫描或横向探测特征"
    }
  ],
  "evidence": {
    "learner_metric_json": {},
    "host_evidence_json": {},
    "flow_evidence_json": null
  },
  "rules": [
    {
      "rule_id": "learner_host_scan_host_evidence",
      "rule_version": "v1",
      "target_attack_type": "HOST_SCAN",
      "match": "strong",
      "source": "host_evidence_json",
      "metric": "summary.max_host_out_degree_score",
      "value": 86.0,
      "weak_threshold": 65,
      "strong_threshold": 80,
      "weight": 0.9,
      "explain": "该学习器内部存在主机出向 hub，符合主机扫描或横向探测特征"
    }
  ]
}
```

要求：

- 每个输出必须包含 `rule_set.id` 和 `rule_set.version`。
- 每条命中必须包含 `rule_id`、`rule_version`、`value`、阈值和解释。
- 不允许只输出攻击类型而没有证据。
- `host_evidence_json` 必须说明证据来自该 learner 内部哪些主机子图。
- 多个攻击类型可以同时命中，不强行只选一个。

---

## 11. 攻击类型聚合

多条规则可以贡献同一个学习器攻击类型。

第一版使用简单可解释公式：

```text
confidence(attack_type) =
  clamp(
    sum(rule_weight * match_strength) / sum(rule_weight),
    0,
    1
  )
```

匹配强度：

```text
strong = 1.0
weak   = 0.5
none   = 0.0
```

如果需要把主机证据数量纳入置信度，可以增加上限封顶的数量加成：

```text
host_bonus = min(0.15, evidence_host_count * 0.03)
confidence = min(1.0, base_confidence + host_bonus)
```

风险分和风险等级不属于攻击类型本身，建议由 `risk_scorer` 基于 `rule_json` 另算：

```text
risk_score = clamp(max_confidence * attack_type_weight + exposure_bonus, 0, 100)
risk_level = LOW / MEDIUM / HIGH / CRITICAL
```

---

## 12. 存储位置

学习器定性结果写入当前态：

```text
pg_learner.rule_json
pg_learner.rule_set_id
pg_learner.rule_set_version
```

如果规则结果变化，需要写学习器更新快照：

```text
pg_learner_snapshot.rule_json
update_reasons = ["rule_changed"]
```

快照不是每个窗口都写一次，而是学习器发生更新时写一次。规则版本变化、规则命中结果变化、学习器画像明显变化都可以作为写快照原因。

---

## 13. 版本策略

规则版本建议使用日期 + 小版本：

```text
2026-05-27.v1
2026-05-27.v2
2026-06-01.v1
```

以下变化必须升级版本：

- 修改阈值。
- 修改权重。
- 修改 `target_attack_type`。
- 修改解释文案。
- 启用或禁用规则。
- 新增或删除规则。

严禁覆盖已经上线使用过的同名同版本规则文件。

---

## 14. 落地阶段

### P0

不做规则，只保证学习器、流表、快照的数据结构能承载规则结果。

### P1

实现学习器定性规则基础设施：

- `learner_metric_builder`
- `learner_host_feature_builder`
- `rule_config_loader`
- `rule_engine`
- `rule_result_builder`
- Live flush 写入 `pg_learner.rule_json`

P1 主要使用：

```text
learner_metric_json
host_evidence_json
```

### P2

完善主机证据层：

- 保存更完整的 `host_evidence_json`
- 支持 top host 证据回溯
- 规则变化时写 `pg_learner_snapshot`
- 前端学习器详情展示主机证据

### P3

发展流级证据层：

- XSS
- SQL Injection
- Command Injection
- Malformed HTTP
- 可疑 TLS/DNS

流级规则输出仍然向上汇总到学习器 `rule_json`，不作为独立规则体系。

---

## 15. 设计底线

必须坚持：

```text
规则最终给学习器定性
主机级特征是 learner 内部证据，不是独立规则对象
流级特征是 learner 内部证据，放后续发展方向
不写死规则
不覆盖旧版本
不输出无证据攻击类型
不混淆攻击类型和风险等级
历史查询读快照，不用当前 learner 解释过去
```
