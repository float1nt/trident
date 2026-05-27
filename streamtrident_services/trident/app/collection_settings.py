from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from ipaddress import IPv4Address
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field, field_validator


DEFAULT_SETTINGS: dict[str, Any] = {
    "maxTrafficLimitGbps": 10,
    "sourceIpRanges": [{"startIp": "0.0.0.0", "endIp": "255.255.255.255"}],
    "destIpRanges": [{"startIp": "0.0.0.0", "endIp": "255.255.255.255"}],
    "protocols": ["TCP", "UDP", "ICMP", "HTTP", "HTTPS", "DNS", "SSH", "SMB", "RDP", "FTP", "OTHER"],
}

PROTOCOL_OPTIONS: list[dict[str, str]] = [
    {"value": "TCP", "label": "TCP"},
    {"value": "UDP", "label": "UDP"},
    {"value": "HTTP", "label": "HTTP"},
    {"value": "HTTPS", "label": "HTTPS"},
    {"value": "DNS", "label": "DNS"},
    {"value": "SSH", "label": "SSH"},
    {"value": "SMB", "label": "SMB"},
    {"value": "RDP", "label": "RDP"},
    {"value": "ICMP", "label": "ICMP"},
    {"value": "TLS", "label": "TLS"},
    {"value": "FTP", "label": "FTP"},
    {"value": "OTHER", "label": "其他"},
]

_ALLOWED_PROTOCOLS = {item["value"] for item in PROTOCOL_OPTIONS}
_POLICY_PROTOCOL_ALIASES = {
    "HTTPS": "tls",
    "TLS": "tls",
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


class CollectionSettings(BaseModel):
    maxTrafficLimitGbps: float = Field(gt=0)
    sourceIpRanges: list[IpRangeItem] = Field(min_length=1)
    destIpRanges: list[IpRangeItem] = Field(min_length=1)
    protocols: list[str] = Field(min_length=1)

    @field_validator("protocols")
    @classmethod
    def validate_protocols(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().upper() for value in values if value.strip()]
        invalid = sorted(set(normalized) - _ALLOWED_PROTOCOLS)
        if invalid:
            raise ValueError(f"unsupported protocols: {', '.join(invalid)}")
        return normalized


class CollectionSettingsRepository:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def get_settings(self, *, session_id: str) -> CollectionSettings:
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
SELECT settings_json
FROM pg_collection_settings
WHERE session_id = %s
LIMIT 1
""",
                    (session_id,),
                )
                row = cur.fetchone()
        if not row:
            return CollectionSettings.model_validate(DEFAULT_SETTINGS)
        return CollectionSettings.model_validate(row["settings_json"])

    def save_settings(self, *, session_id: str, settings: CollectionSettings) -> CollectionSettings:
        import psycopg
        from psycopg.types.json import Jsonb

        payload = settings.model_dump()
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
INSERT INTO pg_collection_settings (session_id, settings_json)
VALUES (%s, %s)
ON CONFLICT (session_id) DO UPDATE SET
    settings_json = EXCLUDED.settings_json,
    updated_at = NOW()
""",
                    (session_id, Jsonb(payload)),
                )
        return settings


def compile_suricata_filter_policy(settings: CollectionSettings) -> dict[str, Any]:
    protocols = sorted({_POLICY_PROTOCOL_ALIASES.get(value, value.lower()) for value in settings.protocols})
    return {
        "version": 1,
        "updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "sourceIpRanges": [item.model_dump() for item in settings.sourceIpRanges],
        "destIpRanges": [item.model_dump() for item in settings.destIpRanges],
        "protocols": protocols,
    }


def apply_suricata_config(settings: CollectionSettings) -> dict[str, Any]:
    policy = compile_suricata_filter_policy(settings)
    agents = _suricata_agents_from_env()
    if not agents:
        return {
            "applied": False,
            "restartRequired": True,
            "applyScope": "suricata-agent",
            "agents": [],
            "message": "no suricata agents configured",
        }

    results = [_post_agent_policy(agent, policy) for agent in agents]
    failed = [result for result in results if not result.get("ok")]
    return {
        "applied": not failed,
        "restartRequired": bool(failed),
        "applyScope": "suricata-agent",
        "agents": results,
    }


def _suricata_agents_from_env() -> list[dict[str, str]]:
    raw_urls = os.getenv("TRIDENT_SURICATA_AGENT_URLS", "").strip()
    if not raw_urls:
        return []
    token = os.getenv("TRIDENT_SURICATA_AGENT_TOKEN", "").strip()
    agents = []
    for index, raw_url in enumerate(raw_urls.split(","), start=1):
        url = raw_url.strip().rstrip("/")
        if url:
            agents.append({"name": f"suricata-agent-{index}", "url": url, "token": token})
    return agents


def _post_agent_policy(agent: dict[str, str], policy: dict[str, Any]) -> dict[str, Any]:
    url = f"{agent['url']}/agent/v1/suricata/filter/apply"
    payload = json.dumps(policy).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if agent.get("token"):
        headers["Authorization"] = f"Bearer {agent['token']}"
    request = Request(url, data=payload, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
        data = json.loads(body) if body else {}
        return {
            "name": agent["name"],
            "url": agent["url"],
            "ok": True,
            "response": data,
        }
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {
            "name": agent["name"],
            "url": agent["url"],
            "ok": False,
            "error": f"http {exc.code}: {body[:300]}",
        }
    except (URLError, TimeoutError, OSError) as exc:
        return {
            "name": agent["name"],
            "url": agent["url"],
            "ok": False,
            "error": str(exc),
        }
