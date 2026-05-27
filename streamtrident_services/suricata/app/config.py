from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class SuricataConfig:
    redis_url: str = "redis://127.0.0.1:6379/0"
    output_stream: str = "suricata:cic_flow"
    stream_maxlen: int = 1_000_000
    event_type: str = "cic_flow"
    session_id: str = "suricata-live"


def load_config(path: str | Path | None) -> SuricataConfig:
    if path is None:
        return SuricataConfig()
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"config must be a mapping: {path}")
    return SuricataConfig(
        redis_url=str(payload.get("redis_url", "redis://127.0.0.1:6379/0")),
        output_stream=str(payload.get("output_stream", "suricata:cic_flow")),
        stream_maxlen=int(payload.get("stream_maxlen", 1_000_000)),
        event_type=str(payload.get("event_type", "cic_flow")),
        session_id=str(payload.get("session_id", "suricata-live")),
    )

