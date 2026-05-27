from __future__ import annotations

from typing import Any


class LearnerRepository:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def upsert_current_learner(self, learner: dict[str, Any]) -> None:
        import psycopg
        from psycopg.types.json import Jsonb

        columns = [
            "session_id",
            "learner_name",
            "learner_status",
            "creation_window_index",
            "last_seen_window_index",
            "last_seen_at",
            "current_snapshot_id",
            "current_snapshot_version",
            "flow_count",
            "assignment_share",
            "unknown_absorb_count",
            "protocol_cluster_type",
            "temporal_cluster_type",
            "port_cluster_type",
            "stability_score",
            "drift_score",
            "risk_score",
            "risk_band",
            "risk_reason",
            "profile_json",
            "metric_json",
            "rule_json",
            "topology_json",
        ]
        values = {column: learner.get(column) for column in columns}
        for column in ("profile_json", "metric_json", "rule_json", "topology_json"):
            if values[column] is not None:
                values[column] = Jsonb(values[column])
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
INSERT INTO pg_learner ({", ".join(columns)})
VALUES ({", ".join("%(" + column + ")s" for column in columns)})
ON CONFLICT (session_id, learner_name) DO UPDATE SET
    learner_status = EXCLUDED.learner_status,
    last_seen_window_index = EXCLUDED.last_seen_window_index,
    last_seen_at = EXCLUDED.last_seen_at,
    updated_at = NOW(),
    current_snapshot_id = EXCLUDED.current_snapshot_id,
    current_snapshot_version = EXCLUDED.current_snapshot_version,
    flow_count = EXCLUDED.flow_count,
    assignment_share = EXCLUDED.assignment_share,
    unknown_absorb_count = EXCLUDED.unknown_absorb_count,
    protocol_cluster_type = EXCLUDED.protocol_cluster_type,
    temporal_cluster_type = EXCLUDED.temporal_cluster_type,
    port_cluster_type = EXCLUDED.port_cluster_type,
    stability_score = EXCLUDED.stability_score,
    drift_score = EXCLUDED.drift_score,
    risk_score = EXCLUDED.risk_score,
    risk_band = EXCLUDED.risk_band,
    risk_reason = EXCLUDED.risk_reason,
    profile_json = EXCLUDED.profile_json,
    metric_json = EXCLUDED.metric_json,
    rule_json = EXCLUDED.rule_json,
    topology_json = EXCLUDED.topology_json
""",
                    values,
                )

    def list_learners(self, *, session_id: str | None = None) -> list[dict[str, Any]]:
        where = "WHERE session_id = %s" if session_id else ""
        params = (session_id,) if session_id else ()
        return self._fetch_all(
            f"""
SELECT *
FROM pg_learner
{where}
ORDER BY learner_name
""",
            params,
        )

    def get_learner(self, *, session_id: str, learner_name: str) -> dict[str, Any] | None:
        rows = self._fetch_all(
            """
SELECT *
FROM pg_learner
WHERE session_id = %s AND learner_name = %s
LIMIT 1
""",
            (session_id, learner_name),
        )
        return rows[0] if rows else None

    def ping(self) -> bool:
        self._fetch_all("SELECT 1 AS ok", ())
        return True

    def _fetch_all(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return list(cur.fetchall())
