from __future__ import annotations

import numpy as np

from app.flow_loader import FlowLoader
from app.redis_consumer import RedisStreamMessage
from app.runtime.quality import build_learner_audit, feature_drift_score


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
