# Learner Metric Topology Family Rules

本文档把学习器详情页中的 v4 拓扑审计指标，映射为**数据集无关的拓扑形态/攻击族参考规则标签**。

这些规则用于人工研判，不是真值标签，也不是组合风险分。规则只说明：

```text
某学习器的指标形态与哪类正常流量形态、攻击形态或攻击族相近。
```

## 1. 分析口径

分析数据：

```text
data/aligned_2017_2019_2026_sampled_x5_yeartagged_for_main.csv
```

分析时只保留：

```text
Label 以 2017| 或 2019| 开头的流
```

该 aligned 文件由项目内公开数据集原始 CSV 对齐后生成，也是当前 Trident run 与 `visualize` 页面常用的数据口径。每个真实 `Label` 被临时当作一个“类学习器”，使用当前代码中的 audit 指标计算指标画像：

```text
dst_port_entropy
dst_port_richness
src_port_entropy
dst_port_top1_concentration
endpoint_edge_entropy
top1_endpoint_edge_share
edge_reuse_ratio
host_edge_entropy
dst_host_concentration
host_max_in_degree_ratio
host_max_out_degree_ratio
max_in_degree_ratio
max_out_degree_ratio
src_dst_endpoint_asymmetry
src_endpoint_concentration
dst_endpoint_concentration
leaf_ratio
edge_per_node
low_reciprocity
temporal_burst
temporal_global_spread
temporal_intra_uniformity
```

规则阈值使用上述指标的 `score_0_100`。

## 2. 总体发现

### 2.1 正常流量

CICIDS2017 与 CICIDS2019 的 `BENIGN` 都表现为：

- `endpoint_edge_entropy` 高，边分布较散。
- `top1_endpoint_edge_share` 很低，没有单一 IP:Port 边支配。
- `edge_reuse_ratio` 中等，不像一次性扫描边，也不像极端固定边复用。
- `dst_port_entropy` 低到中等，目的端口比 2019 反射攻击更集中。
- `low_reciprocity` 中等，低于大多数 2019 UDP/反射攻击。

因此正常参考规则优先描述“**边分散、无单边支配、目的端口不是大范围扫散、流内并非极端单向**”。

### 2.2 CICIDS2017 固定目的服务攻击族

2017 中以下攻击在现有指标上高度相似：

```text
DDOS
DOS_HULK
DOS_GOLDENEYE
DOS_SLOWHTTPTEST
DOS_SLOWLORIS
FTP-PATATOR
SSH-PATATOR
WEB_ATTACK_BRUTE_FORCE / XSS / SQL_INJECTION
BOTNET
```

共同形态：

- `dst_port_entropy` 接近 0。
- `dst_port_top1_concentration` 接近 100。
- `dst_endpoint_concentration` 与 `max_in_degree_ratio` 极高。
- `endpoint_edge_entropy` 仍可能很高，因为源端口或源 endpoint 变化很多。
- `top1_endpoint_edge_share` 常很低，不能把“低 Top1 边占比”误判为 benign。
- `leaf_ratio` 很高，图形态接近大量源指向少数目的 endpoint。

这说明 2017 的许多攻击不是“单条边反复出现”，而是“**固定目的服务 + 大量变化源端**”。

### 2.3 CICIDS2017 PortScan

`PORTSCAN` 与 `INFILTRATION_-_PORTSCAN` 表现为：

- `dst_port_entropy` 极高。
- `dst_port_top1_concentration` 极低。
- `dst_endpoint_concentration` 极低。
- `endpoint_edge_entropy` 极高。
- `low_reciprocity` 不如 2019 UDP/反射族极端。

在类级聚合后，`max_out_degree_ratio` 未必很高，因为扫描流会被多个源拆开。学习器级别若恰好聚到单源扫描，则 `max_out_degree_ratio` 仍然有用。

### 2.4 CICIDS2019 反射/UDP/SYN 攻击族

2019 中以下类型整体非常接近：

```text
DRDOS_DNS
DRDOS_LDAP
DRDOS_MSSQL
DRDOS_NETBIOS
DRDOS_NTP
DRDOS_SNMP
DRDOS_SSDP
DRDOS_UDP
SYN
TFTP
UDP-LAG
```

共同形态：

- `dst_port_entropy` 接近 100。
- `dst_port_top1_concentration` 接近 0。
- `endpoint_edge_entropy` 接近 100。
- `edge_reuse_ratio` 很低。
- `low_reciprocity` 极高，流记录内单向包特征强。
- 多数类 `temporal_global_spread` 很低，说明在当前 aligned 口径里位于很窄的全局时段。

这类指标更像“**高端口分散 + 大量一次性边 + 极强单向性**”，与 2017 固定目的服务攻击族不同。

### 2.5 不能精确区分的边界

只使用这些拓扑/时间指标时，下列攻击不应强行做精确分类：

