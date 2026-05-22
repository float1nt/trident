"""Per-metric semantics for learner topology audit (strength tags, not risk levels).

Core set: per-learner endpoint/host topology metrics. Removed keys are listed in
REMOVED_METRICS — do not re-export without review.
"""
from __future__ import annotations

from typing import Dict, TypedDict

METRIC_AUDIT_VERSION = 4

CORE_METRIC_KEYS = (
    "dst_port_entropy",
    "dst_port_richness",
    "src_port_entropy",
    "dst_port_top1_concentration",
    "endpoint_edge_entropy",
    "top1_endpoint_edge_share",
    "edge_reuse_ratio",
    "host_edge_entropy",
    "dst_host_concentration",
    "host_max_in_degree_ratio",
    "host_max_out_degree_ratio",
    "max_in_degree_ratio",
    "max_out_degree_ratio",
    "src_dst_endpoint_asymmetry",
    "src_endpoint_concentration",
    "dst_endpoint_concentration",
    "leaf_ratio",
    "edge_per_node",
    "low_reciprocity",
    "temporal_burst",
    "temporal_global_spread",
    "temporal_intra_uniformity",
)


class MetricMeta(TypedDict):
    trait_axis: str
    tag_low: str
    tag_high: str
    explain: str


# Removed in v2 (redundant or algebraically dependent on a kept metric).
REMOVED_METRICS: Dict[str, str] = {
    "port_pair_entropy": "与 src/dst 端口熵高度相关，保留分列熵即可",
    "dst_port_hhi_concentration": "与目的端口 Top1 集中度、熵信息重复",
    "endpoint_edge_regular": "恒为 1 − endpoint_edge_entropy",
    "top5_endpoint_edge_share": "与 Top1 边占比强相关，Top1 更易解释",
    "hub_in_strength": "与 dst_endpoint_concentration 等价（最大目的端点流占比）",
    "hub_out_strength": "与 src_endpoint_concentration 等价（最大源端点流占比）",
    "temporal_regular": "已移除；曾为 1 − temporal_entropy",
    "temporal_entropy": "v3 拆为 temporal_global_spread + temporal_intra_uniformity",
}

