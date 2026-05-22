# Learner Topology Metric Audit Design

本文档定义一套面向学习器的拓扑/行为审计指标，用于在 `visualize` 可视化页面中展示每个学习器的内部流拓扑特征、指标分数和语义化解释。

核心原则：

- 不生成组合总分。
- 每个指标独立输出 `raw_value`、`score_0_100`、`semantic_level` 和 `semantic_text`。
- 指标分数只表示该指标自身的强弱，不代表综合风险。
- 人工根据多个指标共同判断学习器是 benign-like、flood-like、scan-like、single-service-like 或其他形态。

## 1. 数据输入

每个学习器需要关联到原始流量字段：

```text
assigned_learner
Src IP
Dst IP
Src Port
Dst Port
Timestamp    # 可选，但强烈建议
LabelNorm    # 可选，用于展示 attack_ratio / dominant_label
```

推荐从以下文件或数据结构 join 得到每个 learner 的流集合：

```text
outputs/runs/<run_id>/sample_learner_assignments.csv
原始 flow dataframe
outputs/runs/<run_id>/learner_label_distribution.csv
```

已有可参考实现：

```text
scripts/analyze_learner_internal_topology.py
trident_stream/dataset_topology.py
visualize/src/components/LearnerInternalTopologyPanel.tsx
```

## 2. 基础定义

对每个学习器内部的流，构造：

```text
SrcEP = Src IP + ":" + Src Port
DstEP = Dst IP + ":" + Dst Port
HostEdge = Src IP -> Dst IP
EndpointEdge = SrcEP -> DstEP
PortPair = Src Port -> Dst Port
N = learner 内流数量
```

归一化 Shannon entropy：

```text
H = -sum(p_i * ln(p_i))
H_norm = H / ln(K)
```

其中 `K` 为类别数。若 `K <= 1`，则 `H_norm = 0`。

集中度：

```text
HHI = sum(p_i^2)
top1_share = max(count_i) / N
top5_share = sum(top5 count_i) / N
```

**分数含义**：`score_0_100` 仅表示该拓扑特征的**表现强度**（0–100），不是风险分、异常分或 benign/attack 分。

**强度档位**（各指标通用，中性）：

```text
0–19    VERY_LOW   很弱
20–39   LOW        较弱
40–59   MID        中等
60–79   HIGH       较强
80–100  VERY_HIGH  很强
```

**每条指标另输出**（见 `trident_stream/metric_audit_catalog.py`）：

```text
trait_axis        特征维度（dispersion / concentration / burst / …）— 驱动 UI 色系
trait_axis_label  维度中文名（分散度、集中度、…）
semantic_tag      该分数下的特征短语（如「目的端口分散」「流内双向包较均衡」）
semantic_text     完整解释（含「高分=…低分=…」）
```

注意：高分可能是分散、集中、突发、单向等**不同含义**，必须由 `semantic_tag` + `semantic_text` 解读，禁止把 HIGH/EXTREME 当作「异常」。

## 3. 输出 JSON

建议新增文件：

```text
outputs/runs/<run_id>/learner_topology_metric_audit.json
```

JSON 结构：

```json
{
  "version": 1,
  "generated_from": {
    "assignments": "sample_learner_assignments.csv",
    "label_distribution": "learner_label_distribution.csv"
  },
  "learners": [
    {
      "learner_name": "learner_17",
      "flow_count": 12345,
      "attack_ratio": 0.92,
      "dominant_label": "DDoS",
      "dominant_ratio": 0.91,
      "metrics": [
        {
          "group": "边集中/复用",
          "metric_key": "top1_endpoint_edge_share",
          "metric_name": "Top1 IP:Port 边占比",
          "raw_value": 0.96,
          "score_0_100": 96.0,
          "semantic_level": "EXTREME",
          "semantic_text": "单条 IP:Port 边支配流量，程序化重复特征极强。"
        }
      ],
      "qualitative_hints": [
        {
          "hint_key": "Flood-like",
          "hint_text": "少数目的或少数边承载大量流量，并伴随时间突发。"
        }
      ]
    }
  ]
}
```

## 4. 指标定义（v4 核心集，共 22 项）

设计原则：每个保留指标应提供**独立视角**；若与另一指标单调相关（如 HHI≈Top1、规则度=1−熵、Hub 流量占比=端点 Top1），只保留更易解释的一项。

### 4.0 审计：保留 vs 移除

