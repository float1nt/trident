from __future__ import annotations

import hashlib
import json
import os
import socket
import threading
import time
from datetime import datetime, timezone
from ipaddress import IPv4Address
from pathlib import Path
from typing import Any
from urllib.parse import quote

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator


_APPLY_LOCK = threading.Lock()
_ALLOWED_PROTOCOLS = {
    "dns",
    "ftp",
    "http",
    "icmp",
    "icmpv4",
    "icmpv6",
    "other",
    "rdp",
    "smb",
    "smb2",
    "ssh",
    "tcp",
    "tls",
    "udp",
}


class IpRangeItem(BaseModel):
    startIp: str
    endIp: str

    @field_validator("startIp", "endIp")
    @classmethod
    def validate_ipv4(cls, value: str) -> str:
        IPv4Address(value)
        return value

    @field_validator("endIp")
    @classmethod
    def validate_range_order(cls, value: str, info: Any) -> str:
        start = info.data.get("startIp")
        if start is not None and int(IPv4Address(start)) > int(IPv4Address(value)):
            raise ValueError("endIp must be greater than or equal to startIp")
        return value


class SuricataFilterPolicy(BaseModel):
    version: int = Field(default=1, ge=1)
    updatedAt: str | None = None
    sourceIpRanges: list[IpRangeItem] = Field(default_factory=list, max_length=256)
    destIpRanges: list[IpRangeItem] = Field(default_factory=list, max_length=256)
    protocols: list[str] = Field(default_factory=list)

    @field_validator("protocols")
    @classmethod
    def validate_protocols(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().lower() for value in values if value.strip()]
        invalid = sorted(set(normalized) - _ALLOWED_PROTOCOLS)
        if invalid:
            raise ValueError(f"unsupported protocols: {', '.join(invalid)}")
        return normalized


