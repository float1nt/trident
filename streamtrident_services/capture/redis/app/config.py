from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(slots=True)
class RedisServiceConfig:
    url: str = "redis://127.0.0.1:6379/0"
    queue_type: str = "list"
    input_stream: str = "suricata:cic_flow"
    consumer_group: str = "trident-online"
    consumer_name: str = "trident-01"
    start_id: str = "0"


def load_config(path: str | Path | None) -> RedisServiceConfig:
    if path is None:
        return RedisServiceConfig()
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"config must be a mapping: {path}")
    return RedisServiceConfig(
        url=str(payload.get("url", "redis://127.0.0.1:6379/0")),
        queue_type=str(payload.get("queue_type", "list")).lower(),
        input_stream=str(payload.get("input_stream", "suricata:cic_flow")),
        consumer_group=str(payload.get("consumer_group", "trident-online")),
        consumer_name=str(payload.get("consumer_name", "trident-01")),
        start_id=str(payload.get("start_id", "0")),
    )
