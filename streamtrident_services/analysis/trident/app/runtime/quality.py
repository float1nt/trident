from __future__ import annotations

import json
import math
from ipaddress import ip_address
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

import numpy as np

from ..flow_loader import FlowRecord

RULE_SET_ID = "learner_attack_rules"
RULE_SET_VERSION = "2026-06-02.v3"
BASELINE_LEARNER_NAME = "0000|UNLABELED"
BASELINE_BENIGN_RULE_ID = "learner_baseline_benign_fixed"
BASELINE_BENIGN_CONFIDENCE = 0.35
ATTACK_EXPLAIN: dict[str, str] = {
    "ENCRYPTED_INTERNAL_SCAN": "单台主机在短时间内向大量内部主机或端口发起高并发连接，形成明显扫描拓扑。",
    "ENCRYPTED_PROTOCOL_BRUTE_FORCE": "攻击源持续密集访问固定加密服务端口，连接路径高度复用，符合加密协议暴力破解行为。",
    "P2P_BOTNET_COMMUNICATION": "单台内部主机连接大量分散外部 IP，连接离散且边复用低，符合 P2P 僵尸网络组网通信行为。",
    "ENCRYPTED_AUTOMATED_VULNERABILITY_SWEEP": "外部主机短时间访问大量内部 HTTPS 站点，目标端口集中，形成自动化漏洞刷网拓扑。",
    "ENCRYPTED_MULTI_HOP_PROXY": "同一节点同时维持多条入向和出向加密链路，呈现中转代理拓扑。",
    "BENIGN_NORMAL": "未命中攻击规则，行为更接近正常业务流量。",
    "UNKNOWN_SUSPECTED": "存在异常迹象，但尚未匹配到已命名攻击类型。",
}
ATTACK_CATEGORY: dict[str, str] = {
    "ENCRYPTED_INTERNAL_SCAN": "恶意攻击类",
    "ENCRYPTED_PROTOCOL_BRUTE_FORCE": "恶意攻击类",
    "P2P_BOTNET_COMMUNICATION": "恶意攻击类",
    "ENCRYPTED_AUTOMATED_VULNERABILITY_SWEEP": "恶意攻击类",
    "ENCRYPTED_MULTI_HOP_PROXY": "恶意攻击类",
    "UNKNOWN_SUSPECTED": "恶意攻击类",
}
BASELINE_BENIGN_EXPLAIN = "冷启动结束后的 baseline 学习器，规则层固定标记为正常业务流量。"
SESSION_BASELINE_PROFILE_KEY = "session_baseline_learner"
COLD_START_ABSORBED_SHARE_THRESHOLD = 0.10


def is_baseline_learner(
    learner_name: str,
    *,
    session_baseline_learner: str | None = None,
) -> bool:
    name = str(learner_name).strip()
    baseline = str(session_baseline_learner or "").strip()
    if baseline:
        return name == baseline
    return name == BASELINE_LEARNER_NAME


def _profile_json(row: dict[str, Any]) -> dict[str, Any]:
    profile = row.get("profile_json")
    if isinstance(profile, dict):
        return profile
    if isinstance(profile, str) and profile.strip():
        try:
            parsed = json.loads(profile)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


def _learner_flow_count(row: dict[str, Any], flow_counts: dict[str, int] | None) -> int:
    name = str(row.get("learner_name") or "").strip()
    if flow_counts and name in flow_counts:
        return int(flow_counts[name])
    return int(row.get("flow_count") or 0)


