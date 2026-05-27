from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..flow_loader import FlowRecord
from ..runtime.online_engine import FlowAssignment
from .clickhouse_http import ClickHouseHTTPClient


@dataclass(frozen=True, slots=True)
class AssignmentUpdate:
    record: FlowRecord
    assigned_learner: str
    is_unknown: bool
    window_index: int
    pred_loss: float
    threshold: float
    assignment_meta: str
    learner_snapshot_id: str
    learner_snapshot_version: int

    @classmethod
    def from_record(cls, record: FlowRecord, assignment: FlowAssignment, *, window_index: int) -> "AssignmentUpdate":
        return cls(
            record=record,
            assigned_learner=assignment.assigned_learner,
            is_unknown=assignment.is_unknown,
            window_index=window_index,
            pred_loss=assignment.pred_loss,
            threshold=assignment.threshold,
            assignment_meta=json.dumps(assignment.assignment_meta, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            learner_snapshot_id=assignment.learner_snapshot_id,
            learner_snapshot_version=assignment.learner_snapshot_version,
        )

    def to_clickhouse_row(self) -> dict[str, Any]:
        row = self.record.to_clickhouse_row()
        row.update(
            {
                "assigned_learner": self.assigned_learner,
                "is_unknown": 1 if self.is_unknown else 0,
                "window_index": self.window_index,
                "pred_loss": self.pred_loss,
                "threshold": self.threshold,
                "assignment_meta": self.assignment_meta,
                "learner_snapshot_id": self.learner_snapshot_id,
                "learner_snapshot_version": self.learner_snapshot_version,
                "record_version": self.record.record_version + 1,
                "record_stage": "assigned",
            }
        )
        return row


class ChFlowRepository:
    def __init__(self, dsn: str) -> None:
        self.client = ClickHouseHTTPClient(dsn)

    def insert_ingested(self, records: list[FlowRecord]) -> int:
        rows = [record.to_clickhouse_row() for record in records]
        self.client.insert_json_each_row("ch_flow", rows)
        return len(rows)

    def insert_assignments(self, updates: list[AssignmentUpdate]) -> int:
        rows = [update.to_clickhouse_row() for update in updates]
        self.client.insert_json_each_row("ch_flow", rows)
        return len(rows)

    def list_flows(
        self,
        *,
        session_id: str | None = None,
        window_index: int | None = None,
        learner_name: str | None = None,
        is_unknown: bool | None = None,
        time_from: str | None = None,
        time_to: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> list[dict[str, Any]]:
        filters: list[str] = []
        if session_id:
            filters.append(f"session_id = {_quote(session_id)}")
        if window_index is not None:
            filters.append(f"window_index = {int(window_index)}")
        if learner_name:
            filters.append(f"assigned_learner = {_quote(learner_name)}")
        if is_unknown is not None:
            filters.append(f"is_unknown = {1 if is_unknown else 0}")
        if time_from:
            filters.append(f"event_time >= parseDateTime64BestEffort({_quote(time_from)}, 3)")
        if time_to:
            filters.append(f"event_time <= parseDateTime64BestEffort({_quote(time_to)}, 3)")
        if cursor:
            filters.append(f"flow_uid > {_quote(cursor)}")
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        capped = max(1, min(int(limit), 1000))
        sql = f"""
SELECT
    session_id,
    flow_uid,
    event_time,
    src_ip,
    dst_ip,
    src_port,
    dst_port,
    protocol,
    feature_profile,
    features_json,
    assigned_learner,
    is_unknown,
    window_index,
    pred_loss,
    threshold,
    assignment_meta,
    learner_snapshot_id,
    learner_snapshot_version,
    mq_type,
    mq_topic,
    mq_message_id,
    source_flow_id,
    record_version,
    record_stage
FROM ch_flow FINAL
{where}
ORDER BY event_time DESC, flow_uid ASC
LIMIT {capped}
FORMAT JSONEachRow
"""
        text = self.client.execute(sql)
        return [row for line in text.splitlines() if line.strip() for row in [_parse_json(line)]]

    def count_flows(self, *, session_id: str | None = None) -> int:
        where = f"WHERE session_id = {_quote(session_id)}" if session_id else ""
        text = self.client.execute(f"SELECT count() FROM ch_flow FINAL {where} FORMAT TabSeparated")
        return int(text.strip() or "0")

    def max_window_index(self, *, session_id: str | None = None) -> int:
        where = f"WHERE session_id = {_quote(session_id)}" if session_id else ""
        text = self.client.execute(f"SELECT max(window_index) FROM ch_flow FINAL {where} FORMAT TabSeparated")
        value = text.strip()
        return int(value) if value and value != "\\N" else 0

    def ping(self) -> bool:
        self.client.execute("SELECT 1 FORMAT TabSeparated")
        return True


def _quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _parse_json(line: str) -> dict[str, Any]:
    import json

    parsed = json.loads(line)
    return parsed if isinstance(parsed, dict) else {}
