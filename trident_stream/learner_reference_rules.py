"""Dataset-agnostic learner reference rule matching."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, TypedDict

REFERENCE_RULES_VERSION = "topology-family-v1"


class LearnerReferenceRuleMatch(TypedDict):
    key: str
    name: str
    tone: str
    semantic: str


MetricScores = Mapping[str, float]


def _score_map(metrics: List[Dict[str, Any]]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for m in metrics:
        key = str(m.get("metric_key", ""))
        score = m.get("score_0_100")
        if key and isinstance(score, (int, float)) and float(score) == float(score):
            out[key] = float(score)
    return out


def _at_least(scores: MetricScores, key: str, minimum: float) -> bool:
    value = scores.get(key)
    return value is not None and float(value) >= minimum


def _at_most(scores: MetricScores, key: str, maximum: float) -> bool:
    value = scores.get(key)
    return value is not None and float(value) <= maximum


def _between(scores: MetricScores, key: str, low: float, high: float) -> bool:
    return _at_least(scores, key, low) and _at_most(scores, key, high)


def _has_fixed_target_service_core(scores: MetricScores) -> bool:
    return (
        _at_most(scores, "dst_port_entropy", 12)
        and _at_most(scores, "dst_port_richness", 30)
        and _at_least(scores, "dst_port_top1_concentration", 95)
        and _at_least(scores, "endpoint_edge_entropy", 80)
        and _at_least(scores, "src_port_entropy", 80)
    )


def _has_fixed_target_support(scores: MetricScores) -> bool:
    return (
        _at_least(scores, "dst_host_concentration", 65)
        or _at_least(scores, "max_in_degree_ratio", 75)
        or _at_least(scores, "host_max_in_degree_ratio", 75)
    )


def _is_fixed_target_service_attack(scores: MetricScores) -> bool:
    return _has_fixed_target_service_core(scores) and _has_fixed_target_support(scores)


def _is_diffuse_one_way_attack(scores: MetricScores) -> bool:
    return (
        _at_least(scores, "dst_port_entropy", 90)
        and _at_least(scores, "dst_port_richness", 90)
        and _at_most(scores, "dst_port_top1_concentration", 10)
        and _at_least(scores, "endpoint_edge_entropy", 95)
        and _at_most(scores, "edge_reuse_ratio", 25)
        and _at_least(scores, "low_reciprocity", 85)
    )


_REFERENCE_RULES: List[Dict[str, Any]] = [
    {
        "key": "benign-natural-dispersion",
        "name": "正常流量参考匹配",
        "tone": "benign",
        "semantic": "边分布较散、无单边支配，目的端口丰富度处于常见服务混合范围，流内单向性也不极端。",
        "match": lambda s: (
            _at_least(s, "endpoint_edge_entropy", 82)
            and _at_most(s, "top1_endpoint_edge_share", 8)
            and _between(s, "edge_reuse_ratio", 35, 65)
            and _at_most(s, "dst_port_entropy", 45)
            and _at_most(s, "dst_port_richness", 75)
            and _between(s, "dst_port_top1_concentration", 20, 85)
            and _at_most(s, "low_reciprocity", 70)
            and _at_most(s, "max_out_degree_ratio", 15)
        ),
    },
    {
        "key": "fixed-service-dos-ddos-family",
        "name": "DoS/DDoS 等固定服务攻击族",
        "tone": "attack",
        "semantic": "该形态与 DoS/DDoS 及其他固定服务攻击族相近：目的服务几乎固定，大量变化源端指向少数目的 endpoint。",
        "match": _is_fixed_target_service_attack,
    },
    {
        "key": "slow-dos-fixed-service",
        "name": "Slow DoS 类攻击参考匹配",
        "tone": "attack",
        "semantic": "固定目的服务汇聚仍明显，同时流内单向性更强，提示慢速或低反馈的服务冲击行为。",
        "match": lambda s: _is_fixed_target_service_attack(s) and _at_least(s, "low_reciprocity", 68),
    },
    {
        "key": "portscan-wide-target",
        "name": "PortScan 类攻击参考匹配",
        "tone": "attack",
        "semantic": "目的端口丰富度和分布熵同时偏高，目的 endpoint 大范围展开，单一服务不占主导。",
        "match": lambda s: (
            _at_least(s, "dst_port_entropy", 90)
            and _at_least(s, "dst_port_richness", 70)
            and _at_most(s, "dst_port_top1_concentration", 15)
            and _at_most(s, "dst_endpoint_concentration", 15)
            and _at_least(s, "endpoint_edge_entropy", 90)
            and _at_most(s, "low_reciprocity", 75)
        ),
    },
    {
        "key": "heartbleed-like-small-sample",
        "name": "Heartbleed 小样本参考匹配",
        "tone": "caution",
        "semantic": "少量流集中在极少边上；这类小样本形态只适合作为人工复核提示。",
        "match": lambda s: (
            _at_most(s, "endpoint_edge_entropy", 20)
            and _at_least(s, "top1_endpoint_edge_share", 80)
            and _at_least(s, "dst_port_top1_concentration", 95)
            and _at_most(s, "src_port_entropy", 25)
        ),
    },
    {
        "key": "diffuse-one-way-drdos-udp-syn-family",
        "name": "DRDoS/UDP/SYN 单向攻击族",
        "tone": "attack",
        "semantic": "该形态与 DRDoS、UDP/SYN 冲击族相近：目的端口高度分散，边接近一次性，流记录内强单向。",
        "match": _is_diffuse_one_way_attack,
    },
    {
        "key": "drdos-dns-ldap-ntp-like",
        "name": "DRDoS DNS/LDAP/NTP 类参考匹配",
        "tone": "attack",
        "semantic": "在高分散单向形态上，源端口分散度处于中高区间，提示一类较稳定的端口展开模式。",
        "match": lambda s: _is_diffuse_one_way_attack(s) and _between(s, "src_port_entropy", 65, 85),
    },
    {
        "key": "drdos-snmp-ssdp-tftp-like",
        "name": "DRDoS SNMP/SSDP/TFTP 类参考匹配",
        "tone": "attack",
        "semantic": "在高分散单向形态上，源端口分散度更高，提示源端口展开更充分的子形态。",
        "match": lambda s: _is_diffuse_one_way_attack(s) and _between(s, "src_port_entropy", 85, 98),
    },
    {
        "key": "drdos-udp-syn-udp-lag-like",
        "name": "DRDoS UDP/SYN/UDP-LAG 类参考匹配",
        "tone": "attack",
        "semantic": "在高分散单向形态上，源端口也极分散，提示源端和目的端同时高度展开。",
        "match": lambda s: _is_diffuse_one_way_attack(s) and _at_least(s, "src_port_entropy", 98),
    },
    {
        "key": "web-ddos-bidirectional-hub-like",
        "name": "WebDDoS 类攻击参考匹配",
        "tone": "caution",
        "semantic": "目的端口没有全局扫散，但入向和出向 hub 同时明显，提示围绕服务节点的双向冲击结构。",
        "match": lambda s: (
            _between(s, "dst_port_entropy", 35, 65)
            and _between(s, "dst_port_top1_concentration", 50, 85)
            and _at_least(s, "max_in_degree_ratio", 80)
            and _at_least(s, "max_out_degree_ratio", 80)
            and _at_least(s, "endpoint_edge_entropy", 90)
        ),
    },
]


def evaluate_learner_reference_rules(
    metrics: List[Dict[str, Any]],
) -> List[LearnerReferenceRuleMatch]:
    scores = _score_map(metrics)
    matches: List[LearnerReferenceRuleMatch] = []
    for rule in _REFERENCE_RULES:
        if rule["match"](scores):
            matches.append(
                {
                    "key": str(rule["key"]),
                    "name": str(rule["name"]),
                    "tone": str(rule["tone"]),
                    "semantic": str(rule["semantic"]),
                }
            )
    return matches
