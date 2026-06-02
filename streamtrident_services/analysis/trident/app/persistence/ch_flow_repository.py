from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..flow_loader import FlowRecord
from ..protocol_utils import main_protocol_sql as _main_protocol_sql
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
    def __init__(self, dsn: str, *, display_timezone: str | None = None) -> None:
        from ..timezone_utils import display_timezone_name

        self.client = ClickHouseHTTPClient(
            dsn,
            session_timezone=display_timezone_name(display_timezone),
        )

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
    app_proto,
    total_bytes,
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
FROM ch_flow
{where}
ORDER BY event_time DESC, flow_uid ASC
LIMIT {capped}{offset_clause}
FORMAT JSONEachRow
"""
        text = self.client.execute(sql)
        rows = [row for line in text.splitlines() if line.strip() for row in [_parse_json(line)]]
        total: int | None = None
        if offset is not None:
            total_text = self.client.execute(f"SELECT count() AS total FROM ch_flow {where} FORMAT JSONEachRow")
            total_rows = [_parse_json(line) for line in total_text.splitlines() if line.strip()]
            total = int(total_rows[0].get("total") or 0) if total_rows else 0
        return {
            "items": rows,
            "total": total,
            "limit": capped,
            "offset": safe_offset if offset is not None else None,
            "next_cursor": rows[-1]["flow_uid"] if rows else None,
        }

    def get_flow_detail(self, *, session_id: str, flow_uid: str) -> dict[str, Any] | None:
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
    app_proto,
    total_bytes,
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
    payload_sample_b64,
    payload_sample_bytes,
    payload_original_bytes,
    payload_truncated,
    payload_direction,
    record_version,
    record_stage
FROM ch_flow
WHERE session_id = {_quote(session_id)} AND flow_uid = {_quote(flow_uid)}
ORDER BY record_version DESC
LIMIT 1
FORMAT JSONEachRow
"""
        text = self.client.execute(sql)
        rows = [_parse_json(line) for line in text.splitlines() if line.strip()]
        return rows[0] if rows else None

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
        top_n: int = 8,
        edges_per_victim: int = 10,
        include_stats: bool = True,
        approximate_stats: bool = True,
    ) -> dict[str, Any]:
        top_victims = max(1, min(int(top_n), 500))
        per_victim = max(1, min(int(edges_per_victim), 100))
        risk_names = risk_learners or []
        if node_mode == "endpoint":
            host_graph = self._topology_host_graph(
                session_id=session_id,
                risk_learners=risk_names,
                learner_name=learner_name,
                subject_ip=subject_ip,
                traffic_kind=traffic_kind,
                time_from=time_from,
                time_to=time_to,
                top_victims=top_victims,
                edges_per_victim=per_victim,
                include_stats=include_stats,
                approximate_stats=approximate_stats,
            )
            graph = self._topology_endpoint_graph_from_host_edges(
                host_graph=host_graph,
                session_id=session_id,
                risk_learners=risk_names,
                learner_name=learner_name,
                subject_ip=subject_ip,
                traffic_kind=traffic_kind,
                time_from=time_from,
                time_to=time_to,
                top_victims=top_victims,
                edges_per_victim=per_victim,
            )
            if include_stats:
                endpoint_stats = dict(graph.get("stats") or {})
                graph["stats"] = dict(host_graph.get("stats") or endpoint_stats)
                graph["stats"]["displayed_victim_count"] = int(
                    endpoint_stats.get("displayed_victim_count") or 0
                )
                graph["stats"]["edges_per_victim"] = per_victim
                graph["stats"]["top_victims_limit"] = top_victims
                total_flow_count = int(host_graph.get("flow_count") or 0)
                if total_flow_count:
                    graph["flow_count"] = total_flow_count
                    graph["total_flow_count"] = total_flow_count
                    graph["stats"]["total_flow_count"] = total_flow_count
            return graph
        return self._topology_host_graph(
            session_id=session_id,
            risk_learners=risk_names,
            learner_name=learner_name,
            subject_ip=subject_ip,
            traffic_kind=traffic_kind,
            time_from=time_from,
            time_to=time_to,
            top_victims=top_victims,
            edges_per_victim=per_victim,
            include_stats=include_stats,
            approximate_stats=approximate_stats,
        )

    def topology_graph_pair(
        self,
        *,
        session_id: str,
        risk_learners: list[str] | None = None,
        learner_name: str | None = None,
        subject_ip: str | None = None,
        traffic_kind: str = "combined",
        time_from: str | None = None,
        time_to: str | None = None,
        top_n: int = 8,
        edges_per_victim: int = 10,
        include_stats: bool = True,
        approximate_stats: bool = True,
    ) -> dict[str, dict[str, Any]]:
        top_victims = max(1, min(int(top_n), 500))
        per_victim = max(1, min(int(edges_per_victim), 100))
        risk_names = risk_learners or []
        host_graph = self._topology_host_graph(
            session_id=session_id,
            risk_learners=risk_names,
            learner_name=learner_name,
            subject_ip=subject_ip,
            traffic_kind=traffic_kind,
            time_from=time_from,
            time_to=time_to,
            top_victims=top_victims,
            edges_per_victim=per_victim,
            include_stats=include_stats,
            approximate_stats=approximate_stats,
        )
        endpoint_graph = self._topology_endpoint_graph_from_host_edges(
            host_graph=host_graph,
            session_id=session_id,
            risk_learners=risk_names,
            learner_name=learner_name,
            subject_ip=subject_ip,
            traffic_kind=traffic_kind,
            time_from=time_from,
            time_to=time_to,
            top_victims=top_victims,
            edges_per_victim=per_victim,
        )
        if include_stats:
            endpoint_stats = dict(endpoint_graph.get("stats") or {})
            endpoint_graph["stats"] = dict(host_graph.get("stats") or endpoint_stats)
            endpoint_graph["stats"]["displayed_victim_count"] = int(
                endpoint_stats.get("displayed_victim_count") or 0
            )
            endpoint_graph["stats"]["edges_per_victim"] = per_victim
            endpoint_graph["stats"]["top_victims_limit"] = top_victims
            total_flow_count = int(host_graph.get("flow_count") or 0)
            if total_flow_count:
                endpoint_graph["flow_count"] = total_flow_count
                endpoint_graph["total_flow_count"] = total_flow_count
                endpoint_graph["stats"]["total_flow_count"] = total_flow_count
        return {"host": host_graph, "endpoint": endpoint_graph}

    def _topology_host_graph(
        self,
        *,
        session_id: str,
        risk_learners: list[str],
        learner_name: str | None,
        subject_ip: str | None,
        traffic_kind: str,
        time_from: str | None,
        time_to: str | None,
        top_victims: int,
        edges_per_victim: int,
        include_stats: bool,
        approximate_stats: bool,
    ) -> dict[str, Any]:
        abnormal = _abnormal_expr(risk_learners)
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
        is_benign_expr = f"NOT ({abnormal})"
        main_protocol = _main_protocol_sql()
        victim_sql = f"""
WITH victim_counts AS (
    SELECT
        dst_ip AS victim,
        count() AS victim_flow_count
    FROM ch_flow
    {where}
    GROUP BY victim
),
victim_rows AS (
    SELECT victim, victim_flow_count
    FROM victim_counts
    ORDER BY victim_flow_count DESC, victim ASC
    LIMIT {top_victims}
)
SELECT 'victim' AS row_type, victim, victim_flow_count
FROM victim_rows
UNION ALL
SELECT 'stat' AS row_type, '' AS victim, sum(victim_flow_count) AS victim_flow_count
FROM victim_counts
FORMAT JSONEachRow
"""
        victim_text = self.client.execute(victim_sql)
        victims: list[str] = []
        stat_rows: list[dict[str, Any]] = []
        for line in victim_text.splitlines():
            if not line.strip():
                continue
            row = _parse_json(line)
            if row.get("row_type") == "victim":
                victim = str(row.get("victim") or "")
                if victim:
                    victims.append(victim)
            elif row.get("row_type") == "stat":
                stat_rows.append(
                    {
                        "row_type": "stat",
                        "id": "",
                        "source": "",
                        "target": "",
                        "value": int(row.get("victim_flow_count") or 0),
                        "out_flow_count": 0,
                        "in_flow_count": 0,
                        "is_benign": 0,
                        "protocol": "",
                    }
                )
        if not victims:
            graph = _build_topology_graph_from_rows(
                stat_rows,
                node_mode="host",
                top_victims=top_victims,
                edges_per_victim=edges_per_victim,
            )
            return graph
        edge_where = _where([*filters, _in_filter("dst_ip", victims)])
        sql = f"""
WITH edge_source AS (
    SELECT
        src_ip AS source,
        dst_ip AS target,
        {is_benign_expr} AS is_benign,
        {main_protocol} AS main_protocol
    FROM ch_flow
    {edge_where}
),
edge_agg AS (
    SELECT
        source,
        target,
        count() AS value,
        min(is_benign) AS is_benign,
        topK(1)(main_protocol)[1] AS protocol
    FROM edge_source
    GROUP BY source, target
),
ranked_edges AS (
    SELECT
        source,
        target,
        value,
        is_benign,
        protocol,
        row_number() OVER (PARTITION BY target ORDER BY value DESC, source ASC) AS edge_rank
    FROM edge_agg
),
edge_rows AS (
    SELECT source, target, value, is_benign, protocol
    FROM ranked_edges
    WHERE edge_rank <= {edges_per_victim}
),
node_protocol_rows AS (
    SELECT node, topK(1)(edge_protocol)[1] AS protocol
    FROM (
        SELECT source AS node, protocol AS edge_protocol
        FROM edge_rows
        UNION ALL
        SELECT target AS node, protocol AS edge_protocol
        FROM edge_rows
    )
    GROUP BY node
),
node_rows AS (
    SELECT
        node AS id,
        sum(out_count) AS out_flow_count,
        sum(in_count) AS in_flow_count,
        sum(out_count) + sum(in_count) AS flow_count
    FROM (
        SELECT source AS node, value AS out_count, 0 AS in_count FROM edge_rows
        UNION ALL
        SELECT target AS node, 0 AS out_count, value AS in_count FROM edge_rows
    )
    GROUP BY node
)
SELECT 'node' AS row_type, nr.id, '' AS source, '' AS target, nr.flow_count AS value, nr.out_flow_count, nr.in_flow_count, 0 AS is_benign, ifNull(npr.protocol, '') AS protocol
FROM node_rows nr
LEFT JOIN node_protocol_rows npr ON nr.id = npr.node
UNION ALL
SELECT 'edge' AS row_type, '' AS id, source, target, value, 0 AS out_flow_count, 0 AS in_flow_count, is_benign, ifNull(protocol, '') AS protocol
FROM edge_rows
FORMAT JSONEachRow
"""
        text = self.client.execute(sql)
        rows = [*stat_rows, *[_parse_json(line) for line in text.splitlines() if line.strip()]]
        graph = _build_topology_graph_from_rows(
            rows,
            node_mode="host",
            top_victims=top_victims,
            edges_per_victim=edges_per_victim,
        )
        if include_stats:
            stats = self.topology_stats(
                session_id=session_id,
                risk_learners=risk_learners,
                learner_name=learner_name,
                subject_ip=subject_ip,
                traffic_kind=traffic_kind,
                time_from=time_from,
                time_to=time_to,
                approximate=approximate_stats,
            )
            stats["displayed_victim_count"] = graph["stats"]["displayed_victim_count"]
            stats["edges_per_victim"] = edges_per_victim
            stats["top_victims_limit"] = top_victims
            graph["stats"] = stats
            total_flow_count = int(stats.get("total_flow_count") or 0)
            if total_flow_count:
                graph["flow_count"] = total_flow_count
                graph["total_flow_count"] = total_flow_count
        return graph

    def _topology_endpoint_graph_from_host_edges(
        self,
        *,
        host_graph: dict[str, Any],
        session_id: str,
        risk_learners: list[str],
        learner_name: str | None,
        subject_ip: str | None,
        traffic_kind: str,
        time_from: str | None,
        time_to: str | None,
        top_victims: int,
        edges_per_victim: int,
    ) -> dict[str, Any]:
        pairs = _host_pairs_from_graph(host_graph)
        if not pairs:
            return _empty_topology_graph_from_graph(host_graph, "endpoint")
        abnormal = _abnormal_expr(risk_learners)
        filters = [
            f"session_id = {_quote(session_id)}",
            _target_source_pair_filter("dst_ip", "src_ip", pairs),
            _time_filter("event_time", time_from, time_to),
            f"assigned_learner = {_quote(learner_name)}" if learner_name else None,
            f"src_ip = {_quote(subject_ip)}" if subject_ip else None,
        ]
        if traffic_kind == "benign":
            filters.append(f"NOT ({abnormal})")
        elif traffic_kind == "attack":
            filters.append(abnormal)
        where = _where(filters)
        is_benign_expr = f"NOT ({abnormal})"
        main_protocol = _main_protocol_sql()
        stat_row = _stat_row_from_graph("", host_graph)
        sql = f"""
WITH edge_source AS (
    SELECT
        src_ip AS source_host,
        dst_ip AS target_host,
        src_ip AS source,
        concat(dst_ip, ':', toString(dst_port)) AS target,
        {is_benign_expr} AS is_benign,
        {main_protocol} AS main_protocol
    FROM ch_flow
    {where}
),
edge_agg AS (
    SELECT
        source_host,
        target_host,
        source,
        target,
        count() AS value,
        min(is_benign) AS is_benign,
        topK(1)(main_protocol)[1] AS protocol
    FROM edge_source
    GROUP BY source_host, target_host, source, target
),
ranked_edges AS (
    SELECT
        source_host,
        target_host,
        source,
        target,
        value,
        is_benign,
        protocol,
        row_number() OVER (
            PARTITION BY source_host, target_host
            ORDER BY value DESC, source ASC, target ASC
        ) AS edge_rank
    FROM edge_agg
),
edge_rows AS (
    SELECT source, target, value, is_benign, protocol
    FROM ranked_edges
    WHERE edge_rank <= {edges_per_victim}
),
node_protocol_rows AS (
    SELECT node, topK(1)(edge_protocol)[1] AS protocol
    FROM (
        SELECT source AS node, protocol AS edge_protocol
        FROM edge_rows
        UNION ALL
        SELECT target AS node, protocol AS edge_protocol
        FROM edge_rows
    )
    GROUP BY node
),
node_rows AS (
    SELECT
        node AS id,
        sum(out_count) AS out_flow_count,
        sum(in_count) AS in_flow_count,
        sum(out_count) + sum(in_count) AS flow_count
    FROM (
        SELECT source AS node, value AS out_count, 0 AS in_count FROM edge_rows
        UNION ALL
        SELECT target AS node, 0 AS out_count, value AS in_count FROM edge_rows
    )
    GROUP BY node
)
SELECT 'node' AS row_type, nr.id, '' AS source, '' AS target, nr.flow_count AS value, nr.out_flow_count, nr.in_flow_count, 0 AS is_benign, ifNull(npr.protocol, '') AS protocol
FROM node_rows nr
LEFT JOIN node_protocol_rows npr ON nr.id = npr.node
UNION ALL
SELECT 'edge' AS row_type, '' AS id, source, target, value, 0 AS out_flow_count, 0 AS in_flow_count, is_benign, ifNull(protocol, '') AS protocol
FROM edge_rows
FORMAT JSONEachRow
"""
        text = self.client.execute(sql)
        rows = [stat_row, *[_parse_json(line) for line in text.splitlines() if line.strip()]]
        return _build_topology_graph_from_rows(
            rows,
            node_mode="endpoint",
            top_victims=top_victims,
            edges_per_victim=edges_per_victim,
        )

    def dashboard_topology_graphs(
        self,
        *,
        session_id: str,
        node_mode: str,
        risk_learners: list[str] | None = None,
        time_from: str | None = None,
        time_to: str | None = None,
        main_top_n: int = 50,
        compact_top_n: int = 8,
        main_edges_per_victim: int = 15,
        compact_edges_per_victim: int = 13,
    ) -> dict[str, dict[str, Any]]:
        main_top_victims = max(1, min(int(main_top_n), 500))
        compact_top_victims = max(1, min(int(compact_top_n), 500))
        main_per_victim = max(1, min(int(main_edges_per_victim), 100))
        compact_per_victim = max(1, min(int(compact_edges_per_victim), 100))
        risk_names = risk_learners or []
        abnormal = _abnormal_expr(risk_names)
        where = _where(
            [
                f"session_id = {_quote(session_id)}",
                _time_filter("event_time", time_from, time_to),
            ]
        )
        if node_mode == "endpoint":
            source_expr = "concat(src_ip, ':', toString(src_port))"
            target_expr = "concat(dst_ip, ':', toString(dst_port))"
        else:
            source_expr = "src_ip"
            target_expr = "dst_ip"
        is_benign_expr = f"NOT ({abnormal})"
        main_protocol = _main_protocol_sql()
        if node_mode == "endpoint":
            return self._dashboard_endpoint_topology_from_host_edges(
                session_id=session_id,
                risk_learners=risk_names,
                time_from=time_from,
                time_to=time_to,
                main_top_n=main_top_victims,
                compact_top_n=compact_top_victims,
                main_edges_per_victim=main_per_victim,
                compact_edges_per_victim=compact_per_victim,
            )
        victim_sql = f"""
WITH victim_counts AS (
    SELECT
        topology_kind,
        {target_expr} AS victim,
        count() AS victim_flow_count
    FROM ch_flow
    ARRAY JOIN if({abnormal}, ['combined', 'attack'], ['combined', 'benign']) AS topology_kind
    {where}
    GROUP BY topology_kind, victim
),
victim_rows AS (
    SELECT topology_kind, victim, victim_flow_count
    FROM (
        SELECT
            topology_kind,
            victim,
            victim_flow_count,
            row_number() OVER (PARTITION BY topology_kind ORDER BY victim_flow_count DESC, victim ASC) AS victim_rank
        FROM victim_counts
    )
    WHERE victim_rank <= if(topology_kind = 'combined', {main_top_victims}, {compact_top_victims})
)
SELECT 'victim' AS row_type, topology_kind, victim, victim_flow_count
FROM victim_rows
UNION ALL
SELECT 'stat' AS row_type, topology_kind, '' AS victim, sum(victim_flow_count) AS victim_flow_count
FROM victim_counts
GROUP BY topology_kind
FORMAT JSONEachRow
"""
        victim_text = self.client.execute(victim_sql)
        victims_by_kind: dict[str, list[str]] = {"combined": [], "benign": [], "attack": []}
        stat_rows: list[dict[str, Any]] = []
        for line in victim_text.splitlines():
            if not line.strip():
                continue
            row = _parse_json(line)
            kind = str(row.get("topology_kind") or "")
            if kind not in victims_by_kind:
                continue
            if row.get("row_type") == "victim":
                victim = str(row.get("victim") or "")
                if victim:
                    victims_by_kind[kind].append(victim)
            elif row.get("row_type") == "stat":
                stat_rows.append(
                    {
                        "row_type": "stat",
                        "topology_kind": kind,
                        "id": "",
                        "source": "",
                        "target": "",
                        "value": int(row.get("victim_flow_count") or 0),
                        "out_flow_count": 0,
                        "in_flow_count": 0,
                        "is_benign": 0,
                        "protocol": "",
                    }
                )
        combined_targets = victims_by_kind["combined"]
        benign_targets = victims_by_kind["benign"]
        attack_targets = victims_by_kind["attack"]
        all_targets = sorted({*combined_targets, *benign_targets, *attack_targets})
        if not all_targets:
            return {
                "combined": _build_topology_graph_from_rows(
                    [row for row in stat_rows if row.get("topology_kind") == "combined"],
                    node_mode=node_mode,
                    top_victims=main_top_victims,
                    edges_per_victim=main_per_victim,
                ),
                "benign": _build_topology_graph_from_rows(
                    [row for row in stat_rows if row.get("topology_kind") == "benign"],
                    node_mode=node_mode,
                    top_victims=compact_top_victims,
                    edges_per_victim=compact_per_victim,
                ),
                "attack": _build_topology_graph_from_rows(
                    [row for row in stat_rows if row.get("topology_kind") == "attack"],
                    node_mode=node_mode,
                    top_victims=compact_top_victims,
                    edges_per_victim=compact_per_victim,
                ),
            }
        combined_filter = _in_filter("target", combined_targets) or "0"
        benign_filter = _in_filter("target", benign_targets) or "0"
        attack_filter = _in_filter("target", attack_targets) or "0"
        edge_where = _where(
            [
                f"session_id = {_quote(session_id)}",
                _time_filter("event_time", time_from, time_to),
                _endpoint_target_filter(all_targets) if node_mode == "endpoint" else _in_filter(target_expr, all_targets),
            ]
        )
        sql = f"""
WITH edge_source AS (
    SELECT
        {source_expr} AS source,
        {target_expr} AS target,
        {abnormal} AS is_attack,
        {main_protocol} AS main_protocol
    FROM ch_flow
    {edge_where}
),
edge_agg AS (
    SELECT
        source,
        target,
        countIf({combined_filter}) AS combined_value,
        countIf({benign_filter} AND NOT is_attack) AS benign_value,
        countIf({attack_filter} AND is_attack) AS attack_value,
        topKIf(1)(main_protocol, {combined_filter})[1] AS combined_protocol,
        topKIf(1)(main_protocol, {benign_filter} AND NOT is_attack)[1] AS benign_protocol,
        topKIf(1)(main_protocol, {attack_filter} AND is_attack)[1] AS attack_protocol
    FROM edge_source
    GROUP BY source, target
),
expanded_edges AS (
    SELECT
        tupleElement(kind_row, 1) AS topology_kind,
        source,
        target,
        tupleElement(kind_row, 2) AS value,
        tupleElement(kind_row, 3) AS is_benign,
        tupleElement(kind_row, 4) AS protocol
    FROM edge_agg
    ARRAY JOIN [
        ('combined', combined_value, 0, combined_protocol),
        ('benign', benign_value, 1, benign_protocol),
        ('attack', attack_value, 0, attack_protocol)
    ] AS kind_row
    WHERE value > 0
),
ranked_edges AS (
    SELECT
        topology_kind,
        source,
        target,
        value,
        is_benign,
        protocol,
        row_number() OVER (PARTITION BY topology_kind, target ORDER BY value DESC, source ASC) AS edge_rank
    FROM expanded_edges
),
edge_rows AS (
    SELECT topology_kind, source, target, value, is_benign, protocol
    FROM ranked_edges
    WHERE edge_rank <= if(topology_kind = 'combined', {main_per_victim}, {compact_per_victim})
),
node_protocol_rows AS (
    SELECT topology_kind, node, topK(1)(edge_protocol)[1] AS protocol
    FROM (
        SELECT topology_kind, source AS node, protocol AS edge_protocol
        FROM edge_rows
        UNION ALL
        SELECT topology_kind, target AS node, protocol AS edge_protocol
        FROM edge_rows
    )
    GROUP BY topology_kind, node
),
node_rows AS (
    SELECT
        topology_kind,
        node AS id,
        sum(out_count) AS out_flow_count,
        sum(in_count) AS in_flow_count,
        sum(out_count) + sum(in_count) AS flow_count
    FROM (
        SELECT topology_kind, source AS node, value AS out_count, 0 AS in_count FROM edge_rows
        UNION ALL
        SELECT topology_kind, target AS node, 0 AS out_count, value AS in_count FROM edge_rows
    )
    GROUP BY topology_kind, node
)
SELECT 'node' AS row_type, nr.topology_kind AS topology_kind, nr.id, '' AS source, '' AS target, nr.flow_count AS value, nr.out_flow_count, nr.in_flow_count, 0 AS is_benign, ifNull(npr.protocol, '') AS protocol
FROM node_rows nr
LEFT JOIN node_protocol_rows npr ON nr.topology_kind = npr.topology_kind AND nr.id = npr.node
UNION ALL
SELECT 'edge' AS row_type, topology_kind, '' AS id, source, target, value, 0 AS out_flow_count, 0 AS in_flow_count, is_benign, ifNull(protocol, '') AS protocol
FROM edge_rows
FORMAT JSONEachRow
"""
        text = self.client.execute(sql)
        rows_by_kind: dict[str, list[dict[str, Any]]] = {"combined": [], "benign": [], "attack": []}
        for row in stat_rows:
            kind = str(row.get("topology_kind") or "")
            if kind in rows_by_kind:
                rows_by_kind[kind].append(row)
        for line in text.splitlines():
            if not line.strip():
                continue
            row = _parse_json(line)
            kind = str(row.get("topology_kind") or "")
            if kind in rows_by_kind:
                rows_by_kind[kind].append(row)
        return {
            "combined": _build_topology_graph_from_rows(
                rows_by_kind["combined"],
                node_mode=node_mode,
                top_victims=main_top_victims,
                edges_per_victim=main_per_victim,
            ),
            "benign": _build_topology_graph_from_rows(
                rows_by_kind["benign"],
                node_mode=node_mode,
                top_victims=compact_top_victims,
                edges_per_victim=compact_per_victim,
            ),
            "attack": _build_topology_graph_from_rows(
                rows_by_kind["attack"],
                node_mode=node_mode,
                top_victims=compact_top_victims,
                edges_per_victim=compact_per_victim,
            ),
        }

    def _dashboard_endpoint_topology_from_host_edges(
        self,
        *,
        session_id: str,
        risk_learners: list[str],
        time_from: str | None,
        time_to: str | None,
        main_top_n: int,
        compact_top_n: int,
        main_edges_per_victim: int,
        compact_edges_per_victim: int,
    ) -> dict[str, dict[str, Any]]:
        host_graphs = self.dashboard_topology_graphs(
            session_id=session_id,
            node_mode="host",
            risk_learners=risk_learners,
            time_from=time_from,
            time_to=time_to,
            main_top_n=main_top_n,
            compact_top_n=compact_top_n,
            main_edges_per_victim=main_edges_per_victim,
            compact_edges_per_victim=compact_edges_per_victim,
        )
        pairs_by_kind: dict[str, list[tuple[str, str]]] = {
            "combined": _host_pairs_from_graph(host_graphs["combined"]),
            "benign": _host_pairs_from_graph(host_graphs["benign"]),
            "attack": _host_pairs_from_graph(host_graphs["attack"]),
        }
        all_pairs = sorted({pair for pairs in pairs_by_kind.values() for pair in pairs})
        if not all_pairs:
            return {
                "combined": _empty_topology_graph_from_graph(host_graphs["combined"], "endpoint"),
                "benign": _empty_topology_graph_from_graph(host_graphs["benign"], "endpoint"),
                "attack": _empty_topology_graph_from_graph(host_graphs["attack"], "endpoint"),
            }

        abnormal = _abnormal_expr(risk_learners)
        main_protocol = _main_protocol_sql()
        source_expr = "src_ip"
        target_expr = "concat(dst_ip, ':', toString(dst_port))"
        combined_filter = _host_pair_filter("source_host", "target_host", pairs_by_kind["combined"]) or "0"
        benign_filter = _host_pair_filter("source_host", "target_host", pairs_by_kind["benign"]) or "0"
        attack_filter = _host_pair_filter("source_host", "target_host", pairs_by_kind["attack"]) or "0"
        edge_where = _where(
            [
                f"session_id = {_quote(session_id)}",
                _target_source_pair_filter("dst_ip", "src_ip", all_pairs),
                _time_filter("event_time", time_from, time_to),
            ]
        )
        # Endpoint topology is a drill-down of the displayed host edges. Keep the
        # destination service port, but aggregate client-side ephemeral ports into
        # the source host so high-cardinality ports cannot explode the overview graph.
        main_per_host_edge = main_edges_per_victim
        compact_per_host_edge = compact_edges_per_victim
        sql = f"""
WITH edge_source AS (
    SELECT
        src_ip AS source_host,
        dst_ip AS target_host,
        {source_expr} AS source,
        {target_expr} AS target,
        {abnormal} AS is_attack,
        {main_protocol} AS main_protocol
    FROM ch_flow
    {edge_where}
),
edge_agg AS (
    SELECT
        source_host,
        target_host,
        source,
        target,
        countIf({combined_filter}) AS combined_value,
        countIf({benign_filter} AND NOT is_attack) AS benign_value,
        countIf({attack_filter} AND is_attack) AS attack_value,
        topKIf(1)(main_protocol, {combined_filter})[1] AS combined_protocol,
        topKIf(1)(main_protocol, {benign_filter} AND NOT is_attack)[1] AS benign_protocol,
        topKIf(1)(main_protocol, {attack_filter} AND is_attack)[1] AS attack_protocol
    FROM edge_source
    GROUP BY source_host, target_host, source, target
),
expanded_edges AS (
    SELECT
        tupleElement(kind_row, 1) AS topology_kind,
        source_host,
        target_host,
        source,
        target,
        tupleElement(kind_row, 2) AS value,
        tupleElement(kind_row, 3) AS is_benign,
        tupleElement(kind_row, 4) AS protocol
    FROM edge_agg
    ARRAY JOIN [
        ('combined', combined_value, 0, combined_protocol),
        ('benign', benign_value, 1, benign_protocol),
        ('attack', attack_value, 0, attack_protocol)
    ] AS kind_row
    WHERE value > 0
),
ranked_edges AS (
    SELECT
        topology_kind,
        source_host,
        target_host,
        source,
        target,
        value,
        is_benign,
        protocol,
        row_number() OVER (
            PARTITION BY topology_kind, source_host, target_host
            ORDER BY value DESC, source ASC, target ASC
        ) AS edge_rank
    FROM expanded_edges
),
edge_rows AS (
    SELECT topology_kind, source, target, value, is_benign, protocol
    FROM ranked_edges
    WHERE edge_rank <= if(topology_kind = 'combined', {main_per_host_edge}, {compact_per_host_edge})
),
node_protocol_rows AS (
    SELECT topology_kind, node, topK(1)(edge_protocol)[1] AS protocol
    FROM (
        SELECT topology_kind, source AS node, protocol AS edge_protocol
        FROM edge_rows
        UNION ALL
        SELECT topology_kind, target AS node, protocol AS edge_protocol
        FROM edge_rows
    )
    GROUP BY topology_kind, node
),
node_rows AS (
    SELECT
        topology_kind,
        node AS id,
        sum(out_count) AS out_flow_count,
        sum(in_count) AS in_flow_count,
        sum(out_count) + sum(in_count) AS flow_count
    FROM (
        SELECT topology_kind, source AS node, value AS out_count, 0 AS in_count FROM edge_rows
        UNION ALL
        SELECT topology_kind, target AS node, 0 AS out_count, value AS in_count FROM edge_rows
    )
    GROUP BY topology_kind, node
)
SELECT 'node' AS row_type, nr.topology_kind AS topology_kind, nr.id, '' AS source, '' AS target, nr.flow_count AS value, nr.out_flow_count, nr.in_flow_count, 0 AS is_benign, ifNull(npr.protocol, '') AS protocol
FROM node_rows nr
LEFT JOIN node_protocol_rows npr ON nr.topology_kind = npr.topology_kind AND nr.id = npr.node
UNION ALL
SELECT 'edge' AS row_type, topology_kind, '' AS id, source, target, value, 0 AS out_flow_count, 0 AS in_flow_count, is_benign, ifNull(protocol, '') AS protocol
FROM edge_rows
FORMAT JSONEachRow
"""
        text = self.client.execute(sql)
        rows_by_kind: dict[str, list[dict[str, Any]]] = {
            kind: [_stat_row_from_graph(kind, graph)]
            for kind, graph in host_graphs.items()
        }
        for line in text.splitlines():
            if not line.strip():
                continue
            row = _parse_json(line)
            kind = str(row.get("topology_kind") or "")
            if kind in rows_by_kind:
                rows_by_kind[kind].append(row)
        return {
            "combined": _build_topology_graph_from_rows(
                rows_by_kind["combined"],
                node_mode="endpoint",
                top_victims=main_top_n,
                edges_per_victim=main_per_host_edge,
            ),
            "benign": _build_topology_graph_from_rows(
                rows_by_kind["benign"],
                node_mode="endpoint",
                top_victims=compact_top_n,
                edges_per_victim=compact_per_host_edge,
            ),
            "attack": _build_topology_graph_from_rows(
                rows_by_kind["attack"],
                node_mode="endpoint",
                top_victims=compact_top_n,
                edges_per_victim=compact_per_host_edge,
            ),
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
        approximate: bool = True,
    ) -> dict[str, Any]:
        risk_names = risk_learners or []
        abnormal = _abnormal_expr(risk_names)
        uniq_fn = "uniqCombined" if approximate else "uniqExact"
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
WITH total AS (SELECT count() AS total_count FROM ch_flow {where}),
ports AS (
    SELECT dst_port, count() AS port_count
    FROM ch_flow
    {where}
    GROUP BY dst_port
    ORDER BY port_count DESC, dst_port ASC
    LIMIT 1
),
ips AS (
    SELECT {uniq_fn}(ip) AS unique_ip_count
    FROM (
        SELECT src_ip AS ip FROM ch_flow {where}
        UNION ALL
        SELECT dst_ip AS ip FROM ch_flow {where}
    )
),
endpoints AS (
    SELECT {uniq_fn}(endpoint) AS unique_endpoint_count
    FROM (
        SELECT concat(src_ip, ':', toString(src_port)) AS endpoint FROM ch_flow {where}
        UNION ALL
        SELECT concat(dst_ip, ':', toString(dst_port)) AS endpoint FROM ch_flow {where}
    )
),
dst_ports AS (
    SELECT {uniq_fn}(dst_port) AS unique_dst_port_count
    FROM ch_flow
    {where}
)
SELECT
    total.total_count AS total_flow_count,
    ifNull(any(ports.dst_port), 0) AS top_dst_port,
    if(total.total_count = 0, 0, ifNull(any(ports.port_count), 0) / total.total_count) AS top_dst_port_ratio,
    any(ips.unique_ip_count) AS unique_ip_count,
    any(endpoints.unique_endpoint_count) AS unique_endpoint_count,
    any(dst_ports.unique_dst_port_count) AS unique_dst_port_count
