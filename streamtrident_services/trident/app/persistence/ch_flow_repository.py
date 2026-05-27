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
        src_ip: str | None = None,
        dst_ip: str | None = None,
        is_unknown: bool | None = None,
        time_from: str | None = None,
        time_to: str | None = None,
        limit: int = 100,
        offset: int | None = None,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        filters: list[str] = []
        if session_id:
            filters.append(f"session_id = {_quote(session_id)}")
        if window_index is not None:
            filters.append(f"window_index = {int(window_index)}")
        if learner_name:
            filters.append(f"assigned_learner = {_quote(learner_name)}")
        if src_ip:
            filters.append(f"src_ip = {_quote(src_ip)}")
        if dst_ip:
            filters.append(f"dst_ip = {_quote(dst_ip)}")
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
        safe_offset = max(0, int(offset or 0))
        offset_clause = f" OFFSET {safe_offset}" if offset is not None else ""
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
LIMIT {capped}{offset_clause}
FORMAT JSONEachRow
"""
        text = self.client.execute(sql)
        rows = [row for line in text.splitlines() if line.strip() for row in [_parse_json(line)]]
        total: int | None = None
        if offset is not None:
            total_text = self.client.execute(f"SELECT count() AS total FROM ch_flow FINAL {where} FORMAT JSONEachRow")
            total_rows = [_parse_json(line) for line in total_text.splitlines() if line.strip()]
            total = int(total_rows[0].get("total") or 0) if total_rows else 0
        return {
            "items": rows,
            "total": total,
            "limit": capped,
            "offset": safe_offset if offset is not None else None,
            "next_cursor": rows[-1]["flow_uid"] if rows else None,
        }

    def topology_graph(
        self,
        *,
        session_id: str,
        node_mode: str,
        risk_learners: list[str] | None = None,
        learner_name: str | None = None,
        subject_ip: str | None = None,
        traffic_kind: str = "combined",
        time_from: str | None = None,
        time_to: str | None = None,
        top_n: int = 50,
    ) -> dict[str, Any]:
        top_n = max(1, min(int(top_n), 500))
        risk_names = risk_learners or []
        abnormal = _abnormal_expr(risk_names)
        filters = [
            f"session_id = {_quote(session_id)}",
            _time_filter("event_time", time_from, time_to),
            f"assigned_learner = {_quote(learner_name)}" if learner_name else None,
            f"src_ip = {_quote(subject_ip)}" if subject_ip else None,
        ]
        if traffic_kind == "benign":
            filters.append(f"NOT ({abnormal})")
        elif traffic_kind == "attack":
            filters.append(abnormal)
        where = _where(filters)
        if node_mode == "endpoint":
            source_expr = "concat(src_ip, ':', toString(src_port))"
            target_expr = "concat(dst_ip, ':', toString(dst_port))"
        else:
            source_expr = "src_ip"
            target_expr = "dst_ip"
        is_benign_expr = f"NOT ({abnormal})"
        top_nodes_sql = f"""
    SELECT node
    FROM (
        SELECT {source_expr} AS node, count() AS c FROM ch_flow FINAL {where} GROUP BY node
        UNION ALL
        SELECT {target_expr} AS node, count() AS c FROM ch_flow FINAL {where} GROUP BY node
    )
    GROUP BY node
    ORDER BY sum(c) DESC, node ASC
    LIMIT {top_n}
"""
        edge_where = _where(
            [
                *filters,
                f"{source_expr} IN ({top_nodes_sql})",
                f"{target_expr} IN ({top_nodes_sql})",
            ]
        )
        sql = f"""
WITH edge_rows AS (
    SELECT
        {source_expr} AS source,
        {target_expr} AS target,
        count() AS value,
        min({is_benign_expr}) AS is_benign
    FROM ch_flow FINAL
    {edge_where}
    GROUP BY source, target
),
node_rows AS (
    SELECT node AS id, sum(c) AS flow_count
    FROM (
        SELECT {source_expr} AS node, count() AS c FROM ch_flow FINAL {where} GROUP BY node
        UNION ALL
        SELECT {target_expr} AS node, count() AS c FROM ch_flow FINAL {where} GROUP BY node
    )
    WHERE node IN ({top_nodes_sql})
    GROUP BY node
)
SELECT 'node' AS row_type, id, '' AS source, '' AS target, flow_count AS value, 0 AS is_benign
FROM node_rows
UNION ALL
SELECT 'edge' AS row_type, '' AS id, source, target, value, is_benign
FROM edge_rows
FORMAT JSONEachRow
"""
        text = self.client.execute(sql)
        rows = [_parse_json(line) for line in text.splitlines() if line.strip()]
        nodes = []
        links = []
        total = 0
        for row in rows:
            if row.get("row_type") == "node":
                node_id = str(row.get("id") or "")
                flow_count = int(row.get("value") or 0)
                total += flow_count
                nodes.append(_topology_node(node_id, flow_count, node_mode=node_mode))
            elif row.get("row_type") == "edge":
                links.append(
                    {
                        "source": str(row.get("source") or ""),
                        "target": str(row.get("target") or ""),
                        "value": int(row.get("value") or 0),
                        "is_benign": bool(int(row.get("is_benign") or 0)),
                    }
                )
        stats = self.topology_stats(
            session_id=session_id,
            risk_learners=risk_names,
            learner_name=learner_name,
            traffic_kind=traffic_kind,
            time_from=time_from,
            time_to=time_to,
        )
        return {
            "flow_count": sum(link["value"] for link in links) or total,
            "node_mode": node_mode,
            "nodes": nodes,
            "links": links,
            "stats": stats,
        }

    def topology_stats(
        self,
        *,
        session_id: str,
        risk_learners: list[str] | None = None,
        learner_name: str | None = None,
        subject_ip: str | None = None,
        traffic_kind: str = "combined",
        time_from: str | None = None,
        time_to: str | None = None,
    ) -> dict[str, Any]:
        risk_names = risk_learners or []
        abnormal = _abnormal_expr(risk_names)
        filters = [
            f"session_id = {_quote(session_id)}",
            _time_filter("event_time", time_from, time_to),
            f"assigned_learner = {_quote(learner_name)}" if learner_name else None,
            f"src_ip = {_quote(subject_ip)}" if subject_ip else None,
        ]
        if traffic_kind == "benign":
            filters.append(f"NOT ({abnormal})")
        elif traffic_kind == "attack":
            filters.append(abnormal)
        where = _where(filters)
        sql = f"""
