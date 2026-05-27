from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


class IpRangeItem(BaseModel):
    startIp: str
    endIp: str


class SuricataFilterPolicy(BaseModel):
    version: int = 1
    updatedAt: str | None = None
    sourceIpRanges: list[IpRangeItem] = Field(default_factory=list)
    destIpRanges: list[IpRangeItem] = Field(default_factory=list)
    protocols: list[str] = Field(default_factory=list)


def create_app() -> FastAPI:
    app = FastAPI(title="Suricata Agent")

    @app.get("/agent/v1/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "container": _suricata_container(),
            "filterConfig": _filter_config_path(),
        }

    @app.post("/agent/v1/suricata/filter/apply")
    def apply_filter(policy: SuricataFilterPolicy, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        _authorize(authorization)
        path = Path(_filter_config_path())
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = policy.model_dump()
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)
        status = _restart_container(_suricata_container())
        return {
            "applied": True,
            "container": _suricata_container(),
            "filterConfig": str(path),
            "dockerStatus": status,
        }

    return app


def _authorize(authorization: str | None) -> None:
    token = os.getenv("SURICATA_AGENT_TOKEN", "").strip()
    if not token:
        return
    if authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="invalid agent token")


def _filter_config_path() -> str:
    return os.getenv("SURICATA_FILTER_CONFIG_PATH", "/etc/suricata-cic/filter.json")


def _suricata_container() -> str:
    return os.getenv("SURICATA_CONTAINER", "streamtrident-suricata-cic")


def _restart_container(container: str) -> int:
    timeout = int(os.getenv("SURICATA_RESTART_TIMEOUT", "10"))
    socket_path = os.getenv("DOCKER_SOCKET", "/var/run/docker.sock")
    status, body = _docker_unix_request(
        socket_path=socket_path,
        method="POST",
        path=f"/containers/{container}/restart?t={timeout}",
    )
    if status not in {204, 304}:
        raise HTTPException(
            status_code=502,
            detail=f"failed to restart {container}: docker status={status} body={body[:300]}",
        )
    return status


def _docker_unix_request(*, socket_path: str, method: str, path: str) -> tuple[int, str]:
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
    response = b"".join(chunks)
    header, _, body = response.partition(b"\r\n\r\n")
    status_line = header.splitlines()[0].decode("ascii", errors="replace") if header else ""
    parts = status_line.split(" ", 2)
    if len(parts) < 2 or not parts[1].isdigit():
        raise RuntimeError(f"invalid docker response: {status_line}")
    return int(parts[1]), body.decode("utf-8", errors="replace")


def main() -> int:
    host = os.getenv("SURICATA_AGENT_HOST", "0.0.0.0")
    port = int(os.getenv("SURICATA_AGENT_PORT", "19100"))
    uvicorn.run(create_app(), host=host, port=port, access_log=False)
    return 0


app = create_app()


if __name__ == "__main__":
    raise SystemExit(main())