FROM total
LEFT JOIN ports ON 1 = 1
LEFT JOIN ips ON 1 = 1
LEFT JOIN endpoints ON 1 = 1
LEFT JOIN dst_ports ON 1 = 1
GROUP BY total.total_count
FORMAT JSONEachRow
"""
        text = self.client.execute(sql)
        rows = [_parse_json(line) for line in text.splitlines() if line.strip()]
        return rows[0] if rows else {"top_dst_port": 0, "top_dst_port_ratio": 0}

    def dashboard_topology_stats(
        self,
        *,
        session_id: str,
        risk_learners: list[str] | None = None,
        time_from: str | None = None,
        time_to: str | None = None,
        approximate: bool = True,
    ) -> dict[str, dict[str, Any]]:
        risk_names = risk_learners or []
        abnormal = _abnormal_expr(risk_names)
        uniq_fn = "uniqCombined" if approximate else "uniqExact"
        where = _where(
            [
                f"session_id = {_quote(session_id)}",
                _time_filter("event_time", time_from, time_to),
            ]
        )
        sql = f"""
WITH flow_rows AS (
    SELECT
        topology_kind,
        src_ip,
        dst_ip,
        src_port,
        dst_port
    FROM ch_flow
    ARRAY JOIN if({abnormal}, ['combined', 'attack'], ['combined', 'benign']) AS topology_kind
    {where}
),
total_rows AS (
    SELECT topology_kind, count() AS total_flow_count
    FROM flow_rows
    GROUP BY topology_kind
),
port_counts AS (
    SELECT topology_kind, dst_port, count() AS port_count
    FROM flow_rows
    GROUP BY topology_kind, dst_port
),
top_ports AS (
    SELECT topology_kind, dst_port, port_count
    FROM (
        SELECT
            topology_kind,
            dst_port,
            port_count,
            row_number() OVER (PARTITION BY topology_kind ORDER BY port_count DESC, dst_port ASC) AS port_rank
        FROM port_counts
    )
    WHERE port_rank = 1
),
ips AS (
    SELECT topology_kind, {uniq_fn}(ip) AS unique_ip_count
    FROM (
        SELECT topology_kind, src_ip AS ip FROM flow_rows
        UNION ALL
        SELECT topology_kind, dst_ip AS ip FROM flow_rows
    )
    GROUP BY topology_kind
),
endpoints AS (
    SELECT topology_kind, {uniq_fn}(endpoint) AS unique_endpoint_count
    FROM (
        SELECT topology_kind, concat(src_ip, ':', toString(src_port)) AS endpoint FROM flow_rows
        UNION ALL
        SELECT topology_kind, concat(dst_ip, ':', toString(dst_port)) AS endpoint FROM flow_rows
    )
    GROUP BY topology_kind
),
dst_ports AS (
    SELECT topology_kind, {uniq_fn}(dst_port) AS unique_dst_port_count
    FROM flow_rows
    GROUP BY topology_kind
)
SELECT
    total_rows.topology_kind AS topology_kind,
    total_rows.total_flow_count AS total_flow_count,
    ifNull(top_ports.dst_port, 0) AS top_dst_port,
    if(total_rows.total_flow_count = 0, 0, ifNull(top_ports.port_count, 0) / total_rows.total_flow_count) AS top_dst_port_ratio,
    ifNull(ips.unique_ip_count, 0) AS unique_ip_count,
    ifNull(endpoints.unique_endpoint_count, 0) AS unique_endpoint_count,
    ifNull(dst_ports.unique_dst_port_count, 0) AS unique_dst_port_count
