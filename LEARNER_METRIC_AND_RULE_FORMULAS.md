# 学习器拓扑指标与规则层匹配公式说明

本文档记录当前 Trident 学习器定性链路中，`learner_topology_metric_audit.json`
里的 **v4 指标计算公式**，以及 `visualize` 学习器详情页中
**规则层匹配结果** 的规则公式。

对应实现：

- 指标计算：`trident_stream/learner_metric_audit.py`
- 指标语义：`trident_stream/metric_audit_catalog.py`
- 可视化 artifact 导出：`trident_stream/visualization_artifacts.py`
- 前端规则匹配：`visualize/src/lib/learnerReferenceRules.ts`

重要约束：

- 所有指标的 `score_0_100` 都表示该维度上的**特征强度**，不是风险分。
- 不计算组合总分。
- 规则层匹配是**数据集无关的流量形态/攻击族参考标签**，不是真值标签，也不是最终攻击判定。
- 历史公开数据集只用于观察攻击形态和标定阈值；运行时输出不携带数据集年份、数据集名或原始样本标签。
- 同一学习器可以命中多条规则。

---

## 1. 输入与符号

对一个学习器，令其被分配到的流集合为：

```text
F = {f_1, f_2, ..., f_n}
n = |F|
```

每条流至少需要以下字段：

```text
SrcIP
DstIP
SrcPort
DstPort
```

可选字段：

```text
Timestamp
Total Fwd Packet / Total Fwd Packets / Fwd Packet
Total Bwd packets / Total Bwd Packets / Bwd Packet
```

定义：

```text
SrcEP_i = SrcIP_i + ":" + SrcPort_i
DstEP_i = DstIP_i + ":" + DstPort_i
EndpointEdge_i = SrcEP_i -> DstEP_i
HostEdge_i = SrcIP_i -> DstIP_i
```

对任意离散变量 `X`，记：

```text
count_X(x) = X 中类别 x 的出现次数
C_X = {count_X(x) | x in unique(X)}
```

---

## 2. 通用函数

### 2.1 归一化 Shannon 熵

用于端口、边、时间分布等。

```text
S = sum_j c_j
p_j = c_j / S
H = - sum_j p_j * ln(p_j)
H_norm = H / ln(K)
```

其中：

- `c_j` 是类别或 bin 的计数。
- 默认 `K = len({j | c_j > 0})`。
- 若显式传入固定 bin 数，则 `K = k_categories`。
- 若 `S <= 0` 或有效类别数小于等于 1，则 `H_norm = 0`。
- 结果裁剪到 `[0, 1]`。

代码：

```text
_norm_entropy(values, k_categories=None)
```

### 2.2 HHI 集中度

```text
HHI = sum_j p_j^2
```

其中 `p_j = c_j / sum(c)`。

代码：

```text
_hhi(values)
```

### 2.3 Top1 占比

```text
Top1Share(C) = max(C) / sum(C)
```

若无计数或总和为 0，则为 0。

代码：

```text
_top1_share(values)
```

### 2.4 丰富度分数

用于 `dst_port_richness`。

```text
observable = max(1, min(sample_count, max_categories))
score = min(100, ln(1 + unique_count) / ln(1 + observable) * 100)
```

目的端口最大类别数使用：

```text
max_categories = 65536
```

代码：

```text
_richness_score(unique_count, sample_count, max_categories)
```

### 2.5 有向最大入度/出度比例

给定有向边集合：

```text
E = {(src_i, dst_i)}
V = unique(src) union unique(dst)
```

去重边后：

```text
in_peers(v) = {u | (u, v) in E}
out_peers(v) = {w | (v, w) in E}
denom = max(1, |V| - 1)
max_in_degree_ratio = max_v |in_peers(v)| / denom
max_out_degree_ratio = max_v |out_peers(v)| / denom
```

代码：

```text
_directed_degree_ratios(src, dst)
```

