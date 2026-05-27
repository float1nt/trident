from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import create_app


def _route(app, path: str):
    for route in app.routes:
        if getattr(route, "path", None) == path:
            return route.endpoint
    raise AssertionError(f"route not found: {path}")


def test_auth_login_me_and_logout() -> None:
    app = create_app(None)

    login = _route(app, "/auth/login")
    me = _route(app, "/auth/me")
    logout = _route(app, "/auth/logout")

    payload = login(SimpleNamespace(username="alice", password="secret"))
    assert payload["code"] == 200
    assert payload["data"]["user"]["username"] == "alice"
    assert payload["data"]["user"]["nickname"] == "alice"
    token = payload["data"]["token"]

    me_payload = me(authorization=f"Bearer {token}")
    assert me_payload["data"]["user"]["username"] == "alice"

    logout_payload = logout()
    assert logout_payload["data"] is None


def test_auth_me_rejects_invalid_token() -> None:
    app = create_app(None)
    me = _route(app, "/auth/me")

    with pytest.raises(HTTPException) as excinfo:
        me(authorization="Bearer invalid.token")

    assert excinfo.value.status_code == 401
