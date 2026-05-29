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
        runtime_mode="cold_start",
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
    assert result.new_learners[0]["learner_name"] == "COLD_0|BENIGN"
    assert result.metrics["accepted_count"] == 2


def test_online_engine_promotes_unknown_cluster_to_new_learner() -> None:
    cfg = replace(
        TridentConfig(),
        runtime_mode="inference",
        inference_require_cold_start=False,
        algorithm_backend="iforest",
        min_class_samples=1,
        increment_min_samples=100,
        cluster_trigger_size=2,
        new_learner_min_size=2,
        dbscan_min_samples=1,
        dbscan_eps=10.0,
        max_train_per_class=100,
    )
    cold = OnlineEngine(session_id="s1", cfg=replace(cfg, runtime_mode="cold_start"))
    cold.process_window(FlowWindow(window_index=1, items=[_flow("1-0", dst_port=80)]))
    engine = OnlineEngine(session_id="s1", cfg=cfg, learner_rows=[cold._learner_row("COLD_0|BENIGN")])
    engine.tsieve.learners["COLD_0|BENIGN"].threshold = -1.0
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


def test_inference_does_not_create_initial_learner_when_empty() -> None:
    cfg = replace(TridentConfig(), runtime_mode="inference", inference_require_cold_start=False)
    engine = OnlineEngine(session_id="s1", cfg=cfg)

    result = engine.process_window(FlowWindow(window_index=1, items=[_flow("1-0"), _flow("2-0")]))

    assert result.metrics["learner_count"] == 0
    assert result.new_learners == []
    assert all(assignment.is_unknown for assignment in result.assignments)


def test_online_engine_learner_row_contains_audit_payloads(tmp_path) -> None:
    cfg = replace(
        TridentConfig(),
        runtime_mode="cold_start",
        algorithm_backend="iforest",
        min_class_samples=1,
        increment_min_samples=1,
        max_train_per_class=100,
        model_store_dir=str(tmp_path),
    )
    engine = OnlineEngine(session_id="s1", cfg=cfg)
    engine.process_window(FlowWindow(window_index=1, items=[_flow("1-0"), _flow("2-0")]))

    row = engine._learner_row("COLD_0|BENIGN")

    assert row["metric_json"]["recent_record_count"] == 2
    assert "quality_gates" in row["profile_json"]
    assert "trident_model" not in row["profile_json"]
    assert row["profile_json"]["model_ref"]["path"]
    assert "rules" in row["rule_json"]
    assert "top" in row["topology_json"]


def test_online_engine_finalizes_cold_start_after_stable_observing_window() -> None:
    cfg = replace(
        TridentConfig(),
        runtime_mode="cold_start",
        algorithm_backend="iforest",
        window_size=2,
        min_class_samples=1,
        increment_min_samples=100,
        cluster_trigger_size=2,
        new_learner_min_size=2,
        dbscan_min_samples=1,
        dbscan_eps=10.0,
        max_train_per_class=100,
        cold_start_min_windows=2,
        cold_start_stable_windows=1,
        cold_start_min_flows=3,
    )
    engine = OnlineEngine(session_id="s1", cfg=cfg)
    engine.process_window(FlowWindow(window_index=1, items=[_flow("1-0", dst_port=80)]))
    assert engine.baseline_learner_name == "COLD_0|BENIGN"
    engine.tsieve.learners["COLD_0|BENIGN"].threshold = -1.0
    result = engine.process_window(
        FlowWindow(window_index=2, items=[_flow("2-0", dst_port=65000), _flow("3-0", dst_port=65001)])
    )

    assert result.metrics["new_learner_count"] == 1
    assert result.new_learners[0]["learner_name"] == "COLD_1|BENIGN"
    assert engine.cold_start_complete is False

    stable = engine.process_window(FlowWindow(window_index=3, items=[_flow("4-0", dst_port=65000)]))

    assert engine.cold_start_complete is True
    assert stable.metrics["cold_start_finalized"] is True
    assert set(stable.metrics["baseline_learner_names"]) == {"COLD_0|BENIGN", "COLD_1|BENIGN"}
    finalized = {row["learner_name"]: row for row in stable.updated_learners}
    assert finalized["COLD_0|BENIGN"]["rule_json"]["attack_types"][0]["attack_type"] == "BENIGN_NORMAL"
    assert finalized["COLD_1|BENIGN"]["rule_json"]["attack_types"][0]["attack_type"] == "BENIGN_NORMAL"


def test_online_engine_patches_only_current_window_assignments_on_cross_window_promotion() -> None:
    cfg = replace(
        TridentConfig(),
        runtime_mode="inference",
        inference_require_cold_start=False,
        algorithm_backend="iforest",
        min_class_samples=1,
        increment_min_samples=100,
        cluster_trigger_size=2,
        new_learner_min_size=2,
        dbscan_min_samples=1,
        dbscan_eps=10.0,
        max_train_per_class=100,
    )
    cold = OnlineEngine(session_id="s1", cfg=replace(cfg, runtime_mode="cold_start"))
    cold.process_window(FlowWindow(window_index=1, items=[_flow("1-0", dst_port=80)]))
    engine = OnlineEngine(session_id="s1", cfg=cfg, learner_rows=[cold._learner_row("COLD_0|BENIGN")])
    engine.tsieve.learners["COLD_0|BENIGN"].threshold = -1.0
    first_unknown = engine.process_window(FlowWindow(window_index=2, items=[_flow("2-0", dst_port=65000)]))
    assert first_unknown.metrics["unknown_count"] == 1
    assert first_unknown.assignments[0].assigned_learner == ""

    result = engine.process_window(FlowWindow(window_index=3, items=[_flow("3-0", dst_port=65001)]))

    new_name = result.new_learners[0]["learner_name"]
    current_window_assignment = result.assignments[0]
    assert current_window_assignment.assigned_learner == new_name
    assert current_window_assignment.is_unknown is False
    assert first_unknown.assignments[0].assigned_learner == ""


def test_new_learner_names_use_next_available_numeric_suffix() -> None:
    cfg = replace(
        TridentConfig(),
        runtime_mode="inference",
        inference_require_cold_start=False,
        algorithm_backend="iforest",
        min_class_samples=1,
        increment_min_samples=100,
        cluster_trigger_size=2,
        new_learner_min_size=2,
        dbscan_min_samples=1,
        dbscan_eps=10.0,
        max_train_per_class=100,
    )
    cold = OnlineEngine(session_id="s1", cfg=replace(cfg, runtime_mode="cold_start"))
    cold.process_window(FlowWindow(window_index=1, items=[_flow("1-0", dst_port=80)]))
    row = cold._learner_row("COLD_0|BENIGN")
    new7 = dict(row)
    new7["learner_name"] = "NEW_7"
    engine = OnlineEngine(session_id="s1", cfg=cfg, learner_rows=[row, new7])
    engine.tsieve.learners["COLD_0|BENIGN"].threshold = -1.0
    engine.tsieve.learners["NEW_7"].threshold = -1.0

    result = engine.process_window(
        FlowWindow(window_index=2, items=[_flow("2-0", dst_port=65000), _flow("3-0", dst_port=65001)])
    )

    assert result.new_learners[0]["learner_name"] == "NEW_8"
