from __future__ import annotations

from app.collection_agent_state import (
    CollectionAgentStateRepository,
    refresh_collection_agent_states,
)


class FakeRepository:
    def __init__(self) -> None:
        self.saved: list[dict] = []

    def save_state(self, **state) -> None:
        self.saved.append(state)


def test_refresh_marks_matching_running_agent_effective(monkeypatch) -> None:
    repo = FakeRepository()
    monkeypatch.setenv("TRIDENT_SURICATA_AGENT_URLS", "http://agent-1:19100")
    monkeypatch.setattr(
        "app.collection_agent_state._get_agent_status",
        lambda agent: {
            "sampledAt": "2026-06-02T10:00:00Z",
            "filter": {"version": 7},
            "suricata": {"running": True},
        },
    )

    result = refresh_collection_agent_states(session_id="session-1", desired_revision=7, repo=repo)

    assert result["desiredRevision"] == 7
    assert result["agents"][0]["reachable"] is True
    assert result["agents"][0]["effective"] is True
    assert repo.saved[0]["effective_revision"] == 7


def test_refresh_marks_mismatched_revision_not_effective(monkeypatch) -> None:
    repo = FakeRepository()
    monkeypatch.setenv("TRIDENT_SURICATA_AGENT_URLS", "http://agent-1:19100")
    monkeypatch.setattr(
        "app.collection_agent_state._get_agent_status",
        lambda agent: {"filter": {"version": 6}, "suricata": {"running": True}},
    )

    result = refresh_collection_agent_states(session_id="session-1", desired_revision=7, repo=repo)

    assert result["agents"][0]["effective"] is False


def test_refresh_caches_unreachable_agent_error(monkeypatch) -> None:
    repo = FakeRepository()
    monkeypatch.setenv("TRIDENT_SURICATA_AGENT_URLS", "http://agent-1:19100")
    monkeypatch.setattr(
        "app.collection_agent_state._get_agent_status",
        lambda agent: (_ for _ in ()).throw(OSError("connection refused")),
    )

    result = refresh_collection_agent_states(session_id="session-1", desired_revision=7, repo=repo)

    assert result["agents"][0]["reachable"] is False
    assert result["agents"][0]["effective"] is False
    assert "connection refused" in result["agents"][0]["error"]
    assert repo.saved[0]["last_error"] == "connection refused"


def test_repository_list_states_returns_cached_agents(monkeypatch) -> None:
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query, params) -> None:
            return None

        def fetchall(self):
            return [
                {
                    "agent_name": "agent-1",
                    "agent_url": "http://agent-1:19100",
                    "reachable": True,
                    "effective": True,
                    "desired_revision": 7,
                    "effective_revision": 7,
                    "status_json": {"suricata": {"running": True}},
                    "last_error": None,
                    "sampled_at": None,
                }
            ]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr("psycopg.connect", lambda *args, **kwargs: FakeConnection())

    result = CollectionAgentStateRepository("postgresql://unused").list_states(
        session_id="session-1",
        desired_revision=7,
    )

    assert result["desiredRevision"] == 7
    assert result["agents"][0]["name"] == "agent-1"