### 2.6 分数档位

所有 `score_0_100` 映射为强度档位：

| 分数范围 | strength_band | 中文 |
|---:|---|---|
| `[0, 20)` | `VERY_LOW` | 很弱 |
| `[20, 40)` | `LOW` | 较弱 |
| `[40, 60)` | `MID` | 中等 |
| `[60, 80)` | `HIGH` | 较强 |
| `[80, 100]` | `VERY_HIGH` | 很强 |

---

## 3. 22 个核心指标公式

当前版本：

```text
METRIC_AUDIT_VERSION = 4
metric_count = 22
```

### 3.1 端口指标

#### 3.1.1 `dst_port_entropy`

名称：目的端口熵

```text
C = value_counts(DstPort)
raw_value = H_norm(C)
score_0_100 = raw_value * 100
```

语义：

- 高分：已出现的目的端口之间分布更均匀。
- 低分：少数目的端口占主导。
- 注意：该指标衡量均匀度，不等同于端口种类多；端口种类需看 `dst_port_richness`。

#### 3.1.2 `dst_port_richness`

名称：目的端口丰富度

```text
unique_count = nunique(DstPort)
raw_value = unique_count
observable = max(1, min(n, 65536))
score_0_100 = min(100, ln(1 + unique_count) / ln(1 + observable) * 100)
```

语义：

- 高分：目的端口种类确实大范围展开。
- 低分：目的端口种类少。

#### 3.1.3 `src_port_entropy`

名称：源端口熵

```text
C = value_counts(SrcPort)
raw_value = H_norm(C)
score_0_100 = raw_value * 100
```

语义：

- 高分：源端口分布更均匀、更分散。
- 低分：源端口高度固定或模板化。
- 注意：临时源端口会抬高该值，需要结合主机级指标解释。

#### 3.1.4 `dst_port_top1_concentration`

名称：目的端口 Top1 集中度

```text
C = value_counts(DstPort)
raw_value = Top1Share(C)
score_0_100 = raw_value * 100
```

语义：

- 高分：流量集中在单一目的端口。
- 低分：目的端口较分散。

---

### 3.2 IP:Port 边指标

#### 3.2.1 `endpoint_edge_entropy`

名称：IP:Port 边熵

```text
EndpointEdge_i = SrcEP_i -> DstEP_i
C = value_counts(EndpointEdge)
raw_value = H_norm(C)
score_0_100 = raw_value * 100
```

语义：

- 高分：大量不同 IP:Port 边各承载少量流。
- 低分：少数边反复出现，边高度复用或模板化。

#### 3.2.2 `top1_endpoint_edge_share`

名称：Top1 边占比

```text
C = value_counts(EndpointEdge)
raw_value = Top1Share(C)
score_0_100 = raw_value * 100
```

语义：

- 高分：单条 `SrcEP -> DstEP` 边承担大部分流。
- 低分：流量分散在多条边。

#### 3.2.3 `edge_reuse_ratio`

名称：边复用率

```text
unique_edges = nunique(EndpointEdge)
raw_value = n / max(1, unique_edges)
score_0_100 = min(100, ln(1 + raw_value) / ln(101) * 100)
```

语义：

- 高分：平均每条边承载多条流。
- 低分：大量唯一边，每条边只有少量流。

---

### 3.3 主机层指标

主机层忽略端口，用于削弱临时源端口对 endpoint 指标的影响。

#### 3.3.1 `host_edge_entropy`

名称：主机边熵

```text
HostEdge_i = SrcIP_i -> DstIP_i
C = value_counts(HostEdge)
raw_value = H_norm(C)
score_0_100 = raw_value * 100
```

语义：

- 高分：`SrcIP -> DstIP` 主机边分布更分散。
- 低分：少数主机边反复出现。

#### 3.3.2 `dst_host_concentration`

名称：目的主机集中度

```text
C = value_counts(DstIP)
raw_value = Top1Share(C)
score_0_100 = raw_value * 100
```

