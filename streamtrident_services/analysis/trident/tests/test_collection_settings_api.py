from __future__ import annotations

from fastapi import HTTPException

from app.api import create_app
from app.collection_settings import CollectionSettings, CollectionSettingsState


def _route(app, path: str, method: str = "GET"):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"route not found: {path}")


def _settings() -> CollectionSettings:
    return CollectionSettings.model_validate(
        {
            "maxTrafficLimitGbps": 10,
            "sourceIpRanges": [{"startIp": "0.0.0.0", "endIp": "255.255.255.255"}],
            "destIpRanges": [{"startIp": "0.0.0.0", "endIp": "255.255.255.255"}],
            "protocols": ["TCP"],
        }
    )


class FakeRepository:
    def __init__(self) -> None:
        self.state = CollectionSettingsState(settings=_settings(), revision=4)
        self.recorded: list[dict] = []

    def get_state(self, *, session_id: str) -> CollectionSettingsState:
        return self.state

    def save_settings(self, *, session_id: str, settings: CollectionSettings) -> CollectionSettingsState:
        self.state = CollectionSettingsState(settings=settings, revision=5)
        return self.state

    def record_apply_result(self, *, session_id: str, apply_result: dict) -> None:
        self.recorded.append(apply_result)


def test_put_collection_settings_returns_revision_and_apply_result(monkeypatch) -> None:
    repo = FakeRepository()
    monkeypatch.setattr("app.api._collection_settings_repo", lambda cfg: repo)
    monkeypatch.setattr(
        "app.api.apply_suricata_config",
        lambda settings, revision: {"applied": True, "agents": [], "revision": revision},
    )
    endpoint = _route(create_app(None), "/collection/settings", "PUT")

    response = endpoint(_settings())

    assert response["data"]["revision"] == 5
    assert response["data"]["apply"]["applied"] is True
    assert repo.recorded == [{"applied": True, "agents": [], "revision": 5}]


def test_put_collection_settings_reports_saved_state_when_apply_fails(monkeypatch) -> None:
    repo = FakeRepository()
    monkeypatch.setattr("app.api._collection_settings_repo", lambda cfg: repo)
    monkeypatch.setattr(
        "app.api.apply_suricata_config",
        lambda settings, revision: {"applied": False, "agents": [{"name": "agent-1", "ok": False}]},
    )
    endpoint = _route(create_app(None), "/collection/settings", "PUT")

    try:
        endpoint(_settings())
    except HTTPException as exc:
        assert exc.status_code == 502
        assert exc.detail["saved"] is True
        assert exc.detail["revision"] == 5
        assert exc.detail["agents"] == [{"name": "agent-1", "ok": False}]
    else:
        raise AssertionError("expected HTTPException")

    assert repo.recorded == [{"applied": False, "agents": [{"name": "agent-1", "ok": False}]}]


def test_apply_collection_settings_reuses_current_revision(monkeypatch) -> None:
    repo = FakeRepository()
    revisions: list[int] = []
    monkeypatch.setattr("app.api._collection_settings_repo", lambda cfg: repo)
    monkeypatch.setattr(
        "app.api.apply_suricata_config",
        lambda settings, revision: revisions.append(revision) or {"applied": True, "agents": []},
    )
    endpoint = _route(create_app(None), "/collection/settings/apply", "POST")

    response = endpoint()

    assert response["data"]["applied"] is True
    assert revisions == [4]