- 2017 的 `DOS_HULK`、`DDOS`、`FTP-PATATOR`、`SSH-PATATOR`、多数 `WEB_ATTACK`。
- 2019 多种 `DRDOS_*` 与 `TFTP`、`SYN`、`UDP-LAG`。
- 少样本类，如 `HEARTBLEED`、`INFILTRATION`、非 attempted 的 SQL injection / XSS。

因此前端输出的是**参考规则标签**。同一学习器可以同时命中多个候选标签族。

## 3. 逐类指标特征

### 3.1 CICIDS2017

| 真实标签 | 指标语义画像 | 规则归属 |
|---|---|---|
| `BENIGN` | 边熵高、单边不支配、目的端口中低熵、复用中等、流内单向性不极端 | 正常参考 |
| `DDOS` | 目的端口固定、目的 endpoint 集中、入向 hub 极强、星型叶子多 | 2017 固定目的服务攻击 |
| `DOS_HULK` | 目的端口固定、目的 endpoint 集中、边熵高但边由变化源端展开 | 2017 固定目的服务攻击 |
| `DOS_GOLDENEYE` | 与固定目的 DoS 相同，流内单向性中等偏强 | 2017 固定目的服务攻击 |
| `DOS_SLOWHTTPTEST` | 固定目的端口和目的 endpoint，部分样本流内单向性更强 | 2017 固定目的慢速 DoS |
| `DOS_SLOWLORIS` | 固定目的端口、目的 endpoint 极集中，单向性强于普通 benign | 2017 固定目的慢速 DoS |
| `FTP-PATATOR` | 固定服务目的、入向 hub 极强、源端口高度分散 | 2017 固定目的服务攻击 |
| `SSH-PATATOR` | 固定服务目的、入向 hub 极强、源端口高度分散 | 2017 固定目的服务攻击 |
| `BOTNET` | 固定目的端口、目的 endpoint 极集中、边由源变化展开 | 2017 固定目的服务攻击 |
| `WEB_ATTACK_-_BRUTE_FORCE` | 固定 Web 服务目的、入向 hub 强、边熵高 | 2017 固定目的服务攻击 |
| `WEB_ATTACK_-_XSS` | 固定 Web 服务目的、入向 hub 强、样本较少 | 2017 固定目的服务攻击 |
| `WEB_ATTACK_-_SQL_INJECTION` | 固定 Web 服务目的、入向 hub 强、样本很少 | 2017 固定目的服务攻击 |
| `PORTSCAN` | 目的端口熵极高、目的端点分散、目的端口 Top1 很低 | 2017 端口扫描 |
| `INFILTRATION_-_PORTSCAN` | 与 PortScan 相近，源/目的规模不对称更明显 | 2017 端口扫描 |
| `INFILTRATION` | 小样本固定目的行为，单边占比与边复用更高 | 2017 小样本固定目标参考 |
| `HEARTBLEED` | 极少样本、固定边与固定端口明显、单边占比极高 | 2017 固定单边小样本参考 |

带 `_-_ATTEMPTED` 的 2017 标签通常继承其主类规则。规则文档保留主类名称，前端标签中把 attempted 作为该主类的参考候选，而不是另造一套过拟合阈值。

### 3.2 CICIDS2019

| 真实标签 | 指标语义画像 | 规则归属 |
|---|---|---|
| `BENIGN` | 边熵高、单边不支配、目的端口中等分散、复用中等 | 正常参考 |
| `DRDOS_DNS` | 目的端口极分散、边接近一次性、流内极单向，源端口分散度中高 | 2019 高分散单向放大攻击 |
| `DRDOS_LDAP` | 与 DNS 族相近，源端口分散度中高 | 2019 高分散单向放大攻击 |
| `DRDOS_MSSQL` | 高目的端口熵、极低目的端口 Top1、极强单向性 | 2019 高分散单向放大攻击 |
| `DRDOS_NETBIOS` | 高目的端口熵、边一次性、单向性极强 | 2019 高分散单向放大攻击 |
| `DRDOS_NTP` | 高目的端口熵、边一次性、单向性极强，时间窗内不均匀更明显 | 2019 高分散单向放大攻击 |
| `DRDOS_SNMP` | 高目的端口熵、高源端口分散、单向性极强 | 2019 高分散单向放大攻击 |
| `DRDOS_SSDP` | 高目的/源端口分散、单向性极强 | 2019 高分散单向放大攻击 |
| `DRDOS_UDP` | 目的/源端口都极分散、单向性极强 | 2019 高分散单向 UDP 攻击 |
| `SYN` | 目的/源端口都极分散、单向性很强 | 2019 高分散单向 SYN 攻击 |
| `TFTP` | 高目的端口熵、高源端口分散、边一次性 | 2019 高分散单向攻击 |
| `UDP-LAG` | 目的/源端口都极分散、单向性很强 | 2019 高分散单向 UDP 攻击 |
| `WEBDDOS` | 目的端口中等分散但源/目的 hub 同时明显，类似固定 Web 目标的高扇入/扇出小类 | 2019 WebDDoS 参考 |