语义：

- 高分：流量高度流向少数目的主机。
- 低分：目的主机较分散。

#### 3.3.3 `host_max_in_degree_ratio`

名称：主机最大入度比例

```text
E_host = unique({(SrcIP_i, DstIP_i)})
V_host = unique(SrcIP) union unique(DstIP)
raw_value = max_v |{u | (u, v) in E_host}| / max(1, |V_host| - 1)
score_0_100 = raw_value * 100
```

语义：

- 高分：许多不同源主机连接到同一目的主机，主机入向 hub 明显。
- 低分：主机入度较分散。

#### 3.3.4 `host_max_out_degree_ratio`

名称：主机最大出度比例

```text
E_host = unique({(SrcIP_i, DstIP_i)})
V_host = unique(SrcIP) union unique(DstIP)
raw_value = max_v |{w | (v, w) in E_host}| / max(1, |V_host| - 1)
score_0_100 = raw_value * 100
```

语义：

- 高分：单一源主机连接许多目的主机，主机级出向 hub 明显。
- 低分：主机出度较分散。

---

### 3.4 端点与方向指标

#### 3.4.1 `max_in_degree_ratio`

名称：最大入度比例

```text
E_ep = unique({(SrcEP_i, DstEP_i)})
V_ep = unique(SrcEP) union unique(DstEP)
raw_value = max_v |{u | (u, v) in E_ep}| / max(1, |V_ep| - 1)
score_0_100 = raw_value * 100
```

语义：

- 高分：许多不同源 endpoint 连接到同一目的 endpoint，endpoint 入向星型明显。
- 注意：源临时端口会放大该值，应与 `host_max_in_degree_ratio` 对照。

#### 3.4.2 `max_out_degree_ratio`

名称：最大出度比例

```text
E_ep = unique({(SrcEP_i, DstEP_i)})
V_ep = unique(SrcEP) union unique(DstEP)
raw_value = max_v |{w | (v, w) in E_ep}| / max(1, |V_ep| - 1)
score_0_100 = raw_value * 100
```

语义：

- 高分：单一源 endpoint 连接大量目的 endpoint，endpoint 出向星型明显。

#### 3.4.3 `src_dst_endpoint_asymmetry`

名称：源/目的规模不对称

```text
unique_src = nunique(SrcEP)
unique_dst = nunique(DstEP)
all_unique = |unique(SrcEP) union unique(DstEP)|
raw_value = abs(unique_src - unique_dst) / max(1, all_unique)
score_0_100 = raw_value * 100
```

语义：

- 高分：源端点数与目的端点数差异大。
- 低分：两侧规模接近。

#### 3.4.4 `src_endpoint_concentration`

名称：源端点集中度

```text
C = value_counts(SrcEP)
raw_value = Top1Share(C)
score_0_100 = raw_value * 100
```

语义：

- 高分：流量高度来自少数源 endpoint。
- 低分：源 endpoint 较分散。

#### 3.4.5 `dst_endpoint_concentration`

名称：目的端点集中度

```text
C = value_counts(DstEP)
raw_value = Top1Share(C)
score_0_100 = raw_value * 100
```

语义：

- 高分：流量高度流向少数目的 endpoint。
- 低分：目的 endpoint 较分散。

---

### 3.5 图形态指标

图形态指标使用去重后的 endpoint 有向边：

```text
E_ep = unique({(SrcEP_i, DstEP_i)})
V_ep = unique(SrcEP) union unique(DstEP)
```

#### 3.5.1 `leaf_ratio`

名称：叶子节点比例

先把 endpoint 有向边当成无向边，计算无向邻居集合：

```text
N_undir(v) = {u | (u, v) in E_ep or (v, u) in E_ep}
leaf_count = |{v in V_ep | |N_undir(v)| <= 1}|
raw_value = leaf_count / max(1, |V_ep|)
score_0_100 = raw_value * 100
```

