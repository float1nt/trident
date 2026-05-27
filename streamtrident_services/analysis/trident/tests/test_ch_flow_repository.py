from __future__ import annotations

from app.flow_loader import FlowLoader
from app.persistence.ch_flow_repository import AssignmentUpdate
from app.redis_consumer import RedisStreamMessage
from app.runtime.online_engine import FlowAssignment


def test_assignment_update_preserves_base_row_and_increments_version() -> None:
    message = RedisStreamMessage(
        "suricata:cic_flow",
        "1000-0",
        {"dst_port": "443", "app_proto": "tls", "total_bytes": "2048"},
    )
    record = FlowLoader(session_id="s1", feature_profile="compact").load(message)
    assignment = FlowAssignment(
        flow_uid=record.flow_uid,
        assigned_learner="BASELINE_0",
        is_unknown=False,
        pred_loss=0.1,
        threshold=0.35,
        assignment_meta={"engine": "unit"},
        learner_snapshot_id="snap-1",
        learner_snapshot_version=1,
    )

    row = AssignmentUpdate.from_record(record, assignment, window_index=7).to_clickhouse_row()

    assert row["flow_uid"] == record.flow_uid
    assert row["dst_port"] == 443
    assert row["app_proto"] == "tls"
    assert row["total_bytes"] == 2048
    assert row["assigned_learner"] == "BASELINE_0"
    assert row["record_stage"] == "assigned"
    assert row["record_version"] == 1001
