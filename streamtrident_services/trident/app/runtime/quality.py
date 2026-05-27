from __future__ import annotations

import math
from collections import Counter
from typing import Any

import numpy as np

from ..flow_loader import FlowRecord


def feature_drift_score(history: np.ndarray, samples: np.ndarray) -> float:
    if len(history) == 0 or len(samples) == 0:
        return float("nan")
    h_mean = np.mean(history, axis=0)
    s_mean = np.mean(samples, axis=0)
    h_std = np.std(history, axis=0) + 1e-9
    z = np.abs(s_mean - h_mean) / h_std
    return float(np.mean(np.clip(z, 0.0, 10.0)) / 10.0)


def entropy_ratio(values: list[Any]) -> float:
    if not values:
        return 0.0
    counts = Counter(str(value) for value in values)
    if len(counts) <= 1:
        return 0.0
    total = float(sum(counts.values()))
    entropy = -sum((count / total) * math.log(count / total) for count in counts.values())
    return float(entropy / math.log(len(counts)))


def top_share(values: list[Any]) -> float:
    if not values:
        return 0.0
    counts = Counter(str(value) for value in values)
    return float(max(counts.values()) / max(1, len(values)))


def build_learner_audit(
    *,
    learner_name: str,
    records: list[FlowRecord],
    flow_count: int,
    unknown_buffer_size: int,
    threshold: float,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], float, str, str]:
    src_ips = [record.src_ip for record in records]
    dst_ips = [record.dst_ip for record in records]
    src_ports = [record.src_port for record in records]
    dst_ports = [record.dst_port for record in records]
    protocols = [record.protocol for record in records]
    dst_port_top_share = top_share(dst_ports)
    src_ip_top_share = top_share(src_ips)
    dst_ip_top_share = top_share(dst_ips)
    protocol_top_share = top_share(protocols)
    dst_port_entropy = entropy_ratio(dst_ports)
    edge_entropy = entropy_ratio([f"{r.src_ip}:{r.src_port}->{r.dst_ip}:{r.dst_port}" for r in records])
    concentration = max(dst_port_top_share, src_ip_top_share, dst_ip_top_share, protocol_top_share)
    size_confidence = min(1.0, math.log1p(max(flow_count, len(records))) / math.log1p(10000))
    risk_score = float(min(1.0, max(0.0, 0.55 * concentration + 0.25 * (1.0 - dst_port_entropy) + 0.20 * (1.0 - size_confidence))))
    risk_band = risk_band_for_score(risk_score)
    risk_reason = (
        f"concentration={concentration:.3f},dst_port_entropy={dst_port_entropy:.3f},"
        f"size_confidence={size_confidence:.3f},unknown_buffer={unknown_buffer_size}"
    )
    metric_json = {
        "flow_count": int(flow_count),
        "recent_record_count": len(records),
        "unknown_buffer_size": int(unknown_buffer_size),
        "threshold": float(threshold),
        "dst_port_entropy": dst_port_entropy,
        "src_port_entropy": entropy_ratio(src_ports),
        "protocol_entropy": entropy_ratio(protocols),
        "endpoint_edge_entropy": edge_entropy,
        "top1_dst_port_share": dst_port_top_share,
        "top1_src_ip_share": src_ip_top_share,
        "top1_dst_ip_share": dst_ip_top_share,
        "top1_protocol_share": protocol_top_share,
        "unique_src_ip_count": len(set(src_ips)),
        "unique_dst_ip_count": len(set(dst_ips)),
        "unique_dst_port_count": len(set(dst_ports)),
    }
    topology_json = {
        "version": 1,
        "learner_name": learner_name,
        "nodes": {
            "src_ip_count": len(set(src_ips)),
            "dst_ip_count": len(set(dst_ips)),
            "dst_port_count": len(set(dst_ports)),
        },
        "top": {
            "src_ips": _top_counts(src_ips),
            "dst_ips": _top_counts(dst_ips),
            "dst_ports": _top_counts(dst_ports),
            "protocols": _top_counts(protocols),
        },
    }
    rule_json = {
        "version": 1,
        "rules": reference_rules(metric_json, risk_score),
    }
    return metric_json, topology_json, rule_json, risk_score, risk_band, risk_reason


def reference_rules(metrics: dict[str, Any], risk_score: float) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    if float(metrics.get("top1_dst_port_share", 0.0)) >= 0.75:
        rules.append({"rule": "dst_port_concentrated", "severity": "medium", "text": "Destination port distribution is highly concentrated."})
    if float(metrics.get("top1_protocol_share", 0.0)) >= 0.90:
        rules.append({"rule": "protocol_concentrated", "severity": "low", "text": "Most flows use the same protocol."})
    if float(metrics.get("endpoint_edge_entropy", 0.0)) <= 0.20 and int(metrics.get("recent_record_count", 0)) > 0:
        rules.append({"rule": "endpoint_reuse", "severity": "medium", "text": "Endpoint edges show repeated reuse."})
    if risk_score >= 0.75:
        rules.append({"rule": "high_risk_learner", "severity": "high", "text": "Combined topology and size signals indicate high learner risk."})
    return rules


def risk_band_for_score(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def _top_counts(values: list[Any], limit: int = 10) -> list[dict[str, Any]]:
    counts = Counter(str(value) for value in values)
    return [{"value": value, "count": int(count)} for value, count in counts.most_common(limit)]
