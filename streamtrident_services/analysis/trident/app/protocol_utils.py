from __future__ import annotations

from typing import Any

_PLACEHOLDER_APP_PROTOS = frozenset({"unknown", "none", "-"})


def is_meaningful_app_proto(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text) and text.lower() not in _PLACEHOLDER_APP_PROTOS


def transport_protocol_name(protocol: Any) -> str:
    try:
        proto = int(protocol)
    except (TypeError, ValueError):
        return ""
    return {1: "ICMP", 6: "TCP", 17: "UDP"}.get(proto, str(proto) if proto else "")


def resolve_flow_protocol_name(*, app_proto: Any = None, protocol: Any = None) -> str:
    if is_meaningful_app_proto(app_proto):
        return str(app_proto).strip().upper()
    transport = transport_protocol_name(protocol)
    return transport or "UNKNOWN"


def resolve_flow_protocol_from_row(row: dict[str, Any]) -> str:
    return resolve_flow_protocol_name(
        app_proto=row.get("app_proto"),
        protocol=row.get("protocol"),
    )


def main_protocol_sql() -> str:
    return (
        "if(app_proto != '' AND lower(app_proto) NOT IN ('unknown', 'none', '-'), "
        "app_proto, "
        "multiIf(protocol = 1, 'ICMP', protocol = 6, 'TCP', protocol = 17, 'UDP', toString(protocol)))"
    )
