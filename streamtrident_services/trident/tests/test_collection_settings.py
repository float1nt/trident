from __future__ import annotations

import json

import pytest

from app.collection_settings import (
    CollectionSettings,
    apply_suricata_config,
    compile_suricata_filter_policy,
)


def test_collection_settings_compiles_suricata_policy() -> None:
    settings = CollectionSettings.model_validate(
        {
            "maxTrafficLimitGbps": 10,
            "sourceIpRanges": [{"startIp": "10.0.0.1", "endIp": "10.0.0.9"}],
            "destIpRanges": [{"startIp": "8.8.8.8", "endIp": "8.8.8.8"}],
            "protocols": ["TCP", "HTTPS", "DNS"],
        }
    )

    policy = compile_suricata_filter_policy(settings)

    assert policy["sourceIpRanges"] == [{"startIp": "10.0.0.1", "endIp": "10.0.0.9"}]
    assert policy["destIpRanges"] == [{"startIp": "8.8.8.8", "endIp": "8.8.8.8"}]
    assert policy["protocols"] == ["dns", "tcp", "tls"]


def test_collection_settings_rejects_bad_ip_range() -> None:
    with pytest.raises(ValueError):
        CollectionSettings.model_validate(
            {
                "maxTrafficLimitGbps": 10,
                "sourceIpRanges": [{"startIp": "10.0.0.9", "endIp": "10.0.0.1"}],
                "destIpRanges": [{"startIp": "8.8.8.8", "endIp": "8.8.8.8"}],
                "protocols": ["TCP"],
            }
        )


def test_apply_suricata_config_returns_pending_without_agents(monkeypatch) -> None:
    monkeypatch.delenv("TRIDENT_SURICATA_AGENT_URLS", raising=False)
    settings = CollectionSettings.model_validate(
        {
            "maxTrafficLimitGbps": 10,
            "sourceIpRanges": [{"startIp": "0.0.0.0", "endIp": "255.255.255.255"}],
            "destIpRanges": [{"startIp": "0.0.0.0", "endIp": "255.255.255.255"}],
            "protocols": ["OTHER"],
        }
    )

    result = apply_suricata_config(settings)

    assert result["applied"] is False
    assert result["restartRequired"] is True
    assert result["agents"] == []


def test_apply_suricata_config_posts_policy_to_agent(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def read(self) -> bytes:
            return b'{"applied": true}'

    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["authorization"] = request.headers.get("Authorization")
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setenv("TRIDENT_SURICATA_AGENT_URLS", "http://agent-1:19100")
    monkeypatch.setenv("TRIDENT_SURICATA_AGENT_TOKEN", "secret")
    monkeypatch.setattr("app.collection_settings.urlopen", fake_urlopen)
    settings = CollectionSettings.model_validate(
        {
            "maxTrafficLimitGbps": 10,
            "sourceIpRanges": [{"startIp": "0.0.0.0", "endIp": "255.255.255.255"}],
            "destIpRanges": [{"startIp": "0.0.0.0", "endIp": "255.255.255.255"}],
            "protocols": ["HTTPS"],
        }
    )

    result = apply_suricata_config(settings)

    assert result["applied"] is True
    assert captured["url"] == "http://agent-1:19100/agent/v1/suricata/filter/apply"
    assert captured["payload"]["protocols"] == ["tls"]
    assert captured["authorization"] == "Bearer secret"