def resolve_session_baseline_learner(
    learners: list[dict[str, Any]],
    *,
    flow_counts: dict[str, int] | None = None,
) -> str | None:
    rows = [row for row in learners if str(row.get("learner_name") or "").strip()]
    if not rows:
        return None

    for row in rows:
        stored = str(_profile_json(row).get(SESSION_BASELINE_PROFILE_KEY) or "").strip()
        if stored:
            return stored

    sorted_by_creation = sorted(
        rows,
        key=lambda row: (int(row.get("creation_window_index") or 0), str(row.get("learner_name") or "")),
    )
    first_name = str(sorted_by_creation[0].get("learner_name") or "")
    total_flows = sum(_learner_flow_count(row, flow_counts) for row in sorted_by_creation)
    first_flows = _learner_flow_count(sorted_by_creation[0], flow_counts)
    if (
        first_name == BASELINE_LEARNER_NAME
        and len(sorted_by_creation) > 1
        and total_flows > 0
        and first_flows / total_flows < COLD_START_ABSORBED_SHARE_THRESHOLD
    ):
        successors = [row for row in sorted_by_creation if str(row.get("learner_name") or "") != BASELINE_LEARNER_NAME]
        if successors:
            return str(
                max(
                    successors,
                    key=lambda row: _learner_flow_count(row, flow_counts),
                ).get("learner_name")
                or ""
            ).strip() or None

    if first_name:
        return first_name
    names = [str(row.get("learner_name") or "").strip() for row in rows]
    if BASELINE_LEARNER_NAME in names:
        return BASELINE_LEARNER_NAME
    return names[0]


def feature_drift_score(history: np.ndarray, samples: np.ndarray) -> float:
    if len(history) == 0 or len(samples) == 0:
        return float("nan")
    h_mean = np.mean(history, axis=0)
    s_mean = np.mean(samples, axis=0)
    h_std = np.std(history, axis=0) + 1e-9
    z = np.abs(s_mean - h_mean) / h_std
    return float(np.mean(np.clip(z, 0.0, 10.0)) / 10.0)


def build_learner_audit(
    *,
    learner_name: str,
    records: list[FlowRecord],
    flow_count: int,
    unknown_buffer_size: int,
    threshold: float,
    session_baseline_learner: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], float, str, str]:
    metrics = _build_v4_metrics(records, flow_count=flow_count, unknown_buffer_size=unknown_buffer_size, threshold=threshold)
    topology_json = _build_topology_json(learner_name, records)
    host_evidence_json = _build_host_evidence_json(learner_name, records)
    attack_types, rule_hits = _match_attack_rules(metrics, host_evidence_json)
    risk_score = float(max((item["confidence"] for item in attack_types), default=0.0))
    risk_band = risk_band_for_score(risk_score)
    dominant = attack_types[0]["attack_type"] if attack_types else "NONE"
    risk_reason = (
        f"dominant_attack={dominant},risk_score={risk_score:.3f},"
        f"dst_port_entropy={_m(metrics, 'dst_port_entropy'):.1f},"
        f"dst_port_top1_concentration={_m(metrics, 'dst_port_top1_concentration'):.1f},"
        f"unknown_buffer={unknown_buffer_size}"
    )
    rule_json = {
        "version": 1,
        "rule_set": {"id": RULE_SET_ID, "version": RULE_SET_VERSION},
        "target": {"learner_name": learner_name},
        "attack_types": attack_types,
        "evidence": {
            "learner_metric_json": metrics,
            "host_evidence_json": host_evidence_json,
            "flow_evidence_json": None,
        },
        "rules": rule_hits,
    }
    return metrics, topology_json, rule_json, risk_score, risk_band, risk_reason


def apply_cold_start_benign_audit(
    *,
    learner_name: str,
    records: list[FlowRecord],
    flow_count: int,
    unknown_buffer_size: int,
    threshold: float,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], float, str, str]:
    metrics = _build_v4_metrics(records, flow_count=flow_count, unknown_buffer_size=unknown_buffer_size, threshold=threshold)
    topology_json = _build_topology_json(learner_name, records)
    host_evidence_json = _build_host_evidence_json(learner_name, records)
    attack_types, rule_hits = _baseline_benign_rule(metrics)
    risk_score = BASELINE_BENIGN_CONFIDENCE
    risk_band = "low"
    risk_reason = (
        f"cold_start_learner={learner_name},fixed_benign=1,risk_score={risk_score:.3f},"
        f"flow_count={int(metrics.get('flow_count') or flow_count)},"
        f"unknown_buffer={unknown_buffer_size}"
    )
    rule_json = {
        "version": 1,
        "rule_set": {"id": RULE_SET_ID, "version": RULE_SET_VERSION},
        "target": {"learner_name": learner_name},
        "attack_types": attack_types,
        "evidence": {
            "learner_metric_json": metrics,
            "host_evidence_json": host_evidence_json,
            "flow_evidence_json": None,
        },
        "rules": rule_hits,
    }
    return metrics, topology_json, rule_json, risk_score, risk_band, risk_reason


