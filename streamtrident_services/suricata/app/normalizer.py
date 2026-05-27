from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Mapping


ALIASES: dict[str, tuple[str, ...]] = {
    "event_time": ("event_time", "timestamp", "Timestamp", "time"),
    "src_ip": ("src_ip", "source_ip", "Source IP", "Src IP"),
    "dst_ip": ("dst_ip", "destination_ip", "Destination IP", "Dst IP"),
    "src_port": ("src_port", "source_port", "Source Port", "Src Port"),
    "dst_port": ("dst_port", "destination_port", "Destination Port", "Dst Port"),
    "protocol": ("protocol", "proto", "Protocol"),
    "source_flow_id": ("source_flow_id", "flow_id", "flowid", "Flow ID"),
}


def _pick(payload: Mapping[str, Any], key: str, default: Any = "") -> Any:
    for alias in ALIASES[key]:
        value = payload.get(alias)
        if value not in (None, ""):
            return value
    return default


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _flow_uid(session_id: str, event_time: str, src_ip: str, dst_ip: str, src_port: int | None, dst_port: int | None, protocol: int | None, source_flow_id: str) -> str:
    raw = "|".join(
        [
            session_id,
            event_time,
            src_ip,
            dst_ip,
            "" if src_port is None else str(src_port),
            "" if dst_port is None else str(dst_port),
            "" if protocol is None else str(protocol),
            source_flow_id,
        ]
    )
    return f"{session_id}:{sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def normalize_event(payload: Mapping[str, Any], *, event_type: str, session_id: str) -> dict[str, str]:
    event_time = str(_pick(payload, "event_time", _utc_now()))
    src_ip = str(_pick(payload, "src_ip", ""))
    dst_ip = str(_pick(payload, "dst_ip", ""))
    src_port = _to_int(_pick(payload, "src_port", None))
    dst_port = _to_int(_pick(payload, "dst_port", None))
    protocol = _to_int(_pick(payload, "protocol", None))
    source_flow_id = str(_pick(payload, "source_flow_id", ""))

    features = payload.get("features")
    if not isinstance(features, dict):
        features = payload.get("features_json")
        if isinstance(features, str) and features.strip():
            try:
                features = json.loads(features)
            except json.JSONDecodeError:
                features = {}
        else:
            features = {}

    flow_uid = str(payload.get("flow_uid") or _flow_uid(session_id, event_time, src_ip, dst_ip, src_port, dst_port, protocol, source_flow_id))
    record = {
        "event_type": str(payload.get("event_type", event_type)),
        "event_time": event_time,
        "session_id": session_id,
        "flow_uid": flow_uid,
        "src_ip": src_ip,
        "dst_ip": dst_ip,
        "src_port": "" if src_port is None else str(src_port),
        "dst_port": "" if dst_port is None else str(dst_port),
        "protocol": "" if protocol is None else str(protocol),
        "source_flow_id": source_flow_id,
        "features_json": json.dumps(features, ensure_ascii=False, separators=(",", ":")),
        "raw_event_json": json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":")),
    }
    return record