| 保留 | 维度 | 移除（原因） |
|------|------|----------------|
| `dst_port_entropy` | 目的端口已出现类别间的分布均匀度 | `port_pair_entropy`（与 src/dst 熵重复） |
| `dst_port_richness` | 目的端口唯一数/丰富度 | |
| `src_port_entropy` | 源端口分散度 | `dst_port_hhi_concentration`（与 Top1/熵重复） |
| `dst_port_top1_concentration` | 目的端口 Top1 | |
| `endpoint_edge_entropy` | 边分散度 | `endpoint_edge_regular`（=1−边熵） |
| `top1_endpoint_edge_share` | 单边主导 | `top5_endpoint_edge_share`（与 Top1 强相关） |
| `edge_reuse_ratio` | 边复用（与边熵互补） | |
| `host_edge_entropy` | 忽略端口后的主机边熵 | |
| `dst_host_concentration` | 目的主机集中度 | |
| `host_max_in_degree_ratio` | 主机层入向星型 | |
| `host_max_out_degree_ratio` | 主机层出向星型 | |
| `src_dst_endpoint_asymmetry` | 源/目的规模差 | `hub_in/out_strength`（= dst/src 端点 Top1） |
| `src_endpoint_concentration` | 源端 Top1 | |
| `dst_endpoint_concentration` | 目的端 Top1 | |
| `max_in_degree_ratio` | 入向星型（多源→一点） | |
| `max_out_degree_ratio` | 出向星型（一点→多目的） | |
| `leaf_ratio` | 叶子/星型拓扑 | |
| `edge_per_node` | 连接密度 | |
| `low_reciprocity` | 流内 Fwd/Bwd 单向性 | |
| `temporal_burst` | 时间突发 | `temporal_regular`（已移除） |
| `temporal_global_spread` | 全局时间分散 | `temporal_entropy`（v3 拆分） |
| `temporal_intra_uniformity` | 活跃窗内均匀 | |

**解读矩阵（高分≈该列右侧描述，非“异常”）：**

| 形态 | 端口 | 边 | 端点/方向 | 时间 | 单向性 |
|------|------|-----|-----------|------|--------|
| 扫描 | 目的端口分散 | 边分散、低复用 | 出向星型、源集中 | 可突发 | 高 |
| Flood | 目的端口可集中 | 单边主导、高复用 | 目的端集中 | 突发强 | 高 |
| Benign | 不定 | 边较散、低 Top1 | 较均衡 | 跨度大/较均匀 | 低 |

### 4.1 端口

#### `dst_port_entropy`

```text
raw_value = norm_entropy(Dst Port)
score_0_100 = raw_value * 100
```

语义：

```text
高分表示已出现目的端口之间的流量分布更均匀。
极高时不一定代表端口种类多，需要结合目的端口丰富度、源集中度、出度和低互惠性判断。
低分表示目的端口高度集中，常见于固定服务访问、服务打击或 flood。
```

#### `dst_port_richness`

```text
raw_value = unique(Dst Port)
score_0_100 = log1p(raw_value) / log1p(min(N, 65536)) * 100
```

语义：

```text
原始值给出不同目的端口数。
高分表示在当前 learner 流量规模下目的端口确实大范围展开。
它与目的端口熵配合使用，避免把少量端口上的均匀分布误读成扫描式多端口展开。
```

#### `src_port_entropy`

```text
raw_value = norm_entropy(Src Port)
score_0_100 = raw_value * 100
```

语义：

```text
高分表示已出现源端口之间的分布更均匀。
低分表示源端口模板化，可能来自固定程序、脚本或少量连接模板；临时源端口会抬高该指标，需对照主机层指标。
```

#### `dst_port_top1_concentration`

```text
raw_value = top1_share(Dst Port)
score_0_100 = raw_value * 100
```

语义：

```text
高分表示少数目的端口承载大量流量，常见于固定服务攻击、flood 或单服务访问。
```

### 4.2 边

以下指标基于 `EndpointEdge = SrcEP -> DstEP`。

#### `endpoint_edge_entropy`

```text
raw_value = norm_entropy(EndpointEdge)
score_0_100 = raw_value * 100
```

语义：

```text
高分表示 IP:Port 边分布更分散。
低分表示少数边被反复使用，拓扑更模板化。
```

#### `top1_endpoint_edge_share`

```text
raw_value = top1_share(EndpointEdge)
score_0_100 = raw_value * 100
```

语义：

```text
高分表示单条 IP:Port 边支配学习器流量。
```

#### `edge_reuse_ratio`

```text
raw_value = N / unique_endpoint_edges
score_0_100 = min(100, log1p(raw_value) / log1p(100) * 100)
```