WITH total AS (SELECT count() AS total_count FROM ch_flow FINAL {where}),
ports AS (
    SELECT dst_port, count() AS port_count
    FROM ch_flow FINAL
    {where}
    GROUP BY dst_port
    ORDER BY port_count DESC, dst_port ASC
    LIMIT 1
)
SELECT
    ifNull(any(ports.dst_port), 0) AS top_dst_port,
    if(total.total_count = 0, 0, ifNull(any(ports.port_count), 0) / total.total_count) AS top_dst_port_ratio
FROM total
LEFT JOIN ports ON 1 = 1
GROUP BY total.total_count
FORMAT JSONEachRow
"""
        text = self.client.execute(sql)
        rows = [_parse_json(line) for line in text.splitlines() if line.strip()]
        return rows[0] if rows else {"top_dst_port": 0, "top_dst_port_ratio": 0}

    def dashboard_summary(
        self,
        *,
        session_id: str,
        risk_learners: list[str],
        time_from: str | None = None,
        time_to: str | None = None,
    ) -> dict[str, Any]:
        where = _where(
            [
                f"session_id = {_quote(session_id)}",
                _time_filter("event_time", time_from, time_to),
            ]
        )
        abnormal = _abnormal_expr(risk_learners)
        sql = f"""
SELECT
    count() AS total_flows,
    uniqExact(protocol) AS protocol_count,
    countIf({abnormal}) AS risk_flows,
    countIf(NOT ({abnormal})) AS normal_flows,
    uniqExactIf(src_ip, {abnormal}) AS risk_ip_count,
    max(window_index) AS current_window_index
FROM ch_flow FINAL
{where}
FORMAT JSONEachRow
"""
        text = self.client.execute(sql)
        rows = [_parse_json(line) for line in text.splitlines() if line.strip()]
        return rows[0] if rows else {}

    def protocol_distribution(
        self,
        *,
        session_id: str,
        learner_name: str | None = None,
        src_ip: str | None = None,
        time_from: str | None = None,
        time_to: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        where = _where(
            [
                f"session_id = {_quote(session_id)}",
                f"assigned_learner = {_quote(learner_name)}" if learner_name else None,
                f"src_ip = {_quote(src_ip)}" if src_ip else None,
                _time_filter("event_time", time_from, time_to),
            ]
        )
        capped = max(1, min(int(limit), 1000))
        sql = f"""
SELECT protocol, count() AS value
FROM ch_flow FINAL
{where}
GROUP BY protocol
ORDER BY value DESC, protocol ASC
LIMIT {capped}
FORMAT JSONEachRow
"""
        text = self.client.execute(sql)
        return [row for line in text.splitlines() if line.strip() for row in [_parse_json(line)]]

    def top_subject_ip_counts_by_learner(
        self,
        *,
        session_id: str,
        learner_name: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        capped = max(1, min(int(limit), 1000))
        where = _where(
            [
                f"session_id = {_quote(session_id)}",
                f"assigned_learner = {_quote(learner_name)}",
            ]
        )
        sql = f"""
SELECT src_ip AS ip, count() AS triggerCount
FROM ch_flow FINAL
{where}
GROUP BY src_ip
ORDER BY triggerCount DESC, ip ASC
LIMIT {capped}
FORMAT JSONEachRow
"""
        text = self.client.execute(sql)
        return [row for line in text.splitlines() if line.strip() for row in [_parse_json(line)]]

    def top_subject_ips_by_learner(
        self,
        *,
        session_id: str,
        learner_names: list[str],
        limit_per_learner: int = 5,
    ) -> dict[str, list[str]]:
        if not learner_names:
            return {}
        where = _where(
            [
                f"session_id = {_quote(session_id)}",
                _in_filter("assigned_learner", learner_names),
            ]
        )
        capped = max(1, min(int(limit_per_learner), 20))
        sql = f"""
