from __future__ import annotations

from app.api import create_app
from app.collection_settings import CollectionSettings, CollectionSettingsState


def _route(app, path: str, method: str = "GET"):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"route not found: {path}")


class FakeSettingsRepository:
    def get_state(self, *, session_id: str) -> CollectionSettingsState:
        return CollectionSettingsState(
            settings=CollectionSettings.model_validate(
                {
                    "maxTrafficLimitGbps": 10,
                    "sourceIpRanges": [{"startIp": "0.0.0.0", "endIp": "255.255.255.255"}],
                    "destIpRanges": [{"startIp": "0.0.0.0", "endIp": "255.255.255.255"}],
                    "protocols": ["TCP"],
                }
            ),
            revision=7,
        )


class FakeAgentRepository:
    def list_states(self, *, session_id: str, desired_revision: int):
        return {"desiredRevision": desired_revision, "agents": [{"name": "cached-agent"}]}


def test_collection_agents_status_returns_cached_states(monkeypatch) -> None:
    monkeypatch.setattr("app.api._collection_settings_repo", lambda cfg: FakeSettingsRepository())
    monkeypatch.setattr("app.api._collection_agent_state_repo", lambda cfg: FakeAgentRepository())

    response = _route(create_app(None), "/collection/agents/status")()

    assert response["data"]["desiredRevision"] == 7
    assert response["data"]["agents"][0]["name"] == "cached-agent"


def test_collection_agents_refresh_polls_agents(monkeypatch) -> None:
    monkeypatch.setattr("app.api._collection_settings_repo", lambda cfg: FakeSettingsRepository())
    monkeypatch.setattr("app.api._collection_agent_state_repo", lambda cfg: FakeAgentRepository())
    monkeypatch.setattr(
        "app.api.refresh_collection_agent_states",
        lambda session_id, desired_revision, repo: {
            "desiredRevision": desired_revision,
            "agents": [{"name": "fresh-agent"}],
        },
    )

    response = _route(create_app(None), "/collection/agents/refresh", "POST")()

    assert response["data"]["desiredRevision"] == 7
    assert response["data"]["agents"][0]["name"] == "fresh-agent"