语义：

- 高分：大量叶子节点，拓扑呈星型或放射状，常见于扫描或 DDoS。
- 低分：节点连接更丰富。

#### 3.5.2 `edge_per_node`

名称：边节点比

```text
raw_value = |E_ep| / max(1, |V_ep|)
score_0_100 = min(100, ln(1 + raw_value) / ln(11) * 100)
```

语义：

- 高分：相对节点数，边较多，连接密度较高。
- 低分：连接稀疏。

#### 3.5.3 `low_reciprocity`

名称：低互惠性

该指标不使用反向 HostEdge 计数，而使用 CIC 流记录内的 Fwd/Bwd 包字段。

对所有 `Fwd + Bwd > 0` 的流：

```text
weighted_reciprocity =
  sum_i min(Fwd_i, Bwd_i) / sum_i (Fwd_i + Bwd_i)

raw_value = 1 - weighted_reciprocity
score_0_100 = raw_value * 100
```

若缺少 Fwd/Bwd 包字段，或所有流的 `Fwd + Bwd <= 0`，则该指标不输出。

语义：

- 高分：流记录内反向包极少，单向性强。
- 低分：Fwd/Bwd 包较均衡，更接近正常双向会话。

---

### 3.6 时间行为指标

时间指标需要 `Timestamp`，并且需要全局 run 时间跨度：

```text
global_time_span = max(Timestamp_all_joined) - min(Timestamp_all_joined)
global_time_origin = min(Timestamp_all_joined)
```

若当前学习器有效时间戳小于 2 条，或全局跨度小于等于 0，则不输出时间指标。

常量：

```text
LOCAL_TEMPORAL_BINS = 100
GLOBAL_BIN_TARGET_WIDTH_SEC = 3600
GLOBAL_BIN_MIN = 128
GLOBAL_BIN_MAX = 2048
```

#### 3.6.1 `temporal_burst`

名称：时间突发

当前学习器时间范围：

```text
t_min = min(Timestamp)
t_max = max(Timestamp)
learner_span = t_max - t_min
```

将当前学习器时间戳按 `[t_min, t_max]` 分为 100 个局部 bin：

```text
bin_counts_local = hist(Timestamp, bins=100, range=[t_min, t_max])
hhi_local = HHI(bin_counts_local)
span_ratio = learner_span / global_time_span
raw_value = 0.5 * hhi_local + 0.5 * (1 - min(span_ratio, 1))
score_0_100 = raw_value * 100
```

语义：

- 高分：短时间集中爆发。
- 低分：活跃时段长或时间更分散。

#### 3.6.2 `temporal_global_spread`

名称：全局时间分散度

全局 bin 数：

```text
n_global_bins = min(2048, max(128, global_time_span / 3600))
```

将当前学习器时间戳按全局时间轴 `[global_time_origin, global_time_origin + global_time_span]`
分箱：

```text
bin_counts_global = hist(Timestamp, bins=n_global_bins, global_range)
i_min = bin_index(t_min)
i_max = bin_index(t_max)
window_counts = bin_counts_global[i_min : i_max + 1]
occupied_global = {c in window_counts | c > 0}
```

若 `len(occupied_global) <= 1`：

```text
raw_value = 0
```

否则：

```text
raw_value = H_norm(occupied_global)
score_0_100 = raw_value * 100
```

语义：

- 高分：在该学习器已占用的全局时段足迹内分布更均匀。
- 低分：流更挤在少数时段。
- 注意：它不是全局占用跨度，跨度应结合 `temporal_burst`。

#### 3.6.3 `temporal_intra_uniformity`

名称：活跃窗内均匀度

复用 `temporal_burst` 中的 100 个局部 bin：

```text
occupied = {c in bin_counts_local | c > 0}
raw_value = H_norm(occupied)
score_0_100 = raw_value * 100
```

语义：