FROM total_rows
LEFT JOIN top_ports ON total_rows.topology_kind = top_ports.topology_kind
LEFT JOIN ips ON total_rows.topology_kind = ips.topology_kind
LEFT JOIN endpoints ON total_rows.topology_kind = endpoints.topology_kind
LEFT JOIN dst_ports ON total_rows.topology_kind = dst_ports.topology_kind
FORMAT JSONEachRow
"""
        text = self.client.execute(sql)
        stats = {
            "combined": _empty_topology_stats(),
            "benign": _empty_topology_stats(),
            "attack": _empty_topology_stats(),
        }
        for line in text.splitlines():
            if not line.strip():
                continue
            row = _parse_json(line)
            kind = str(row.get("topology_kind") or "")
            if kind not in stats:
                continue
            stats[kind] = {
                "total_flow_count": int(row.get("total_flow_count") or 0),
                "top_dst_port": int(row.get("top_dst_port") or 0),
                "top_dst_port_ratio": float(row.get("top_dst_port_ratio") or 0),
                "unique_ip_count": int(row.get("unique_ip_count") or 0),
                "unique_endpoint_count": int(row.get("unique_endpoint_count") or 0),
                "unique_dst_port_count": int(row.get("unique_dst_port_count") or 0),
            }
        return stats

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
        main_protocol = _main_protocol_sql()
        sql = f"""
