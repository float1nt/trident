from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from ..api_schema import ApiResponse
from ..auth import AuthManager, AuthError, extract_bearer_token


class LoginPayload(BaseModel):
    username: str
    password: str


def register_auth_routes(app: FastAPI, auth_manager: AuthManager) -> None:
    @app.post("/auth/login", response_model=ApiResponse)
    def login(payload: LoginPayload) -> dict[str, Any]:
        try:
            token, user = auth_manager.login(payload.username, payload.password)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        return _ok({"token": token, "user": user.to_dict()})

    @app.get("/auth/me", response_model=ApiResponse)
    def me(authorization: str | None = Header(default=None, alias="Authorization")) -> dict[str, Any]:
        token = extract_bearer_token(authorization)
        try:
            user = auth_manager.verify_token(token)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        return _ok({"user": user.to_dict()})

    @app.post("/auth/logout", response_model=ApiResponse)
    def logout() -> dict[str, Any]:
        return _ok(None)


def _ok(data: Any) -> dict[str, Any]:
    return {"code": 200, "message": "success", "data": data}