def create_app() -> FastAPI:
    app = FastAPI(title="Suricata Agent")

    @app.middleware("http")
    async def enforce_apply_request_size(request: Request, call_next):
        if request.method == "POST" and request.url.path == "/agent/v1/suricata/filter/apply":
            body = await request.body()
            if len(body) > _max_body_bytes():
                return JSONResponse(status_code=413, content={"detail": "request body too large"})

            async def receive() -> dict[str, Any]:
                return {"type": "http.request", "body": body, "more_body": False}

            request._receive = receive
        return await call_next(request)

    @app.get("/agent/v1/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "container": _suricata_container(),
            "filterConfig": _filter_config_path(),
        }

    @app.get("/agent/v1/status")
    def status(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        _authorize(authorization)
        return _status()

    @app.post("/agent/v1/suricata/filter/apply")
    def apply_filter(policy: SuricataFilterPolicy, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        _authorize(authorization)
        with _APPLY_LOCK:
            return _apply_filter(policy)

    return app


def _apply_filter(policy: SuricataFilterPolicy) -> dict[str, Any]:
    container = _suricata_container()
    path = Path(_filter_config_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = policy.model_dump()
    previous = path.read_bytes() if path.exists() else None
    previous_path = path.with_name(f"{path.name}.previous")
    if previous is not None:
        previous_path.write_bytes(previous)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    try:
        status = _restart_container(container)
        if not _wait_for_container_running(container):
            raise RuntimeError(f"{container} did not return to running state")
    except Exception as exc:
        rollback_error = _rollback_filter(path=path, previous=previous, container=container)
        detail = f"failed to apply Suricata filter: {exc}"
        if rollback_error:
            detail += f"; rollback failed: {rollback_error}"
        raise HTTPException(status_code=502, detail=detail) from exc
    return {
        "applied": True,
        "version": policy.version,
        "policyHash": _policy_hash(payload),
        "container": container,
        "filterConfig": str(path),
        "dockerStatus": status,
        "suricataRunning": True,
        "appliedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def _rollback_filter(*, path: Path, previous: bytes | None, container: str) -> str | None:
    try:
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            tmp = path.with_name(f".{path.name}.rollback.tmp")
            tmp.write_bytes(previous)
            tmp.replace(path)
        _restart_container(container)
        if not _wait_for_container_running(container):
            return f"{container} did not return to running state after rollback"
    except Exception as exc:
        return str(exc)
    return None


def _policy_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _status() -> dict[str, Any]:
    filter_payload = _load_filter_payload()
    try:
        redis_state = _redis_queue_state()
    except Exception as exc:
        redis_state = {"type": None, "length": None, "error": str(exc)}
    redis_state.update(
        {
            "host": _redis_host(),
            "port": _redis_port(),
            "key": _redis_key(),
        }
    )
    try:
        suricata_state = _container_state(_suricata_container())
    except Exception as exc:
        suricata_state = {"running": False, "status": "unknown", "error": str(exc)}
    return {
        "ok": True,
        "agentId": os.getenv("SURICATA_AGENT_ID", socket.gethostname()),
        "hostname": socket.gethostname(),
        "sampledAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "iface": os.getenv("SURICATA_IFACE", "eth0"),
        "filter": {
            "version": filter_payload.get("version"),
            "policyHash": _policy_hash(filter_payload) if filter_payload else None,
            "updatedAt": filter_payload.get("updatedAt"),
        },
        "suricata": {
            "container": _suricata_container(),
            **suricata_state,
        },
        "redis": redis_state,
    }


def _load_filter_payload() -> dict[str, Any]:
    path = Path(_filter_config_path())
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _authorize(authorization: str | None) -> None:
    token = os.getenv("SURICATA_AGENT_TOKEN", "").strip()
    if not token:
        return
    if authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="invalid agent token")


def _max_body_bytes() -> int:
    return int(os.getenv("SURICATA_AGENT_MAX_BODY_BYTES", str(256 * 1024)))


def _filter_config_path() -> str:
    return os.getenv("SURICATA_FILTER_CONFIG_PATH", "/etc/suricata-cic/filter.json")


def _suricata_container() -> str:
    return os.getenv("SURICATA_CONTAINER", "streamtrident-suricata-cic")


def _redis_host() -> str:
    return os.getenv("SURICATA_REDIS_HOST", "redis")


def _redis_port() -> int:
    return int(os.getenv("SURICATA_REDIS_PORT", "6379"))


def _redis_key() -> str:
    return os.getenv("SURICATA_REDIS_KEY", "suricata:cic_flow")


def _redis_command(*parts: str) -> Any:
    import redis

    client = redis.Redis(host=_redis_host(), port=_redis_port(), decode_responses=True)
    return client.execute_command(*parts)


def _redis_queue_state() -> dict[str, Any]:
    key = _redis_key()
    key_type = str(_redis_command("TYPE", key))
    if key_type == "none":
        return {"type": key_type, "length": 0}
    if key_type == "list":
        return {"type": key_type, "length": int(_redis_command("LLEN", key))}
    if key_type == "stream":
        return {"type": key_type, "length": int(_redis_command("XLEN", key))}
    return {"type": key_type, "length": None, "error": f"unsupported Redis key type: {key_type}"}


def _restart_container(container: str) -> int:
    timeout = int(os.getenv("SURICATA_RESTART_TIMEOUT", "10"))
    socket_path = os.getenv("DOCKER_SOCKET", "/var/run/docker.sock")
    status, body = _docker_unix_request(
        socket_path=socket_path,
        method="POST",
        path=f"/containers/{container}/restart?t={timeout}",
    )
    if status not in {204, 304}:
        body_text = body.decode("utf-8", errors="replace")
        raise HTTPException(
            status_code=502,
            detail=f"failed to restart {container}: docker status={status} body={body_text[:300]}",
        )
    return status


def _wait_for_container_running(container: str) -> bool:
    timeout = float(os.getenv("SURICATA_START_TIMEOUT", "15"))
    interval = float(os.getenv("SURICATA_START_POLL_INTERVAL", "0.5"))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _container_running(container):
            return True
        time.sleep(interval)
    return _container_running(container)


def _container_running(container: str) -> bool:
    return _container_state(container)["running"]


def _container_state(container: str) -> dict[str, Any]:
    socket_path = os.getenv("DOCKER_SOCKET", "/var/run/docker.sock")
    status, body = _docker_unix_request(
        socket_path=socket_path,
        method="GET",
        path=f"/containers/{quote(container, safe='')}/json",
    )
    if status != 200:
        return {"running": False, "status": f"docker-http-{status}"}
    payload = _load_json_object(body)
    state = payload.get("State", {})
    return {
        "running": bool(state.get("Running")),
        "status": str(state.get("Status") or "unknown"),
    }


def _load_json_object(body: bytes) -> dict[str, Any]:
    text = body.decode("utf-8", errors="replace").strip()
    if not text:
        raise ValueError("empty docker JSON body")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("docker JSON body must be an object")
    return payload


def _decode_chunked_body(data: bytes) -> bytes:
    out = bytearray()
    pos = 0
    while pos < len(data):
        line_end = data.find(b"\r\n", pos)
        if line_end < 0:
            break
        size_token = data[pos:line_end].split(b";", 1)[0].strip()
        if not size_token:
            break
        try:
            chunk_size = int(size_token, 16)
        except ValueError:
            break
        pos = line_end + 2
        if chunk_size == 0:
            break
        out.extend(data[pos : pos + chunk_size])
        pos += chunk_size + 2
    return bytes(out)


def _parse_http_response(response: bytes) -> tuple[int, bytes]:
    header_bytes, _, body_bytes = response.partition(b"\r\n\r\n")
    header_lines = header_bytes.split(b"\r\n")
    if not header_lines:
        raise RuntimeError("invalid docker response: missing status line")
    status_line = header_lines[0].decode("ascii", errors="replace")
    parts = status_line.split(" ", 2)
    if len(parts) < 2 or not parts[1].isdigit():
        raise RuntimeError(f"invalid docker response: {status_line}")

    headers: dict[str, bytes] = {}
    for line in header_lines[1:]:
        if b":" not in line:
            continue
        name, value = line.split(b":", 1)
        headers[name.strip().lower()] = value.strip()

    if headers.get(b"transfer-encoding", b"").lower() == b"chunked":
        body_bytes = _decode_chunked_body(body_bytes)
    elif b"content-length" in headers:
        content_length = int(headers[b"content-length"])
        body_bytes = body_bytes[:content_length]

    return int(parts[1]), body_bytes


def _docker_unix_request(*, socket_path: str, method: str, path: str) -> tuple[int, bytes]:
    request = (
        f"{method} {path} HTTP/1.1\r\n"
        "Host: docker\r\n"
        "Content-Length: 0\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode("ascii")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(30)
        client.connect(socket_path)
        client.sendall(request)
        chunks: list[bytes] = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    return _parse_http_response(b"".join(chunks))


def main() -> int:
    host = os.getenv("SURICATA_AGENT_HOST", "0.0.0.0")
    port = int(os.getenv("SURICATA_AGENT_PORT", "19100"))
    uvicorn.run(create_app(), host=host, port=port, access_log=False)
    return 0


app = create_app()


if __name__ == "__main__":
    raise SystemExit(main())