def risk_band_for_score(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def _build_v4_metrics(
    records: list[FlowRecord],
    *,
    flow_count: int,
    unknown_buffer_size: int,
    threshold: float,
) -> dict[str, Any]:
    src_ips = [record.src_ip for record in records]
    dst_ips = [record.dst_ip for record in records]
    src_ports = [record.src_port for record in records]
    dst_ports = [record.dst_port for record in records]
    src_eps = [(record.src_ip, record.src_port) for record in records]
    dst_eps = [(record.dst_ip, record.dst_port) for record in records]
    endpoint_edges = list(zip(src_eps, dst_eps))
    host_edges = [(record.src_ip, record.dst_ip) for record in records]

    src_nodes = {src for src, _ in endpoint_edges}
    dst_nodes = {dst for _, dst in endpoint_edges}
    endpoint_nodes = src_nodes | dst_nodes
    endpoint_edge_unique = set(endpoint_edges)
    host_nodes = set(src_ips) | set(dst_ips)
    host_edge_unique = set(host_edges)
    protocols = [int(record.protocol or 0) for record in records]
    n = max(1, len(records))
    protocol_tcp_share = sum(1 for proto in protocols if proto == 6) / float(n) * 100.0
    protocol_udp_share = sum(1 for proto in protocols if proto == 17) / float(n) * 100.0

    temporal = _temporal_scores(records)
    reciprocal_flow_count = _reciprocal_flow_count(endpoint_edges)
    packet_low_reciprocity = _flow_packet_low_reciprocity(records)
    edge_per_node_raw = len(endpoint_edge_unique) / max(1, len(endpoint_nodes))
    edge_reuse_raw = n / max(1, len(endpoint_edge_unique))

    metrics = {
        "metric_version": 4,
        "flow_count": int(flow_count),
        "recent_record_count": len(records),
        "unknown_buffer_size": int(unknown_buffer_size),
        "threshold": float(threshold),
        "dst_port_entropy": _entropy_norm(dst_ports),
        "dst_port_richness": _richness(dst_ports, n=n, cap=65536),
        "src_port_entropy": _entropy_norm(src_ports),
        "dst_port_top1_concentration": _top1_share(dst_ports),
        "endpoint_edge_entropy": _entropy_norm(endpoint_edges),
        "top1_endpoint_edge_share": _top1_share(endpoint_edges),
        "edge_reuse_ratio": _clamp100(_safe_log_ratio(edge_reuse_raw, base=101.0)),
        "host_edge_entropy": _entropy_norm(host_edges),
        "dst_host_concentration": _top1_share(dst_ips),
        "host_max_in_degree_ratio": _max_in_degree_ratio(host_edge_unique, host_nodes),
        "host_max_out_degree_ratio": _max_out_degree_ratio(host_edge_unique, host_nodes),
        "max_in_degree_ratio": _max_in_degree_ratio(endpoint_edge_unique, endpoint_nodes),
        "max_out_degree_ratio": _max_out_degree_ratio(endpoint_edge_unique, endpoint_nodes),
        "src_dst_endpoint_asymmetry": _src_dst_asymmetry(src_nodes, dst_nodes),
        "src_endpoint_concentration": _top1_share(src_eps),
        "dst_endpoint_concentration": _top1_share(dst_eps),
        "leaf_ratio": _leaf_ratio(endpoint_edge_unique, endpoint_nodes),
        "edge_per_node": _clamp100(_safe_log_ratio(edge_per_node_raw, base=11.0)),
        "low_reciprocity": (
            packet_low_reciprocity
            if packet_low_reciprocity is not None
            else _clamp100((1.0 - reciprocal_flow_count / float(n)) * 100.0)
        ),
        "temporal_burst": temporal["temporal_burst"],
        "temporal_global_spread": temporal["temporal_global_spread"],
        "temporal_intra_uniformity": temporal["temporal_intra_uniformity"],
        "sample_insufficient": len(records) < 5,
        "unique_src_ip_count": len(set(src_ips)),
        "unique_dst_ip_count": len(set(dst_ips)),
        "unique_dst_port_count": len(set(dst_ports)),
        "top1_dst_port_share": _top1_share(dst_ports) / 100.0,
        "top1_src_ip_share": _top1_share(src_ips) / 100.0,
        "top1_dst_ip_share": _top1_share(dst_ips) / 100.0,
        "protocol_tcp_share": round(protocol_tcp_share, 6),
        "protocol_udp_share": round(protocol_udp_share, 6),
        "src_private_ip_share": _private_ip_share(src_ips),
        "dst_private_ip_share": _private_ip_share(dst_ips),
        "dst_public_ip_share": _clamp100(100.0 - _private_ip_share(dst_ips)),
        "dst_443_share": _top_value_share(dst_ports, 443),
    }
    return metrics


def _build_topology_json(learner_name: str, records: list[FlowRecord]) -> dict[str, Any]:
    src_ips = [record.src_ip for record in records]
    dst_ips = [record.dst_ip for record in records]
    dst_ports = [record.dst_port for record in records]
    protocols = [record.protocol for record in records]
    return {
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


def _build_host_evidence_json(learner_name: str, records: list[FlowRecord]) -> dict[str, Any]:
    by_src: dict[str, list[FlowRecord]] = defaultdict(list)
    by_dst: dict[str, list[FlowRecord]] = defaultdict(list)
    for record in records:
        by_src[record.src_ip].append(record)
        by_dst[record.dst_ip].append(record)

    top_source_hosts = []
    for host, host_records in sorted(by_src.items(), key=lambda item: len(item[1]), reverse=True)[:5]:
        metrics = _host_subset_metrics(host_records)
        evidence = _host_evidence_types(metrics, source_mode=True)
        top_source_hosts.append({"host_ip": host, "flow_count": len(host_records), "metrics": metrics, "evidence_types": evidence})

    top_destination_hosts = []
    for host, host_records in sorted(by_dst.items(), key=lambda item: len(item[1]), reverse=True)[:5]:
        metrics = _host_subset_metrics(host_records)
        evidence = _host_evidence_types(metrics, source_mode=False)
        top_destination_hosts.append({"host_ip": host, "flow_count": len(host_records), "metrics": metrics, "evidence_types": evidence})

    src_evs = [e for item in top_source_hosts for e in item["evidence_types"]]
    dst_evs = [e for item in top_destination_hosts for e in item["evidence_types"]]
    return {
        "metric_version": 4,
        "learner_name": learner_name,
        "top_source_hosts": top_source_hosts,
        "top_destination_hosts": top_destination_hosts,
        "summary": {
            "max_host_out_degree_score": _max_metric(top_source_hosts, "host_max_out_degree_ratio"),
            "max_host_in_degree_score": _max_metric(top_destination_hosts, "host_max_in_degree_ratio"),
            "max_temporal_burst_score": max(
                _max_metric(top_source_hosts, "temporal_burst"),
                _max_metric(top_destination_hosts, "temporal_burst"),
            ),
            "internal_scan_evidence_count": sum(
                1 for item in top_source_hosts if "ENCRYPTED_INTERNAL_SCAN" in item["evidence_types"]
            ),
            "source_evidence_types": sorted(set(src_evs)),
            "destination_evidence_types": sorted(set(dst_evs)),
        },
    }


def _host_subset_metrics(records: list[FlowRecord]) -> dict[str, float]:
    learner_like = _build_v4_metrics(records, flow_count=len(records), unknown_buffer_size=0, threshold=0.0)
    keys = [
        "host_max_out_degree_ratio",
        "host_max_in_degree_ratio",
        "dst_port_richness",
        "host_edge_entropy",
        "dst_port_top1_concentration",
        "max_out_degree_ratio",
        "max_in_degree_ratio",
        "dst_host_concentration",
        "dst_endpoint_concentration",
        "edge_reuse_ratio",
        "endpoint_edge_entropy",
        "temporal_burst",
        "dst_port_entropy",
        "low_reciprocity",
    ]
    return {key: float(learner_like.get(key) or 0.0) for key in keys}


def _baseline_benign_rule(metrics: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    attack_types = [
        {
            "attack_type": "BENIGN_NORMAL",
            "confidence": BASELINE_BENIGN_CONFIDENCE,
            "evidence_rules": [BASELINE_BENIGN_RULE_ID],
            "explain": BASELINE_BENIGN_EXPLAIN,
        }
    ]
    rule_hits = [
        {
            "rule_id": BASELINE_BENIGN_RULE_ID,
            "rule_version": "v1",
            "target_attack_type": "BENIGN_NORMAL",
            "match": "strong",
            "source": "baseline_policy",
            "metric": "flow_count",
            "value": round(float(metrics.get("flow_count") or 0), 6),
            "weak_threshold": 0.0,
            "strong_threshold": 0.0,
            "weight": 1.0,
            "explain": BASELINE_BENIGN_EXPLAIN,
        }
    ]
    return attack_types, rule_hits


def _host_evidence_types(metrics: dict[str, float], *, source_mode: bool) -> list[str]:
    out: list[str] = []
    if source_mode:
        if (
            metrics["dst_port_entropy"] >= 80.0
            and metrics["dst_port_richness"] >= 60.0
            and metrics["dst_port_top1_concentration"] <= 25.0
            and metrics["endpoint_edge_entropy"] >= 85.0
        ):
            out.append("ENCRYPTED_INTERNAL_SCAN")
        if (
            metrics["host_max_out_degree_ratio"] >= 65.0
            and (
                (metrics["dst_port_richness"] <= 45.0 and metrics["host_edge_entropy"] >= 70.0)
                or (metrics["max_out_degree_ratio"] >= 60.0 and metrics["dst_port_top1_concentration"] >= 50.0)
            )
        ):
            out.append("ENCRYPTED_INTERNAL_SCAN")
    return sorted(set(out))


def _match_attack_rules(
    metrics: dict[str, Any],
    host_evidence_json: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    scores: dict[str, float] = {}
    rule_hits: list[dict[str, Any]] = []
    rule_refs: dict[str, list[str]] = defaultdict(list)

    def add_rule(
        *,
        rule_id: str,
        attack_type: str,
        confidence: float,
        metric: str,
        value: float,
        explain: str,
    ) -> None:
        scores[attack_type] = max(scores.get(attack_type, 0.0), confidence)
        rule_refs[attack_type].append(rule_id)
        rule_hits.append(
            {
                "rule_id": rule_id,
                "rule_version": "v1",
                "target_attack_type": attack_type,
                "attack_category": ATTACK_CATEGORY[attack_type],
                "match": "strong",
                "source": "learner_topology",
                "metric": metric,
                "value": round(float(value), 6),
                "explain": explain,
            }
        )

    tcp_share = _m(metrics, "protocol_tcp_share")
    internal_scan = (
        tcp_share >= 50.0
        and (
            (
                _m(metrics, "dst_port_entropy") >= 75.0
                and _m(metrics, "dst_port_richness") >= 55.0
                and _m(metrics, "endpoint_edge_entropy") >= 75.0
            )
            or (
                _m(metrics, "host_max_out_degree_ratio") >= 65.0
                and _m(metrics, "src_private_ip_share") >= 70.0
                and _m(metrics, "dst_private_ip_share") >= 70.0
                and _m(metrics, "unique_dst_ip_count") >= 10.0
            )
        )
    )
    if internal_scan:
        add_rule(
            rule_id="learner_encrypted_internal_scan",
            attack_type="ENCRYPTED_INTERNAL_SCAN",
            confidence=0.9,
            metric="host_max_out_degree_ratio",
            value=_m(metrics, "host_max_out_degree_ratio"),
            explain=ATTACK_EXPLAIN["ENCRYPTED_INTERNAL_SCAN"],
        )

    brute_force = (
        tcp_share >= 50.0
        and _m(metrics, "dst_port_entropy") <= 25.0
        and _m(metrics, "dst_port_top1_concentration") >= 70.0
        and _m(metrics, "edge_reuse_ratio") >= 50.0
    )
    if brute_force:
        add_rule(
            rule_id="learner_encrypted_protocol_brute_force",
            attack_type="ENCRYPTED_PROTOCOL_BRUTE_FORCE",
            confidence=0.82,
            metric="edge_reuse_ratio",
            value=_m(metrics, "edge_reuse_ratio"),
            explain=ATTACK_EXPLAIN["ENCRYPTED_PROTOCOL_BRUTE_FORCE"],
        )

    p2p_botnet = (
        _m(metrics, "host_max_out_degree_ratio") >= 65.0
        and _m(metrics, "unique_dst_ip_count") >= 20.0
        and _m(metrics, "dst_public_ip_share") >= 70.0
        and _m(metrics, "dst_host_concentration") <= 15.0
        and _m(metrics, "edge_reuse_ratio") <= 35.0
        and _m(metrics, "dst_port_richness") <= 45.0
    )
    if p2p_botnet:
        add_rule(
            rule_id="learner_p2p_botnet_communication",
            attack_type="P2P_BOTNET_COMMUNICATION",
            confidence=0.88,
            metric="host_max_out_degree_ratio",
            value=_m(metrics, "host_max_out_degree_ratio"),
            explain=ATTACK_EXPLAIN["P2P_BOTNET_COMMUNICATION"],
        )

    automated_sweep = (
        tcp_share >= 70.0
        and _m(metrics, "src_private_ip_share") <= 30.0
        and _m(metrics, "dst_private_ip_share") >= 70.0
        and _m(metrics, "host_max_out_degree_ratio") >= 65.0
        and _m(metrics, "unique_dst_ip_count") >= 10.0
        and _m(metrics, "dst_443_share") >= 70.0
    )
    if automated_sweep:
        add_rule(
            rule_id="learner_encrypted_automated_vulnerability_sweep",
            attack_type="ENCRYPTED_AUTOMATED_VULNERABILITY_SWEEP",
            confidence=0.86,
            metric="dst_443_share",
            value=_m(metrics, "dst_443_share"),
            explain=ATTACK_EXPLAIN["ENCRYPTED_AUTOMATED_VULNERABILITY_SWEEP"],
        )

    multi_hop_proxy = (
        _m(metrics, "host_max_in_degree_ratio") >= 40.0
        and _m(metrics, "host_max_out_degree_ratio") >= 40.0
        and _m(metrics, "unique_src_ip_count") >= 3.0
        and _m(metrics, "unique_dst_ip_count") >= 3.0
    )
    if multi_hop_proxy:
        add_rule(
            rule_id="learner_encrypted_multi_hop_proxy",
            attack_type="ENCRYPTED_MULTI_HOP_PROXY",
            confidence=0.78,
            metric="host_max_out_degree_ratio",
            value=_m(metrics, "host_max_out_degree_ratio"),
            explain=ATTACK_EXPLAIN["ENCRYPTED_MULTI_HOP_PROXY"],
        )

    attack_types: list[dict[str, Any]] = []
    for attack, confidence in scores.items():
        attack_types.append(
            {
                "attack_type": attack,
                "attack_category": ATTACK_CATEGORY[attack],
                "confidence": round(confidence, 6),
                "evidence_rules": sorted(set(rule_refs.get(attack, []))),
                "explain": ATTACK_EXPLAIN.get(attack, attack),
            }
        )
    attack_types.sort(key=lambda item: (-float(item["confidence"]), item["attack_type"]))

    # 良性/未知兜底：确保每个学习器都能给出可解释的定性结果
    if not attack_types:
        benign_like = (
            _m(metrics, "dst_port_top1_concentration") <= 65.0
            and _m(metrics, "low_reciprocity") <= 65.0
            and _m(metrics, "edge_reuse_ratio") <= 60.0
            and _m(metrics, "host_max_in_degree_ratio") <= 70.0
            and _m(metrics, "host_max_out_degree_ratio") <= 70.0
        )
        if benign_like:
            benign_confidence = min(
                0.35,
                max(0.18, 0.35 - _m(metrics, "temporal_burst") / 300.0),
            )
            attack_types = [
                {
                    "attack_type": "BENIGN_NORMAL",
                    "confidence": round(benign_confidence, 6),
                    "evidence_rules": ["learner_benign_fallback"],
                    "explain": ATTACK_EXPLAIN["BENIGN_NORMAL"],
                }
            ]
            rule_hits.append(
                {
                    "rule_id": "learner_benign_fallback",
                    "rule_version": "v1",
                    "target_attack_type": "BENIGN_NORMAL",
                    "match": "strong",
                    "source": "learner_metric_json",
                    "metric": "temporal_burst",
                    "value": _m(metrics, "temporal_burst"),
                    "weak_threshold": 60.0,
                    "strong_threshold": 45.0,
                    "weight": 0.5,
                    "explain": ATTACK_EXPLAIN["BENIGN_NORMAL"],
                }
            )
        else:
            attack_types = [
                {
                    "attack_type": "UNKNOWN_SUSPECTED",
                    "attack_category": ATTACK_CATEGORY["UNKNOWN_SUSPECTED"],
                    "confidence": 0.35,
                    "evidence_rules": ["learner_unknown_fallback"],
                    "explain": ATTACK_EXPLAIN["UNKNOWN_SUSPECTED"],
                }
            ]
            rule_hits.append(
                {
                    "rule_id": "learner_unknown_fallback",
                    "rule_version": "v1",
                    "target_attack_type": "UNKNOWN_SUSPECTED",
                    "attack_category": ATTACK_CATEGORY["UNKNOWN_SUSPECTED"],
                    "match": "weak",
                    "source": "learner_metric_json",
                    "metric": "dst_port_entropy",
                    "value": _m(metrics, "dst_port_entropy"),
                    "weak_threshold": 0.0,
                    "strong_threshold": 0.0,
                    "weight": 0.3,
                    "explain": ATTACK_EXPLAIN["UNKNOWN_SUSPECTED"],
                }
            )
    return attack_types, rule_hits


def _temporal_scores(records: list[FlowRecord]) -> dict[str, float]:
    ts = [_parse_event_time(record.event_time) for record in records]
    ts = [item for item in ts if item is not None]
    if len(ts) < 2:
        return {"temporal_burst": 0.0, "temporal_global_spread": 0.0, "temporal_intra_uniformity": 0.0}
    ts.sort()
    start = ts[0]
    end = ts[-1]
    span = max(1.0, end - start)
    bins = 10
    local_counts = [0] * bins
    for t in ts:
        idx = min(bins - 1, int(((t - start) / span) * bins))
        local_counts[idx] += 1
    total = float(len(ts))
    probs = [count / total for count in local_counts if count > 0]
    hhi = sum(p * p for p in probs) * 100.0
    active_span = max(0.0, end - start)
    burst = 0.5 * hhi + 0.5 * max(0.0, 1.0 - active_span / span) * 100.0

    global_counts = Counter(datetime.fromtimestamp(t).hour for t in ts)
    temporal_global = _entropy_norm(list(global_counts.elements()))
    temporal_intra = _entropy_from_counts(local_counts)
    return {
        "temporal_burst": _clamp100(burst),
        "temporal_global_spread": _clamp100(temporal_global),
        "temporal_intra_uniformity": _clamp100(temporal_intra),
    }


def _parse_event_time(text: str) -> float | None:
    try:
        dt = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.timestamp()


def _entropy_norm(values: list[Any]) -> float:
    if not values:
        return 0.0
    counts = Counter(map(str, values))
    return _entropy_from_counts(counts.values())


def _entropy_from_counts(counts: Any) -> float:
    counts = [int(c) for c in counts if int(c) > 0]
    if len(counts) <= 1:
        return 0.0
    total = float(sum(counts))
    probs = [c / total for c in counts]
    entropy = -sum(p * math.log(p) for p in probs)
    return (entropy / math.log(len(counts))) * 100.0


def _top1_share(values: list[Any]) -> float:
    if not values:
        return 0.0
    counts = Counter(map(str, values))
    return (max(counts.values()) / max(1, len(values))) * 100.0


def _richness(values: list[Any], *, n: int, cap: int) -> float:
    unique_count = len(set(map(str, values)))
    denom = math.log(1 + min(max(1, n), cap))
    if denom <= 0:
        return 0.0
    return _clamp100(math.log(1 + unique_count) / denom * 100.0)


def _max_in_degree_ratio(edges: set[tuple[Any, Any]], nodes: set[Any]) -> float:
    if len(nodes) <= 1:
        return 0.0
    indeg: Counter[Any] = Counter(dst for _, dst in edges)
    return _clamp100((max(indeg.values()) if indeg else 0) / max(1, len(nodes) - 1) * 100.0)


def _max_out_degree_ratio(edges: set[tuple[Any, Any]], nodes: set[Any]) -> float:
    if len(nodes) <= 1:
        return 0.0
    outdeg: Counter[Any] = Counter(src for src, _ in edges)
    return _clamp100((max(outdeg.values()) if outdeg else 0) / max(1, len(nodes) - 1) * 100.0)


def _src_dst_asymmetry(src_nodes: set[Any], dst_nodes: set[Any]) -> float:
    union = src_nodes | dst_nodes
    return _clamp100(abs(len(src_nodes) - len(dst_nodes)) / max(1, len(union)) * 100.0)


def _leaf_ratio(edges: set[tuple[Any, Any]], nodes: set[Any]) -> float:
    if not nodes:
        return 0.0
    degree: Counter[Any] = Counter()
    for src, dst in edges:
        degree[src] += 1
        degree[dst] += 1
    leaf_count = sum(1 for node in nodes if degree.get(node, 0) <= 1)
    return _clamp100(leaf_count / max(1, len(nodes)) * 100.0)


def _reciprocal_flow_count(endpoint_edges: list[tuple[Any, Any]]) -> int:
    counter = Counter(endpoint_edges)
    reciprocal = 0
    for (src, dst), count in counter.items():
        rev = counter.get((dst, src), 0)
        reciprocal += min(count, rev)
    return reciprocal


def _flow_packet_low_reciprocity(records: list[FlowRecord]) -> float | None:
    balanced_packets = 0.0
    total_packets = 0.0
    for record in records:
        try:
            features = json.loads(record.features_json)
        except json.JSONDecodeError:
            continue
        if not isinstance(features, dict):
            continue
        fwd = _first_non_negative_number(features, ("Total Fwd Packet", "Total Fwd Packets", "Fwd Packet"))
        bwd = _first_non_negative_number(features, ("Total Bwd packets", "Total Bwd Packets", "Bwd Packet"))
        if fwd is None or bwd is None or fwd + bwd <= 0:
            continue
        balanced_packets += min(fwd, bwd)
        total_packets += fwd + bwd
    if total_packets <= 0:
        return None
    return _clamp100((1.0 - balanced_packets / total_packets) * 100.0)


def _first_non_negative_number(features: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        try:
            value = float(features[key])
        except (KeyError, TypeError, ValueError):
            continue
        if value >= 0.0 and value == value:
            return value
    return None


def _private_ip_share(values: list[str]) -> float:
    if not values:
        return 0.0
    private = 0
    for value in values:
        try:
            private += int(ip_address(str(value)).is_private)
        except ValueError:
            continue
    return _clamp100(private / len(values) * 100.0)


def _top_value_share(values: list[Any], target: Any) -> float:
    if not values:
        return 0.0
    return _clamp100(sum(1 for value in values if value == target) / len(values) * 100.0)


def _safe_log_ratio(value: float, *, base: float) -> float:
    return math.log(1 + max(0.0, value)) / math.log(base) * 100.0


def _clamp100(value: float) -> float:
    return float(min(100.0, max(0.0, value)))


def _m(metrics: dict[str, Any], key: str) -> float:
    try:
        return float(metrics.get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _top_counts(values: list[Any], limit: int = 10) -> list[dict[str, Any]]:
    counts = Counter(str(value) for value in values)
    return [{"value": value, "count": int(count)} for value, count in counts.most_common(limit)]


def _max_metric(items: list[dict[str, Any]], metric: str) -> float:
    return max((float(item.get("metrics", {}).get(metric) or 0.0) for item in items), default=0.0)