语义：

```text
高分表示每条边平均被大量复用，常见于 flood、固定连接或批量请求。
```

### 4.3 主机层

以下指标基于 `HostEdge = Src IP -> Dst IP`。它们忽略源临时端口，用于给 endpoint 图补上下文。

```text
host_edge_entropy
dst_host_concentration
host_max_in_degree_ratio
host_max_out_degree_ratio
```

语义：

```text
主机边熵用来确认 IP 层关系是否同样分散。
目的主机集中度和主机入/出度用于确认 hub 是否真实存在于主机层，而不只是 IP:Port endpoint 被临时端口放大。
```

### 4.4 端点与方向

#### `max_in_degree_ratio`

```text
raw_value = max_in_degree / max(1, node_count - 1)
score_0_100 = raw_value * 100
```

语义：

```text
高分表示很多源连接到同一目的，呈入向 hub。
```

#### `max_out_degree_ratio`

```text
raw_value = max_out_degree / max(1, node_count - 1)
score_0_100 = raw_value * 100
```

语义：

```text
高分表示单一源连接很多目的，偏扫描或横向探测。
```

#### `src_dst_endpoint_asymmetry`

```text
raw_value = abs(unique_src_endpoint - unique_dst_endpoint) / max(1, unique_endpoint_nodes)
score_0_100 = raw_value * 100
```

语义：

```text
高分表示源/目的角色明显不对称，常见于攻击、扫描或批量请求。
```

#### `src_endpoint_concentration`

```text
raw_value = top1_share(SrcEP)
score_0_100 = raw_value * 100
```

语义：

```text
高分表示流量高度来自少数源 endpoint。
```

#### `dst_endpoint_concentration`

```text
raw_value = top1_share(DstEP)
score_0_100 = raw_value * 100
```

语义：

```text
高分表示流量高度流向少数目的 endpoint。
```

### 4.5 图形态

#### `leaf_ratio`

构建无向 `EndpointEdge` 图。

```text
raw_value = degree <= 1 的节点数 / node_count
score_0_100 = raw_value * 100
```

语义：

```text
高分表示大量叶子节点，拓扑呈星型或放射状，常见于扫描或 DDoS。
```

#### `edge_per_node`

```text
raw_value = unique_endpoint_edges / unique_endpoint_nodes
score_0_100 = min(100, log1p(raw_value) / log1p(10) * 100)
```

语义：

```text
高分表示拓扑连接密度较高，需要结合熵、集中度和 hub 指标解释。
```

#### `low_reciprocity`

CIC 导出的每行是**单向流记录**，很少出现成对的 `A→B` 与 `B→A` 两行，因此不能再用反向 HostEdge 计数（否则 benign 也会接近 100）。

改用**流记录内的 Fwd/Bwd 包平衡**（同一行上的 `Total Fwd Packet` 与 `Total Bwd packets`）：

```text
packet_reciprocity = sum(min(FwdPkt, BwdPkt)) / sum(FwdPkt + BwdPkt)
raw_value = 1 - packet_reciprocity
score_0_100 = raw_value * 100
```

语义：

```text
高分表示流内反向包占比极低（单向、扫描、flood）。
低分表示 Fwd/Bwd 包较均衡，更接近正常 TCP/UDP 会话。
若导出数据缺少 Fwd/Bwd 包字段，则该指标不输出，不能把“不可计算”解释为强单向。
```

### 4.6 时间行为

时间指标可选，但强烈建议加入。v3 将原 `temporal_entropy` 拆成两个独立视角（避免「攻击低熵 / 正常高熵」与实现语义打架）。

- **`temporal_burst`**：局部 HHI + 全局 `span_ratio`（短 campaign、窗内集中 → 高分）。
- **`temporal_global_spread`**：在 **run 全局时间轴** 上按约 **1h/bin** 自适应分箱（128–2048 bin），在 learner 已占用的全局时间足迹内衡量分布均匀度。它不是“占了多少小时”的跨度指标。
- **`temporal_intra_uniformity`**：在 **learner 局部** `[t_min, t_max]` 上落 **100** 个 bin，熵的 `K` = **有流量的 bin 个数**（与原 `temporal_entropy` 相同）。

#### `temporal_burst`

```text
temporal_hhi = HHI(time_bin on learner-local [t_min, t_max], 100 bins)
span_ratio = learner_time_span / global_time_span
raw_value = 0.5 * temporal_hhi + 0.5 * (1 - min(span_ratio, 1))
score_0_100 = raw_value * 100
```

