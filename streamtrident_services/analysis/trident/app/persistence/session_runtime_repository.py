from __future__ import annotations

from typing import Any


class SessionRuntimeRepository:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def get(self, *, session_id: str) -> dict[str, Any] | None:
        rows = self._fetch_all(
            """
SELECT *
FROM pg_session_runtime
WHERE session_id = %s
LIMIT 1
""",
            (session_id,),
        )
        return rows[0] if rows else None

    def upsert_runtime(self, payload: dict[str, Any]) -> None:
        import psycopg
        from psycopg.types.json import Jsonb

        columns = [
            "session_id",
            "runtime_mode",
            "cold_start_finalized",
            "cold_start_flow_count",
            "cold_start_windows_processed",
            "cold_start_finalize_reason",
            "session_baseline_learner",
            "baseline_learner_names",
            "cold_start_stable_streak",
            "cold_start_finalized_at",
        ]
        values = {column: payload.get(column) for column in columns}
        if values.get("baseline_learner_names") is not None:
            values["baseline_learner_names"] = Jsonb(values["baseline_learner_names"])
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
INSERT INTO pg_session_runtime ({", ".join(columns)})
VALUES ({", ".join("%(" + column + ")s" for column in columns)})
ON CONFLICT (session_id) DO UPDATE SET
    runtime_mode = EXCLUDED.runtime_mode,
    cold_start_finalized = EXCLUDED.cold_start_finalized,
    cold_start_flow_count = EXCLUDED.cold_start_flow_count,
    cold_start_windows_processed = EXCLUDED.cold_start_windows_processed,
    cold_start_finalize_reason = COALESCE(EXCLUDED.cold_start_finalize_reason, pg_session_runtime.cold_start_finalize_reason),
    session_baseline_learner = COALESCE(EXCLUDED.session_baseline_learner, pg_session_runtime.session_baseline_learner),
    baseline_learner_names = COALESCE(EXCLUDED.baseline_learner_names, pg_session_runtime.baseline_learner_names),
    cold_start_stable_streak = EXCLUDED.cold_start_stable_streak,
    cold_start_finalized_at = COALESCE(EXCLUDED.cold_start_finalized_at, pg_session_runtime.cold_start_finalized_at),
    updated_at = NOW()
""",
                    values,
                )

    def validate_inference_ready(self, *, session_id: str, learners: list[dict[str, Any]]) -> None:
        runtime = self.get(session_id=session_id)
        if not runtime or not bool(runtime.get("cold_start_finalized")):
            raise RuntimeError("inference mode requires cold_start_finalized session; run make prod-start-coldstart or make test-start-coldstart first")
        cold_learners = [row for row in learners if str(row.get("learner_name") or "").startswith("COLD_")]
        if not cold_learners:
            raise RuntimeError("inference mode requires at least one COLD_*|BENIGN learner; run make prod-start-coldstart or make test-start-coldstart first")
        for row in cold_learners:
            profile = row.get("profile_json") if isinstance(row.get("profile_json"), dict) else {}
            model_ref = profile.get("model_ref") if isinstance(profile, dict) else None
            feature_columns = profile.get("feature_columns") if isinstance(profile, dict) else None
            if not isinstance(model_ref, dict) or not model_ref.get("path"):
                name = str(row.get("learner_name") or "")
                raise RuntimeError(f"inference mode requires loadable model_ref for cold-start learner: {name}")
            if not isinstance(feature_columns, list) or not feature_columns:
                name = str(row.get("learner_name") or "")
                raise RuntimeError(f"inference mode requires feature schema for cold-start learner: {name}")

    def _fetch_all(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return list(cur.fetchall())