METRIC_CATALOG: Dict[str, MetricMeta] = {
    "dst_port_entropy": {
        "trait_axis": "dispersion",
        "tag_low": "目的端口集中",
        "tag_high": "目的端口分散",
        "explain": "分数高=已出现的目的端口之间分布更均匀；低=少数端口占主导。该熵描述分布均匀度，端口种类数请结合目的端口丰富度。",
    },
    "dst_port_richness": {
        "trait_axis": "richness",
        "tag_low": "目的端口种类少",
        "tag_high": "目的端口种类丰富",
        "explain": "原始值=不同目的端口数；分数按当前流量规模归一化。高分表示目的端口确实大范围展开，可与目的端口熵区分“均匀”与“种类多”。",
    },
    "src_port_entropy": {
        "trait_axis": "dispersion",
        "tag_low": "源端口模板化",
        "tag_high": "源端口分散",
        "explain": "分数高=已出现源端口之间分布更均匀；低=源端口高度固定。临时源端口会抬高该指标，应结合主机级指标解释。",
    },
    "dst_port_top1_concentration": {
        "trait_axis": "concentration",
        "tag_low": "目的端口分散",
        "tag_high": "目的端口高度集中",
        "explain": "分数高=流量集中在单一目的端口；低=目的端口较分散。",
    },
    "endpoint_edge_entropy": {
        "trait_axis": "dispersion",
        "tag_low": "边高度复用/模板化",
        "tag_high": "边分布分散",
        "explain": "分数高=大量不同 IP:Port 边各承载少量流；低=少数边反复出现。",
    },
    "top1_endpoint_edge_share": {
        "trait_axis": "concentration",
        "tag_low": "无边主导",
        "tag_high": "单条边主导流量",
        "explain": "分数高=一条 SrcEP→DstEP 承担大部分流；低=流量分散在多条边。",
    },
    "edge_reuse_ratio": {
        "trait_axis": "reuse",
        "tag_low": "边几乎不复用",
        "tag_high": "边复用率高",
        "explain": "分数高=平均每条边承载多条流；低=大量唯一边（每条边少量流）。与边熵互补：扫描常高熵低复用，flood 常低熵高复用。",
    },
    "host_edge_entropy": {
        "trait_axis": "dispersion",
        "tag_low": "主机边模板化",
        "tag_high": "主机边分布分散",
        "explain": "分数高=SrcIP→DstIP 主机边分布更散；低=少数主机边反复出现。它忽略源临时端口，可与 IP:Port 边熵对照。",
    },
    "dst_host_concentration": {
        "trait_axis": "concentration",
        "tag_low": "目的主机分散",
        "tag_high": "目的主机高度集中",
        "explain": "分数高=流量高度流向少数目的主机；低=目的主机较分散。",
    },
    "host_max_in_degree_ratio": {
        "trait_axis": "hub_in",
        "tag_low": "主机入度分散",
        "tag_high": "主机入向 hub 明显",
        "explain": "分数高=许多不同源主机连接到同一目的主机；它比 endpoint 入度更少受源临时端口影响。",
    },
    "host_max_out_degree_ratio": {
        "trait_axis": "hub_out",
        "tag_low": "主机出度分散",
        "tag_high": "主机出向 hub 明显",
        "explain": "分数高=单一源主机连接许多目的主机；它比 endpoint 出度更接近主机级扫描结构。",
    },
    "max_in_degree_ratio": {
        "trait_axis": "hub_in",
        "tag_low": "入度分散",
        "tag_high": "入向 hub 明显",
        "explain": "分数高=许多不同源 endpoint 连接到同一目的 endpoint（入向星型）；源临时端口会放大该值，需与主机级入度对照。",
    },
    "max_out_degree_ratio": {
        "trait_axis": "hub_out",
        "tag_low": "出度分散",
        "tag_high": "出向 hub 明显",
        "explain": "分数高=单一源 endpoint 连接大量目的 endpoint（出向星型）；低=出度较均匀，需与主机级出度对照。",
    },
    "src_dst_endpoint_asymmetry": {
        "trait_axis": "asymmetry",
        "tag_low": "源目规模均衡",
        "tag_high": "源/目的规模不对称",
        "explain": "分数高=源端点数与目的端点数差异大；低=两侧规模接近。",
    },
    "src_endpoint_concentration": {
        "trait_axis": "concentration",
        "tag_low": "源端分散",
        "tag_high": "源端高度集中",
        "explain": "分数高=流量高度来自少数源 endpoint（单源发出）；低=源较分散。",
    },
    "dst_endpoint_concentration": {
        "trait_axis": "concentration",
        "tag_low": "目的端分散",
        "tag_high": "目的端高度集中",
        "explain": "分数高=流量高度流向少数目的 endpoint（单点吸收）；低=目的较分散。",
    },
    "leaf_ratio": {
        "trait_axis": "structure",
        "tag_low": "非叶子节点多",
        "tag_high": "叶子节点占比高",
        "explain": "分数高=拓扑多叶子，呈星型或放射状；低=节点连接更丰富。",
    },
    "edge_per_node": {
        "trait_axis": "density",
        "tag_low": "连接稀疏",
        "tag_high": "边/节点比高",
        "explain": "分数高=相对节点数边较多；低=连接稀疏。需结合边熵与集中度解读。",
    },
    "low_reciprocity": {
        "trait_axis": "unidirectional",
        "tag_low": "流内双向包较均衡",
        "tag_high": "流内单向性强",
        "explain": "分数高=Fwd 包远大于 Bwd（单向）；低=同一条流记录内 Fwd/Bwd 包较均衡，更接近正常会话。",
    },
    "temporal_burst": {
        "trait_axis": "burst",
        "tag_low": "时间跨度大/突发弱",
        "tag_high": "时间突发明显",
        "explain": "分数高=相对全局窗口时间短且时间分布集中；低=活跃时段长或时间更分散。",
    },
    "temporal_global_spread": {
        "trait_axis": "time_global",
        "tag_low": "全局时间轴上集中",
        "tag_high": "全局时间轴上分散",
        "explain": "分数高=在该学习器已占用的全局时段足迹内分布更均匀；低=流更挤在少数时段。它不是全局占用跨度，跨度请结合时间突发。",
    },
    "temporal_intra_uniformity": {
        "trait_axis": "time_uniformity",
        "tag_low": "活跃窗内时段集中",
        "tag_high": "活跃窗内时段均匀",
        "explain": "分数高=在本学习器 [t_min,t_max] 内流在各时间段较均匀；低=挤在少数时段。持续 flood 常高分，与全局分散度互补。",
    },
}

TRAIT_AXIS_LABELS: Dict[str, str] = {
    "dispersion": "分散度",
    "concentration": "集中度",
    "reuse": "复用度",
    "richness": "丰富度",
    "hub_in": "入向连接",
    "hub_out": "出向连接",
    "asymmetry": "不对称",
    "structure": "拓扑形态",
    "density": "连接密度",
    "unidirectional": "单向性",
    "burst": "时间突发",
    "time_global": "全局时间分散",
    "time_uniformity": "窗内时间均匀",
}