SELECT
    count() AS total_flows,
    sum(flow_total_bytes) AS total_bytes,
    uniqExact(main_protocol) AS protocol_count,
    countIf({abnormal}) AS risk_flows,
    countIf(NOT ({abnormal})) AS normal_flows,
    sumIf(flow_total_bytes, {abnormal}) AS risk_bytes,
    sumIf(flow_total_bytes, NOT ({abnormal})) AS normal_bytes,
    uniqExactIf(dst_ip, {abnormal}) AS risk_ip_count,
    groupUniqArrayIf(assigned_learner, {abnormal}) AS active_abnormal_learners,
    max(window_index) AS current_window_index
FROM (
    SELECT
        total_bytes AS flow_total_bytes,
        {main_protocol} AS main_protocol,
        is_unknown,
        assigned_learner,
        dst_ip,
        window_index
    FROM ch_flow
    {where}
)
FORMAT JSONEachRow
"""
        text = self.client.execute(sql)
        rows = [_parse_json(line) for line in text.splitlines() if line.strip()]
        return rows[0] if rows else {}

    def traffic_trend(
        self,
        *,
        session_id: str,
        risk_learners: list[str],
        bucket: str,
        time_from: str | None = None,
        time_to: str | None = None,
    ) -> list[dict[str, Any]]:
        bucket_expr = {
            "hour": "toStartOfHour(event_time)",
            "day": "toStartOfDay(event_time)",
            "week": "toStartOfWeek(event_time, 1)",
        }.get(bucket)
        if bucket_expr is None:
            raise ValueError(f"unsupported traffic trend bucket: {bucket}")
        where = _where(
            [
                f"session_id = {_quote(session_id)}",
                _time_filter("event_time", time_from, time_to),
            ]
        )
        abnormal = _abnormal_expr(risk_learners)
        sql = f"""