- 高分：在本学习器 `[t_min, t_max]` 内，流在各活跃时间段较均匀。
- 低分：流集中在少数活跃时段。

---

## 4. qualitative_hints 粗粒度形态提示

`qualitative_hints` 写入 `learner_topology_metric_audit.json`，用于辅助解释。
它们不是前端攻击族规则，也不是最终结论。

令：

```text
s(k) = metric k 的 score_0_100
缺失指标按 0 处理
```

### 4.1 `Flood-like`

```text
(s(top1_endpoint_edge_share) >= 80
 或 s(dst_endpoint_concentration) >= 80)
且 s(temporal_burst) >= 50
```

语义：

```text
少数目的/少数边承载大量流量，并伴随时间突发。
```

### 4.2 `Scan-like`

```text
s(dst_port_entropy) >= 80
且 s(max_out_degree_ratio) >= 50
且 s(low_reciprocity) >= 70
且 s(edge_reuse_ratio) <= 55
```

语义：

```text
目的端口分散、出向星型明显，且流内单向性强，偏扫描或探测。
```

### 4.3 `Single-service-like`

```text
s(dst_port_top1_concentration) >= 80
且 (
  s(top1_endpoint_edge_share) >= 60
  或 s(endpoint_edge_entropy) <= 35
)
```

语义：

```text
流量集中到少数服务端口和少数边，偏固定服务打击或固定服务访问。
```

### 4.4 `Benign-like`

```text
s(endpoint_edge_entropy) >= 60
且 s(top1_endpoint_edge_share) <= 30
且 s(low_reciprocity) <= 60
且 s(temporal_burst) <= 50
且 s(temporal_global_spread) >= 35
```

语义：

```text
边分布较分散，单边支配不明显；全局时间较分散、突发不强。
```

---

## 5. 前端规则层匹配

前端规则实现：

```text
visualize/src/lib/learnerReferenceRules.ts
```

匹配流程：

```text
1. metrics[] -> scores: Record<metric_key, score_0_100>
2. 遍历 REFERENCE_RULES
3. 对每条规则执行 match(scores)
4. 返回所有 match 为 true 的规则
```

辅助谓词：

```text
atLeast(scores, key, min):
  scores[key] 是有限数字 且 scores[key] >= min

atMost(scores, key, max):
  scores[key] 是有限数字 且 scores[key] <= max

between(scores, key, min, max):
  atLeast(scores, key, min) 且 atMost(scores, key, max)
```

若某规则依赖的指标不存在，则该条件为 false。

---

## 6. 当前规则公式

### 6.1 正常流量参考匹配

规则标签：

```text
正常流量参考匹配
```

公式：

```text
s(endpoint_edge_entropy) >= 82
且 s(top1_endpoint_edge_share) <= 8
且 35 <= s(edge_reuse_ratio) <= 65
且 s(dst_port_entropy) <= 45
且 s(dst_port_richness) <= 75
且 20 <= s(dst_port_top1_concentration) <= 85
且 s(low_reciprocity) <= 70
且 s(max_out_degree_ratio) <= 15
```

语义：

```text
边分布较散、无单边支配，目的端口丰富度处于常见服务混合范围，
流内单向性也不极端。
```

标定依据：

```text
来自历史良性流量画像的共性：边分布较散、单边不支配、目的服务混合但不过度扫散。
```

---

### 6.2 DoS/DDoS 等固定服务攻击族

规则标签：

```text
DoS/DDoS 等固定服务攻击族
```

该规则由两个子公式组成。

#### 6.2.1 固定服务核心条件

```text
hasFixedTargetServiceCore(s) =
  s(dst_port_entropy) <= 12
  且 s(dst_port_richness) <= 30
  且 s(dst_port_top1_concentration) >= 95
  且 s(endpoint_edge_entropy) >= 80
  且 s(src_port_entropy) >= 80
```

解释：

