from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.request import Request, urlopen

from .collection_settings import _suricata_agents_from_env


class CollectionAgentStateRepository:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def save_state(
        self,
        *,
        session_id: str,
        agent_name: str,
        agent_url: str,
        reachable: bool,
        effective: bool,
        desired_revision: int,
        effective_revision: int | None,
        status_json: dict[str, Any] | None,
        last_error: str | None,
        sampled_at: str | None,
    ) -> None:
        import psycopg
        from psycopg.types.json import Jsonb

        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
INSERT INTO pg_collection_agent_state (
    session_id,
    agent_name,
    agent_url,
    reachable,
    effective,
    desired_revision,
    effective_revision,
    status_json,
    last_error,
    sampled_at
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (session_id, agent_name) DO UPDATE SET
    agent_url = EXCLUDED.agent_url,
    reachable = EXCLUDED.reachable,
    effective = EXCLUDED.effective,
    desired_revision = EXCLUDED.desired_revision,
    effective_revision = EXCLUDED.effective_revision,
    status_json = COALESCE(EXCLUDED.status_json, pg_collection_agent_state.status_json),
    last_error = EXCLUDED.last_error,
    sampled_at = COALESCE(EXCLUDED.sampled_at, pg_collection_agent_state.sampled_at),
    updated_at = NOW()
""",
                    (
                        session_id,
                        agent_name,
                        agent_url,
                        reachable,
                        effective,
                        desired_revision,
                        effective_revision,
                        Jsonb(status_json) if status_json is not None else None,
                        last_error,
                        sampled_at,
                    ),
                )

    def list_states(self, *, session_id: str, desired_revision: int) -> dict[str, Any]:
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
SELECT agent_name,
       agent_url,
       reachable,
       effective,
       desired_revision,
       effective_revision,
       status_json,
       last_error,
       sampled_at
FROM pg_collection_agent_state
WHERE session_id = %s
ORDER BY agent_name
""",
                    (session_id,),
                )
                rows = cur.fetchall()
        return {
            "desiredRevision": desired_revision,
            "agents": [_row_to_response(row) for row in rows],
        }


def refresh_collection_agent_states(
    *,
    session_id: str,
    desired_revision: int,
    repo: CollectionAgentStateRepository,
) -> dict[str, Any]:
    agents = _suricata_agents_from_env()
    results = []
    for agent in agents:
        try:
            status = _get_agent_status(agent)
            effective_revision = _effective_revision(status)
            effective = bool(
                status.get("suricata", {}).get("running")
                and effective_revision == desired_revision
            )
            result = {
                "name": agent["name"],
                "url": agent["url"],
                "reachable": True,
                "effective": effective,
                "desiredRevision": desired_revision,
                "effectiveRevision": effective_revision,
                "status": status,
                "sampledAt": status.get("sampledAt"),
                "error": None,
            }
            repo.save_state(
                session_id=session_id,
                agent_name=agent["name"],
                agent_url=agent["url"],
                reachable=True,
                effective=effective,
                desired_revision=desired_revision,
                effective_revision=effective_revision,
                status_json=status,
                last_error=None,
                sampled_at=status.get("sampledAt"),
            )
        except Exception as exc:
            error = str(exc)
            result = {
                "name": agent["name"],
                "url": agent["url"],
                "reachable": False,
                "effective": False,
                "desiredRevision": desired_revision,
                "effectiveRevision": None,
                "status": None,
                "sampledAt": None,
                "error": error,
            }
            repo.save_state(
                session_id=session_id,
                agent_name=agent["name"],
                agent_url=agent["url"],
                reachable=False,
                effective=False,
                desired_revision=desired_revision,
                effective_revision=None,
                status_json=None,
                last_error=error,
                sampled_at=None,
            )
        results.append(result)
    return {"desiredRevision": desired_revision, "agents": results}


def _get_agent_status(agent: dict[str, str]) -> dict[str, Any]:
    headers = {}
    if agent.get("token"):
        headers["Authorization"] = f"Bearer {agent['token']}"
    request = Request(f"{agent['url']}/agent/v1/status", headers=headers, method="GET")
    with urlopen(request, timeout=10) as response:
        body = response.read().decode("utf-8", errors="replace")
    payload = json.loads(body) if body else {}
    if not isinstance(payload, dict):
        raise ValueError("invalid agent status response")
    return payload


def _effective_revision(status: dict[str, Any]) -> int | None:
    value = status.get("filter", {}).get("version")
    return int(value) if value is not None else None


def _row_to_response(row: dict[str, Any]) -> dict[str, Any]:
    sampled_at = row["sampled_at"]
    if isinstance(sampled_at, datetime):
        sampled_at = sampled_at.isoformat()
    return {
        "name": row["agent_name"],
        "url": row["agent_url"],
        "reachable": row["reachable"],
        "effective": row["effective"],
        "desiredRevision": row["desired_revision"],
        "effectiveRevision": row["effective_revision"],
        "status": row["status_json"],
        "sampledAt": sampled_at,
        "error": row["last_error"],
    }
