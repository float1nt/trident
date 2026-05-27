from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any


class AuthError(ValueError):
    pass


@dataclass(slots=True)
class AuthUser:
    id: int
    username: str
    email: str | None = None
    nickname: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "nickname": self.nickname,
        }


class AuthManager:
    def __init__(self, *, secret: str = "trident-dev-auth-secret", token_ttl_seconds: int = 24 * 60 * 60) -> None:
        self._secret = secret.encode("utf-8")
        self._token_ttl_seconds = token_ttl_seconds

    def login(self, username: str, password: str) -> tuple[str, AuthUser]:
        username = (username or "").strip()
        password = (password or "").strip()
        if not username or not password:
            raise AuthError("username and password are required")
        user = self._make_user(username)
        return self.issue_token(user), user

    def issue_token(self, user: AuthUser) -> str:
        now = int(time.time())
        payload = {
            "sub": user.username,
            "uid": user.id,
            "email": user.email,
            "nickname": user.nickname,
            "iat": now,
            "exp": now + self._token_ttl_seconds,
        }
        payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        payload_b64 = _b64encode(payload_bytes)
        signature = hmac.new(self._secret, payload_b64.encode("ascii"), hashlib.sha256).digest()
        return f"{payload_b64}.{_b64encode(signature)}"

    def verify_token(self, token: str) -> AuthUser:
        token = (token or "").strip()
        if not token:
            raise AuthError("missing token")

        try:
            payload_b64, signature_b64 = token.split(".", 1)
        except ValueError as exc:
            raise AuthError("invalid token format") from exc

        expected_signature = hmac.new(self._secret, payload_b64.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64encode(expected_signature), signature_b64):
            raise AuthError("invalid token signature")

        try:
            payload = json.loads(_b64decode(payload_b64).decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise AuthError("invalid token payload") from exc

        exp = int(payload.get("exp", 0))
        if exp and exp < int(time.time()):
            raise AuthError("token expired")

        username = str(payload.get("sub") or "").strip()
        if not username:
            raise AuthError("invalid token subject")

        return AuthUser(
            id=int(payload.get("uid") or self._user_id(username)),
            username=username,
            email=payload.get("email") or None,
            nickname=payload.get("nickname") or username,
        )

    def _make_user(self, username: str) -> AuthUser:
        return AuthUser(
            id=self._user_id(username),
            username=username,
            email=None,
            nickname=username,
        )

    @staticmethod
    def _user_id(username: str) -> int:
        digest = hashlib.sha256(username.encode("utf-8")).digest()
        return int.from_bytes(digest[:4], byteorder="big", signed=False)


def extract_bearer_token(authorization: str | None) -> str:
    value = (authorization or "").strip()
    if not value:
        return ""
    prefix = "bearer "
    if value.lower().startswith(prefix):
        return value[len(prefix) :].strip()
    return ""


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)
