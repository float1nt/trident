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

## 4. 指标定义

### 4.1 端口随机性

#### `dst_port_entropy`

```text
raw_value = norm_entropy(Dst Port)
score_0_100 = raw_value * 100
```

语义：

```text
高分表示目的端口分布更分散。
极高时不一定良性，需要结合源集中度、出度和低互惠性判断是否为端口扫描。
低分表示目的端口高度集中，常见于固定服务访问、服务打击或 flood。
```

#### `src_port_entropy`

```text
raw_value = norm_entropy(Src Port)
score_0_100 = raw_value * 100
```

语义：

```text
高分表示源端口更分散。
低分表示源端口模板化，可能来自固定程序、脚本或少量连接模板。
```

#### `port_pair_entropy`

```text
raw_value = norm_entropy((Src Port, Dst Port))
score_0_100 = raw_value * 100
```

语义：

```text
高分表示端口组合多样。
低分表示端口组合高度模板化，程序化重复特征更强。
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

#### `dst_port_hhi_concentration`

```text
raw_value = HHI(Dst Port)
score_0_100 = raw_value * 100
```

语义：

```text
高分表示目的端口整体分布高度集中。
```

### 4.2 边集中/复用

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

#### `endpoint_edge_regular`

```text
raw_value = 1 - norm_entropy(EndpointEdge)
score_0_100 = raw_value * 100
```

语义：

```text
高分表示边权高度集中、程序化重复强。
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

#### `top5_endpoint_edge_share`

```text
raw_value = top5_share(EndpointEdge)
score_0_100 = raw_value * 100
```

语义：

```text
高分表示少数 IP:Port 边覆盖大部分流量。
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

### 4.3 Hub 结构

以下指标基于 `EndpointEdge` 有向图。

#### `hub_in_strength`

```text
raw_value = max_in_flow_count / N
score_0_100 = raw_value * 100
```

语义：

```text
高分表示单一目的 endpoint 吸收大量流量，偏 DDoS、服务打击或集中爆破。
```

#### `hub_out_strength`

```text
raw_value = max_out_flow_count / N
score_0_100 = raw_value * 100
```

语义：

```text
高分表示单一源 endpoint 发出大量流量，偏扫描、单源自动化或探测。
```

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

### 4.4 源目的不对称

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
```

### 4.6 时间行为

时间指标可选，但强烈建议加入。它对程序并发、短时间爆发和定时行为非常敏感。

全局时间范围切成固定 bin，推荐 100 个 bin。

- **`temporal_burst`**：按 **全局最早时间戳** 对齐后落 bin（与 run 过滤后数据集一致），衡量相对整段实验窗口的突发与跨度。
- **`temporal_entropy` / `temporal_regular`**：在 **该 learner 自身活跃时段** `[t_min, t_max]` 内落 100 个 bin；熵的 `K` 取 **有流量的 bin 个数**（与端口熵一致），**不要**用固定 100 作分母，否则活跃 bin 只有十几个时分数会被压低到 50 左右。

#### `temporal_burst`

```text
temporal_hhi = HHI(time_bin on learner-local [t_min, t_max], 100 bins)
span_ratio = learner_time_span / global_time_span
raw_value = 0.5 * temporal_hhi + 0.5 * (1 - min(span_ratio, 1))
score_0_100 = raw_value * 100
```

`temporal_hhi` 必须用 **learner 局部时间轴**；若用全局轴，短窗口攻击会与 `temporal_entropy` 一样退化为常数（HHI≈1）。

语义：

```text
高分表示短时间集中爆发。
```

#### `temporal_entropy`

```text
raw_value = norm_entropy(time_bin_counts where count > 0)
K = number of occupied time bins (not 100)
score_0_100 = raw_value * 100
```

语义：

```text
高分表示在 learner 活跃窗口内，有流量的各时间段上分布较均匀。
低分表示流集中在极少数时间段（可能仅 1–2 个 bin）。
```

#### `temporal_regular`

```text
raw_value = 1 - norm_entropy(time_bin)
score_0_100 = raw_value * 100
```

语义：

```text
高分表示时间分布集中或规则，常见于程序化流量。
```

## 4.7 实现审计备忘（常见误读）

| 指标 | 尺度/陷阱 | 说明 |
|------|-----------|------|
| `temporal_entropy` | learner 局部 100 bin，**K=有流量 bin 数** | 不可用全局轴；不可用 K=100 作分母 |
| `temporal_burst` | 局部 HHI + 全局 `span_ratio` | 局部 HHI 不可用全局轴，否则几乎所有短攻击 learner 突发分→100 |
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
top1_endpoint_edge_share >= 80
或 dst_endpoint_concentration >= 80
或 hub_in_strength >= 80
并且 temporal_burst >= 50
```

解释：

```text
少数目的、少数边或单一入向 hub 承载大量流量，并伴随时间突发。
```

### Scan-like

触发条件建议：

```text
dst_port_entropy >= 80
并且 hub_out_strength >= 50
并且 max_out_degree_ratio >= 50
并且 low_reciprocity >= 70
```

解释：

```text
目的端口或目的 endpoint 高度分散，但源端和方向性高度规则，偏扫描或探测。
```

### Single-service-like

触发条件建议：

```text
dst_port_top1_concentration >= 80
并且 endpoint_edge_regular >= 60
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
1. 先看边集中/复用：是否少数边支配。
2. 再看 hub：是目的集中还是源集中。
3. 再看端口熵：是单服务、复杂良性，还是扫描式高熵。
4. 再看低互惠性和叶子节点：是否呈单向星型/放射状。
5. 最后看时间突发：是否短时间程序化并发。
```

典型解释：

```text
Flood-like:
  top1_edge 高、dst_endpoint_concentration 高、hub_in_strength 高、temporal_burst 高。

Scan-like:
  dst_port_entropy 高、max_out_degree_ratio 高、hub_out_strength 高、low_reciprocity 高。

Single-service-like:
  dst_port_top1_concentration 高、endpoint_edge_regular 高、edge_reuse_ratio 高。

Benign-like:
  endpoint_edge_entropy 较高、top1_edge 低、low_reciprocity 不极端、temporal_burst 不强。
```