`temporal_hhi` 必须用 **learner 局部时间轴**；若用全局轴，短窗口攻击 HHI 会失真。

语义：

```text
高分表示短时间集中爆发。
```

#### `temporal_global_spread`

```text
n_global = clamp(128, floor(global_span / 3600s), 2048)
bin_counts = histogram(Timestamp on global [t_run_min, t_run_max], n_global bins)
i_min, i_max = global bin indices of learner t_min / t_max
occupied = bin_counts[i_min : i_max + 1][count > 0]
raw_value = norm_entropy(occupied)   # K = len(occupied)
score_0_100 = raw_value * 100
```

语义：

```text
高分表示在学习器已占用的全局 ~1h 时段中分布较均匀。
低分表示这些已占用时段内仍被少数时段主导；全局跨度另看 `temporal_burst` 的 span 部分。
勿用整段 run 的 bin 总数或足迹内空 bin 作 K（否则 benign 会被压到极低分）。
```

#### `temporal_intra_uniformity`

```text
bin_counts = histogram(Timestamp on learner-local [t_min, t_max], 100 bins)
raw_value = norm_entropy(bin_counts[count > 0])   # K = occupied bins
score_0_100 = raw_value * 100
```

语义：

```text
高分表示在 learner 自身活跃窗口内，各时间段流量较均匀（含持续 flood）。
低分表示窗内挤在极少数时段（端口扫描式爆发）。
勿与全局分散度混读：持续 DDOS 可「全局低分散 + 窗内高均匀」。
```

## 4.7 实现审计备忘（常见误读）

| 指标 | 尺度/陷阱 | 说明 |
|------|-----------|------|
| `temporal_global_spread` | 全局 ~1h/bin，**K=足迹内有流量 bin 数** | 勿用 K=整段 run 或足迹空 bin |
| `temporal_intra_uniformity` | learner 局部 100 bin，**K=有流量 bin 数** | 原 `temporal_entropy`；持续 flood 可高分 |
| `temporal_burst` | 局部 HHI + 全局 `span_ratio` | 局部 HHI 不可用全局轴 |
| `endpoint_edge_entropy` 高 + `top1_endpoint_edge_share` 低 | 不矛盾 | 大量唯一边、每条边仅少量流（扫描）时会出现 |
| `dst_port_entropy` 高 + `dst_port_top1` 低 | 同上 | 端口扫描：多端口各少量流 |
| `low_reciprocity` | 流内 `min(FwdPkt,BwdPkt)/(Fwd+Bwd)` | 反向 HostEdge 在 CIC 里对 benign 也≈0，会误判 |
| 端口/边熵类 | `K`=实际出现的类别数 | `value_counts` 数组，无空类别 |
| `edge_reuse_ratio` | `log1p` 映射到 100 | `reuse=1`（全唯一边）得分约 15，不是 0 |
| `edge_per_node` | `log1p` 映射，`/log1p(10)` | 密度>10 时封顶 100 |

## 5. 定性提示规则

`qualitative_hints` 不是组合分数，只是辅助人工扫读。它不能替代指标面板。

### Flood-like

触发条件建议：

```text
top1_endpoint_edge_share >= 80 或 dst_endpoint_concentration >= 80
并且 temporal_burst >= 50
```

### Scan-like

触发条件建议：

```text
dst_port_entropy >= 80
并且 max_out_degree_ratio >= 50
并且 edge_reuse_ratio <= 55
并且 low_reciprocity >= 70
```

### Single-service-like

触发条件建议：

```text
dst_port_top1_concentration >= 80
并且 (top1_endpoint_edge_share >= 60 或 endpoint_edge_entropy <= 35)
```

解释：

```text
流量集中到少数服务端口和少数边，偏固定服务打击或固定服务访问。
```

### Benign-like

触发条件建议：

```text
endpoint_edge_entropy >= 60
并且 top1_endpoint_edge_share <= 30
并且 low_reciprocity <= 60
并且 temporal_burst <= 50
```

解释：

```text
边分布较分散，单边支配不明显，单向性和时间突发不强。
```

## 6. 前端展示设计

在 `visualize` 的学习器内部拓扑区域增加一个“指标审计”面板。

推荐位置：

```text
visualize/src/components/LearnerInternalTopologyPanel.tsx
```

已有页面展示：

```text
左：IP 拓扑
右：IP:端口拓扑
```

建议新增：

```text
下方或右侧：学习器指标审计表
```

表格列：

```text
分组
指标
分数
等级
原始值
语义解释
```

示例：

