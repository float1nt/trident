"""Redis-backed flow input for Trident.

This module is intentionally optional: importing Trident does not require the
``redis`` package unless a run config selects ``input.source: redis``.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import pandas as pd


DEFAULT_REDIS_LABEL = "0000|UNLABELED"

_COLUMN_ALIASES = {
    "flowid": "Flow ID",
    "flow_id": "Flow ID",
    "srcip": "Src IP",
    "src_ip": "Src IP",
    "sourceip": "Src IP",
    "source_ip": "Src IP",
    "srcaddr": "Src IP",
    "dstip": "Dst IP",
    "dst_ip": "Dst IP",
    "destip": "Dst IP",
    "dest_ip": "Dst IP",
    "destinationip": "Dst IP",
    "destination_ip": "Dst IP",
    "dstaddr": "Dst IP",
    "srcport": "Src Port",
    "src_port": "Src Port",
    "sourceport": "Src Port",
    "source_port": "Src Port",
    "sport": "Src Port",
    "dstport": "Dst Port",
    "dst_port": "Dst Port",
    "destport": "Dst Port",
    "dest_port": "Dst Port",
    "destinationport": "Dst Port",
    "destination_port": "Dst Port",
    "dport": "Dst Port",
    "protocol": "Protocol",
    "proto": "Protocol",
    "timestamp": "Timestamp",
    "time": "Timestamp",
    "label": "Label",
    "eventtype": "event_type",
    "event_type": "event_type",
}

_PROTOCOL_ALIASES = {"tcp": 6, "udp": 17, "icmp": 1, "ipv6-icmp": 58}


def _decode(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _canonical_key(key: Any) -> str:
    text = str(_decode(key)).strip()
    compact = text.replace(" ", "").replace("-", "_").lower()
    return _COLUMN_ALIASES.get(compact, text)


def _parse_jsonish(value: Any) -> Any:
    value = _decode(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"message": text}
    return value


def _unwrap_record(raw: Any, payload_field: Optional[str] = None) -> Dict[str, Any]:
    parsed = _parse_jsonish(raw)
    if isinstance(parsed, Mapping):
        decoded = {str(_decode(k)): _decode(v) for k, v in parsed.items()}
        if payload_field and payload_field in decoded:
            return _unwrap_record(decoded[payload_field], payload_field=None)
        for wrapper in ("message", "event", "json", "eve", "record", "data", "payload"):
            inner = decoded.get(wrapper)
            if isinstance(inner, Mapping):
                return _unwrap_record(inner, payload_field=None)
            if isinstance(inner, str):
                maybe = _parse_jsonish(inner)
                if isinstance(maybe, Mapping):
                    return _unwrap_record(maybe, payload_field=None)
        cic = decoded.get("cic_flow")
        if isinstance(cic, str):
            cic = _parse_jsonish(cic)
        if isinstance(cic, Mapping):
            merged = {k: v for k, v in decoded.items() if k != "cic_flow"}
            merged.update(dict(cic))
            return merged
        return decoded
    return {"message": parsed}


def normalize_flow_record(
    raw: Any,
    *,
    default_label: str = DEFAULT_REDIS_LABEL,
    require_label: bool = False,
    payload_field: Optional[str] = None,
) -> Dict[str, Any]:
    record = _unwrap_record(raw, payload_field=payload_field)
    normalized = {_canonical_key(k): v for k, v in record.items()}
    proto = normalized.get("Protocol")
    if isinstance(proto, str):
        normalized["Protocol"] = _PROTOCOL_ALIASES.get(proto.strip().lower(), proto)
    if "Label" not in normalized or str(normalized.get("Label", "")).strip() == "":
        if require_label:
            raise ValueError("Redis flow message missing required Label")
        normalized["Label"] = default_label
    return normalized


def _records_to_dataframe(records: List[Dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame.from_records(records)
    for col in ("Src Port", "Dst Port", "Protocol"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _list_messages(client: Any, cfg: Mapping[str, Any]) -> Iterable[Any]:
    key = str(cfg.get("key") or cfg.get("queue") or "trident:flows")
    max_messages = int(cfg.get("max_messages", 0) or 0)
    block_timeout = int(cfg.get("block_timeout_seconds", 1) or 0)
    idle_timeout = float(cfg.get("idle_timeout_seconds", 5.0))
    start_idle = time.monotonic()
    count = 0

    while max_messages <= 0 or count < max_messages:
        item = None
        if block_timeout > 0:
            popped = client.blpop(key, timeout=block_timeout)
            if popped:
                _queue, item = popped
        else:
            item = client.lpop(key)

        if item is None:
            if time.monotonic() - start_idle >= idle_timeout:
                break
            continue

        start_idle = time.monotonic()
        count += 1
        yield item


def _stream_messages(client: Any, cfg: Mapping[str, Any]) -> Iterable[Any]:
    stream = str(cfg.get("stream") or cfg.get("key") or "trident:flows")
    max_messages = int(cfg.get("max_messages", 0) or 0)
    batch_size = int(cfg.get("batch_size", 1000) or 1000)
    block_ms = int(float(cfg.get("block_timeout_seconds", 1.0)) * 1000)
    idle_timeout = float(cfg.get("idle_timeout_seconds", 5.0))
    last_id = str(cfg.get("last_id", "0-0"))
    group = cfg.get("consumer_group")
    consumer = str(cfg.get("consumer_name", "trident"))
    ack = bool(cfg.get("ack", True))
    start_idle = time.monotonic()
    count = 0
    if group and bool(cfg.get("create_consumer_group", False)):
        try:
            client.xgroup_create(stream, str(group), id=str(cfg.get("group_start_id", "0-0")), mkstream=True)
        except Exception as exc:  # redis raises ResponseError("BUSYGROUP ...") when it already exists.
            if "BUSYGROUP" not in str(exc):
                raise

    while max_messages <= 0 or count < max_messages:
        if group:
            response = client.xreadgroup(
                groupname=str(group),
                consumername=consumer,
                streams={stream: ">"},
                count=batch_size,
                block=block_ms,
            )
        else:
            response = client.xread({stream: last_id}, count=batch_size, block=block_ms)

        if not response:
            if time.monotonic() - start_idle >= idle_timeout:
                break
            continue

        start_idle = time.monotonic()
        for _stream_name, entries in response:
            for msg_id, fields in entries:
                if max_messages > 0 and count >= max_messages:
                    return
                count += 1
                last_id = _decode(msg_id)
                yield fields
                if group and ack:
                    client.xack(stream, str(group), msg_id)


def load_redis_flows(redis_cfg: Mapping[str, Any], logger: Any = None) -> pd.DataFrame:
    """Drain a finite Redis queue/stream batch into a DataFrame."""
    try:
        import redis  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "input.source=redis requires the optional 'redis' Python package. "
            "Install it before enabling Redis input."
        ) from exc

    url = str(redis_cfg.get("url", "redis://localhost:6379/0"))
    structure = str(redis_cfg.get("data_structure", redis_cfg.get("type", "list"))).strip().lower()
    payload_field = redis_cfg.get("payload_field")
    default_label = str(redis_cfg.get("default_label", DEFAULT_REDIS_LABEL))
    require_label = bool(redis_cfg.get("require_label", False))
    expected_event_type = str(redis_cfg.get("event_type", "cic_flow")).strip()

    client = redis.Redis.from_url(url, decode_responses=False)
    if logger:
        logger.info("[RedisInput] source=%s structure=%s", url, structure)

    if structure in {"list", "queue"}:
        messages = _list_messages(client, redis_cfg)
    elif structure in {"stream", "streams"}:
        messages = _stream_messages(client, redis_cfg)
    else:
        raise ValueError(f"Unsupported Redis data_structure: {structure}")

    records: List[Dict[str, Any]] = []
    bad_records = 0
    skipped_records = 0
    for raw in messages:
        try:
            record = normalize_flow_record(
                raw,
                default_label=default_label,
                require_label=require_label,
                payload_field=str(payload_field) if payload_field else None,
            )
            event_type = str(record.get("event_type", "")).strip()
            if expected_event_type and event_type and event_type != expected_event_type:
                skipped_records += 1
                continue
            records.append(record)
        except Exception:
            bad_records += 1
            if logger:
                logger.exception("[RedisInput] failed to parse message")

    if not records:
        raise RuntimeError("Redis input returned no flow records")

    df = _records_to_dataframe(records)
    if logger:
        logger.info(
            "[RedisInput] loaded_rows=%d skipped_records=%d bad_records=%d columns=%d",
            len(df),
            skipped_records,
            bad_records,
            len(df.columns),
        )
    return df