SELECT assigned_learner, src_ip, count() AS flow_count
FROM ch_flow FINAL
{where}
GROUP BY assigned_learner, src_ip
ORDER BY assigned_learner ASC, flow_count DESC, src_ip ASC
LIMIT {capped} BY assigned_learner
FORMAT JSONEachRow
"""
        text = self.client.execute(sql)
        result: dict[str, list[str]] = {}
        for line in text.splitlines():
            if not line.strip():
                continue
            row = _parse_json(line)
            learner = str(row.get("assigned_learner") or "")
            src_ip = str(row.get("src_ip") or "")
            if learner and src_ip:
                result.setdefault(learner, []).append(src_ip)
        return result

    def risk_ip_view(
        self,
        *,
        session_id: str,
        risk_learners: list[str],
        limit: int = 10,
        offset: int = 0,
        learner_name_like: str | None = None,
        subject_ip_like: str | None = None,
        trigger_time_prefix: str | None = None,
    ) -> dict[str, Any]:
        abnormal = _abnormal_expr(risk_learners)
        filters = [
            f"session_id = {_quote(session_id)}",
            abnormal,
            _contains_filter("assigned_learner", learner_name_like),
            _contains_filter("src_ip", subject_ip_like),
            _prefix_filter("toString(event_time)", trigger_time_prefix),
        ]
        where = _where(filters)
        capped = max(1, min(int(limit), 1000))
        safe_offset = max(0, int(offset))
        total_sql = f"""
SELECT count() AS total
FROM (
    SELECT src_ip, assigned_learner
    FROM ch_flow FINAL
    {where}
    GROUP BY src_ip, assigned_learner
)
FORMAT JSONEachRow
"""
        total_text = self.client.execute(total_sql)
        total_rows = [_parse_json(line) for line in total_text.splitlines() if line.strip()]
        total = int(total_rows[0].get("total") or 0) if total_rows else 0
        sql = f"""
SELECT
    src_ip AS subject_ip,
    assigned_learner,
    max(event_time) AS trigger_time,
    count() AS flow_count,
    sum(is_unknown) AS unknown_count,
    any(dst_ip) AS top_dst_ip,
    any(dst_port) AS top_dst_port,
    any(protocol) AS top_protocol
FROM ch_flow FINAL
{where}
GROUP BY src_ip, assigned_learner
ORDER BY trigger_time DESC, flow_count DESC, subject_ip ASC
LIMIT {capped} OFFSET {safe_offset}
FORMAT JSONEachRow
"""
        text = self.client.execute(sql)
        return {
            "items": [row for line in text.splitlines() if line.strip() for row in [_parse_json(line)]],
            "total": total,
        }

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


def _where(filters: list[str | None]) -> str:
    active = [item for item in filters if item]
    return f"WHERE {' AND '.join(active)}" if active else ""


def _time_filter(column: str, time_from: str | None, time_to: str | None) -> str | None:
    parts: list[str] = []
    if time_from:
        parts.append(f"{column} >= parseDateTime64BestEffort({_quote(time_from)}, 3)")
    if time_to:
        parts.append(f"{column} <= parseDateTime64BestEffort({_quote(time_to)}, 3)")
    return " AND ".join(parts) if parts else None


def _in_filter(column: str, values: list[str]) -> str | None:
    clean = [value for value in values if value]
    if not clean:
        return None
    return f"{column} IN ({', '.join(_quote(value) for value in clean)})"


def _contains_filter(column: str, value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    return f"positionCaseInsensitive({column}, {_quote(text)}) > 0"


def _prefix_filter(expression: str, value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    return f"startsWith({expression}, {_quote(text)})"


def _abnormal_expr(risk_learners: list[str]) -> str:
    risk_filter = _in_filter("assigned_learner", risk_learners)
    if risk_filter:
        return f"(is_unknown = 1 OR {risk_filter})"
    return "(is_unknown = 1)"


def _topology_node(node_id: str, flow_count: int, *, node_mode: str) -> dict[str, Any]:
    ip = node_id
    port: int | None = None
    if node_mode == "endpoint" and ":" in node_id:
        ip, port_text = node_id.rsplit(":", 1)
        try:
            port = int(port_text)
        except ValueError:
            port = None
    return {
        "id": node_id,
        "ip": ip,
        "port": port,
        "flow_count": flow_count,
        "is_internal": _is_internal_ip(ip),
    }


def _is_internal_ip(ip: str) -> bool:
    return (
        ip.startswith("10.")
        or ip.startswith("192.168.")
        or ip.startswith("172.16.")
        or ip.startswith("172.17.")
        or ip.startswith("172.18.")
        or ip.startswith("172.19.")
        or ip.startswith("172.2")
        or ip.startswith("172.30.")
        or ip.startswith("172.31.")
    )
