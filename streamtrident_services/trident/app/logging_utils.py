from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_SERVICE_NAME = "trident"


def configure_logging(
    *,
    service_name: str = "trident",
    log_path: str | Path | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 10,
    mirror_stdout: bool = True,
) -> None:
    global _SERVICE_NAME
    _SERVICE_NAME = service_name

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)

    formatter = logging.Formatter("%(message)s")
    if log_path is not None:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    if mirror_stdout:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)


def emit_event(event: str, **fields: Any) -> None:
    payload = {
        "ts": _now_utc(),
        "service": _SERVICE_NAME,
        "event": event,
        **fields,
    }
    logging.info(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def emit_exception(event: str, **fields: Any) -> None:
    payload = {
        "ts": _now_utc(),
        "service": _SERVICE_NAME,
        "event": event,
        **fields,
    }
    logging.exception(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