- 目的端口高度固定。
- 目的端口种类少。
- 目的端口 Top1 占比极高。
- endpoint 边仍然很分散，说明边熵高主要来自源端展开。
- 源端口高度分散，常见于大量变化源端。

#### 6.2.2 汇聚支撑条件

```text
hasFixedTargetSupport(s) =
  s(dst_host_concentration) >= 65
  或 s(max_in_degree_ratio) >= 75
  或 s(host_max_in_degree_ratio) >= 75
```

解释：

- 目的主机集中，或 endpoint 入向 hub 明显，或主机级入向 hub 明显。
- 主机层指标作为支撑证据，不作为全部固定服务形态的一票否决条件。

#### 6.2.3 最终规则

```text
match =
  hasFixedTargetServiceCore(s)
  且 hasFixedTargetSupport(s)
```

语义：

```text
该形态与 DoS/DDoS 及其他固定服务攻击族相近：
目的服务几乎固定，大量变化源端指向少数目的 endpoint。
```

标定依据：

```text
来自固定目的服务冲击/固定服务访问类画像的共性：
目的端口极集中，源端或边集合大量展开，并存在目的主机或入向 hub 汇聚。
```

---

### 6.3 Slow DoS 类攻击参考匹配

规则标签：

```text
Slow DoS 类攻击参考匹配
```

公式：

```text
match =
  DoS/DDoS 等固定服务攻击族命中
  且 s(low_reciprocity) >= 68
```

展开为：

```text
hasFixedTargetServiceCore(s)
且 hasFixedTargetSupport(s)
且 s(low_reciprocity) >= 68
```

语义：

```text
固定目的服务汇聚仍明显，同时流内单向性更强，
提示慢速或低反馈的服务冲击行为。
```

标定依据：

```text
来自慢速固定服务冲击画像的共性：
固定目的服务汇聚成立，同时流记录内反馈弱、单向性更强。
```

---

### 6.4 PortScan 类攻击参考匹配

规则标签：

```text
PortScan 类攻击参考匹配
```

公式：

```text
s(dst_port_entropy) >= 90
且 s(dst_port_richness) >= 70
且 s(dst_port_top1_concentration) <= 15
且 s(dst_endpoint_concentration) <= 15
且 s(endpoint_edge_entropy) >= 90
且 s(low_reciprocity) <= 75
```

语义：

```text
目的端口丰富度和分布熵同时偏高，
目的 endpoint 大范围展开，单一服务不占主导。
```

标定依据：

```text
来自端口扫描类画像的共性：
目的端口丰富度和目的端口熵很高，单一目的服务不占主导，目的 endpoint 展开明显。
```

---

### 6.5 Heartbleed 小样本参考匹配

规则标签：

```text
Heartbleed 小样本参考匹配
```

公式：

```text
s(endpoint_edge_entropy) <= 20
且 s(top1_endpoint_edge_share) >= 80
且 s(dst_port_top1_concentration) >= 95
且 s(src_port_entropy) <= 25
```

语义：

```text
少量流集中在极少边上；这类小样本形态只适合作为人工复核提示。
```

标定依据：

```text
来自小样本固定边异常画像的共性：
少量流高度集中在极少 endpoint 边上，仅作为人工复核提示。
```

---

### 6.6 DRDoS/UDP/SYN 单向攻击族

规则标签：

```text
DRDoS/UDP/SYN 单向攻击族
```

核心公式：

```text
isDiffuseOneWayAttack(s) =
  s(dst_port_entropy) >= 90
  且 s(dst_port_richness) >= 90
  且 s(dst_port_top1_concentration) <= 10
  且 s(endpoint_edge_entropy) >= 95
  且 s(edge_reuse_ratio) <= 25
  且 s(low_reciprocity) >= 85
```

语义：

```text
该形态与 DRDoS、UDP/SYN 冲击族相近：
目的端口高度分散，边接近一次性，流记录内强单向。
```

标定依据：

