"""Learner topology metric audit — computes 17 independent metrics per learner.

Each metric returns a dict with:
  group, metric_key, metric_name, raw_value, score_0_100, semantic_level, semantic_text

No composite scores. Each metric is independent.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from trident_demo.qualification.metric_catalog import METRIC_CATALOG, TRAIT_AXIS_LABELS

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


def _richness_score(unique_count: int, sample_count: int, max_categories: int) -> float:
    """Log-scaled category richness relative to what this learner could expose."""
    observable = max(1, min(int(sample_count), int(max_categories)))
    return min(100.0, math.log1p(max(0, unique_count)) / math.log1p(observable) * 100.0)


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

    # ── 4.1 端口 ──
    _port_metrics(metrics, dst_port, src_port, n)
    # ── 4.2 边 ──
    _edge_metrics(metrics, ep_edge, n)
    # ── host 级拓扑：忽略源临时端口 ──
    _host_metrics(metrics, src_ip, dst_ip)
    # ── 4.3 端点与方向 ──
    _endpoint_direction_metrics(metrics, src_ep, dst_ep)
    # ── 4.5 图形态 ──
    _graph_shape_metrics(metrics, flows, src_ep, dst_ep, ep_edge, n)
    # ── 4.6 时间行为 (optional) ──
    if "Timestamp" in flows.columns and global_time_span is not None and global_time_span > 0:
        _temporal_metrics(metrics, flows, n, global_time_span, global_time_origin)

    return metrics


# ─────────────────────────────────────────────────────────────
#  4.1 端口
# ─────────────────────────────────────────────────────────────


def _port_metrics(
    metrics: list,
    dst_port: "pd.Series",
    src_port: "pd.Series",
    n: int,
) -> None:
    dst_counts = dst_port.value_counts().to_numpy(dtype=np.float64)
    src_counts = src_port.value_counts().to_numpy(dtype=np.float64)

    h_dst = _norm_entropy(dst_counts)
    metrics.append(_make_metric("端口", "dst_port_entropy", "目的端口熵", h_dst, h_dst * 100))

    dst_unique = int(dst_port.nunique())
    metrics.append(_make_metric(
        "端口",
        "dst_port_richness",
        "目的端口丰富度",
        float(dst_unique),
        _richness_score(dst_unique, n, 65536),
    ))

    h_src = _norm_entropy(src_counts)
    metrics.append(_make_metric("端口", "src_port_entropy", "源端口熵", h_src, h_src * 100))

    t1 = _top1_share(dst_counts)
    metrics.append(_make_metric(
        "端口", "dst_port_top1_concentration", "目的端口 Top1 集中度", t1, t1 * 100
    ))


# ─────────────────────────────────────────────────────────────
#  4.2 边
# ─────────────────────────────────────────────────────────────


def _edge_metrics(
    metrics: list,
    ep_edge: "pd.Series",
    n: int,
) -> None:
    edge_counts = ep_edge.value_counts().to_numpy(dtype=np.float64)
    unique_edges = len(edge_counts)

    h_edge = _norm_entropy(edge_counts)
    metrics.append(_make_metric("边", "endpoint_edge_entropy", "IP:Port 边熵", h_edge, h_edge * 100))

    t1 = _top1_share(edge_counts)
    metrics.append(_make_metric("边", "top1_endpoint_edge_share", "Top1 边占比", t1, t1 * 100))

    reuse = n / max(1, unique_edges)
    score_reuse = min(100.0, math.log1p(reuse) / math.log1p(100) * 100)
    metrics.append(_make_metric("边", "edge_reuse_ratio", "边复用率", reuse, score_reuse))


def _directed_degree_ratios(src: "pd.Series", dst: "pd.Series") -> tuple[float, float]:
    pairs = set(zip(src, dst))
    out_peers: Dict[str, set] = {}
    in_peers: Dict[str, set] = {}
    for s, d in pairs:
        out_peers.setdefault(str(s), set()).add(str(d))
        in_peers.setdefault(str(d), set()).add(str(s))
    node_count = max(1, len(set(src) | set(dst)))
    denom = max(1, node_count - 1)
    max_in = max((len(v) for v in in_peers.values()), default=0)
    max_out = max((len(v) for v in out_peers.values()), default=0)
    return max_in / denom, max_out / denom


def _host_metrics(metrics: list, src_ip: "pd.Series", dst_ip: "pd.Series") -> None:
    host_edge = src_ip + " -> " + dst_ip
    host_edge_counts = host_edge.value_counts().to_numpy(dtype=np.float64)
    h_host = _norm_entropy(host_edge_counts)
    metrics.append(_make_metric("主机层", "host_edge_entropy", "主机边熵", h_host, h_host * 100))

    dst_host_counts = dst_ip.value_counts().to_numpy(dtype=np.float64)
    dst_host_top1 = _top1_share(dst_host_counts)
    metrics.append(_make_metric(
        "主机层",
        "dst_host_concentration",
        "目的主机集中度",
        dst_host_top1,
        dst_host_top1 * 100,
    ))

    max_in, max_out = _directed_degree_ratios(src_ip, dst_ip)
    metrics.append(_make_metric(
        "主机层",
        "host_max_in_degree_ratio",
        "主机最大入度比例",
        max_in,
        max_in * 100,
    ))
    metrics.append(_make_metric(
        "主机层",
        "host_max_out_degree_ratio",
        "主机最大出度比例",
        max_out,
        max_out * 100,
    ))


# ─────────────────────────────────────────────────────────────
#  4.3 端点与方向
# ─────────────────────────────────────────────────────────────


def _endpoint_direction_metrics(
    metrics: list,
    src_ep: "pd.Series",
    dst_ep: "pd.Series",
) -> None:
    unique_src = src_ep.nunique()
    unique_dst = dst_ep.nunique()
    all_unique = len(set(src_ep) | set(dst_ep))

    asym = abs(unique_src - unique_dst) / max(1, all_unique)
    metrics.append(_make_metric(
        "端点与方向", "src_dst_endpoint_asymmetry", "源/目的规模不对称", asym, asym * 100
    ))

    src_counts = src_ep.value_counts().to_numpy(dtype=np.float64)
    metrics.append(_make_metric(
        "端点与方向",
        "src_endpoint_concentration",
        "源端点集中度",
        _top1_share(src_counts),
        _top1_share(src_counts) * 100,
    ))

    dst_counts = dst_ep.value_counts().to_numpy(dtype=np.float64)
    metrics.append(_make_metric(
        "端点与方向",
        "dst_endpoint_concentration",
        "目的端点集中度",
        _top1_share(dst_counts),
        _top1_share(dst_counts) * 100,
    ))

    max_in_deg, max_out_deg = _directed_degree_ratios(src_ep, dst_ep)
    metrics.append(_make_metric(
        "端点与方向",
        "max_in_degree_ratio",
        "最大入度比例",
        max_in_deg,
        max_in_deg * 100,
    ))

    metrics.append(_make_metric(
        "端点与方向",
        "max_out_degree_ratio",
        "最大出度比例",
        max_out_deg,
        max_out_deg * 100,
    ))


def _flow_record_packet_reciprocity(flows: "pd.DataFrame") -> Optional[float]:
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
        return None

    fwd = pd.to_numeric(flows[fwd_col], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)
    bwd = pd.to_numeric(flows[bwd_col], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)
    denom = fwd + bwd
    mask = denom > 0
    if not np.any(mask):
        return None
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
    if weighted_recip is None:
        return
    low_recip = max(0.0, min(1.0, 1.0 - weighted_recip))
    metrics.append(_make_metric(
        "图形态", "low_reciprocity", "低互惠性",
        low_recip, low_recip * 100,
        "高分=流记录内反向包极少（单向）；低分=Fwd/Bwd 包较均衡，更接近正常双向会话。"
    ))


# ─────────────────────────────────────────────────────────────
#  4.6 时间行为
# ─────────────────────────────────────────────────────────────

LOCAL_TEMPORAL_BINS = 100
GLOBAL_BIN_TARGET_WIDTH_SEC = 3600.0  # ~1h per global bin
GLOBAL_BIN_MIN = 128
GLOBAL_BIN_MAX = 2048


def _resolve_global_temporal_bins(global_span_sec: float) -> int:
    """Adaptive global bin count (~1h width) so short campaigns stay in few bins."""
    return int(
        min(
            GLOBAL_BIN_MAX,
            max(GLOBAL_BIN_MIN, global_span_sec / GLOBAL_BIN_TARGET_WIDTH_SEC),
        )
    )


def _timestamp_bin_index(
    t: "pd.Timestamp",
    origin: "pd.Timestamp",
    span_sec: float,
    n_bins: int,
) -> int:
    offset = (t - origin).total_seconds()
    ratio = min(1.0, max(0.0, offset / max(1e-9, float(span_sec))))
    if ratio >= 1.0:
        return n_bins - 1
    return min(n_bins - 1, max(0, int(ratio * n_bins)))


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

    # Burst: local time concentration + global span ratio (short campaigns score high).
    bin_counts_local = _time_bin_counts(ts, t_min, max(learner_span, 1e-9), LOCAL_TEMPORAL_BINS)
    hhi_local = _hhi(bin_counts_local)
    span_ratio = learner_span / max(1e-9, global_time_span)
    burst_raw = 0.5 * hhi_local + 0.5 * (1.0 - min(span_ratio, 1.0))
    metrics.append(_make_metric(
        "时间行为", "temporal_burst", "时间突发",
        burst_raw, burst_raw * 100,
        "高分=短时间集中爆发。"
    ))

    # Global spread: run-wide timeline, but normalize only within this learner's
    # global footprint [t_min, t_max] (not K=full run bins — that crushed benign scores).
    n_global_bins = _resolve_global_temporal_bins(global_time_span)
    bin_counts_global = _time_bin_counts(ts, global_origin, global_time_span, n_global_bins)
    i_min = _timestamp_bin_index(t_min, global_origin, global_time_span, n_global_bins)
    i_max = _timestamp_bin_index(t_max, global_origin, global_time_span, n_global_bins)
    window_counts = bin_counts_global[i_min : i_max + 1]
    occupied_global = window_counts[window_counts > 0]
    if len(occupied_global) <= 1:
        h_global = 0.0
    else:
        # K = occupied global bins in footprint (empty slots in footprint do not inflate score).
        h_global = _norm_entropy(occupied_global)
    metrics.append(_make_metric(
        "时间行为", "temporal_global_spread", "全局时间分散度", h_global, h_global * 100
    ))

    # Intra-window uniformity: learner-local bins, K = occupied bins only.
    occupied = bin_counts_local[bin_counts_local > 0]
    h_intra = _norm_entropy(occupied)
    metrics.append(_make_metric(
        "时间行为", "temporal_intra_uniformity", "活跃窗内均匀度", h_intra, h_intra * 100
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
    if (
        s("top1_endpoint_edge_share") >= 80 or s("dst_endpoint_concentration") >= 80
    ) and s("temporal_burst") >= 50:
        hints.append({
            "hint_key": "Flood-like",
            "hint_text": "少数目的/少数边承载大量流量，并伴随时间突发。"
        })

    # Scan-like
    if (
        s("dst_port_entropy") >= 80
        and s("max_out_degree_ratio") >= 50
        and s("low_reciprocity") >= 70
        and s("edge_reuse_ratio") <= 55
    ):
        hints.append({
            "hint_key": "Scan-like",
            "hint_text": "目的端口分散、出向星型明显，且流内单向性强，偏扫描或探测。"
        })

    # Single-service-like
    if s("dst_port_top1_concentration") >= 80 and (
        s("top1_endpoint_edge_share") >= 60 or s("endpoint_edge_entropy") <= 35
    ):
        hints.append({
            "hint_key": "Single-service-like",
            "hint_text": "流量集中到少数服务端口和少数边，偏固定服务打击或固定服务访问。"
        })

    # Benign-like
    if (
        s("endpoint_edge_entropy") >= 60
        and s("top1_endpoint_edge_share") <= 30
        and s("low_reciprocity") <= 60
        and s("temporal_burst") <= 50
        and s("temporal_global_spread") >= 35
    ):
        hints.append({
            "hint_key": "Benign-like",
            "hint_text": "边分布较分散，单边支配不明显；全局时间较分散、突发不强。"
        })

    return hints
