from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Mapping

from .redis_consumer import RedisStreamMessage


ALIASES: dict[str, tuple[str, ...]] = {
    "event_time": ("event_time", "timestamp", "Timestamp", "time", "flow_start"),
    "src_ip": ("src_ip", "source_ip", "Source IP", "Src IP"),
    "dst_ip": ("dst_ip", "destination_ip", "Destination IP", "Dst IP"),
    "src_port": ("src_port", "source_port", "Source Port", "Src Port"),
    "dst_port": ("dst_port", "destination_port", "Destination Port", "Dst Port"),
    "protocol": ("protocol", "proto", "Protocol"),
    "app_proto": ("app_proto", "application_protocol", "app_protocol", "Application Protocol"),
    "source_flow_id": ("source_flow_id", "flow_id", "flowid", "Flow ID"),
}


@dataclass(frozen=True, slots=True)
class FlowRecord:
    session_id: str
    flow_uid: str
    event_time: str
    src_ip: str
    dst_ip: str
    src_port: int
    dst_port: int
    protocol: int
    app_proto: str
    feature_profile: str
    features_json: str
    mq_type: str
    mq_topic: str
    mq_message_id: str
    source_flow_id: str
    raw_event: str
    record_version: int
    record_stage: str = "ingested"
    window_index: int = 0

    def to_clickhouse_row(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "flow_uid": self.flow_uid,
            "event_time": _clickhouse_datetime64(self.event_time),
            "src_ip": self.src_ip,
            "dst_ip": self.dst_ip,
            "src_port": self.src_port,
            "dst_port": self.dst_port,
            "protocol": self.protocol,
            "app_proto": self.app_proto,
            "feature_profile": self.feature_profile,
            "features_json": self.features_json,
            "window_index": self.window_index,
            "mq_type": self.mq_type,
            "mq_topic": self.mq_topic,
            "mq_message_id": self.mq_message_id,
            "source_flow_id": self.source_flow_id,
            "raw_event": self.raw_event,
            "record_version": self.record_version,
            "record_stage": self.record_stage,
        }


class FlowLoader:
    def __init__(self, *, session_id: str, feature_profile: str) -> None:
        self.session_id = session_id
        self.feature_profile = feature_profile

    def load(self, message: RedisStreamMessage) -> FlowRecord:
        fields = dict(message.fields)
        raw_payload = _parse_raw_payload(fields)
        merged = {**raw_payload, **fields}

        event_time = _normalize_time(_pick(merged, "event_time", None))
        src_ip = str(_pick(merged, "src_ip", ""))
        dst_ip = str(_pick(merged, "dst_ip", ""))
        src_port = _uint16(_pick(merged, "src_port", 0))
        dst_port = _uint16(_pick(merged, "dst_port", 0))
        protocol = _protocol(_pick(merged, "protocol", 0))
        app_proto = _app_proto(_pick(merged, "app_proto", "unknown"))
        source_flow_id = str(_pick(merged, "source_flow_id", ""))
        features = _features(merged)
        raw_event = _raw_event(fields, raw_payload)
        flow_uid = str(merged.get("flow_uid") or f"{message.stream}:{message.message_id}")

        return FlowRecord(
            session_id=str(merged.get("session_id") or self.session_id),
            flow_uid=flow_uid,
            event_time=event_time,
            src_ip=src_ip,
            dst_ip=dst_ip,
            src_port=src_port,
            dst_port=dst_port,
            protocol=protocol,
            app_proto=app_proto,
            feature_profile=self.feature_profile,
            features_json=json.dumps(features, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
            mq_type=str(merged.get("event_type") or "cic_flow"),
            mq_topic=message.stream,
            mq_message_id=message.message_id,
            source_flow_id=source_flow_id,
            raw_event=raw_event,
            record_version=_record_version(message.message_id),
        )


def stable_flow_uid(
    *,
    session_id: str,
    event_time: str,
    src_ip: str,
    dst_ip: str,
    src_port: int,
    dst_port: int,
    protocol: int,
    app_proto: str,
    source_flow_id: str,
    mq_message_id: str,
) -> str:
    raw = "|".join(
        [
            session_id,
            event_time,
            src_ip,
            dst_ip,
            str(src_port),
            str(dst_port),
            str(protocol),
            app_proto,
            source_flow_id,
            mq_message_id,
        ]
    )
    return f"{session_id}:{sha256(raw.encode('utf-8')).hexdigest()[:20]}"


def _pick(payload: Mapping[str, Any], key: str, default: Any) -> Any:
    for alias in ALIASES[key]:
        value = payload.get(alias)
        if value not in (None, ""):
            return value
    return default


def _parse_raw_payload(fields: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("raw_event_json", "raw_event"):
        value = fields.get(key)
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
    return {}


def _features(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = payload.get("features")
    if isinstance(value, dict):
        return value
    value = payload.get("features_json")
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _raw_event(fields: Mapping[str, Any], raw_payload: Mapping[str, Any]) -> str:
    raw = fields.get("raw_event_json") or fields.get("raw_event")
    if isinstance(raw, str) and raw.strip():
        return raw
    payload = raw_payload if raw_payload else fields
    return json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _normalize_time(value: Any) -> str:
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000.0
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            return text
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _clickhouse_datetime64(value: str) -> str:
    text = str(value).strip()
    if not text:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text.replace("T", " ").replace("Z", "")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _uint16(value: Any) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return 0
    return max(0, min(65535, number))


def _protocol(value: Any) -> int:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "tcp":
            return 6
        if normalized == "udp":
            return 17
        if normalized in {"icmp", "icmpv4"}:
            return 1
    return _uint16(value)


def _app_proto(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip()
        return text if text else "unknown"
    if value is None:
        return "unknown"
    text = str(value).strip()
    return text if text else "unknown"


def _record_version(message_id: str) -> int:
    head = str(message_id).split("-", 1)[0]
    try:
        return int(head)
    except ValueError:
        return int(datetime.now(timezone.utc).timestamp() * 1000)
