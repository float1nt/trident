"""Learner topology metric audit — computes 20+ independent metrics per learner.

Each metric returns a dict with:
  group, metric_key, metric_name, raw_value, score_0_100, semantic_level, semantic_text

No composite scores. Each metric is independent.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .metric_audit_catalog import METRIC_CATALOG, TRAIT_AXIS_LABELS

STRENGTH_BANDS = ["VERY_LOW", "LOW", "MID", "HIGH", "VERY_HIGH"]
STRENGTH_LABELS = ["很弱", "较弱", "中等", "较强", "很强"]


def _score_to_strength(score: float) -> tuple[str, str]:
    """Map 0–100 score to neutral strength band (not risk / anomaly)."""
    s = max(0.0, min(100.0, float(score)))
    if s < 20:
        return "VERY_LOW", "很弱"
    if s < 40:
        return "LOW", "较弱"
    if s < 60:
        return "MID", "中等"
    if s < 80:
        return "HIGH", "较强"
    return "VERY_HIGH", "很强"


def _semantic_tag(score: float, meta: Dict[str, str]) -> str:
    s = max(0.0, min(100.0, float(score)))
    if s >= 80:
        return meta["tag_high"]
    if s >= 50:
        return f"偏{meta['tag_high']}" if not meta["tag_high"].startswith("偏") else meta["tag_high"]
    if s >= 20:
        return f"偏{meta['tag_low']}" if not meta["tag_low"].startswith("偏") else meta["tag_low"]
    return meta["tag_low"]


def _norm_entropy(values: np.ndarray, *, k_categories: Optional[int] = None) -> float:
    """Normalized Shannon entropy H / ln(K).

    Args:
        values: category counts (value_counts) OR fixed-length histogram bins.
        k_categories: divisor K; default len(values). For histograms with empty bins,
            pass k_categories=len(values) (e.g. 100). For value_counts arrays, omit.
    """
    v = np.asarray(values, dtype=np.float64)
    s = float(np.sum(v))
    if s <= 0:
        return 0.0
    p = v[v > 0] / s
    if len(p) <= 1:
        return 0.0
    h = float(-np.sum(p * np.log(p)))
    k = int(k_categories) if k_categories is not None else int(len(v))
    if k <= 1:
        return 0.0
    return min(1.0, max(0.0, h / math.log(k)))


def _hhi(values: np.ndarray) -> float:
    """Herfindahl-Hirschman Index: sum(p_i^2)."""
    v = np.asarray(values, dtype=np.float64)
    s = float(np.sum(v))
    if s <= 0:
        return 0.0
    p = v / s
    return float(np.sum(p * p))


def _top1_share(values: np.ndarray) -> float:
    v = np.asarray(values, dtype=np.float64)
    s = float(np.sum(v))
    if s <= 0 or len(v) == 0:
        return 0.0
    return float(np.max(v) / s)


def _top5_share(values: np.ndarray) -> float:
    v = np.asarray(values, dtype=np.float64)
    s = float(np.sum(v))
    if s <= 0:
        return 0.0
    top5 = np.sort(v)[-5:]
    return float(np.sum(top5) / s)


def _make_metric(
    group: str,
    key: str,
    name: str,
    raw: float,
    score: float,
    text: str | None = None,
) -> Dict[str, Any]:
    meta = METRIC_CATALOG.get(key, {})
    trait_axis = meta.get("trait_axis", "neutral")
    band, strength_label = _score_to_strength(score)
    semantic_tag = _semantic_tag(score, meta) if meta else strength_label
    explain = meta.get("explain", text or "") if meta else (text or "")
    return {
        "group": group,
        "metric_key": key,
        "metric_name": name,
        "raw_value": round(raw, 6),
        "score_0_100": round(score, 2),
        "trait_axis": trait_axis,
        "trait_axis_label": TRAIT_AXIS_LABELS.get(trait_axis, trait_axis),
        "strength_band": band,
        "strength_label": strength_label,
        "semantic_tag": semantic_tag,
        "semantic_text": explain,
        # Deprecated: kept for older JSON; do not use as risk level.
        "semantic_level": band,
    }


# ─────────────────────────────────────────────────────────────
#  Main entry point
# ─────────────────────────────────────────────────────────────


def compute_learner_metrics(
    learner_name: str,
    flows: "pd.DataFrame",
    global_time_span: Optional[float] = None,
    global_time_origin: Optional["pd.Timestamp"] = None,
) -> List[Dict[str, Any]]:
    """Compute all metrics for one learner from its flow DataFrame.

    Required columns: SrcIP, DstIP, SrcPort, DstPort
    Optional: Timestamp (for temporal metrics)

    Args:
        learner_name: learner identifier
        flows: DataFrame with the learner's assigned flows
        global_time_span: total time span of the entire run (seconds).
                          If None, temporal metrics are skipped.
        global_time_origin: dataset-wide earliest timestamp for bin alignment.
                            If None, uses min timestamp within this learner's flows.

    Returns:
        list of metric dicts
    """

    if flows.empty:
        return []

    n = len(flows)
    src_ip = flows["SrcIP"].astype(str).str.strip()
    dst_ip = flows["DstIP"].astype(str).str.strip()
    src_port = flows["SrcPort"].fillna(0).astype(int).astype(str)
    dst_port = flows["DstPort"].fillna(0).astype(int).astype(str)

    # Endpoint composites
    src_ep = src_ip + ":" + src_port
    dst_ep = dst_ip + ":" + dst_port
    ep_edge = src_ep + " -> " + dst_ep  # SrcEP -> DstEP direction matters

    metrics: List[Dict[str, Any]] = []

    # ── 4.1 端口随机性 ──
    _port_entropy_metrics(metrics, dst_port, src_port, dst_port, n)
    # ── 4.2 边集中/复用 ──
    _edge_reuse_metrics(metrics, ep_edge, n)
    # ── 4.3 Hub 结构 ──
    _hub_metrics(metrics, src_ep, dst_ep, n)
    # ── 4.4 源目的不对称 ──
    _asymmetry_metrics(metrics, src_ep, dst_ep)
    # ── 4.5 图形态 ──
    _graph_shape_metrics(metrics, flows, src_ep, dst_ep, ep_edge, n)
    # ── 4.6 时间行为 (optional) ──
    if "Timestamp" in flows.columns and global_time_span is not None and global_time_span > 0:
        _temporal_metrics(metrics, flows, n, global_time_span, global_time_origin)

    return metrics


# ─────────────────────────────────────────────────────────────
#  4.1 端口随机性
# ─────────────────────────────────────────────────────────────


def _port_entropy_metrics(
    metrics: list,
    dst_port: "pd.Series",
    src_port: "pd.Series",
    dst_port_orig: "pd.Series",
    n: int,
) -> None:
    dst_counts = dst_port.value_counts().to_numpy(dtype=np.float64)
    src_counts = src_port.value_counts().to_numpy(dtype=np.float64)
    pair = (src_port.astype(str) + "->" + dst_port_orig.astype(str)).value_counts().to_numpy(dtype=np.float64)

    # dst_port_entropy
    h_dst = _norm_entropy(dst_counts)
    metrics.append(_make_metric(
        "端口随机性", "dst_port_entropy", "目的端口熵",
        h_dst, h_dst * 100,
        "高分=目的端口更分散，需结合源集中度和互惠性判断是否为端口扫描；低分=端口高度集中，常见于固定服务/food。"
    ))

    # src_port_entropy
    h_src = _norm_entropy(src_counts)
    metrics.append(_make_metric(
        "端口随机性", "src_port_entropy", "源端口熵",
        h_src, h_src * 100,
        "高分=源端口更分散；低分=源端口模板化，来自固定程序/脚本。"
    ))

    # port_pair_entropy
    h_pair = _norm_entropy(pair)
    metrics.append(_make_metric(
        "端口随机性", "port_pair_entropy", "端口对熵",
        h_pair, h_pair * 100,
        "高分=端口组合多样；低分=端口组合高度模板化，程序化重复更强。"
    ))

    # dst_port_top1_concentration
    t1 = _top1_share(dst_counts)
    metrics.append(_make_metric(
        "端口随机性", "dst_port_top1_concentration", "目的端口 Top1 集中度",
        t1, t1 * 100,
        "高分=少数目的端口承载大量流量，常见于固定服务攻击/food/单服务访问。"
    ))

    # dst_port_hhi_concentration
    hhi = _hhi(dst_counts)
    metrics.append(_make_metric(
        "端口随机性", "dst_port_hhi_concentration", "目的端口 HHI 集中度",
        hhi, hhi * 100,
        "高分=目的端口整体分布高度集中。"
    ))


# ─────────────────────────────────────────────────────────────
#  4.2 边集中/复用
# ─────────────────────────────────────────────────────────────


def _edge_reuse_metrics(
    metrics: list,
    ep_edge: "pd.Series",
    n: int,
) -> None:
    edge_counts = ep_edge.value_counts().to_numpy(dtype=np.float64)
    unique_edges = len(edge_counts)

    # endpoint_edge_entropy
    h_edge = _norm_entropy(edge_counts)
    metrics.append(_make_metric(
        "边集中/复用", "endpoint_edge_entropy", "IP:Port 边熵",
        h_edge, h_edge * 100,
        "高分=IP:Port边分布更分散；低分=少数边被反复使用，拓扑模板化。"
    ))

    # endpoint_edge_regular
    reg = 1.0 - h_edge
    metrics.append(_make_metric(
        "边集中/复用", "endpoint_edge_regular", "IP:Port 边规则度",
        reg, reg * 100,
        "高分=边权高度集中、程序化重复强。"
    ))

    # top1_endpoint_edge_share
    t1 = _top1_share(edge_counts)
    metrics.append(_make_metric(
        "边集中/复用", "top1_endpoint_edge_share", "Top1 IP:Port 边占比",
        t1, t1 * 100,
        "高分=单条IP:Port边支配流量，程序化重复特征极强。"
    ))

    # top5_endpoint_edge_share
    t5 = _top5_share(edge_counts)
    metrics.append(_make_metric(
        "边集中/复用", "top5_endpoint_edge_share", "Top5 IP:Port 边占比",
        t5, t5 * 100,
        "高分=少数IP:Port边覆盖大部分流量。"
    ))

    # edge_reuse_ratio
    reuse = n / max(1, unique_edges)
    score_reuse = min(100.0, math.log1p(reuse) / math.log1p(100) * 100)
    metrics.append(_make_metric(
        "边集中/复用", "edge_reuse_ratio", "边复用率",
        reuse, score_reuse,
        "高分=每条边平均被大量复用，常见于food/固定连接/批量请求。"
    ))


# ─────────────────────────────────────────────────────────────
#  4.3 Hub 结构
# ─────────────────────────────────────────────────────────────


def _hub_metrics(
    metrics: list,
    src_ep: "pd.Series",
    dst_ep: "pd.Series",
    n: int,
) -> None:
    src_counts = src_ep.value_counts()
    dst_counts = dst_ep.value_counts()

    pairs = set(zip(src_ep, dst_ep))
    out_peers: Dict[str, set] = {}
    in_peers: Dict[str, set] = {}
    for s, d in pairs:
        out_peers.setdefault(s, set()).add(d)
        in_peers.setdefault(d, set()).add(s)

    all_eps = set(src_counts.index) | set(dst_counts.index)
    node_count = max(1, len(all_eps))

    # hub_in_strength
    max_in_flow = float(dst_counts.max()) if len(dst_counts) else 0.0
    s_in = max_in_flow / max(1, n)
    metrics.append(_make_metric(
        "Hub结构", "hub_in_strength", "入向 Hub 流量占比",
        s_in, s_in * 100,
        "高分=单一目的endpoint吸收大量流量，偏DDoS/服务打击/集中爆破。"
    ))

    # hub_out_strength
    max_out_flow = float(src_counts.max()) if len(src_counts) else 0.0
    s_out = max_out_flow / max(1, n)
    metrics.append(_make_metric(
        "Hub结构", "hub_out_strength", "出向 Hub 流量占比",
        s_out, s_out * 100,
        "高分=单一源endpoint发出大量流量，偏扫描/单源自动化/探测。"
    ))

    # max_in_degree_ratio
    max_in_deg = max((len(v) for v in in_peers.values()), default=0)
    r_in_deg = max_in_deg / max(1, node_count - 1)
    metrics.append(_make_metric(
        "Hub结构", "max_in_degree_ratio", "最大入度比例",
        r_in_deg, r_in_deg * 100,
        "高分=很多源连接到同一目的，呈入向hub。"
    ))

    # max_out_degree_ratio
    max_out_deg = max((len(v) for v in out_peers.values()), default=0)
    r_out_deg = max_out_deg / max(1, node_count - 1)
    metrics.append(_make_metric(
        "Hub结构", "max_out_degree_ratio", "最大出度比例",
        r_out_deg, r_out_deg * 100,
        "高分=单一源连接很多目的，偏扫描或横向探测。"
    ))


# ─────────────────────────────────────────────────────────────
#  4.4 源目的不对称
# ─────────────────────────────────────────────────────────────


def _asymmetry_metrics(
    metrics: list,
    src_ep: "pd.Series",
    dst_ep: "pd.Series",
) -> None:
    unique_src = src_ep.nunique()
    unique_dst = dst_ep.nunique()
    all_unique = len(set(src_ep) | set(dst_ep))

    # src_dst_endpoint_asymmetry
    asym = abs(unique_src - unique_dst) / max(1, all_unique)
    metrics.append(_make_metric(
        "源目的不对称", "src_dst_endpoint_asymmetry", "源/目的端点不对称度",
        asym, asym * 100,
        "高分=源/目的角色明显不对称，常见于攻击/扫描/批量请求。"
    ))

    # src_endpoint_concentration
    src_counts = src_ep.value_counts().to_numpy(dtype=np.float64)
    t1_src = _top1_share(src_counts)
    metrics.append(_make_metric(
        "源目的不对称", "src_endpoint_concentration", "源端点集中度",
        t1_src, t1_src * 100,
        "高分=流量高度来自少数源endpoint。"
    ))

    # dst_endpoint_concentration
    dst_counts = dst_ep.value_counts().to_numpy(dtype=np.float64)
    t1_dst = _top1_share(dst_counts)
    metrics.append(_make_metric(
        "源目的不对称", "dst_endpoint_concentration", "目的端点集中度",
        t1_dst, t1_dst * 100,
        "高分=流量高度流向少数目的endpoint。"
    ))


def _flow_record_packet_reciprocity(flows: "pd.DataFrame") -> float:
    """Bidirectional balance using CIC per-flow Total Fwd / Total Bwd packet counts."""
    fwd_col = None
    bwd_col = None
    for cand in ("Total Fwd Packet", "Total Fwd Packets", "Fwd Packet"):
        if cand in flows.columns:
            fwd_col = cand
            break
    for cand in ("Total Bwd packets", "Total Bwd Packets", "Bwd Packet"):
        if cand in flows.columns:
            bwd_col = cand
            break
    if fwd_col is None or bwd_col is None:
        return 0.0

    fwd = pd.to_numeric(flows[fwd_col], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)
    bwd = pd.to_numeric(flows[bwd_col], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)
    denom = fwd + bwd
    mask = denom > 0
    if not np.any(mask):
        return 0.0
    return float(np.minimum(fwd[mask], bwd[mask]).sum() / denom[mask].sum())


# ─────────────────────────────────────────────────────────────
#  4.5 图形态
# ─────────────────────────────────────────────────────────────


def _graph_shape_metrics(
    metrics: list,
    flows: "pd.DataFrame",
    src_ep: "pd.Series",
    dst_ep: "pd.Series",
    ep_edge: "pd.Series",
    n: int,
) -> None:

    edge_df = pd.DataFrame({"src": src_ep, "dst": dst_ep}).drop_duplicates()
    if edge_df.empty:
        # empty graph → zero metrics
        metrics.append(_make_metric("图形态", "leaf_ratio", "叶子节点比例", 0.0, 0.0, "无节点。"))
        metrics.append(_make_metric("图形态", "edge_per_node", "边节点比", 0.0, 0.0, "无边。"))
        metrics.append(_make_metric("图形态", "low_reciprocity", "低互惠性", 0.0, 0.0, "无数据。"))
        return

    nodes = set(edge_df["src"]) | set(edge_df["dst"])
    node_count = len(nodes)
    unique_edges = len(edge_df)

    # leaf_ratio — build undirected degree
    undirected: Dict[str, set] = {}
    for _, r in edge_df.iterrows():
        s, d = str(r["src"]), str(r["dst"])
        undirected.setdefault(s, set()).add(d)
        undirected.setdefault(d, set()).add(s)
    leaf_count = sum(1 for v in undirected.values() if len(v) <= 1)
    leaf_r = leaf_count / max(1, node_count)
    metrics.append(_make_metric(
        "图形态", "leaf_ratio", "叶子节点比例",
        leaf_r, leaf_r * 100,
        "高分=大量叶子节点，拓扑呈星型或放射状，常见于扫描或DDoS。"
    ))

    # edge_per_node — log-scaled (avoids arbitrary /5 cap)
    epn = unique_edges / max(1, node_count)
    score_epn = min(100.0, math.log1p(epn) / math.log1p(10.0) * 100.0)
    metrics.append(_make_metric(
        "图形态", "edge_per_node", "边节点比",
        epn, score_epn,
        "高分=拓扑连接密度较高（约≥10条边/节点接近满分）；需结合熵/集中度/hub指标解释。"
    ))

    # low_reciprocity — CIC flow records are unidirectional rows; reverse Src→Dst
    # rows are rare even for benign TCP. Use per-flow Fwd/Bwd packet balance instead.
    weighted_recip = _flow_record_packet_reciprocity(flows)
    low_recip = max(0.0, min(1.0, 1.0 - weighted_recip))
    metrics.append(_make_metric(
        "图形态", "low_reciprocity", "低互惠性",
        low_recip, low_recip * 100,
        "高分=流记录内反向包极少（单向）；低分=Fwd/Bwd 包较均衡，更接近正常双向会话。"
    ))


# ─────────────────────────────────────────────────────────────
#  4.6 时间行为
# ─────────────────────────────────────────────────────────────


def _time_bin_counts(
    ts: "pd.Series",
    origin: "pd.Timestamp",
    span_sec: float,
    n_bins: int = 100,
) -> np.ndarray:
    """Histogram flow timestamps into fixed bins over [origin, origin + span_sec]."""
    bin_counts = np.zeros(n_bins, dtype=np.float64)
    denom = max(1e-9, float(span_sec))
    for t in ts:
        offset = (t - origin).total_seconds()
        ratio = min(1.0, max(0.0, offset / denom))
        # Map [0,1] → bin 0..n_bins-1; ratio==1 lands in last bin.
        if ratio >= 1.0:
            idx = n_bins - 1
        else:
            idx = min(n_bins - 1, max(0, int(ratio * n_bins)))
        bin_counts[idx] += 1
    return bin_counts


def _temporal_metrics(
    metrics: list,
    flows: "pd.DataFrame",
    n: int,
    global_time_span: float,
    global_time_origin: Optional["pd.Timestamp"] = None,
) -> None:
    ts = pd.to_datetime(flows["Timestamp"], errors="coerce").dropna()
    if len(ts) < 2 or global_time_span <= 0:
        return

    global_origin = global_time_origin if global_time_origin is not None else ts.min()
    t_min = ts.min()
    t_max = ts.max()
    learner_span = (t_max - t_min).total_seconds()

    n_bins = 100
    # Burst: local time concentration + global span ratio (short campaigns score high).
    bin_counts_local = _time_bin_counts(ts, t_min, max(learner_span, 1e-9), n_bins)
    hhi_local = _hhi(bin_counts_local)
    span_ratio = learner_span / max(1e-9, global_time_span)
    burst_raw = 0.5 * hhi_local + 0.5 * (1.0 - min(span_ratio, 1.0))
    metrics.append(_make_metric(
        "时间行为", "temporal_burst", "时间突发",
        burst_raw, burst_raw * 100,
        "高分=短时间集中爆发。"
    ))

    # temporal_entropy: normalize by occupied bins only (same principle as port entropy).
    # Using K=100 slots would cap scores when e.g. 10–20 active bins span the window.
    occupied = bin_counts_local[bin_counts_local > 0]
    h_time = _norm_entropy(occupied)
    metrics.append(_make_metric(
        "时间行为", "temporal_entropy", "时间熵",
        h_time, h_time * 100,
        "高分=在活跃时段内时间分布更均匀（按有流的时间 bin 归一化）；低分=集中在极少数时段。"
    ))

    # temporal_regular
    reg_t = 1.0 - h_time
    metrics.append(_make_metric(
        "时间行为", "temporal_regular", "时间规则度",
        reg_t, reg_t * 100,
        "高分=时间分布集中或规则，常见于程序化流量。"
    ))


# ─────────────────────────────────────────────────────────────
#  Qualitative hints
# ─────────────────────────────────────────────────────────────


def compute_qualitative_hints(metrics: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Derive qualitative hints from metric scores (not a composite score)."""
    hints: List[Dict[str, str]] = []
    scores: Dict[str, float] = {m["metric_key"]: m["score_0_100"] for m in metrics}

    def s(k: str) -> float:
        return scores.get(k, 0.0)

    # Flood-like
    if (s("top1_endpoint_edge_share") >= 80 or s("dst_endpoint_concentration") >= 80 or s("hub_in_strength") >= 80) and s("temporal_burst") >= 50:
        hints.append({
            "hint_key": "Flood-like",
            "hint_text": "少数目的/少数边或单一入向hub承载大量流量，并伴随时间突发。"
        })

    # Scan-like
    if s("dst_port_entropy") >= 80 and s("hub_out_strength") >= 50 and s("max_out_degree_ratio") >= 50 and s("low_reciprocity") >= 70:
        hints.append({
            "hint_key": "Scan-like",
            "hint_text": "目的端口或目的endpoint高度分散，但源端和方向性高度规则，偏扫描或探测。"
        })

    # Single-service-like
    if s("dst_port_top1_concentration") >= 80 and s("endpoint_edge_regular") >= 60:
        hints.append({
            "hint_key": "Single-service-like",
            "hint_text": "流量集中到少数服务端口和少数边，偏固定服务打击或固定服务访问。"
        })

    # Benign-like
    if s("endpoint_edge_entropy") >= 60 and s("top1_endpoint_edge_share") <= 30 and s("low_reciprocity") <= 60 and s("temporal_burst") <= 50:
        hints.append({
            "hint_key": "Benign-like",
            "hint_text": "边分布较分散，单边支配不明显，单向性和时间突发不强。"
        })

    return hints