```text
来自高分散单向冲击画像的共性：
目的端口和 endpoint 边高度展开，边复用低，流记录内强单向。
```

---

### 6.7 DRDoS DNS/LDAP/NTP 类参考匹配

规则标签：

```text
DRDoS DNS/LDAP/NTP 类参考匹配
```

公式：

```text
isDiffuseOneWayAttack(s)
且 65 <= s(src_port_entropy) <= 85
```

语义：

```text
在高分散单向形态上，源端口分散度处于中高区间，
提示一类较稳定的端口展开模式。
```

标定依据：

```text
来自中高源端口分散度的反射/放大类子形态画像。
```

---

### 6.8 DRDoS SNMP/SSDP/TFTP 类参考匹配

规则标签：

```text
DRDoS SNMP/SSDP/TFTP 类参考匹配
```

公式：

```text
isDiffuseOneWayAttack(s)
且 85 <= s(src_port_entropy) <= 98
```

语义：

```text
在高分散单向形态上，源端口分散度更高，
提示源端口展开更充分的子形态。
```

标定依据：

```text
来自高源端口分散度的反射/放大类子形态画像。
```

---

### 6.9 DRDoS UDP/SYN/UDP-LAG 类参考匹配

规则标签：

```text
DRDoS UDP/SYN/UDP-LAG 类参考匹配
```

公式：

```text
isDiffuseOneWayAttack(s)
且 s(src_port_entropy) >= 98
```

语义：

```text
在高分散单向形态上，源端口也极分散，
提示源端和目的端同时高度展开。
```

标定依据：

```text
来自极高源端口分散度的 UDP/SYN 冲击类子形态画像。
```

---

### 6.10 WebDDoS 类攻击参考匹配

规则标签：

```text
WebDDoS 类攻击参考匹配
```

公式：

```text
35 <= s(dst_port_entropy) <= 65
且 50 <= s(dst_port_top1_concentration) <= 85
且 s(max_in_degree_ratio) >= 80
且 s(max_out_degree_ratio) >= 80
且 s(endpoint_edge_entropy) >= 90
```

语义：

```text
目的端口没有全局扫散，但入向和出向 hub 同时明显，
提示围绕服务节点的双向冲击结构。
```

标定依据：

```text
来自双向 hub 服务冲击画像的共性：
目的端口没有全局扫散，但入向和出向 hub 同时明显。
```

---

## 7. 规则层输出字段

每条命中的规则返回：

```json
{
  "key": "diffuse-one-way-drdos-udp-syn-family",
  "name": "DRDoS/UDP/SYN 单向攻击族",
  "tone": "attack",
  "semantic": "该形态与 DRDoS、UDP/SYN 冲击族相近：目的端口高度分散，边接近一次性，流记录内强单向。"
}
```

前端当前展示：

- `name`
- `semantic`
- 命中数量

前端当前不展示：

- 数据集年份
- 原始数据集标签
- 标定样本名称

原因是页面希望展示“规则层参考匹配结果”，避免把标定来源误读为最终结论。

---

## 8. 被移除或不再导出的指标

当前 v4 不再导出下列指标：

| 指标 | 移除原因 |
|---|---|
| `port_pair_entropy` | 与源/目的端口熵高度相关，保留分列熵即可 |
| `dst_port_hhi_concentration` | 与目的端口 Top1 集中度、熵信息重复 |
| `endpoint_edge_regular` | 恒为 `1 - endpoint_edge_entropy` |
| `top5_endpoint_edge_share` | 与 Top1 边占比强相关，Top1 更易解释 |
| `hub_in_strength` | 与 `dst_endpoint_concentration` 等价 |
| `hub_out_strength` | 与 `src_endpoint_concentration` 等价 |
| `temporal_regular` | 曾为 `1 - temporal_entropy` |
| `temporal_entropy` | v3 拆为 `temporal_global_spread` 与 `temporal_intra_uniformity` |