```text
边集中/复用 | Top1 IP:Port 边占比 | 96 | EXTREME | 0.9600 | 单条 IP:Port 边支配流量，程序化重复特征极强。
时间行为     | 时间突发            | 88 | EXTREME | 0.8800 | 短时间集中爆发。
图形态       | 低互惠性            | 94 | EXTREME | 0.9400 | 通信单向性强，偏攻击、扫描或探测。
```

分数展示建议：

- 每个指标用独立进度条或色条。
- 不显示总分。
- 不做平均值。
- `EXTREME` 用高亮色，但不要把它解释成最终恶意结论。
- `dst_port_entropy` 这类“高熵可能是良性也可能是扫描”的指标，必须展示完整语义解释。

## 7. 前端数据加载建议

在 `GraphAnalysisPage.tsx` 中增加可选 JSON 加载：

```text
fetchRunJsonOptional<LearnerTopologyMetricAuditJson>(
  selectedRunId,
  'learner_topology_metric_audit.json'
)
```

然后传入：

```text
<LearnerInternalTopologyPanel
  data={learnerNetworkTopology}
  metricAudit={learnerTopologyMetricAudit}
  ...
/>
```

新增 TypeScript 类型：

```ts
export type LearnerMetricAuditItem = {
  group: string
  metric_key: string
  metric_name: string
  raw_value: number
  score_0_100: number
  trait_axis?: string
  trait_axis_label?: string
  strength_band?: 'VERY_LOW' | 'LOW' | 'MID' | 'HIGH' | 'VERY_HIGH'
  strength_label?: string
  semantic_tag?: string
  semantic_text: string
}

export type LearnerMetricHint = {
  hint_key: string
  hint_text: string
}

export type LearnerMetricAuditView = {
  learner_name: string
  flow_count: number
  attack_ratio?: number
  dominant_label?: string
  dominant_ratio?: number
  metrics: LearnerMetricAuditItem[]
  qualitative_hints?: LearnerMetricHint[]
}

export type LearnerTopologyMetricAuditJson = {
  version: number
  learners: LearnerMetricAuditView[]
}
```

## 8. 后端实现建议

新增脚本：

```text
scripts/export_learner_topology_metric_audit.py
```

输入：

```text
python3 scripts/export_learner_topology_metric_audit.py outputs/runs/<run_id>
```

输出：

```text
outputs/runs/<run_id>/learner_topology_metric_audit.json
```

实现步骤：

1. 读取 `config_snapshot.yaml`，加载原始数据集。
2. 读取 `sample_learner_assignments.csv`。
3. 用 `row_index` 将原始流和 `assigned_learner` join。
4. 可选读取 `learner_label_distribution.csv`，补充 `attack_ratio`、`dominant_label`、`dominant_ratio`。
5. 按 `assigned_learner` 分组。
6. 对每个 learner 计算本文定义的全部指标。
7. 为每个指标生成 `score_0_100`、`semantic_level`、`semantic_text`。
8. 根据规则生成 `qualitative_hints`。
9. 写出 JSON。

建议将指标计算逻辑放到可复用模块，例如：

```text
trident_stream/learner_metric_audit.py
```

这样实验主流程和独立脚本都能复用。

## 9. 缺失值处理

若某个 learner 流数量为 0：

```text
flow_count = 0
metrics = []
qualitative_hints = []
```

若某类指标无法计算：

```json
{
  "raw_value": null,
  "score_0_100": null,
  "semantic_level": "UNKNOWN",
  "semantic_text": "该指标因缺少 Timestamp 字段无法计算。"
}
```

时间字段缺失时，只跳过时间类指标，不影响拓扑类指标。

## 10. 人工解读方式

不要使用一个总分判断学习器性质。推荐按证据链读：

```text
1. 边看：分散度 vs Top1 主导 vs 复用率。
2. 再看端点：目的/源 Top1 与入向/出向星型（度比例）。
3. 再看端口熵：扫描式高熵 vs 单服务集中。
4. 再看低互惠与叶子：单向与会话形态。
5. 最后看时间：突发、全局分散、窗内均匀（三者分开）。
```

典型解释：

```text
Flood-like:
  top1_edge 高、dst_endpoint_concentration 高、temporal_burst 高。

Scan-like:
  dst_port_entropy 高、max_out_degree_ratio 高、低_reciprocity 高、edge_reuse 偏低。

Single-service-like:
  dst_port_top1 高、top1_edge 高或边熵低。

Benign-like:
  endpoint_edge_entropy 较高、top1_edge 低、low_reciprocity 偏低；global_spread 偏高、burst 不强。
```
