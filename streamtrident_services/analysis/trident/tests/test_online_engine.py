from __future__ import annotations

from dataclasses import replace

from app.config import TridentConfig
from app.flow_loader import FlowLoader
from app.redis_consumer import RedisStreamMessage
from app.runtime.online_engine import OnlineEngine
from app.window_buffer import BufferedFlow, FlowWindow


def _flow(message_id: str, dst_port: int = 443) -> BufferedFlow:
    message = RedisStreamMessage(
        "suricata:cic_flow",
        message_id,
        {
            "event_time": "2026-05-26T10:00:00Z",
            "src_ip": "10.0.0.1",
            "dst_ip": "10.0.0.2",
            "src_port": "12345",
            "dst_port": str(dst_port),
            "protocol": "TCP",
            "features_json": "{\"bytes\":100}",
        },
    )
    record = FlowLoader(session_id="s1", feature_profile="compact").load(message)
    return BufferedFlow(message=message, record=record)


def test_online_engine_assigns_and_updates_seed_learner() -> None:
    cfg = replace(
        TridentConfig(),
        algorithm_backend="iforest",
        min_class_samples=1,
        increment_min_samples=1,
        max_train_per_class=100,
    )
    engine = OnlineEngine(session_id="s1", cfg=cfg)
    window = FlowWindow(window_index=1, items=[_flow("1-0"), _flow("2-0")])

    result = engine.process_window(window)

    assert len(result.assignments) == 2
    assert all(not assignment.is_unknown for assignment in result.assignments)
    assert result.updated_learners[0]["learner_name"] == "0000|UNLABELED"
    assert result.metrics["accepted_count"] == 2


def test_online_engine_promotes_unknown_cluster_to_new_learner() -> None:
    cfg = replace(
        TridentConfig(),
        algorithm_backend="iforest",
        min_class_samples=1,
        increment_min_samples=100,
        cluster_trigger_size=2,
        new_learner_min_size=2,
        dbscan_min_samples=1,
        dbscan_eps=10.0,
        max_train_per_class=100,
    )
    engine = OnlineEngine(session_id="s1", cfg=cfg)
    engine.process_window(FlowWindow(window_index=1, items=[_flow("1-0", dst_port=80)]))
    engine.tsieve.learners["0000|UNLABELED"].threshold = -1.0
    window = FlowWindow(window_index=2, items=[_flow("2-0", dst_port=65000), _flow("3-0", dst_port=65001)])

    result = engine.process_window(window)

    assert result.metrics["unknown_count"] == 0
    assert result.metrics["accepted_count"] == 2
    assert result.metrics["new_learner_count"] == 1
    new_name = result.new_learners[0]["learner_name"]
    assert new_name.startswith("NEW_")
    promoted = [assignment for assignment in result.assignments if assignment.assigned_learner == new_name]
    assert len(promoted) == 2
    assert all(not assignment.is_unknown for assignment in promoted)
    assert all(assignment.assignment_meta.get("promoted_from_unknown") for assignment in promoted)


def test_online_engine_learner_row_contains_audit_payloads(tmp_path) -> None:
    cfg = replace(
        TridentConfig(),
        algorithm_backend="iforest",
        min_class_samples=1,
        increment_min_samples=1,
        max_train_per_class=100,
        model_store_dir=str(tmp_path),
    )
    engine = OnlineEngine(session_id="s1", cfg=cfg)
    engine.process_window(FlowWindow(window_index=1, items=[_flow("1-0"), _flow("2-0")]))

    row = engine._learner_row("0000|UNLABELED")

    assert row["metric_json"]["recent_record_count"] == 2
    assert "quality_gates" in row["profile_json"]
    assert "trident_model" not in row["profile_json"]
    assert row["profile_json"]["model_ref"]["path"]
    assert "rules" in row["rule_json"]
    assert "top" in row["topology_json"]


def test_online_engine_finalizes_cold_start_baseline_to_dominant_learner() -> None:
    cfg = replace(
        TridentConfig(),
        algorithm_backend="iforest",
        window_size=2,
        min_class_samples=1,
        increment_min_samples=100,
        cluster_trigger_size=2,
        new_learner_min_size=2,
        dbscan_min_samples=1,
        dbscan_eps=10.0,
        max_train_per_class=100,
    )
    engine = OnlineEngine(session_id="s1", cfg=cfg)
    engine.process_window(FlowWindow(window_index=1, items=[_flow("1-0", dst_port=80)]))
    assert engine.baseline_learner_name == "0000|UNLABELED"
    engine.tsieve.learners["0000|UNLABELED"].threshold = -1.0
    result = engine.process_window(
        FlowWindow(window_index=2, items=[_flow("2-0", dst_port=65000), _flow("3-0", dst_port=65001)])
    )

    assert result.metrics["new_learner_count"] == 1
    new_name = result.new_learners[0]["learner_name"]
    assert engine.cold_start_complete is True
    assert engine.baseline_learner_name == new_name
    assert result.new_learners[0]["rule_json"]["attack_types"][0]["attack_type"] == "BENIGN_NORMAL"


def test_online_engine_patches_only_current_window_assignments_on_cross_window_promotion() -> None:
    cfg = replace(
        TridentConfig(),
        algorithm_backend="iforest",
        min_class_samples=1,
        increment_min_samples=100,
        cluster_trigger_size=2,
        new_learner_min_size=2,
        dbscan_min_samples=1,
        dbscan_eps=10.0,
        max_train_per_class=100,
    )
    engine = OnlineEngine(session_id="s1", cfg=cfg)
    engine.process_window(FlowWindow(window_index=1, items=[_flow("1-0", dst_port=80)]))
    engine.tsieve.learners["0000|UNLABELED"].threshold = -1.0
    first_unknown = engine.process_window(FlowWindow(window_index=2, items=[_flow("2-0", dst_port=65000)]))
    assert first_unknown.metrics["unknown_count"] == 1
    assert first_unknown.assignments[0].assigned_learner == ""

    result = engine.process_window(FlowWindow(window_index=3, items=[_flow("3-0", dst_port=65001)]))

    new_name = result.new_learners[0]["learner_name"]
    current_window_assignment = result.assignments[0]
    assert current_window_assignment.assigned_learner == new_name
    assert current_window_assignment.is_unknown is False
    assert first_unknown.assignments[0].assigned_learner == ""
