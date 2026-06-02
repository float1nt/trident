from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def _policy(version: int = 4) -> dict:
    return {
        "version": version,
        "sourceIpRanges": [{"startIp": "10.0.0.1", "endIp": "10.0.0.9"}],
        "destIpRanges": [{"startIp": "8.8.8.8", "endIp": "8.8.8.8"}],
        "protocols": ["tcp", "tls"],
    }


def test_apply_filter_returns_version_hash_and_running_state(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "filter.json"
    monkeypatch.setenv("SURICATA_FILTER_CONFIG_PATH", str(target))
    monkeypatch.setattr("app.main._restart_container", lambda container: 204)
    monkeypatch.setattr("app.main._container_running", lambda container: True)

    response = TestClient(create_app()).post("/agent/v1/suricata/filter/apply", json=_policy())

    assert response.status_code == 200
    assert response.json()["version"] == 4
    assert response.json()["policyHash"].startswith("sha256:")
    assert response.json()["suricataRunning"] is True
    assert json.loads(target.read_text(encoding="utf-8"))["version"] == 4


def test_apply_filter_rejects_invalid_ip_range() -> None:
    payload = _policy()
    payload["sourceIpRanges"] = [{"startIp": "10.0.0.9", "endIp": "10.0.0.1"}]

    response = TestClient(create_app()).post("/agent/v1/suricata/filter/apply", json=payload)

    assert response.status_code == 422


def test_apply_filter_rejects_unsupported_protocol() -> None:
    payload = _policy()
    payload["protocols"] = ["not-a-real-protocol"]

    response = TestClient(create_app()).post("/agent/v1/suricata/filter/apply", json=payload)

    assert response.status_code == 422


def test_apply_filter_rejects_oversized_request(monkeypatch) -> None:
    monkeypatch.setenv("SURICATA_AGENT_MAX_BODY_BYTES", "128")
    payload = _policy()
    payload["updatedAt"] = "x" * 256

    response = TestClient(create_app()).post("/agent/v1/suricata/filter/apply", json=payload)

    assert response.status_code == 413


def test_apply_filter_restores_previous_policy_when_restart_does_not_recover(
    monkeypatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "filter.json"
    previous = _policy(version=3)
    target.write_text(json.dumps(previous), encoding="utf-8")
    restarts: list[str] = []
    running_states = iter([False, True])
    monkeypatch.setenv("SURICATA_FILTER_CONFIG_PATH", str(target))
    monkeypatch.setattr("app.main._restart_container", lambda container: restarts.append(container) or 204)
    monkeypatch.setattr("app.main._wait_for_container_running", lambda container: next(running_states))

    response = TestClient(create_app()).post("/agent/v1/suricata/filter/apply", json=_policy(version=4))

    assert response.status_code == 502
    assert json.loads(target.read_text(encoding="utf-8"))["version"] == 3
    assert len(restarts) == 2


def test_status_reports_filter_container_and_list_queue(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "filter.json"
    target.write_text(json.dumps(_policy(version=8)), encoding="utf-8")
    monkeypatch.setenv("SURICATA_FILTER_CONFIG_PATH", str(target))
    monkeypatch.setenv("SURICATA_IFACE", "ens35")
    monkeypatch.setenv("SURICATA_REDIS_HOST", "redis")
    monkeypatch.setenv("SURICATA_REDIS_PORT", "6379")
    monkeypatch.setenv("SURICATA_REDIS_KEY", "suricata:cic_flow")
    monkeypatch.setattr(
        "app.main._container_state",
        lambda container: {"running": True, "status": "running"},
    )
    monkeypatch.setattr("app.main._redis_queue_state", lambda: {"type": "list", "length": 12})

    response = TestClient(create_app()).get("/agent/v1/status")

    assert response.status_code == 200
    assert response.json()["iface"] == "ens35"
    assert response.json()["filter"]["version"] == 8
    assert response.json()["filter"]["policyHash"].startswith("sha256:")
    assert response.json()["suricata"]["running"] is True
    assert response.json()["redis"]["key"] == "suricata:cic_flow"
    assert response.json()["redis"]["type"] == "list"
    assert response.json()["redis"]["length"] == 12


def test_redis_queue_state_uses_llen_for_list(monkeypatch) -> None:
    commands: list[tuple[str, ...]] = []

    def fake_command(*parts: str):
        commands.append(parts)
        return "list" if parts[0] == "TYPE" else 14

    monkeypatch.setattr("app.main._redis_command", fake_command)

    assert __import__("app.main", fromlist=["_redis_queue_state"])._redis_queue_state()["length"] == 14
    assert commands == [("TYPE", "suricata:cic_flow"), ("LLEN", "suricata:cic_flow")]


def test_redis_queue_state_uses_xlen_for_stream(monkeypatch) -> None:
    commands: list[tuple[str, ...]] = []

    def fake_command(*parts: str):
        commands.append(parts)
        return "stream" if parts[0] == "TYPE" else 21

    monkeypatch.setattr("app.main._redis_command", fake_command)

    assert __import__("app.main", fromlist=["_redis_queue_state"])._redis_queue_state()["length"] == 21
    assert commands == [("TYPE", "suricata:cic_flow"), ("XLEN", "suricata:cic_flow")]


def test_status_requires_token_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("SURICATA_AGENT_TOKEN", "secret")

    response = TestClient(create_app()).get("/agent/v1/status")

    assert response.status_code == 401


def test_status_keeps_reporting_when_redis_probe_fails(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "filter.json"
    target.write_text(json.dumps(_policy(version=8)), encoding="utf-8")
    monkeypatch.setenv("SURICATA_FILTER_CONFIG_PATH", str(target))
    monkeypatch.setattr(
        "app.main._container_state",
        lambda container: {"running": True, "status": "running"},
    )
    monkeypatch.setattr(
        "app.main._redis_queue_state",
        lambda: (_ for _ in ()).throw(OSError("redis unavailable")),
    )

    response = TestClient(create_app()).get("/agent/v1/status")

    assert response.status_code == 200
    assert response.json()["redis"]["length"] is None
    assert response.json()["redis"]["error"] == "redis unavailable"


def test_status_keeps_reporting_when_docker_probe_fails(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "filter.json"
    target.write_text(json.dumps(_policy(version=8)), encoding="utf-8")
    monkeypatch.setenv("SURICATA_FILTER_CONFIG_PATH", str(target))
    monkeypatch.setattr(
        "app.main._container_state",
        lambda container: (_ for _ in ()).throw(OSError("docker unavailable")),
    )
    monkeypatch.setattr("app.main._redis_queue_state", lambda: {"type": "list", "length": 2})

    response = TestClient(create_app()).get("/agent/v1/status")

    assert response.status_code == 200
    assert response.json()["suricata"]["running"] is False
    assert response.json()["suricata"]["error"] == "docker unavailable"
