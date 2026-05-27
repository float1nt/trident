from __future__ import annotations

from typing import Any


class SnapshotRepository:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def insert_snapshot(self, snapshot: dict[str, Any]) -> None:
        import psycopg
        from psycopg.types.json import Jsonb

        columns = [
            "snapshot_id",
            "session_id",
            "learner_name",
            "snapshot_version",
            "window_index",
            "snapshot_reason",
            "profile_json",
            "metric_json",
            "rule_json",
            "topology_json",
            "risk_score",
            "risk_band",
            "risk_reason",
            "threshold",
            "model_state_hash",
        ]
        values = {column: snapshot.get(column) for column in columns}
        for column in ("profile_json", "metric_json", "rule_json", "topology_json"):
            if values[column] is not None:
                values[column] = Jsonb(values[column])
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
INSERT INTO pg_learner_snapshot ({", ".join(columns)})
VALUES ({", ".join("%(" + column + ")s" for column in columns)})
ON CONFLICT (snapshot_id) DO NOTHING
""",
                    values,
                )

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM pg_learner_snapshot WHERE snapshot_id = %s LIMIT 1", (snapshot_id,))
                row = cur.fetchone()
                return dict(row) if row else None
