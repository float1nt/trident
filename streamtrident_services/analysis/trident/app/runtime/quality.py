from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

import numpy as np

from ..flow_loader import FlowRecord

RULE_SET_ID = "learner_attack_rules"
RULE_SET_VERSION = "2026-05-27.v1"
ATTACK_EXPLAIN: dict[str, str] = {
    "PORT_SCAN": "攻击源针对少量固定目标主机，批量试探大量不同端口，探测开放服务，为后续渗透做铺垫，整体端口分散、无固定访问服务。",
    "HOST_SCAN": "攻击源依托固定常用服务端口，批量访问内网大量不同目标主机，探测存活资产，是典型的内网横向渗透前置行为。",
    "DDOS_VICTIM": "海量分布式源IP集中冲击单一或少量目标主机的固定服务端口，通过流量洪泛消耗目标带宽与算力，可能造成服务瘫痪。",
    "DOS_ATTACKER": "攻击源高频重复连接固定目标服务，依托高复用连接路径持续施压，耗尽目标资源实现单点打击。",
    "DRDOS_REFLECTION_FAMILY": "攻击者伪造受害者地址利用第三方服务放大流量，具备端口极度分散、连接一次性、流量单向失衡的特征，对目标形成无差别洪泛冲击。",
    "SLOW_DOS_SUSPECTED": "不依靠大流量洪泛，通过低速请求、长效弱连接持续占用目标Web及固定服务资源，缓慢耗尽服务端会话与算力导致服务失效。",
    "WEB_DDOS_SUSPECTED": "海量访问源集中针对80、443等Web端口及业务接口发起复杂高频请求，依托多样业务访问路径施压，专门打击Web业务服务。",
    "BRUTE_FORCE_SUSPECTED": "攻击源反复高频访问SSH、Web等固定登录端口，持续尝试账号密码组合，流量重复度高。",
    "BENIGN_NORMAL": "未命中攻击规则，行为更接近正常业务流量。",
    "UNKNOWN_SUSPECTED": "存在异常迹象，但尚未匹配到已命名攻击类型。",
}


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
    n = max(1, len(records))

    temporal = _temporal_scores(records)
    reciprocal_flow_count = _reciprocal_flow_count(endpoint_edges)
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
        "low_reciprocity": _clamp100((1.0 - reciprocal_flow_count / float(n)) * 100.0),
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
            "host_scan_evidence_count": sum(1 for item in top_source_hosts if "HOST_SCAN" in item["evidence_types"]),
            "ddos_victim_evidence_count": sum(1 for item in top_destination_hosts if "DDOS_VICTIM" in item["evidence_types"]),
            "dos_attacker_evidence_count": sum(1 for item in top_source_hosts if "DOS_ATTACKER" in item["evidence_types"]),
            "port_scan_evidence_count": sum(1 for item in top_source_hosts if "PORT_SCAN" in item["evidence_types"]),
            "drdos_evidence_count": sum(1 for item in top_destination_hosts if "DRDOS_REFLECTION_FAMILY" in item["evidence_types"])
            + sum(1 for item in top_source_hosts if "DRDOS_REFLECTION_FAMILY" in item["evidence_types"]),
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


def _host_evidence_types(metrics: dict[str, float], *, source_mode: bool) -> list[str]:
    out: list[str] = []
    if source_mode:
        if (
            metrics["dst_port_entropy"] >= 80.0
            and metrics["dst_port_richness"] >= 60.0
            and metrics["dst_port_top1_concentration"] <= 25.0
            and metrics["endpoint_edge_entropy"] >= 85.0
        ):
            out.append("PORT_SCAN")
        if (
            metrics["host_max_out_degree_ratio"] >= 65.0
            and (
                (metrics["dst_port_richness"] <= 45.0 and metrics["host_edge_entropy"] >= 70.0)
                or (metrics["max_out_degree_ratio"] >= 60.0 and metrics["dst_port_top1_concentration"] >= 50.0)
            )
        ):
            out.append("HOST_SCAN")
        if (
            metrics["dst_host_concentration"] >= 65.0
            and metrics["dst_endpoint_concentration"] >= 60.0
            and metrics["edge_reuse_ratio"] >= 55.0
        ):
            out.append("DOS_ATTACKER")
    if (
        metrics["host_max_in_degree_ratio"] >= 65.0
        and metrics["dst_host_concentration"] >= 65.0
        and (metrics["max_in_degree_ratio"] >= 70.0 or metrics["endpoint_edge_entropy"] >= 75.0)
    ):
        out.append("DDOS_VICTIM")
    if (
        metrics["dst_port_entropy"] >= 80.0
        and metrics["dst_port_richness"] >= 85.0
        and metrics["endpoint_edge_entropy"] >= 85.0
        and metrics["edge_reuse_ratio"] <= 30.0
        and metrics["low_reciprocity"] >= 70.0
    ):
        out.append("DRDOS_REFLECTION_FAMILY")
    return sorted(set(out))


