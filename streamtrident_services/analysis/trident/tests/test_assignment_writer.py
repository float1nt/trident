from __future__ import annotations

from app.flow_loader import FlowLoader
from app.redis_consumer import RedisStreamMessage
from app.runtime.assignment_writer import AssignmentWriter
from app.runtime.online_engine import FlowAssignment


class _Repository:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def insert_assignments(self, updates: list[object]) -> int:
        self.rows = [update.to_clickhouse_row() for update in updates]  # type: ignore[attr-defined]
        return len(self.rows)


def _record() -> object:
    message = RedisStreamMessage(
        "suricata:cic_flow",
        "1-0",
        {
            "event_time": "2026-05-26T10:00:00Z",
            "src_ip": "10.0.0.1",
            "dst_ip": "10.0.0.2",
            "src_port": "12345",
            "dst_port": "443",
            "protocol": "TCP",
            "features_json": "{\"bytes\":100}",
            "payload_sample_b64": "AQID",
            "payload_sample_bytes": "3",
            "payload_original_bytes": "100",
            "payload_truncated": "true",
            "payload_direction": "toserver",
        },
    )
    return FlowLoader(session_id="s1", feature_profile="compact").load(message)


def _assignment() -> FlowAssignment:
    return FlowAssignment(
        flow_uid="suricata:cic_flow:1-0",
        assigned_learner="NEW_1",
        is_unknown=False,
        pred_loss=0.1,
        threshold=0.2,
        assignment_meta={},
    )


def test_assignment_writer_clears_payload_when_policy_rejects_it() -> None:
    repo = _Repository()
    writer = AssignmentWriter(repo)  # type: ignore[arg-type]

    written = writer.write([_record()], [_assignment()], window_index=1, should_keep_payload=lambda _assignment: False)

    assert written == 1
    assert repo.rows[0]["payload_sample_b64"] == ""
    assert repo.rows[0]["payload_sample_bytes"] == 0
    assert repo.rows[0]["payload_original_bytes"] == 0
    assert repo.rows[0]["payload_truncated"] == 0
    assert repo.rows[0]["payload_direction"] == ""


def test_assignment_writer_preserves_payload_when_policy_accepts_it() -> None:
    repo = _Repository()
    writer = AssignmentWriter(repo)  # type: ignore[arg-type]

    written = writer.write([_record()], [_assignment()], window_index=1, should_keep_payload=lambda _assignment: True)

    assert written == 1
    assert repo.rows[0]["payload_sample_b64"] == "AQID"
    assert repo.rows[0]["payload_sample_bytes"] == 3
    assert repo.rows[0]["payload_original_bytes"] == 100
    assert repo.rows[0]["payload_truncated"] == 1
    assert repo.rows[0]["payload_direction"] == "toserver"
