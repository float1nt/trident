from __future__ import annotations

import numpy as np

from app.flow_loader import FlowLoader
from app.redis_consumer import RedisStreamMessage
from app.runtime.quality import apply_cold_start_benign_audit, build_learner_audit, feature_drift_score, resolve_session_baseline_learner


def _record(
    message_id: str,
    dst_port: int,
    *,
    src_ip: str = "10.0.0.1",
    dst_ip: str = "10.0.0.2",
    src_port: int = 1234,
    protocol: str = "TCP",
    fwd_packets: int = 5,
    bwd_packets: int = 5,
) -> object:
    message = RedisStreamMessage(
        "suricata:cic_flow",
        message_id,
        {
            "src_ip": src_ip,
            "dst_ip": dst_ip,
            "src_port": str(src_port),
            "dst_port": str(dst_port),
            "protocol": protocol,
            "features_json": (
                f'{{"bytes":100,"Total Fwd Packet":{fwd_packets},'
                f'"Total Bwd packets":{bwd_packets}}}'
            ),
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


def test_cold_start_finalize_audit_is_fixed_benign_even_with_scan_like_metrics() -> None:
    records = [_record(f"{idx}-0", 1000 + idx) for idx in range(50)]

    metrics, _topology, rules, risk_score, risk_band, risk_reason = apply_cold_start_benign_audit(
        learner_name="COLD_0|BENIGN",
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


def test_build_learner_audit_does_not_protect_cold_learners_after_finalize() -> None:
    records = [_record(f"{idx}-0", 1000 + idx) for idx in range(50)]

    _metrics, _topology, rules, _risk_score, _risk_band, risk_reason = build_learner_audit(
        learner_name="COLD_0|BENIGN",
        records=records,
        flow_count=50,
        unknown_buffer_size=0,
        threshold=0.5,
    )

    assert rules["attack_types"][0]["attack_type"] != "BENIGN_NORMAL"
    assert "fixed_benign=1" not in risk_reason


def test_balanced_cic_flows_can_fall_back_to_benign_normal() -> None:
    records = [
        _record(
            f"{idx}-0",
            443 if idx % 2 == 0 else 80,
            src_ip=f"10.0.0.{idx + 1}",
            dst_ip=f"10.0.1.{idx + 1}",
            src_port=20000 + idx,
        )
        for idx in range(20)
    ]

    metrics, _topology, rules, _risk_score, _risk_band, _risk_reason = build_learner_audit(
        learner_name="NEW_NORMAL",
        records=records,
        flow_count=len(records),
        unknown_buffer_size=0,
        threshold=0.5,
    )

    assert metrics["low_reciprocity"] == 50.0
    assert rules["attack_types"][0]["attack_type"] == "BENIGN_NORMAL"


def test_internal_scan_uses_confirmed_taxonomy_and_category() -> None:
    records = [_record(f"{idx}-0", 1000 + idx, src_port=20000 + idx) for idx in range(80)]

    _metrics, _topology, rules, _risk_score, _risk_band, _risk_reason = build_learner_audit(
        learner_name="NEW_SCAN",
        records=records,
        flow_count=len(records),
        unknown_buffer_size=0,
        threshold=0.5,
    )

    primary = rules["attack_types"][0]
    assert primary["attack_type"] == "ENCRYPTED_INTERNAL_SCAN"
    assert primary["attack_category"] == "恶意攻击类"


def test_p2p_botnet_communication_uses_graph_only_shape() -> None:
    records = [
        _record(
            f"{idx}-0",
            8443,
            dst_ip=f"8.8.8.{idx + 1}",
            src_port=20000 + idx,
        )
        for idx in range(80)
    ]

    _metrics, _topology, rules, _risk_score, _risk_band, _risk_reason = build_learner_audit(
        learner_name="NEW_P2P",
        records=records,
        flow_count=len(records),
        unknown_buffer_size=0,
        threshold=0.5,
    )

    primary = rules["attack_types"][0]
    assert primary["attack_type"] == "P2P_BOTNET_COMMUNICATION"
    assert primary["attack_category"] == "恶意攻击类"


def test_encrypted_protocol_brute_force_uses_confirmed_taxonomy() -> None:
    records = [_record(f"{idx}-0", 443) for idx in range(80)]

    _metrics, _topology, rules, _risk_score, _risk_band, _risk_reason = build_learner_audit(
        learner_name="NEW_BRUTE_FORCE",
        records=records,
        flow_count=len(records),
        unknown_buffer_size=0,
        threshold=0.5,
    )

    primary = rules["attack_types"][0]
    assert primary["attack_type"] == "ENCRYPTED_PROTOCOL_BRUTE_FORCE"
    assert primary["attack_category"] == "恶意攻击类"


def test_automated_vulnerability_sweep_uses_external_to_internal_https_graph() -> None:
    records = [
        _record(
            f"{idx}-0",
            443,
            src_ip="8.8.4.4",
            dst_ip=f"10.0.1.{idx + 1}",
            src_port=20000 + idx,
        )
        for idx in range(40)
    ]

    _metrics, _topology, rules, _risk_score, _risk_band, _risk_reason = build_learner_audit(
        learner_name="NEW_VULN_SWEEP",
        records=records,
        flow_count=len(records),
        unknown_buffer_size=0,
        threshold=0.5,
    )

    primary = rules["attack_types"][0]
    assert primary["attack_type"] == "ENCRYPTED_AUTOMATED_VULNERABILITY_SWEEP"
    assert primary["attack_category"] == "恶意攻击类"


def test_multi_hop_proxy_uses_bidirectional_hub_graph() -> None:
    records = [
        _record("1-0", 443, src_ip="10.0.0.1", dst_ip="10.0.0.5"),
        _record("2-0", 443, src_ip="10.0.0.2", dst_ip="10.0.0.5"),
        _record("3-0", 443, src_ip="10.0.0.3", dst_ip="10.0.0.5"),
        _record("4-0", 443, src_ip="10.0.0.5", dst_ip="8.8.8.1"),
        _record("5-0", 443, src_ip="10.0.0.5", dst_ip="8.8.8.2"),
        _record("6-0", 443, src_ip="10.0.0.5", dst_ip="8.8.8.3"),
    ]

    _metrics, _topology, rules, _risk_score, _risk_band, _risk_reason = build_learner_audit(
        learner_name="NEW_PROXY",
        records=records,
        flow_count=len(records),
        unknown_buffer_size=0,
        threshold=0.5,
    )

    primary = rules["attack_types"][0]
    assert primary["attack_type"] == "ENCRYPTED_MULTI_HOP_PROXY"
    assert primary["attack_category"] == "恶意攻击类"


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
