"""Per-metric semantics for learner topology audit (strength tags, not risk levels)."""
from __future__ import annotations

from typing import Dict, TypedDict


class MetricMeta(TypedDict):
    trait_axis: str
    tag_low: str
    tag_high: str
    explain: str


# trait_axis drives UI color family (magnitude within trait, not good/bad).
METRIC_CATALOG: Dict[str, MetricMeta] = {
    "dst_port_entropy": {
        "trait_axis": "dispersion",
        "tag_low": "目的端口集中",
        "tag_high": "目的端口分散",
        "explain": "分数高=目的端口种类多、分布更散；低=少数端口占主导。高分散常见于扫描，也可能见于多服务访问。",
    },
    "src_port_entropy": {
        "trait_axis": "dispersion",
        "tag_low": "源端口模板化",
        "tag_high": "源端口分散",
        "explain": "分数高=源端口多样；低=源端口高度固定，常见于固定客户端或脚本。",
    },
    "port_pair_entropy": {
        "trait_axis": "dispersion",
        "tag_low": "端口对模板化",
        "tag_high": "端口对组合多样",
        "explain": "分数高=Src/Dst 端口组合多样；低=重复同一端口对模式。",
    },
    "dst_port_top1_concentration": {
        "trait_axis": "concentration",
        "tag_low": "目的端口分散",
        "tag_high": "目的端口高度集中",
        "explain": "分数高=流量集中在单一目的端口；低=目的端口较分散。",
    },
    "dst_port_hhi_concentration": {
        "trait_axis": "concentration",
        "tag_low": "目的端口分布平坦",
        "tag_high": "目的端口整体集中",
        "explain": "HHI 高=目的端口分布集中；低=分布更平坦。",
    },
    "endpoint_edge_entropy": {
        "trait_axis": "dispersion",
        "tag_low": "边高度复用/模板化",
        "tag_high": "边分布分散",
        "explain": "分数高=大量不同 IP:Port 边各承载少量流；低=少数边反复出现。",
    },
    "endpoint_edge_regular": {
        "trait_axis": "concentration",
        "tag_low": "边分布较散",
        "tag_high": "边权集中/规则",
        "explain": "边规则度高=少数边支配；低=边更分散。与边熵互补。",
    },
    "top1_endpoint_edge_share": {
        "trait_axis": "concentration",
        "tag_low": "无边主导",
        "tag_high": "单条边主导流量",
        "explain": "分数高=一条 SrcEP→DstEP 承担大部分流；低=流量分散在多条边。",
    },
    "top5_endpoint_edge_share": {
        "trait_axis": "concentration",
        "tag_low": "Top5 边占比低",
        "tag_high": "少数边覆盖大部分流",
        "explain": "分数高=前 5 条边占大部分流量；低=边权更均匀。",
    },
    "edge_reuse_ratio": {
        "trait_axis": "reuse",
        "tag_low": "边几乎不复用",
        "tag_high": "边复用率高",
        "explain": "分数高=平均每条边承载多条流；低=大量唯一边（每条边少量流）。",
    },
    "hub_in_strength": {
        "trait_axis": "hub_in",
        "tag_low": "入向分散",
        "tag_high": "单一目的端汇聚",
        "explain": "分数高=单一目的 endpoint 吸收大量流；低=入向流量较分散。",
    },
    "hub_out_strength": {
        "trait_axis": "hub_out",
        "tag_low": "出向分散",
        "tag_high": "单一源端发出大量流",
        "explain": "分数高=单一源 endpoint 发出大量流；低=源端较分散。",
    },
    "max_in_degree_ratio": {
        "trait_axis": "hub_in",
        "tag_low": "入度分散",
        "tag_high": "入向 hub 明显",
        "explain": "分数高=许多源连向同一目的；低=入度较均匀。",
    },
    "max_out_degree_ratio": {
        "trait_axis": "hub_out",
        "tag_low": "出度分散",
        "tag_high": "出向 hub 明显",
        "explain": "分数高=单一源连接大量目的；低=出度较均匀。",
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
        "explain": "分数高=流量来自少数源 endpoint；低=源较分散。",
    },
    "dst_endpoint_concentration": {
        "trait_axis": "concentration",
        "tag_low": "目的端分散",
        "tag_high": "目的端高度集中",
        "explain": "分数高=流量指向少数目的 endpoint；低=目的较分散。",
    },
    "leaf_ratio": {
        "trait_axis": "structure",
        "tag_low": "非叶子节点多",
        "tag_high": "叶子节点占比高",
        "explain": "分数高=拓扑多叶子，呈星型/放射状；低=节点连接更丰富。",
    },
    "edge_per_node": {
        "trait_axis": "density",
        "tag_low": "连接稀疏",
        "tag_high": "边/节点比高",
        "explain": "分数高=相对节点数边较多；低=连接稀疏。需结合其他指标解读。",
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
    "temporal_entropy": {
        "trait_axis": "time_spread",
        "tag_low": "时间高度集中",
        "tag_high": "时间分布均匀",
        "explain": "分数高=在活跃时段内流在多个时间段较均匀；低=挤在极少数时段。高均匀常见于持续 benign，也可能见于长时间低速率活动。",
    },
    "temporal_regular": {
        "trait_axis": "time_concentration",
        "tag_low": "时间较分散",
        "tag_high": "时间规则/集中",
        "explain": "分数高=时间分布集中或规则；低=时间更分散。与时间熵互补。",
    },
}

TRAIT_AXIS_LABELS: Dict[str, str] = {
    "dispersion": "分散度",
    "concentration": "集中度",
    "reuse": "复用度",
    "hub_in": "入向汇聚",
    "hub_out": "出向汇聚",
    "asymmetry": "不对称",
    "structure": "拓扑形态",
    "density": "连接密度",
    "unidirectional": "单向性",
    "burst": "时间突发",
    "time_spread": "时间均匀",
    "time_concentration": "时间集中",
}
