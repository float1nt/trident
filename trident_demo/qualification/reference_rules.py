"""Dataset-agnostic learner reference rule matching.

The rule layer is an engineering prior, not a classifier. It emits soft
strong/weak/near matches from backend artifacts so the frontend only renders
backend decisions and cannot drift from the Trident pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any, Callable, Dict, List, Literal, Mapping, Optional, TypedDict

REFERENCE_RULES_VERSION = "topology-family-v2"

RuleTone = Literal["benign", "attack", "caution"]
MatchLevel = Literal["strong", "weak", "near"]


class LearnerReferenceRuleMatch(TypedDict):
    key: str
    name: str
    tone: RuleTone
    match_level: MatchLevel
    evidence_met: int
    evidence_total: int
    semantic: str


MetricScores = Mapping[str, float]
Predicate = Callable[[float], bool]


@dataclass(frozen=True)
class RuleCondition:
    key: str
    label: str
    strong: Predicate
    weak: Predicate
    required: bool = False


@dataclass(frozen=True)
class LearnerReferenceRule:
    key: str
    name: str
    tone: RuleTone
    semantic: str
    conditions: List[RuleCondition]
    weak_min: Optional[int] = None
    near_min: Optional[int] = None


def _score_map(metrics: List[Dict[str, Any]]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for m in metrics:
        key = str(m.get("metric_key", ""))
        score = m.get("score_0_100")
        if key and isinstance(score, (int, float)) and float(score) == float(score):
            out[key] = float(score)
    return out


def _ge(strong_min: float, weak_min: Optional[float] = None) -> Dict[str, Predicate]:
    weak_floor = strong_min if weak_min is None else weak_min
    return {
        "strong": lambda v: v >= strong_min,
        "weak": lambda v: v >= weak_floor,
    }


def _le(strong_max: float, weak_max: Optional[float] = None) -> Dict[str, Predicate]:
    weak_ceiling = strong_max if weak_max is None else weak_max
    return {
        "strong": lambda v: v <= strong_max,
        "weak": lambda v: v <= weak_ceiling,
    }


def _between(
    strong_min: float,
    strong_max: float,
    weak_min: Optional[float] = None,
    weak_max: Optional[float] = None,
) -> Dict[str, Predicate]:
    weak_floor = strong_min if weak_min is None else weak_min
    weak_ceiling = strong_max if weak_max is None else weak_max
    return {
        "strong": lambda v: strong_min <= v <= strong_max,
        "weak": lambda v: weak_floor <= v <= weak_ceiling,
    }


def _condition(
    key: str,
    label: str,
    bounds: Dict[str, Predicate],
    required: bool = False,
) -> RuleCondition:
    return RuleCondition(
        key=key,
        label=label,
        strong=bounds["strong"],
        weak=bounds["weak"],
        required=required,
    )


def _evaluate_rule(
    rule: LearnerReferenceRule,
    scores: MetricScores,
) -> Optional[LearnerReferenceRuleMatch]:
    checks = []
    for condition in rule.conditions:
        value = scores.get(condition.key)
        if value is None:
            checks.append((condition, False, False))
            continue
        checks.append((condition, condition.strong(value), condition.weak(value)))

    required_weak_met = all(not c.required or weak for c, _strong, weak in checks)
    strong_met = sum(1 for _c, strong, _weak in checks if strong)
    weak_met = sum(1 for _c, _strong, weak in checks if weak)
    evidence_total = len(checks)
    weak_min = rule.weak_min if rule.weak_min is not None else ceil(evidence_total * 0.8)
    near_min = rule.near_min if rule.near_min is not None else ceil(evidence_total * 0.65)

    match_level: Optional[MatchLevel] = None
    if required_weak_met and strong_met == evidence_total:
        match_level = "strong"
    elif required_weak_met and weak_met >= weak_min:
        match_level = "weak"
    elif required_weak_met and weak_met >= near_min:
        match_level = "near"

    if match_level is None:
        return None

    return {
        "key": rule.key,
        "name": rule.name,
        "tone": rule.tone,
        "match_level": match_level,
        "evidence_met": strong_met if match_level == "strong" else weak_met,
        "evidence_total": evidence_total,
        "semantic": rule.semantic,
    }


_REFERENCE_RULES: List[LearnerReferenceRule] = [
    LearnerReferenceRule(
        key="benign-natural-dispersion",
        name="正常流量参考匹配",
        tone="benign",
        semantic="边分布较散、无单边支配，目的端口丰富度处于常见服务混合范围，流内单向性也不极端。",
        weak_min=7,
        near_min=6,
        conditions=[
            _condition("endpoint_edge_entropy", "边分布分散", _ge(82, 75), True),
            _condition("top1_endpoint_edge_share", "单边不支配", _le(8, 12), True),
            _condition("edge_reuse_ratio", "边复用中等", _between(35, 65, 25, 75)),
            _condition("dst_port_entropy", "目的端口不过度扫散", _le(45, 55)),
            _condition("dst_port_richness", "目的端口丰富度受控", _le(75, 85)),
            _condition("dst_port_top1_concentration", "目的服务混合但有主服务", _between(20, 85, 10, 92)),
            _condition("low_reciprocity", "流内单向性不极端", _le(70, 78)),
            _condition("max_out_degree_ratio", "无明显单源扇出", _le(15, 22)),
        ],
    ),
    LearnerReferenceRule(
        key="fixed-service-dos-ddos-family",
        name="DoS/DDoS 等固定服务攻击族",
        tone="attack",
        semantic="目的服务几乎固定，大量变化源端指向少数目的 endpoint；边熵高时更应理解为源端展开，而不是天然正常。",
        weak_min=6,
        near_min=5,
        conditions=[
            _condition("dst_port_entropy", "目的端口熵很低", _le(12, 20), True),
            _condition("dst_port_richness", "目的端口种类少", _le(30, 42)),
            _condition("dst_port_top1_concentration", "目的端口 Top1 极高", _ge(95, 90), True),
            _condition("endpoint_edge_entropy", "源端或边集合展开", _ge(80, 70)),
            _condition("src_port_entropy", "源端口分散", _ge(80, 70)),
            _condition("dst_host_concentration", "目的主机汇聚", _ge(65, 55)),
            _condition("max_in_degree_ratio", "入向 hub 明显", _ge(75, 62)),
            _condition("host_max_in_degree_ratio", "主机级入向 hub 明显", _ge(75, 62)),
        ],
    ),
    LearnerReferenceRule(
        key="slow-dos-fixed-service",
        name="Slow DoS 类攻击参考匹配",
        tone="attack",
        semantic="固定目的服务汇聚仍明显，同时流内单向性更强，提示慢速或低反馈的服务冲击行为。",
        weak_min=7,
        near_min=6,
        conditions=[
            _condition("dst_port_entropy", "目的端口熵很低", _le(12, 20), True),
            _condition("dst_port_richness", "目的端口种类少", _le(30, 42)),
            _condition("dst_port_top1_concentration", "目的端口 Top1 极高", _ge(95, 90), True),
            _condition("endpoint_edge_entropy", "源端或边集合展开", _ge(80, 70)),
            _condition("src_port_entropy", "源端口分散", _ge(80, 70)),
            _condition("dst_host_concentration", "目的主机汇聚", _ge(65, 55)),
            _condition("max_in_degree_ratio", "入向 hub 明显", _ge(75, 62)),
            _condition("host_max_in_degree_ratio", "主机级入向 hub 明显", _ge(75, 62)),
            _condition("low_reciprocity", "流内低反馈/单向性偏强", _ge(68, 58), True),
        ],
    ),
    LearnerReferenceRule(
        key="portscan-wide-target",
        name="PortScan 类攻击参考匹配",
        tone="attack",
        semantic="目的端口丰富度和分布熵同时偏高，目的 endpoint 大范围展开，单一服务不占主导。",
        weak_min=5,
        near_min=4,
        conditions=[
            _condition("dst_port_entropy", "目的端口熵很高", _ge(90, 80), True),
            _condition("dst_port_richness", "目的端口丰富", _ge(70, 58), True),
            _condition("dst_port_top1_concentration", "目的端口 Top1 很低", _le(15, 25)),
            _condition("dst_endpoint_concentration", "目的 endpoint 分散", _le(15, 25)),
            _condition("endpoint_edge_entropy", "endpoint 边分散", _ge(90, 80)),
            _condition("low_reciprocity", "单向性不应极端高", _le(75, 82)),
        ],
    ),
    LearnerReferenceRule(
        key="heartbleed-like-small-sample",
        name="Heartbleed 小样本参考匹配",
        tone="caution",
        semantic="少量流集中在极少边上；这类小样本固定边形态只适合作为人工复核提示。",
        weak_min=3,
        near_min=3,
        conditions=[
            _condition("endpoint_edge_entropy", "边熵很低", _le(20, 30), True),
            _condition("top1_endpoint_edge_share", "单边占比很高", _ge(80, 68), True),
            _condition("dst_port_top1_concentration", "目的端口固定", _ge(95, 88)),
            _condition("src_port_entropy", "源端口模板化", _le(25, 38)),
        ],
    ),
    LearnerReferenceRule(
        key="diffuse-one-way-drdos-udp-syn-family",
        name="DRDoS/UDP/SYN 单向攻击族",
        tone="attack",
        semantic="目的端口高度分散，边接近一次性，流记录内强单向；该规则描述高分散单向冲击族，而不是精确分类器。",
        weak_min=5,
        near_min=4,
        conditions=[
            _condition("dst_port_entropy", "目的端口熵很高", _ge(90, 82), True),
            _condition("dst_port_richness", "目的端口丰富度很高", _ge(90, 80), True),
            _condition("dst_port_top1_concentration", "目的端口 Top1 很低", _le(10, 18)),
            _condition("endpoint_edge_entropy", "endpoint 边高度分散", _ge(95, 88)),
            _condition("edge_reuse_ratio", "边复用低", _le(25, 35)),
            _condition("low_reciprocity", "流内单向性强", _ge(85, 75), True),
        ],
    ),
    LearnerReferenceRule(
        key="drdos-dns-ldap-ntp-like",
        name="DRDoS DNS/LDAP/NTP 类参考匹配",
        tone="attack",
        semantic="在高分散单向形态上，源端口分散度处于中高区间，提示一类较稳定的端口展开模式。",
        weak_min=6,
        near_min=5,
        conditions=[
            _condition("dst_port_entropy", "目的端口熵很高", _ge(90, 82), True),
            _condition("dst_port_richness", "目的端口丰富度很高", _ge(90, 80), True),
            _condition("dst_port_top1_concentration", "目的端口 Top1 很低", _le(10, 18)),
            _condition("endpoint_edge_entropy", "endpoint 边高度分散", _ge(95, 88)),
            _condition("edge_reuse_ratio", "边复用低", _le(25, 35)),
            _condition("low_reciprocity", "流内单向性强", _ge(85, 75), True),
            _condition("src_port_entropy", "源端口中高分散", _between(65, 85, 55, 88), True),
        ],
    ),
    LearnerReferenceRule(
        key="drdos-snmp-ssdp-tftp-like",
        name="DRDoS SNMP/SSDP/TFTP 类参考匹配",
        tone="attack",
        semantic="在高分散单向形态上，源端口分散度更高，提示源端口展开更充分的子形态。",
        weak_min=6,
        near_min=5,
        conditions=[
            _condition("dst_port_entropy", "目的端口熵很高", _ge(90, 82), True),
            _condition("dst_port_richness", "目的端口丰富度很高", _ge(90, 80), True),
            _condition("dst_port_top1_concentration", "目的端口 Top1 很低", _le(10, 18)),
            _condition("endpoint_edge_entropy", "endpoint 边高度分散", _ge(95, 88)),
            _condition("edge_reuse_ratio", "边复用低", _le(25, 35)),
            _condition("low_reciprocity", "流内单向性强", _ge(85, 75), True),
            _condition("src_port_entropy", "源端口高分散", _between(85.0001, 97.9999, 82, 98.5), True),
        ],
    ),
    LearnerReferenceRule(
        key="drdos-udp-syn-udp-lag-like",
        name="DRDoS UDP/SYN/UDP-LAG 类参考匹配",
        tone="attack",
        semantic="在高分散单向形态上，源端口也极分散，提示源端和目的端同时高度展开。",
        weak_min=6,
        near_min=5,
        conditions=[
            _condition("dst_port_entropy", "目的端口熵很高", _ge(90, 82), True),
            _condition("dst_port_richness", "目的端口丰富度很高", _ge(90, 80), True),
            _condition("dst_port_top1_concentration", "目的端口 Top1 很低", _le(10, 18)),
            _condition("endpoint_edge_entropy", "endpoint 边高度分散", _ge(95, 88)),
            _condition("edge_reuse_ratio", "边复用低", _le(25, 35)),
            _condition("low_reciprocity", "流内单向性强", _ge(85, 75), True),
            _condition("src_port_entropy", "源端口极高分散", _ge(98, 95), True),
        ],
    ),
    LearnerReferenceRule(
        key="web-ddos-bidirectional-hub-like",
        name="WebDDoS 类攻击参考匹配",
        tone="caution",
        semantic="目的端口没有全局扫散，但入向和出向 hub 同时明显，提示围绕服务节点的双向冲击结构。",
        weak_min=4,
        near_min=4,
        conditions=[
            _condition("dst_port_entropy", "目的端口中等分散", _between(35, 65, 25, 75), True),
            _condition("dst_port_top1_concentration", "目的端口 Top1 中高", _between(50, 85, 40, 92), True),
            _condition("max_in_degree_ratio", "入向 hub 明显", _ge(80, 68)),
            _condition("max_out_degree_ratio", "出向 hub 明显", _ge(80, 68)),
            _condition("endpoint_edge_entropy", "endpoint 边分散", _ge(90, 80)),
        ],
    ),
]

_LEVEL_RANK: Dict[MatchLevel, int] = {"strong": 0, "weak": 1, "near": 2}


def evaluate_learner_reference_rules(
    metrics: List[Dict[str, Any]],
) -> List[LearnerReferenceRuleMatch]:
    scores = _score_map(metrics)
    matches = [m for rule in _REFERENCE_RULES if (m := _evaluate_rule(rule, scores))]
    return sorted(
        matches,
        key=lambda m: (_LEVEL_RANK[m["match_level"]], -m["evidence_met"], m["key"]),
    )
