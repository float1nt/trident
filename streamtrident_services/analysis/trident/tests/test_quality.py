from __future__ import annotations

import numpy as np

from app.flow_loader import FlowLoader
from app.redis_consumer import RedisStreamMessage
from app.runtime.quality import build_learner_audit, feature_drift_score, resolve_session_baseline_learner


def _record(message_id: str, dst_port: int) -> object:
    message = RedisStreamMessage(
        "suricata:cic_flow",
        message_id,
        {
            "src_ip": "10.0.0.1",
            "dst_ip": "10.0.0.2",
            "src_port": "1234",
            "dst_port": str(dst_port),
            "protocol": "TCP",
            "features_json": "{\"bytes\":100}",
        },
    )
    return FlowLoader(session_id="s1", feature_profile="compact").load(message)


def test_feature_drift_score_increases_for_shifted_samples() -> None:
    history = np.zeros((20, 3), dtype=float)
    samples = np.ones((20, 3), dtype=float)

    assert feature_drift_score(history, samples) > 0.1


def test_learner_audit_emits_metrics_rules_topology_and_risk() -> None:
    records = [_record(f"{idx}-0", 443) for idx in range(10)]

    metrics, topology, rules, risk_score, risk_band, risk_reason = build_learner_audit(
        learner_name="NEW_1",
        records=records,
        flow_count=10,
        unknown_buffer_size=3,
        threshold=0.5,
    )

    assert metrics["top1_dst_port_share"] == 1.0
    assert metrics["metric_version"] == 4
    assert topology["top"]["dst_ports"][0]["value"] == "443"
    assert "rule_set" in rules
    assert "attack_types" in rules
    assert isinstance(rules["rules"], list)
    assert 0.0 <= risk_score <= 1.0
    assert risk_band in {"low", "medium", "high"}
    assert "unknown_buffer=3" in risk_reason


def test_baseline_learner_is_fixed_benign_even_with_scan_like_metrics() -> None:
    records = [_record(f"{idx}-0", 1000 + idx) for idx in range(50)]

    metrics, _topology, rules, risk_score, risk_band, risk_reason = build_learner_audit(
        learner_name="0000|UNLABELED",
        records=records,
        flow_count=50,
        unknown_buffer_size=0,
        threshold=0.5,
    )

    assert rules["attack_types"] == [
        {
            "attack_type": "BENIGN_NORMAL",
            "confidence": 0.35,
            "evidence_rules": ["learner_baseline_benign_fixed"],
            "explain": "冷启动结束后的 baseline 学习器，规则层固定标记为正常业务流量。",
        }
    ]
    assert rules["rules"][0]["rule_id"] == "learner_baseline_benign_fixed"
    assert rules["rules"][0]["source"] == "baseline_policy"
    assert metrics["unique_dst_port_count"] == 50
    assert risk_score == 0.35
    assert risk_band == "low"
    assert "fixed_benign=1" in risk_reason


def test_cold_start_dominant_learner_is_fixed_benign_even_if_named_new() -> None:
    records = [_record(f"{idx}-0", 443) for idx in range(50)]

    metrics, _topology, rules, risk_score, risk_band, risk_reason = build_learner_audit(
        learner_name="NEW_1",
        records=records,
        flow_count=50,
        unknown_buffer_size=0,
        threshold=0.5,
        session_baseline_learner="NEW_1",
    )

    assert rules["attack_types"][0]["attack_type"] == "BENIGN_NORMAL"
    assert risk_score == 0.35
    assert risk_band == "low"
    assert "fixed_benign=1" in risk_reason
    assert metrics["flow_count"] == 50


def test_resolve_session_baseline_prefers_dominant_post_cold_start_learner() -> None:
    learners = [
        {
            "learner_name": "0000|UNLABELED",
            "creation_window_index": 1,
            "flow_count": 4510,
            "profile_json": {},
        },
        {
            "learner_name": "NEW_1",
            "creation_window_index": 13,
            "flow_count": 615660,
            "profile_json": {},
        },
    ]

    baseline = resolve_session_baseline_learner(
        learners,
        flow_counts={"0000|UNLABELED": 4510, "NEW_1": 615660},
    )

    assert baseline == "NEW_1"