def _match_attack_rules(
    metrics: dict[str, Any],
    host_evidence_json: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    scores: dict[str, dict[str, float]] = defaultdict(lambda: {"weighted": 0.0, "total": 0.0})
    rule_hits: list[dict[str, Any]] = []
    rule_refs: dict[str, list[str]] = defaultdict(list)

    def add_metric_rule(
        *,
        rule_id: str,
        attack_type: str,
        source: str,
        match: str,
        weight: float,
        metric: str,
        value: float,
        weak_threshold: float,
        strong_threshold: float,
        explain: str,
    ) -> None:
        strength = 1.0 if match == "strong" else 0.5
        scores[attack_type]["weighted"] += weight * strength
        scores[attack_type]["total"] += weight
        rule_refs[attack_type].append(rule_id)
        rule_hits.append(
            {
                "rule_id": rule_id,
                "rule_version": "v1",
                "target_attack_type": attack_type,
                "match": match,
                "source": source,
                "metric": metric,
                "value": round(float(value), 6),
                "weak_threshold": weak_threshold,
                "strong_threshold": strong_threshold,
                "weight": weight,
                "explain": explain,
            }
        )

    # PORT_SCAN
    ps_strong = (
        _m(metrics, "dst_port_entropy") >= 90
        and _m(metrics, "dst_port_richness") >= 70
        and _m(metrics, "dst_port_top1_concentration") <= 15
        and _m(metrics, "dst_endpoint_concentration") <= 15
        and _m(metrics, "endpoint_edge_entropy") >= 90
        and _m(metrics, "low_reciprocity") <= 75
    )
    ps_weak = (
        _m(metrics, "dst_port_entropy") >= 80
        and _m(metrics, "dst_port_richness") >= 60
        and _m(metrics, "dst_port_top1_concentration") <= 25
    )
    if ps_strong or ps_weak or int(host_evidence_json.get("summary", {}).get("port_scan_evidence_count") or 0) >= 1:
        add_metric_rule(
            rule_id="learner_port_scan_core",
            attack_type="PORT_SCAN",
            source="learner_metric_json",
            match="strong" if ps_strong else "weak",
            weight=0.85,
            metric="dst_port_entropy",
            value=_m(metrics, "dst_port_entropy"),
            weak_threshold=80.0,
            strong_threshold=90.0,
            explain=ATTACK_EXPLAIN["PORT_SCAN"],
        )

    # HOST_SCAN
    hs_strong = (
        _m(metrics, "host_max_out_degree_ratio") >= 80
        and _m(metrics, "dst_port_richness") <= 45
        and _m(metrics, "host_edge_entropy") >= 70
    )
    hs_weak = _m(metrics, "host_max_out_degree_ratio") >= 65
    if hs_strong or hs_weak or int(host_evidence_json.get("summary", {}).get("host_scan_evidence_count") or 0) >= 1:
        add_metric_rule(
            rule_id="learner_host_scan_core",
            attack_type="HOST_SCAN",
            source="host_evidence_json",
            match="strong" if hs_strong else "weak",
            weight=0.9,
            metric="summary.max_host_out_degree_score",
            value=float(host_evidence_json.get("summary", {}).get("max_host_out_degree_score") or _m(metrics, "host_max_out_degree_ratio")),
            weak_threshold=65.0,
            strong_threshold=80.0,
            explain=ATTACK_EXPLAIN["HOST_SCAN"],
        )

    # DDOS_VICTIM
    fixed_core = (
        _m(metrics, "dst_port_entropy") <= 12
        and _m(metrics, "dst_port_richness") <= 30
        and _m(metrics, "dst_port_top1_concentration") >= 95
        and _m(metrics, "endpoint_edge_entropy") >= 80
        and _m(metrics, "src_port_entropy") >= 80
    )
    fixed_support = (
        _m(metrics, "dst_host_concentration") >= 65
        or _m(metrics, "max_in_degree_ratio") >= 75
        or _m(metrics, "host_max_in_degree_ratio") >= 75
    )
    dv_strong = fixed_core and fixed_support and _m(metrics, "temporal_burst") >= 60
    dv_weak = fixed_core and fixed_support
    if dv_strong or dv_weak or int(host_evidence_json.get("summary", {}).get("ddos_victim_evidence_count") or 0) >= 1:
        add_metric_rule(
            rule_id="learner_ddos_victim_core",
            attack_type="DDOS_VICTIM",
            source="learner_metric_json",
            match="strong" if dv_strong else "weak",
            weight=1.0,
            metric="host_max_in_degree_ratio",
            value=max(_m(metrics, "host_max_in_degree_ratio"), _m(metrics, "max_in_degree_ratio")),
            weak_threshold=65.0,
            strong_threshold=80.0,
            explain=ATTACK_EXPLAIN["DDOS_VICTIM"],
        )

    # DOS_ATTACKER
    da_strong = (
        _m(metrics, "dst_host_concentration") >= 80
        and _m(metrics, "dst_port_top1_concentration") >= 80
        and _m(metrics, "edge_reuse_ratio") >= 70
        and _m(metrics, "temporal_burst") >= 60
    )
    da_weak = (
        _m(metrics, "dst_host_concentration") >= 65
        and _m(metrics, "dst_endpoint_concentration") >= 60
        and _m(metrics, "edge_reuse_ratio") >= 55
    )
    if da_strong or da_weak or int(host_evidence_json.get("summary", {}).get("dos_attacker_evidence_count") or 0) >= 1:
        add_metric_rule(
            rule_id="learner_dos_attacker_core",
            attack_type="DOS_ATTACKER",
            source="host_evidence_json",
            match="strong" if da_strong else "weak",
            weight=0.95,
            metric="edge_reuse_ratio",
            value=_m(metrics, "edge_reuse_ratio"),
            weak_threshold=55.0,
            strong_threshold=70.0,
            explain=ATTACK_EXPLAIN["DOS_ATTACKER"],
        )

    # DRDOS_REFLECTION_FAMILY
    dr_strong = (
        _m(metrics, "dst_port_entropy") >= 90
        and _m(metrics, "dst_port_richness") >= 90
        and _m(metrics, "dst_port_top1_concentration") <= 10
        and _m(metrics, "endpoint_edge_entropy") >= 95
        and _m(metrics, "edge_reuse_ratio") <= 25
        and _m(metrics, "low_reciprocity") >= 85
    )
    dr_weak = (
        _m(metrics, "dst_port_entropy") >= 80
        and _m(metrics, "endpoint_edge_entropy") >= 85
        and _m(metrics, "low_reciprocity") >= 70
    )
    if dr_strong or dr_weak or int(host_evidence_json.get("summary", {}).get("drdos_evidence_count") or 0) >= 1:
        add_metric_rule(
            rule_id="learner_drdos_reflection_core",
            attack_type="DRDOS_REFLECTION_FAMILY",
            source="learner_metric_json",
            match="strong" if dr_strong else "weak",
            weight=0.9,
            metric="low_reciprocity",
            value=_m(metrics, "low_reciprocity"),
            weak_threshold=70.0,
            strong_threshold=85.0,
            explain=ATTACK_EXPLAIN["DRDOS_REFLECTION_FAMILY"],
        )

    # SLOW_DOS_SUSPECTED
    sd_strong = (
        _m(metrics, "dst_port_entropy") <= 20
        and _m(metrics, "dst_port_top1_concentration") >= 80
        and (_m(metrics, "dst_host_concentration") >= 65 or _m(metrics, "host_max_in_degree_ratio") >= 65)
        and _m(metrics, "low_reciprocity") >= 68
    )
    sd_weak = _m(metrics, "dst_port_top1_concentration") >= 70 and _m(metrics, "low_reciprocity") >= 60
    if sd_strong or sd_weak:
        add_metric_rule(
            rule_id="learner_slow_dos_suspected",
            attack_type="SLOW_DOS_SUSPECTED",
            source="learner_metric_json",
            match="strong" if sd_strong else "weak",
            weight=0.6,
            metric="low_reciprocity",
            value=_m(metrics, "low_reciprocity"),
            weak_threshold=60.0,
            strong_threshold=68.0,
            explain=ATTACK_EXPLAIN["SLOW_DOS_SUSPECTED"],
        )

    # WEB_DDOS_SUSPECTED
    wd_strong = (
        35 <= _m(metrics, "dst_port_entropy") <= 65
        and 50 <= _m(metrics, "dst_port_top1_concentration") <= 85
        and _m(metrics, "max_in_degree_ratio") >= 80
        and _m(metrics, "max_out_degree_ratio") >= 80
        and _m(metrics, "endpoint_edge_entropy") >= 85
    )
    wd_weak = (
        30 <= _m(metrics, "dst_port_entropy") <= 70
        and _m(metrics, "max_in_degree_ratio") >= 65
        and _m(metrics, "endpoint_edge_entropy") >= 75
    )
    if wd_strong or wd_weak:
        add_metric_rule(
            rule_id="learner_web_ddos_suspected",
            attack_type="WEB_DDOS_SUSPECTED",
            source="learner_metric_json",
            match="strong" if wd_strong else "weak",
            weight=0.55,
            metric="endpoint_edge_entropy",
            value=_m(metrics, "endpoint_edge_entropy"),
            weak_threshold=75.0,
            strong_threshold=85.0,
            explain=ATTACK_EXPLAIN["WEB_DDOS_SUSPECTED"],
        )

    # BRUTE_FORCE_SUSPECTED
    bf_strong = (
        _m(metrics, "dst_port_entropy") <= 25
        and _m(metrics, "dst_port_top1_concentration") >= 80
        and _m(metrics, "edge_reuse_ratio") >= 65
        and _m(metrics, "temporal_burst") >= 50
    )
    bf_weak = _m(metrics, "dst_port_top1_concentration") >= 70 and _m(metrics, "edge_reuse_ratio") >= 50
    if bf_strong or bf_weak:
        add_metric_rule(
            rule_id="learner_bruteforce_suspected",
            attack_type="BRUTE_FORCE_SUSPECTED",
            source="learner_metric_json",
            match="strong" if bf_strong else "weak",
            weight=0.55,
            metric="edge_reuse_ratio",
            value=_m(metrics, "edge_reuse_ratio"),
            weak_threshold=50.0,
            strong_threshold=65.0,
            explain=ATTACK_EXPLAIN["BRUTE_FORCE_SUSPECTED"],
        )

    attack_types: list[dict[str, Any]] = []
    for attack, agg in scores.items():
        total = agg["total"]
        if total <= 0:
            continue
        base = max(0.0, min(1.0, agg["weighted"] / total))
        host_bonus = min(0.15, _host_bonus_count(host_evidence_json, attack) * 0.03)
        confidence = min(1.0, base + host_bonus)
        attack_types.append(
            {
                "attack_type": attack,
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
            and _m(metrics, "temporal_burst") <= 60.0
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


def _host_bonus_count(host_evidence_json: dict[str, Any], attack_type: str) -> int:
    summary = host_evidence_json.get("summary", {})
    mapping = {
        "HOST_SCAN": "host_scan_evidence_count",
        "DDOS_VICTIM": "ddos_victim_evidence_count",
        "DOS_ATTACKER": "dos_attacker_evidence_count",
        "PORT_SCAN": "port_scan_evidence_count",
        "DRDOS_REFLECTION_FAMILY": "drdos_evidence_count",
    }
    key = mapping.get(attack_type)
    return int(summary.get(key) or 0) if key else 0


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