SELECT
    formatDateTime(bucket_start, '%Y-%m-%d %H:%i:%S') AS bucket_start,
    sumIf(total_bytes, NOT ({abnormal})) AS normal,
    sumIf(total_bytes, {abnormal}) AS abnormal
FROM (
    SELECT
        {bucket_expr} AS bucket_start,
        total_bytes,
        is_unknown,
        assigned_learner
    FROM ch_flow
    {where}
)
GROUP BY bucket_start
ORDER BY bucket_start ASC
FORMAT JSONEachRow
"""
        text = self.client.execute(sql)
        return [row for line in text.splitlines() if line.strip() for row in [_parse_json(line)]]

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
        main_protocol = _main_protocol_sql()
        sql = f"""
SELECT {main_protocol} AS protocol, count() AS value
FROM ch_flow
{where}
GROUP BY protocol
ORDER BY value DESC, protocol ASC
LIMIT {capped}
FORMAT JSONEachRow
"""
        text = self.client.execute(sql)
        return [row for line in text.splitlines() if line.strip() for row in [_parse_json(line)]]

    def transport_protocol_distribution(
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
FROM ch_flow
{where}
GROUP BY protocol
ORDER BY value DESC, protocol ASC
LIMIT {capped}
FORMAT JSONEachRow
"""
        text = self.client.execute(sql)
        return [row for line in text.splitlines() if line.strip() for row in [_parse_json(line)]]

    def application_protocol_distribution(
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
        app_protocol = (
            "if(app_proto != '' AND lower(app_proto) NOT IN ('unknown', 'none', '-'), "
            "app_proto, 'UNKNOWN')"
        )
        sql = f"""
SELECT {app_protocol} AS protocol, count() AS value
FROM ch_flow
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
FROM ch_flow
{where}
GROUP BY src_ip
ORDER BY triggerCount DESC, ip ASC
LIMIT {capped}
FORMAT JSONEachRow
"""
        text = self.client.execute(sql)
        return [row for line in text.splitlines() if line.strip() for row in [_parse_json(line)]]

    def unique_dst_port_count_by_learner(
        self,
        *,
        session_id: str,
        learner_name: str,
    ) -> int:
        where = _where(
            [
                f"session_id = {_quote(session_id)}",
                f"assigned_learner = {_quote(learner_name)}",
            ]
        )
        sql = f"""
SELECT uniqExact(dst_port) AS port_count
FROM ch_flow
{where}
FORMAT JSONEachRow
"""
        text = self.client.execute(sql)
        for line in text.splitlines():
            if not line.strip():
                continue
            row = _parse_json(line)
            return int(row.get("port_count") or 0)
        return 0

    def unique_src_ip_count_by_learner(
        self,
        *,
        session_id: str,
        learner_name: str,
    ) -> int:
        where = _where(
            [
                f"session_id = {_quote(session_id)}",
                f"assigned_learner = {_quote(learner_name)}",
            ]
        )
        sql = f"""
SELECT uniqExact(src_ip) AS ip_count
FROM ch_flow
{where}
FORMAT JSONEachRow
"""
        text = self.client.execute(sql)
        for line in text.splitlines():
            if not line.strip():
                continue
            row = _parse_json(line)
            return int(row.get("ip_count") or 0)
        return 0

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
FROM ch_flow
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
        risk_learner_filter = _risk_learner_expr(risk_learners)
        filters = [
            f"session_id = {_quote(session_id)}",
            risk_learner_filter,
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
    FROM ch_flow
    {where}
    GROUP BY src_ip, assigned_learner
)
FORMAT JSONEachRow
"""
        total_text = self.client.execute(total_sql)
        total_rows = [_parse_json(line) for line in total_text.splitlines() if line.strip()]
        total = int(total_rows[0].get("total") or 0) if total_rows else 0
        main_protocol = _main_protocol_sql()
        sql = f"""
SELECT
    src_ip AS subject_ip,
    assigned_learner,
    max(event_time) AS trigger_time,
    count() AS flow_count,
    sum(is_unknown) AS unknown_count,
    any(dst_ip) AS top_dst_ip,
    any(dst_port) AS top_dst_port,
    any({main_protocol}) AS top_protocol
FROM ch_flow
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

    def learner_trigger_stats(self, *, session_id: str, learner_names: list[str]) -> dict[str, dict[str, Any]]:
        clean_names = list(dict.fromkeys(name for name in learner_names if name))
        learner_filter = _in_filter("assigned_learner", clean_names)
        if not learner_filter:
            return {}
        where = _where(
            [
                f"session_id = {_quote(session_id)}",
                learner_filter,
            ]
        )
        sql = f"""
SELECT
    assigned_learner,
    min(event_time) AS first_trigger_time,
    max(event_time) AS last_trigger_time,
    count() AS trigger_count
FROM ch_flow
{where}
GROUP BY assigned_learner
FORMAT JSONEachRow
"""
        text = self.client.execute(sql)
        result: dict[str, dict[str, Any]] = {}
        for line in text.splitlines():
            if not line.strip():
                continue
            row = _parse_json(line)
            learner_name = str(row.get("assigned_learner") or "")
            if learner_name:
                result[learner_name] = row
        return result

    def count_flows(self, *, session_id: str | None = None) -> int:
        where = f"WHERE session_id = {_quote(session_id)}" if session_id else ""
        text = self.client.execute(f"SELECT count() FROM ch_flow {where} FORMAT TabSeparated")
        return int(text.strip() or "0")

    def max_window_index(self, *, session_id: str | None = None) -> int:
        where = f"WHERE session_id = {_quote(session_id)}" if session_id else ""
        text = self.client.execute(f"SELECT max(window_index) FROM ch_flow {where} FORMAT TabSeparated")
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


def _endpoint_target_filter(values: list[str]) -> str | None:
    pairs: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for value in values:
        text = str(value or "")
        if ":" not in text:
            continue
        host, port_text = text.rsplit(":", 1)
        if not host:
            continue
        try:
            port = int(port_text)
        except ValueError:
            continue
        if port < 0 or port > 65535:
            continue
        pair = (host, port)
        if pair in seen:
            continue
        seen.add(pair)
        pairs.append(pair)
    if not pairs:
        return _in_filter("concat(dst_ip, ':', toString(dst_port))", values)
    ips = sorted({host for host, _port in pairs})
    tuple_values = ", ".join(f"({_quote(host)}, {port})" for host, port in pairs)
    return f"dst_ip IN ({', '.join(_quote(ip) for ip in ips)}) AND (dst_ip, dst_port) IN ({tuple_values})"


def _host_pair_filter(source_column: str, target_column: str, pairs: list[tuple[str, str]]) -> str | None:
    clean: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for source, target in pairs:
        source_text = str(source or "")
        target_text = str(target or "")
        if not source_text or not target_text:
            continue
        pair = (source_text, target_text)
        if pair in seen:
            continue
        seen.add(pair)
        clean.append(pair)
    if not clean:
        return None
    values = ", ".join(f"({_quote(source)}, {_quote(target)})" for source, target in clean)
    return f"({source_column}, {target_column}) IN ({values})"


def _target_source_pair_filter(target_column: str, source_column: str, pairs: list[tuple[str, str]]) -> str | None:
    clean: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for source, target in pairs:
        source_text = str(source or "")
        target_text = str(target or "")
        if not source_text or not target_text:
            continue
        pair = (target_text, source_text)
        if pair in seen:
            continue
        seen.add(pair)
        clean.append(pair)
    if not clean:
        return None
    targets = sorted({target for target, _source in clean})
    tuple_values = ", ".join(f"({_quote(target)}, {_quote(source)})" for target, source in clean)
    return f"{target_column} IN ({', '.join(_quote(target) for target in targets)}) AND ({target_column}, {source_column}) IN ({tuple_values})"


def _host_pairs_from_graph(graph: dict[str, Any]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for link in graph.get("links") or []:
        source = str(link.get("source") or "")
        target = str(link.get("target") or "")
        if not source or not target:
            continue
        pair = (source, target)
        if pair in seen:
            continue
        seen.add(pair)
        pairs.append(pair)
    return pairs


def _stat_row_from_graph(topology_kind: str, graph: dict[str, Any]) -> dict[str, Any]:
    value = int(graph.get("total_flow_count") or graph.get("flow_count") or 0)
    return {
        "row_type": "stat",
        "topology_kind": topology_kind,
        "id": "",
        "source": "",
        "target": "",
        "value": value,
        "out_flow_count": 0,
        "in_flow_count": 0,
        "is_benign": 0,
        "protocol": "",
    }


def _empty_topology_stats() -> dict[str, Any]:
    return {
        "total_flow_count": 0,
        "top_dst_port": 0,
        "top_dst_port_ratio": 0.0,
        "unique_ip_count": 0,
        "unique_endpoint_count": 0,
        "unique_dst_port_count": 0,
    }


def _empty_topology_graph_from_graph(graph: dict[str, Any], node_mode: str) -> dict[str, Any]:
    value = int(graph.get("total_flow_count") or graph.get("flow_count") or 0)
    return {
        "flow_count": value,
        "total_flow_count": value,
        "node_mode": node_mode,
        "nodes": [],
        "links": [],
        "stats": {"total_flow_count": value},
    }


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
    return _risk_learner_expr(risk_learners)


def _risk_learner_expr(risk_learners: list[str]) -> str:
    return _in_filter("assigned_learner", risk_learners) or "(0 = 1)"


def _build_topology_graph_from_rows(
    rows: list[dict[str, Any]],
    *,
    node_mode: str,
    top_victims: int,
    edges_per_victim: int,
) -> dict[str, Any]:
    nodes = []
    links = []
    victim_ids: set[str] = set()
    total_flow_count = 0
    for row in rows:
        if row.get("row_type") == "edge":
            victim_ids.add(str(row.get("target") or ""))
    for row in rows:
        if row.get("row_type") == "node":
            node_id = str(row.get("id") or "")
            flow_count = int(row.get("value") or 0)
            out_flow_count = int(row.get("out_flow_count") or 0)
            in_flow_count = int(row.get("in_flow_count") or 0)
            nodes.append(
                _topology_node(
                    node_id,
                    flow_count,
                    node_mode=node_mode,
                    out_flow_count=out_flow_count,
                    in_flow_count=in_flow_count,
                    protocol=str(row.get("protocol") or "").strip() or None,
                    role="victim" if node_id in victim_ids else "attacker",
                )
            )
        elif row.get("row_type") == "edge":
            link = {
                "source": str(row.get("source") or ""),
                "target": str(row.get("target") or ""),
                "value": int(row.get("value") or 0),
                "is_benign": bool(int(row.get("is_benign") or 0)),
            }
            protocol = str(row.get("protocol") or "").strip()
            if protocol:
                link["protocol"] = protocol
            links.append(link)
        elif row.get("row_type") == "stat":
            total_flow_count = int(row.get("value") or 0)
    displayed_flow_count = sum(link["value"] for link in links)
    flow_count = total_flow_count or displayed_flow_count
    stats = {
        "total_flow_count": flow_count,
        "displayed_victim_count": len(victim_ids),
        "edges_per_victim": edges_per_victim,
        "top_victims_limit": top_victims,
    }
    return {
        "flow_count": flow_count,
        "total_flow_count": flow_count,
        "node_mode": node_mode,
        "nodes": nodes,
        "links": links,
        "stats": stats,
    }


def _topology_node(
    node_id: str,
    flow_count: int,
    *,
    node_mode: str,
    out_flow_count: int = 0,
    in_flow_count: int = 0,
    protocol: str | None = None,
    role: str | None = None,
) -> dict[str, Any]:
    ip = node_id
    port: int | None = None
    if node_mode == "endpoint" and ":" in node_id:
        ip, port_text = node_id.rsplit(":", 1)
        try:
            port = int(port_text)
        except ValueError:
            port = None
    node = {
        "id": node_id,
        "ip": ip,
        "port": port,
        "flow_count": flow_count,
        "out_flow_count": out_flow_count,
        "in_flow_count": in_flow_count,
        "is_internal": _is_internal_ip(ip),
    }
    if protocol:
        node["protocol"] = protocol
    if role in {"victim", "attacker"}:
        node["role"] = role
    return node


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