## 4. 前端参考规则

下列规则已经以同样语义接入 `visualize` 学习器详情页。变量均为当前 audit 指标分数。

### 4.1 正常流量参考匹配

```text
endpoint_edge_entropy >= 82
top1_endpoint_edge_share <= 8
edge_reuse_ratio between 35 and 65
dst_port_entropy <= 45
dst_port_richness <= 75
dst_port_top1_concentration between 20 and 85
low_reciprocity <= 70
max_out_degree_ratio <= 15
```

语义：

```text
边分布散、无单边支配，目的端口不像扫描/反射攻击那样全局扫散，
流内单向性也未达到 2019 UDP/反射攻击的极端水平。
```

标定依据：

```text
历史良性流量画像的共性。
```

### 4.2 DoS/DDoS 等固定服务攻击族

```text
dst_port_entropy <= 12
dst_port_richness <= 30
dst_port_top1_concentration >= 95
endpoint_edge_entropy >= 80
src_port_entropy >= 80
并且满足至少一项汇聚支撑证据：
dst_host_concentration >= 65
或 max_in_degree_ratio >= 75
或 host_max_in_degree_ratio >= 75
```

语义：

```text
目的服务几乎固定，大量变化源端指向少数目的 endpoint；
边熵可能很高，但高熵来自源端展开，不代表正常。
主机层指标用于提供汇聚支撑证据，不再作为全部固定服务形态的一票否决条件。
```

标定依据：

```text
固定目的服务冲击/固定服务访问类画像的共性。
```

### 4.3 Slow DoS 类攻击参考匹配

```text
命中 DoS/DDoS 等固定服务攻击族
low_reciprocity >= 68
```

语义：

```text
仍是固定目的服务形态，但流内单向性更强；
该规则更接近 SlowHTTPTest / Slowloris 的一部分样本。
```

标定依据：

```text
慢速固定服务冲击画像的共性。
```

### 4.4 PortScan 类攻击参考匹配

```text
dst_port_entropy >= 90
dst_port_richness >= 70
dst_port_top1_concentration <= 15
dst_endpoint_concentration <= 15
endpoint_edge_entropy >= 90
low_reciprocity <= 75
```

语义：

```text
目的端口与目的 endpoint 大范围展开，单一服务不占主导；
其单向性在当前数据口径下通常弱于 2019 UDP/反射攻击族。
```

标定依据：

```text
端口扫描类画像的共性。
```

### 4.5 Heartbleed 小样本参考匹配

```text
endpoint_edge_entropy <= 20
top1_endpoint_edge_share >= 80
dst_port_top1_concentration >= 95
src_port_entropy <= 25
```

语义：

```text
少量流集中在极少边上。当前本地数据中更接近 Heartbleed 的小样本画像；
该标签只能作为人工复核提示。
```

标定依据：

```text
小样本固定边异常画像的共性，仅人工复核提示。
```

### 4.6 DRDoS/UDP/SYN 单向攻击族

```text
dst_port_entropy >= 90
dst_port_richness >= 90
dst_port_top1_concentration <= 10
endpoint_edge_entropy >= 95
edge_reuse_ratio <= 25
low_reciprocity >= 85
```

语义：

```text
目的端口高度分散，边接近一次性，流记录内强单向；
这是多数 DRDoS / UDP / SYN / TFTP 类的共同形态。
```

标定依据：

```text
高分散单向冲击画像的共性。
```

### 4.7 高分散单向攻击的源端口子形态

子形态只解释源端口展开强度，不替代上一条共同规则。

```text
src_port_entropy between 65 and 85
```

子形态语义：

```text
中高源端口分散度。
```

```text
src_port_entropy between 85 and 98
```

子形态语义：

```text
高源端口分散度。
```

```text
src_port_entropy >= 98
```

子形态语义：

```text
极高源端口分散度。
```

### 4.8 WebDDoS 类攻击参考匹配

```text
dst_port_entropy between 35 and 65
dst_port_top1_concentration between 50 and 85
max_in_degree_ratio >= 80
max_out_degree_ratio >= 80
endpoint_edge_entropy >= 90
```

语义：

```text
目的端口没有反射族那样极端分散，但入向和出向 hub 同时明显，
更接近 WebDDoS 类画像。
```

标定依据：

```text
双向 hub 服务冲击画像的共性。
```

## 5. 前端展示约束

学习器详情页应把规则结果显示为：

```text
参考规则标签
规则语义
```

不要显示：

```text
预测攻击类别
最终结论
综合风险分
```

推荐展示话术：

```text
命中参考规则：2019 高分散单向攻击
命中参考规则：DRDoS/UDP/SYN 单向攻击族
语义：目的端口高度分散，边接近一次性，流记录内强单向。
```

人工阅读顺序仍然是先看规则标签，再回到指标条形图核对证据。
